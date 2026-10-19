import hashlib
import json
import logging
import os
from pathlib import Path

from langchain_community.retrievers import BM25Retriever
from langchain_community.vectorstores import FAISS

from backend.utils.vector_store import create_vector_store

logger = logging.getLogger(__name__)

# Directory for persistent FAISS storage
INDEX_DIR = Path("data/faiss_index")

# Directory for uploaded PDFs
UPLOAD_DIR = Path("data/uploads")

# Persistent registry containing document hashes
DOCUMENT_REGISTRY = Path("data/document_registry.json")


class RAGService:

    def __init__(self):
        self.vector_store = None
        self.bm25_retriever = None
        self.documents = []

        # Maps filenames to their SHA-256 hashes
        self.document_registry = self.load_document_registry()

        # Restore the previously saved FAISS index
        self.load_index()

    # --------------------------------------------------
    # DOCUMENT REGISTRY
    # --------------------------------------------------

    def load_document_registry(self):
        """Load previously registered document hashes."""

        if not DOCUMENT_REGISTRY.exists():
            return {}

        try:
            with DOCUMENT_REGISTRY.open("r", encoding="utf-8") as file:
                registry = json.load(file)

            if not isinstance(registry, dict):
                logger.warning("Invalid document registry format.")
                return {}

            return registry

        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to load document registry.")
            return {}

    def save_document_registry(self):
        """Persist document hashes to disk."""

        DOCUMENT_REGISTRY.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temporary_path = DOCUMENT_REGISTRY.with_suffix(".tmp")

        try:
            with temporary_path.open("w", encoding="utf-8") as file:
                json.dump(
                    self.document_registry,
                    file,
                    indent=2
                )

            temporary_path.replace(DOCUMENT_REGISTRY)

        except OSError:
            temporary_path.unlink(missing_ok=True)
            logger.exception("Failed to save document registry.")
            raise

    def is_duplicate(self, file_hash):
        """
        Return True if the same PDF content is already registered.
        """

        return any(
            entry.get("hash") == file_hash
            for entry in self.document_registry.values()
            if isinstance(entry, dict)
        )

    def register_document(self, filename, file_hash):
        """
        Register a PDF after successful indexing.
        """

        self.document_registry[filename] = {
            "hash": file_hash
        }

        self.save_document_registry()

    # --------------------------------------------------
    # INDEX MANAGEMENT
    # --------------------------------------------------

    def build_index(self, chunks):
        """
        Add new PDF chunks to the existing index,
        rebuild BM25, and persist the FAISS index.
        """

        if not chunks:
            raise ValueError(
                "No valid text chunks were provided."
            )

        # Create an index for the newly uploaded PDF
        new_vector_store, _ = create_vector_store(chunks)

        new_documents = list(
            new_vector_store.docstore._dict.values()
        )

        if not new_documents:
            raise ValueError(
                "No documents were created from the uploaded chunks."
            )

        if self.vector_store is None:

            # First indexed PDF
            self.vector_store = new_vector_store
            self.documents = new_documents

        else:

            # Add new vectors without removing existing PDFs
            self.vector_store.merge_from(new_vector_store)

            self.documents.extend(new_documents)

        # Rebuild BM25 using all indexed documents
        self.bm25_retriever = BM25Retriever.from_documents(
            self.documents
        )

        self.bm25_retriever.k = 5

        # Persist the combined FAISS index
        self.save_index()

        logger.info(
            "Index updated. Total indexed chunks: %d",
            len(self.documents)
        )

    def save_index(self):
        """Save the FAISS index to disk."""

        if self.vector_store is None:
            return

        INDEX_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        self.vector_store.save_local(str(INDEX_DIR))

        logger.info(
            "FAISS index saved to %s",
            INDEX_DIR
        )

    def load_index(self):
        """Restore FAISS and rebuild BM25 during startup."""

        index_file = INDEX_DIR / "index.faiss"
        metadata_file = INDEX_DIR / "index.pkl"

        if not (
            index_file.exists()
            and metadata_file.exists()
        ):
            logger.info("No saved FAISS index found.")
            return

        try:
            from backend.utils.vector_store import embedding_model

            self.vector_store = FAISS.load_local(
                str(INDEX_DIR),
                embedding_model,
                allow_dangerous_deserialization=True
            )

            # Restore the indexed document chunks
            self.documents = list(
                self.vector_store.docstore._dict.values()
            )

            # Rebuild BM25 from restored documents
            if self.documents:
                self.bm25_retriever = BM25Retriever.from_documents(
                    self.documents
                )

                self.bm25_retriever.k = 5

            logger.info(
                "Loaded FAISS index with %d chunks.",
                len(self.documents)
            )

        except Exception:
            logger.exception(
                "Failed to load the saved FAISS index."
            )

            self.vector_store = None
            self.bm25_retriever = None
            self.documents = []

    # --------------------------------------------------
    # HYBRID RETRIEVAL
    # --------------------------------------------------

    def search(self, query, k=3):
        """
        Hybrid retrieval with ranking and basic relevance filtering.
        """

        if self.vector_store is None or self.bm25_retriever is None:
            return []

        query = query.strip()

        if not query:
            return []

        # Retrieve candidates from both systems.
        faiss_results = self.vector_store.similarity_search(
            query,
            k=k
        )

        bm25_results = self.bm25_retriever.invoke(query)

        # Combine results and calculate Reciprocal Rank Fusion scores.
        scores = {}
        documents_by_key = {}
        rrf_constant = 60

        for results in (faiss_results, bm25_results):
            for rank, document in enumerate(results, start=1):
                key = (
                    document.metadata.get("source"),
                    document.metadata.get("page"),
                    document.page_content
                )

                documents_by_key[key] = document

                scores[key] = scores.get(key, 0.0) + (
                    1.0 / (rrf_constant + rank)
                )

        ranked_keys = sorted(
            scores,
            key=scores.get,
            reverse=True
        )

        ranked_documents = [
            documents_by_key[key]
            for key in ranked_keys
        ]

        # Basic keyword-overlap filter.
        stop_words = {
            "what", "is", "the", "a", "an", "of", "in",
            "on", "for", "to", "and", "or", "explain",
            "describe", "define", "how", "does", "do"
        }

        query_terms = {
            word.lower().strip(".,?!:;()[]{}")
            for word in query.split()
        } - stop_words

        relevant_documents = []

        for document in ranked_documents:
            text_terms = {
                word.lower().strip(".,?!:;()[]{}")
                for word in document.page_content.split()
            }

            overlap = query_terms.intersection(text_terms)

            if overlap:
                relevant_documents.append(document)

        return relevant_documents[:5]


# --------------------------------------------------
# SHARED RAG SERVICE INSTANCE
# --------------------------------------------------

rag_service = RAGService()
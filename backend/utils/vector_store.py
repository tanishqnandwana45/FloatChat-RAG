from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever


embedding_model = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)


def create_vector_store(chunks):

    documents = []

    for chunk in chunks:

        document = Document(
            page_content=chunk["text"],
            metadata={
                "page": chunk["page"],
                "source": chunk["source"]
            }
        )

        documents.append(document)


    # FAISS vector database
    vector_store = FAISS.from_documents(
        documents,
        embedding_model
    )


    # BM25 keyword retriever
    bm25_retriever = BM25Retriever.from_documents(
        documents
    )

    bm25_retriever.k = 5


    return vector_store, bm25_retriever
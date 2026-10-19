import hashlib
import logging
import os
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from backend.utils.pdf_loader import load_pdf
from backend.utils.chunking import split_text
from backend.services.rag_service import rag_service


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/documents",
    tags=["Documents"]
)

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def calculate_file_hash(file_path: Path) -> str:
    """Calculate the SHA-256 hash of a PDF."""
    sha256 = hashlib.sha256()

    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    Upload a PDF, skip exact duplicates, and index new documents.
    """

    # 1. Validate filename and file type.
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Please select a PDF file."
        )

    filename = Path(file.filename).name

    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported."
        )

    file_path = UPLOAD_DIR / filename
    temp_path = None

    try:
        # 2. Save the incoming file to a temporary path.
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=UPLOAD_DIR,
            suffix=".pdf",
            delete=False
        ) as buffer:
            temp_path = Path(buffer.name)
            total_size = 0

            while True:
                chunk = await file.read(1024 * 1024)

                if not chunk:
                    break

                total_size += len(chunk)

                if total_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="PDF exceeds the 20 MB upload limit."
                    )

                buffer.write(chunk)

        if total_size == 0:
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is empty."
            )

        # 3. Calculate a content hash.
        file_hash = calculate_file_hash(temp_path)

        # 4. Check whether this exact PDF is already indexed.
        if rag_service.is_duplicate(file_hash):
            return {
                "message": "This PDF has already been uploaded and indexed.",
                "filename": filename,
                "duplicate": True
            }

        # 5. Extract PDF text.
        documents = load_pdf(str(temp_path))

        if not documents:
            raise HTTPException(
                status_code=400,
                detail="No readable text was found in this PDF."
            )

        # 6. Create chunks.
        all_chunks = []

        for document in documents:
            chunks = split_text(document["text"])

            for chunk in chunks:
                if chunk.strip():
                    all_chunks.append({
                        "text": chunk,
                        "page": document["page"],
                        "source": filename
                    })

        if not all_chunks:
            raise HTTPException(
                status_code=400,
                detail="No usable text could be extracted from this PDF."
            )

        # 7. Index the document and record its hash.
        rag_service.build_index(all_chunks)

        rag_service.register_document(
            filename=filename,
            file_hash=file_hash
        )

        # Keep the original PDF on disk.
        os.replace(temp_path, file_path)
        temp_path = None

        logger.info(
            "Indexed PDF: %s | Pages: %d | Chunks: %d",
            filename,
            len(documents),
            len(all_chunks)
        )

        return {
            "message": "PDF uploaded and indexed successfully.",
            "filename": filename,
            "pages": len(documents),
            "chunks": len(all_chunks),
            "duplicate": False
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("PDF upload or indexing failed")

        raise HTTPException(
            status_code=500,
            detail="The PDF could not be uploaded or indexed. Please try again."
        )

    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

        await file.close()


@router.get("/search")
def search_documents(query: str):
    """Search indexed PDFs."""
    query = query.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Please enter a search query."
        )

    try:
        results = rag_service.search(query, k=3)

        return {
            "query": query,
            "results": [
                {
                    "text": document.page_content,
                    "page": document.metadata.get("page"),
                    "source": document.metadata.get("source")
                }
                for document in results
            ]
        }

    except Exception:
        logger.exception("Document search failed")

        raise HTTPException(
            status_code=500,
            detail="Document search failed. Please try again."
        )
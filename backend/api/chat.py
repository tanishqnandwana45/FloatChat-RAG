import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.rag_service import rag_service
from backend.services.llm_service import create_llm


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/chat",
    tags=["Chat"]
)


class ChatRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Question about the uploaded documents"
    )


@router.post("/")
def chat(request: ChatRequest):

    query = request.query.strip()

    # 1. Validate the question
    if not query:
        return {
            "answer": "Please enter a question.",
            "sources": []
        }

    # 2. Retrieve relevant documents
    try:
        if rag_service.vector_store is None:
            return {
                "answer": (
                    "No documents are indexed yet. "
                    "Please upload a PDF before asking questions."
                ),
                "sources": []
            }

        results = rag_service.search(
            query,
            k=3
        )

        print("\n--- CHAT RETRIEVAL DEBUG ---")

        for i, document in enumerate(results, start=1):
            print(
                f"Result {i} | "
                f"Source: {document.metadata.get('source')} | "
                f"Page: {document.metadata.get('page')} | "
                f"Text: {document.page_content[:200]}"
            )

        print("--- END DEBUG ---\n")

    except Exception:
        logger.exception("Document retrieval failed")

        raise HTTPException(
            status_code=500,
            detail="Document retrieval failed. Please try again."
        )

    # 3. Handle missing results
    if not results:
        return {
            "answer": (
                "I could not find relevant information "
                "in the indexed documents. "
                "Try rephrasing your question."
            ),
            "sources": []
        }

    # 4. Build the document context
    context = "\n\n".join(
        document.page_content
        for document in results
        if document.page_content
    )

    if not context.strip():
        return {
            "answer": (
                "The retrieved documents did not contain "
                "usable text for this question."
            ),
            "sources": []
        }

    # 5. Generate the answer
    prompt = f"""
You are FloatChat, an AI assistant that answers questions
using the provided document context.

Instructions:
- Base your answer on the provided context.
- Do not invent facts.
- If the context does not contain the answer, say:
  "I could not find that information in the uploaded documents."
- Keep the answer clear and professional.
- Use bullet points when appropriate.

Context:
{context}

Question:
{query}

Answer:
"""

    try:
        llm = create_llm()
        response = llm.invoke(prompt)

        answer = getattr(response, "content", "")

        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("The language model returned an empty answer.")

    except Exception:
        logger.exception("LLM answer generation failed")

        raise HTTPException(
            status_code=502,
            detail=(
                "The AI service could not generate an answer. "
                "Please try again later."
            )
        )

    # 6. Prepare source citations
    sources = []

    for document in results:
        metadata = document.metadata or {}

        '''print("CITATION DEBUG:", {
            "source": metadata.get("source"),
            "page": metadata.get("page"),
            "text": document.page_content[:100]
        })'''

        sources.append({
            "source": metadata.get("source", "Unknown document"),
            "page": metadata.get("page"),
            "text": document.page_content[:500]
        })

    # 7. Return the answer and citations
    return {
        "answer": answer.strip(),
        "sources": sources
    }
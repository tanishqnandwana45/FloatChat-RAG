from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.documents import router as documents_router
from backend.api.chat import router as chat_router

app = FastAPI(
    title="FloatChat API",
    description="Backend API for FloatChat RAG Assistant",
    version="1.0.0",
)

# Allow requests from the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(chat_router)


@app.get("/")
def root():
    return {
        "message": "FloatChat API is running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }
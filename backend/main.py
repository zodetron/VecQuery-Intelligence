"""
main.py — FastAPI application entry point for VecQuery Intelligence.

Registers:
  - CORS middleware (allows the Vite dev server on localhost:5173)
  - GET  /                    → health check
  - POST /upload/             → document ingestion
  - GET  /upload/documents/   → list all ingested documents
  - POST /query/              → hybrid search (returns chunks)
  - POST /answer/             → hybrid search + LLM answer (SSE stream)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import upload, query, answer

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="VecQuery Intelligence",
    description="Cross-document natural language query engine with hybrid pgvector + BM25 search",
    version="0.3.0",
)

# ---------------------------------------------------------------------------
# CORS — allow the Vite React frontend running on localhost:5173
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vite dev server
        "http://localhost:3000",   # fallback if running on 3000
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(upload.router)
app.include_router(query.router)
app.include_router(answer.router)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def health_check():
    """
    Health check endpoint.
    Returns a simple status message to confirm the API is running.
    """
    return {"status": "VecQuery running"}

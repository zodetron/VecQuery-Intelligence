"""
routers/upload.py — FastAPI router for file upload and ingestion.

Endpoints:
  POST   /upload/              — Accept a file, run ingestion, return document id + chunk count.
  GET    /upload/documents/    — List all ingested documents with chunk counts.
  DELETE /upload/documents/{id} — Delete a document and all its chunks + embeddings.

The file is saved to a temporary location, processed, then deleted.
All ingestion errors are caught and returned as HTTP 422 or 500 responses.
"""

import os
import tempfile
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import Chunk, Document, get_db
from ingestion import ingest_file

# ---------------------------------------------------------------------------
# Router setup
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/upload",
    tags=["upload"],
)

# Maximum file size: 50 MB (bytes)
MAX_FILE_SIZE = 50 * 1024 * 1024

# Allowed MIME types and their canonical extensions
ALLOWED_TYPES: dict[str, str] = {
    "application/pdf":                                                          "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/csv":                                                                 "csv",
    "text/plain":                                                               "txt",
    # Some browsers send these for CSV
    "application/csv":                                                          "csv",
    "application/vnd.ms-excel":                                                 "csv",
}

# Fallback: detect type from file extension when content-type is unreliable
ALLOWED_EXTENSIONS = {"pdf", "docx", "csv", "txt"}


def _resolve_extension(filename: str, content_type: str) -> str:
    """
    Determine the canonical file extension.
    Prefers the file extension over the MIME type because browsers sometimes
    send 'application/octet-stream' for all uploads.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ALLOWED_EXTENSIONS:
        return ext
    # Fall back to MIME type lookup
    resolved = ALLOWED_TYPES.get(content_type)
    if resolved:
        return resolved
    return ""


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------

@router.post("/")
async def upload_file(
    file: Annotated[UploadFile, File(description="PDF, DOCX, CSV, or TXT file to ingest")],
    db: Session = Depends(get_db),
):
    """
    Upload a document and run the full ingestion pipeline.

    - Validates file type and size
    - Saves to a temp file on disk
    - Calls ingest_file() which parses → chunks → embeds → stores
    - Returns document_id and chunk_count on success
    - Cleans up the temp file regardless of success or failure
    """
    # --- Validate file type ---
    ext = _resolve_extension(file.filename or "", file.content_type or "")
    if not ext:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported file type. "
                f"Received content-type='{file.content_type}', filename='{file.filename}'. "
                f"Allowed extensions: pdf, docx, csv, txt"
            ),
        )

    # --- Read file content ---
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read uploaded file: {e}")

    # --- Validate file size ---
    if len(content) > MAX_FILE_SIZE:
        size_mb = len(content) / (1024 * 1024)
        raise HTTPException(
            status_code=422,
            detail=f"File too large: {size_mb:.1f} MB. Maximum allowed: 50 MB",
        )

    if len(content) == 0:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    # --- Write to a named temp file so parsers can open it by path ---
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=f".{ext}",
            prefix="vecquery_",
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        print(f"[upload] Received '{file.filename}' ({len(content)/1024:.1f} KB) → temp: {tmp_path}")

        # --- Run ingestion pipeline ---
        result = ingest_file(
            file_path=tmp_path,
            file_name=file.filename or f"upload.{ext}",
            db=db,
        )

        return {
            "status":      "success",
            "document_id": result["document_id"],
            "chunk_count": result["chunk_count"],
            "file_name":   result["file_name"],
            "message":     f"Successfully ingested {result['chunk_count']} chunks from '{result['file_name']}'",
        }

    except ValueError as e:
        # Validation errors from the ingestion pipeline (bad content, unsupported type, etc.)
        raise HTTPException(status_code=422, detail=str(e))

    except RuntimeError as e:
        # Infrastructure errors: Ollama down, DB failure, parse error
        raise HTTPException(status_code=500, detail=str(e))

    except Exception as e:
        # Catch-all for unexpected errors
        raise HTTPException(status_code=500, detail=f"Unexpected ingestion error: {e}")

    finally:
        # Always clean up the temp file
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
            print(f"[upload] Temp file cleaned up: {tmp_path}")


# ---------------------------------------------------------------------------
# GET /upload/documents/
# ---------------------------------------------------------------------------

@router.get("/documents/")
def list_documents(db: Session = Depends(get_db)):
    """
    Return all uploaded documents with their chunk counts.

    Used by the DocumentList frontend component to show what has been ingested.
    Returns documents sorted by upload time descending (newest first).

    Response:
      [
        {
          "id":          int,
          "name":        str,
          "type":        str,
          "uploaded_at": str (ISO 8601),
          "chunk_count": int
        },
        ...
      ]
    """
    try:
        # Join documents with chunk counts using a subquery
        rows = (
            db.query(
                Document.id,
                Document.name,
                Document.type,
                Document.uploaded_at,
                func.count(Chunk.id).label("chunk_count"),
            )
            .outerjoin(Chunk, Chunk.document_id == Document.id)
            .group_by(Document.id, Document.name, Document.type, Document.uploaded_at)
            .order_by(Document.uploaded_at.desc())
            .all()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch documents: {e}")

    return [
        {
            "id":          row.id,
            "name":        row.name,
            "type":        row.type,
            "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
            "chunk_count": row.chunk_count,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# DELETE /upload/documents/{document_id}
# ---------------------------------------------------------------------------

@router.delete("/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    """
    Delete a document and all its associated data (chunks + embeddings).

    The Document ORM model has cascade="all, delete-orphan" on its chunks
    relationship, and Chunk has the same on its embedding relationship, so
    deleting the Document row automatically deletes all child rows in a
    single transaction — no manual cleanup needed.

    Returns:
      {"status": "deleted", "document_id": int, "name": str}

    Raises:
      404 if the document does not exist.
      500 if the database delete fails.
    """
    # Fetch the document first so we can return its name and give a clear 404
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found",
        )

    doc_name = doc.name
    print(f"[upload] Deleting document id={document_id} name='{doc_name}'")

    try:
        db.delete(doc)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete document: {e}",
        )

    print(f"[upload] Deleted document id={document_id} and all its chunks/embeddings")
    return {"status": "deleted", "document_id": document_id, "name": doc_name}

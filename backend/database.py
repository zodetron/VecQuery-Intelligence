"""
database.py — SQLAlchemy connection, session management, and ORM models.

Defines:
  - Engine and SessionLocal for Supabase PostgreSQL
  - Base declarative class for all models
  - ORM models: Document, Chunk, Embedding, QueryLog
  - get_db() dependency for FastAPI route injection
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker
from pgvector.sqlalchemy import Vector

# ---------------------------------------------------------------------------
# Load environment variables from .env
# Always resolve .env relative to this file's directory so the app works
# regardless of which directory uvicorn / python is launched from.
# ---------------------------------------------------------------------------
_ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(_ENV_PATH)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in .env")

# ---------------------------------------------------------------------------
# Driver prefix rewriting
#
# psycopg3 requires the "postgresql+psycopg" scheme.
# The Supabase session pooler URL looks like:
#   postgresql://postgres.PROJECTREF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres
#
# The dot in the username (postgres.PROJECTREF) is valid in a URL and does NOT
# need special handling — SQLAlchemy passes it through to psycopg3 unchanged.
# We only need to rewrite the scheme prefix.
# ---------------------------------------------------------------------------
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
# If the URL already starts with "postgresql+psycopg://" leave it as-is.

# ---------------------------------------------------------------------------
# Engine
#
# pool_pre_ping   — sends a lightweight "SELECT 1" before handing a connection
#                   from the pool; drops and replaces stale connections silently.
# pool_recycle    — forces connections to be closed and reopened after 5 minutes,
#                   preventing the pooler from cutting them off mid-use.
# connect_timeout — passed to psycopg3; aborts a connection attempt after 10s
#                   instead of hanging indefinitely if Supabase is unreachable.
# ---------------------------------------------------------------------------
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    echo=False,
    connect_args={"connect_timeout": 10},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Declarative base — all ORM models inherit from this
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class Document(Base):
    """
    Represents an uploaded file.
    One document → many chunks.
    """
    __tablename__ = "documents"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(512), nullable=False)          # original filename
    type        = Column(String(32), nullable=False)           # pdf | csv | docx | txt
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationship: accessing doc.chunks gives all child Chunk rows
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    """
    A text chunk extracted from a document.
    One chunk → one embedding row.
    """
    __tablename__ = "chunks"

    id          = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    content     = Column(Text, nullable=False)                 # raw text of the chunk
    page_number = Column(Integer, nullable=True)               # page number (PDF/DOCX)
    chunk_index = Column(Integer, nullable=False)              # position within document
    chunk_metadata = Column(JSON, nullable=True)               # extra info (headers, row range, BM25 terms, etc.)

    document  = relationship("Document", back_populates="chunks")
    embedding = relationship("Embedding", back_populates="chunk", uselist=False, cascade="all, delete-orphan")


class Embedding(Base):
    """
    The 768-dimensional vector embedding for a chunk.
    Stored in pgvector's vector column type.
    """
    __tablename__ = "embeddings"

    id       = Column(Integer, primary_key=True, index=True)
    chunk_id = Column(Integer, ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, unique=True)
    vector   = Column(Vector(768), nullable=False)             # nomic-embed-text produces 768-dim vectors

    chunk = relationship("Chunk", back_populates="embedding")


class QueryLog(Base):
    """
    Audit log for every query run through the engine.
    Stores the raw query, planner decision, and which chunks were returned.
    """
    __tablename__ = "query_logs"

    id               = Column(Integer, primary_key=True, index=True)
    query            = Column(Text, nullable=False)
    planner_decision = Column(String(64), nullable=True)       # e.g. "vector", "bm25", "hybrid"
    result_chunk_ids = Column(JSON, nullable=True)             # list of chunk IDs returned
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# FastAPI dependency — yields a DB session and closes it after the request
# ---------------------------------------------------------------------------

def get_db() -> Generator[Session, None, None]:
    """
    Yield a SQLAlchemy session for use in FastAPI route dependencies.
    Always closes the session when the request is done, even on error.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

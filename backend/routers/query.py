"""
routers/query.py — POST /query endpoint.

Orchestrates the full query pipeline:
  1. Validate input
  2. Run query planner → get strategy + cross-doc flag + entities
  3. Dispatch to the appropriate search function:
       keyword  → BM25 search only
       semantic → vector search only
       hybrid   → hybrid (RRF) search
  4. If needs_cross_doc → run entity join on top of search results
  5. Log the query + result chunk IDs to query_logs
  6. Return structured response

Request body:
  {
    "query":  str,        # required — the natural language question
    "top_k":  int = 5     # optional — number of results to return
  }

Response:
  {
    "query":           str,
    "strategy":        "keyword" | "semantic" | "hybrid",
    "reasoning":       str,
    "results": [
      {
        "chunk_id":      int,
        "document_id":   int,
        "document_name": str,
        "document_type": str,
        "content":       str,
        "page_number":   int | None,
        "chunk_index":   int,
        "score":         float,
        "search_type":   str
      }
    ],
    "entity_join":     dict | None,   # present only when needs_cross_doc=True
    "log_id":          int            # query_logs row id
  }
"""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from query_planner import plan_query
from query_logs import log_query
from search.vector_search import vector_search
from search.bm25_search import bm25_search
from search.hybrid_search import hybrid_search
from search.entity_join import entity_join

# ---------------------------------------------------------------------------
# Router setup
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/query",
    tags=["query"],
)

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """Input model for the /query endpoint."""
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language question to ask across your documents",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of chunks to return (1–20, default 5)",
    )


class ChunkResult(BaseModel):
    """A single search result chunk."""
    chunk_id:      int
    document_id:   int
    document_name: str
    document_type: str
    content:       str
    page_number:   Optional[int]
    chunk_index:   int
    score:         float
    search_type:   str


class QueryResponse(BaseModel):
    """Full response from the /query endpoint."""
    query:       str
    strategy:    str
    reasoning:   str
    results:     list[ChunkResult]
    entity_join: Optional[dict]
    log_id:      Optional[int]
    elapsed_ms:  int


# ---------------------------------------------------------------------------
# POST /query/
# ---------------------------------------------------------------------------

@router.post("/", response_model=QueryResponse)
def run_query(
    request: QueryRequest,
    db: Session = Depends(get_db),
):
    """
    Run a natural language query across all ingested documents.

    Pipeline:
      1. Query planner classifies intent → strategy + entities
      2. Search dispatched to vector / BM25 / hybrid based on strategy
      3. Entity join performed if cross-document signals detected
      4. Result logged to query_logs table
      5. Structured response returned
    """
    t0 = time.time()
    query = request.query.strip()
    top_k = request.top_k

    print(f"\n{'='*60}")
    print(f"[query] Incoming query: '{query[:100]}'")
    print(f"[query] top_k={top_k}")
    print(f"{'='*60}")

    # --- Step 1: Query planner ---
    try:
        decision = plan_query(query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query planner failed: {e}")

    # --- Step 2: Search dispatch ---
    results: list[dict[str, Any]] = []

    try:
        if decision.strategy == "keyword":
            print(f"[query] Dispatching to BM25 search...")
            results = bm25_search(query, db, top_k=top_k)

        elif decision.strategy == "semantic":
            print(f"[query] Dispatching to vector search...")
            results = vector_search(query, db, top_k=top_k)

        elif decision.strategy == "hybrid":
            print(f"[query] Dispatching to hybrid search (RRF)...")
            results = hybrid_search(query, db, top_k=top_k)

        else:
            # Fallback — should never happen, but be safe
            print(f"[query] Unknown strategy '{decision.strategy}', falling back to vector")
            results = vector_search(query, db, top_k=top_k)

    except RuntimeError as e:
        # Ollama down, DB error, etc.
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")

    if not results:
        print(f"[query] No results found for strategy={decision.strategy}")

    # --- Step 3: Entity join (if needed) ---
    entity_join_result: Optional[dict] = None

    if decision.needs_cross_doc and decision.entities:
        print(f"[query] Running cross-document entity join for entities: {decision.entities}")
        try:
            entity_join_result = entity_join(
                entities=decision.entities,
                db=db,
                base_results=results,
            )
        except Exception as e:
            # Entity join failure is non-fatal — log and continue
            print(f"[query] Entity join failed (non-fatal): {e}")
            entity_join_result = {"error": str(e), "entity_matches": {}, "document_overlap": []}

    # --- Step 4: Log to query_logs ---
    result_chunk_ids = [r["chunk_id"] for r in results]
    log_id: Optional[int] = None

    try:
        log_entry = log_query(
            db=db,
            query=query,
            planner_decision=decision.strategy,
            result_chunk_ids=result_chunk_ids,
        )
        log_id = log_entry.id
    except RuntimeError as e:
        # Logging failure is non-fatal — warn and continue
        print(f"[query] WARNING: {e}")

    # --- Step 5: Build response ---
    elapsed_ms = int((time.time() - t0) * 1000)

    print(f"\n[query] ✓ Complete in {elapsed_ms}ms — strategy={decision.strategy}, "
          f"results={len(results)}, log_id={log_id}")
    print(f"{'='*60}\n")

    return QueryResponse(
        query=query,
        strategy=decision.strategy,
        reasoning=decision.reasoning,
        results=[ChunkResult(**r) for r in results],
        entity_join=entity_join_result,
        log_id=log_id,
        elapsed_ms=elapsed_ms,
    )

"""
routers/answer.py — POST /answer/ endpoint with Server-Sent Events streaming.

This endpoint is the full end-to-end pipeline:
  1. Validate input (query + top_k)
  2. Run query planner → strategy + entities
  3. Run appropriate search (keyword/semantic/hybrid)
  4. Run entity join if cross-doc signals detected
  5. Log to query_logs
  6. Stream LLM answer token-by-token via SSE
  7. Send final citations event

SSE format:
  Each event is a line: data: <json>\n\n

  Token event:
    data: {"type": "token", "content": "word "}

  Meta event (sent before tokens, contains planner info):
    data: {"type": "meta", "strategy": "hybrid", "reasoning": "...", "chunk_count": 5}

  Citations event (sent after all tokens):
    data: {"type": "citations", "sources": [...]}

  Error event:
    data: {"type": "error", "message": "..."}

  Done event (always last):
    data: {"type": "done"}

The frontend connects via EventSource or fetch with ReadableStream and
renders tokens as they arrive.

Note on FastAPI + SSE:
  We use StreamingResponse with a synchronous generator wrapped in an async
  generator. The generator calls stream_answer() from ollama_client.py which
  uses httpx's synchronous streaming API. This works fine for a local dev
  server — for production you'd want to use httpx.AsyncClient with async
  streaming, but that adds complexity without benefit here.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from query_planner import plan_query
from query_logs import log_query
from search.vector_search import vector_search
from search.bm25_search import bm25_search
from search.hybrid_search import hybrid_search
from search.entity_join import entity_join
from llm.ollama_client import stream_answer

# ---------------------------------------------------------------------------
# Router setup
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/answer",
    tags=["answer"],
)

# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class AnswerRequest(BaseModel):
    """Input model for the /answer/ endpoint."""
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language question to answer from your documents",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Number of source chunks to feed to the LLM (1–10, default 5)",
    )


# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------

def _sse(data: dict) -> str:
    """Format a dict as a Server-Sent Events data line."""
    return f"data: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# POST /answer/
# ---------------------------------------------------------------------------

@router.post("/")
async def answer_query(
    request: AnswerRequest,
    db: Session = Depends(get_db),
):
    """
    Run the full pipeline and stream the LLM answer via Server-Sent Events.

    The response is text/event-stream. The frontend should use EventSource
    or fetch() with a ReadableStream to consume it.

    Pipeline:
      1. Query planner → strategy
      2. Search (keyword/semantic/hybrid)
      3. Entity join (if cross-doc)
      4. Log to query_logs
      5. Stream LLM answer token by token
      6. Send citations as final event
    """
    query = request.query.strip()
    top_k = request.top_k

    print(f"\n{'='*60}")
    print(f"[answer] Incoming query: '{query[:100]}'")
    print(f"[answer] top_k={top_k}")
    print(f"{'='*60}")

    # Run the pipeline synchronously before streaming starts
    # (search + planner are fast; streaming is the slow part)
    try:
        # Step 1 — Planner
        decision = plan_query(query)

        # Step 2 — Search
        results: list[dict[str, Any]] = []
        if decision.strategy == "keyword":
            results = bm25_search(query, db, top_k=top_k)
        elif decision.strategy == "semantic":
            results = vector_search(query, db, top_k=top_k)
        else:
            results = hybrid_search(query, db, top_k=top_k)

        # Step 3 — Entity join (non-fatal)
        entity_join_result: Optional[dict] = None
        if decision.needs_cross_doc and decision.entities:
            try:
                entity_join_result = entity_join(
                    entities=decision.entities,
                    db=db,
                    base_results=results,
                )
            except Exception as e:
                print(f"[answer] Entity join failed (non-fatal): {e}")

        # Step 4 — Log
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
            print(f"[answer] WARNING: {e}")

    except Exception as e:
        # If the pipeline itself fails, return a non-streaming error
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")

    print(f"[answer] Pipeline complete — strategy={decision.strategy}, "
          f"chunks={len(results)}, log_id={log_id}")

    # -----------------------------------------------------------------------
    # Build the SSE streaming generator
    # -----------------------------------------------------------------------

    def event_stream():
        """
        Synchronous generator that yields SSE-formatted strings.
        FastAPI's StreamingResponse will iterate this and send each chunk
        to the client as it's produced.
        """
        # Event 1: meta — send planner info immediately so the UI can show it
        yield _sse({
            "type":        "meta",
            "strategy":    decision.strategy,
            "reasoning":   decision.reasoning,
            "chunk_count": len(results),
            "log_id":      log_id,
            "needs_cross_doc": decision.needs_cross_doc,
            "entity_join": entity_join_result,
        })

        if not results:
            yield _sse({
                "type":    "token",
                "content": "No relevant documents found. Please upload some documents first.",
            })
            yield _sse({"type": "citations", "sources": []})
            yield _sse({"type": "done"})
            return

        # Events 2..N: stream tokens from Ollama
        for event_json in stream_answer(query=query, chunks=results):
            yield f"data: {event_json}\n\n"

        # Final event: done
        yield _sse({"type": "done"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # Prevent buffering at every layer
            "Cache-Control":       "no-cache",
            "X-Accel-Buffering":   "no",
            "Connection":          "keep-alive",
            # Allow the frontend to read these headers
            "Access-Control-Allow-Origin": "*",
        },
    )

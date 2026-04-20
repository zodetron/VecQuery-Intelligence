"""
search/vector_search.py — pgvector cosine similarity search.

How it works:
  1. Embed the query string using Ollama nomic-embed-text (768 dims)
  2. Check how many embeddings exist in the table
  3. Choose search mode:
       - exact scan  (count < 100): plain ORDER BY <=> with no index hint.
         The ivfflat index requires at least as many vectors as its `lists`
         parameter (we created it with lists=100) before it returns any results.
         Below that threshold pgvector silently returns 0 rows when the index
         is used, so we must force a sequential scan instead.
       - index scan  (count >= 100): normal query; the planner will use the
         ivfflat index automatically.
  4. Join back to chunks and documents to return full context.
  5. Return top-k results sorted by similarity score descending.
     No score threshold — all top_k rows are returned regardless of score.

Raw SQL is used instead of ORM because pgvector's <=> operator requires
explicit CAST to the vector type, which is cleaner in raw SQL.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ingestion import embed_text   # reuse the same Ollama embedding function

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TOP_K = 5

# ivfflat index was created with lists=100, so it needs at least 100 rows
# before the planner will use it and return correct results.
IVFFLAT_MIN_ROWS = 100


# ---------------------------------------------------------------------------
# Main search function
# ---------------------------------------------------------------------------

def vector_search(
    query: str,
    db: Session,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """
    Perform semantic similarity search using pgvector cosine distance.

    Args:
        query:  The natural language query string.
        db:     SQLAlchemy session.
        top_k:  Number of top results to return (default 5).

    Returns:
        List of result dicts sorted by similarity score descending.
        No minimum score threshold — always returns up to top_k rows.

        [
          {
            "chunk_id":      int,
            "document_id":   int,
            "document_name": str,
            "document_type": str,
            "content":       str,
            "page_number":   int | None,
            "chunk_index":   int,
            "score":         float,   # cosine similarity (0–1, higher = more similar)
            "search_type":   "vector"
          },
          ...
        ]

    Raises:
        RuntimeError: if Ollama is unreachable or the DB query fails.
    """
    print(f"\n[vector_search] Query: '{query[:80]}' | top_k={top_k}")
    t0 = time.time()

    # ------------------------------------------------------------------
    # Step 1 — Count embeddings to decide which search mode to use
    # ------------------------------------------------------------------
    try:
        count_row = db.execute(text("SELECT COUNT(*) FROM embeddings")).fetchone()
        embedding_count = int(count_row[0]) if count_row else 0
    except Exception as e:
        raise RuntimeError(f"[vector_search] Failed to count embeddings: {e}") from e

    use_exact = embedding_count < IVFFLAT_MIN_ROWS
    mode = "exact sequential scan" if use_exact else "ivfflat index"
    print(f"[vector_search] {embedding_count} embeddings in table — using {mode}")

    # ------------------------------------------------------------------
    # Step 2 — Embed the query
    # ------------------------------------------------------------------
    print("[vector_search] Embedding query via Ollama...")
    t_embed = time.time()
    query_vector = embed_text(query)
    print(f"[vector_search] Query embedded in {round(time.time() - t_embed, 2)}s")

    # Build the pgvector literal: "[0.1, 0.2, ...]"
    vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"

    # ------------------------------------------------------------------
    # Step 3 — Run the search
    #
    # Exact mode:  SET LOCAL enable_indexscan = off forces the planner to
    #              skip the ivfflat index and do a full sequential scan.
    #              This is safe inside a single query execution.
    #
    # Index mode:  Normal query — the planner uses the ivfflat index.
    #
    # Both modes use the same SELECT; only the index hint differs.
    # No WHERE clause filtering on score — we return all top_k rows.
    # ------------------------------------------------------------------
    select_sql = """
        SELECT
            c.id            AS chunk_id,
            c.document_id,
            d.name          AS document_name,
            d.type          AS document_type,
            c.content,
            c.page_number,
            c.chunk_index,
            1 - (e.vector <=> CAST(:query_vec AS vector)) AS similarity
        FROM embeddings e
        JOIN chunks c    ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        ORDER BY e.vector <=> CAST(:query_vec AS vector)
        LIMIT :top_k
    """

    try:
        if use_exact:
            # Disable index scans for this transaction so the planner is
            # forced to do a sequential scan — required when row count is
            # below the ivfflat lists threshold.
            db.execute(text("SET LOCAL enable_indexscan = off"))

        rows = db.execute(
            text(select_sql),
            {"query_vec": vector_literal, "top_k": top_k},
        ).fetchall()

    except Exception as e:
        raise RuntimeError(f"[vector_search] Database query failed: {e}") from e

    # ------------------------------------------------------------------
    # Step 4 — Format results
    # ------------------------------------------------------------------
    results = []
    for row in rows:
        results.append({
            "chunk_id":      row.chunk_id,
            "document_id":   row.document_id,
            "document_name": row.document_name,
            "document_type": row.document_type,
            "content":       row.content,
            "page_number":   row.page_number,
            "chunk_index":   row.chunk_index,
            "score":         round(float(row.similarity), 6),
            "search_type":   "vector",
        })

    elapsed = round(time.time() - t0, 2)
    print(f"[vector_search] Found {len(results)} results in {elapsed}s (mode={mode})")
    for i, r in enumerate(results):
        print(f"  [{i+1}] chunk_id={r['chunk_id']} doc='{r['document_name']}' "
              f"page={r['page_number']} score={r['score']:.4f}")

    return results

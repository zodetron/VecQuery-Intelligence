"""
search/bm25_search.py — BM25 keyword search over stored term scores.

How it works:
  During ingestion, each chunk's BM25 term scores were computed corpus-wide
  and stored in chunk_metadata JSONB under the key "bm25_terms":
      {"word": 1.234, "another": 0.876, ...}

  At query time:
  1. Tokenize the query into terms
  2. Try the fast path: fetch only chunks that contain at least one query
     term using PostgreSQL's JSONB ? operator.
  3. If the fast path returns nothing (e.g. the query terms don't appear in
     any chunk's bm25_terms index — common with very small datasets where
     BM25 scores are low or the tokenizer produced different tokens), fall
     back to fetching ALL chunks and scoring them in Python.
  4. For each candidate chunk, sum the pre-computed BM25 scores for query
     terms that appear in that chunk.
  5. Sort by total score descending, return top-k.

  The fallback ensures results are returned for small datasets where the
  JSONB key-existence filter might be too strict.
"""

from __future__ import annotations

import re
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TOP_K = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize_query(query: str) -> list[str]:
    """
    Tokenize the query the same way ingestion.py tokenizes chunks:
    lowercase, alphanumeric only.
    Returns a deduplicated list of tokens.
    """
    return list(set(re.findall(r"[a-z0-9]+", query.lower())))


def _score_rows(rows: list, query_terms: list[str], top_k: int) -> list[dict[str, Any]]:
    """
    Score a list of DB rows against query_terms by summing their pre-computed
    BM25 scores, then return the top_k highest-scoring rows.

    If a chunk has no BM25 terms at all (e.g. metadata is missing), it is
    assigned a score of 0 and still included so the caller always gets
    something back from a non-empty table.
    """
    scored = []
    for row in rows:
        meta = row.chunk_metadata or {}
        bm25_terms = meta.get("bm25_terms", {})

        total_score = 0.0
        matched = []
        for term in query_terms:
            if term in bm25_terms:
                total_score += bm25_terms[term]
                matched.append(term)

        # Include the row even if score is 0 — the caller asked for results
        # and we should not silently drop chunks just because no term matched.
        scored.append({
            "chunk_id":      row.chunk_id,
            "document_id":   row.document_id,
            "document_name": row.document_name,
            "document_type": row.document_type,
            "content":       row.content,
            "page_number":   row.page_number,
            "chunk_index":   row.chunk_index,
            "score":         round(total_score, 6),
            "matched_terms": matched,
            "search_type":   "bm25",
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Main search function
# ---------------------------------------------------------------------------

def bm25_search(
    query: str,
    db: Session,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """
    Score chunks against the query using pre-computed BM25 term scores.

    Args:
        query:  The natural language or keyword query string.
        db:     SQLAlchemy session.
        top_k:  Number of top results to return (default 5).

    Returns:
        List of result dicts sorted by BM25 score descending.
        Always returns up to top_k results — no minimum score threshold.

        [
          {
            "chunk_id":      int,
            "document_id":   int,
            "document_name": str,
            "document_type": str,
            "content":       str,
            "page_number":   int | None,
            "chunk_index":   int,
            "score":         float,        # sum of BM25 scores for matched terms
            "matched_terms": list[str],
            "search_type":   "bm25"
          },
          ...
        ]
    """
    print(f"\n[bm25_search] Query: '{query[:80]}' | top_k={top_k}")
    t0 = time.time()

    # ------------------------------------------------------------------
    # Step 1 — Tokenize query
    # ------------------------------------------------------------------
    query_terms = _tokenize_query(query)
    if not query_terms:
        print("[bm25_search] No valid query terms after tokenization — returning empty")
        return []

    print(f"[bm25_search] Query terms: {query_terms}")

    # ------------------------------------------------------------------
    # Step 2 — Fast path: fetch only chunks that contain a query term
    #
    # The JSONB ? operator checks for key existence in bm25_terms.
    # Terms come from our own alphanumeric tokenizer so they are safe
    # to interpolate directly into the SQL string.
    # ------------------------------------------------------------------
    term_conditions = " OR ".join(
        f"c.chunk_metadata->'bm25_terms' ? '{term}'"
        for term in query_terms
    )

    fast_sql = text(f"""
        SELECT
            c.id            AS chunk_id,
            c.document_id,
            d.name          AS document_name,
            d.type          AS document_type,
            c.content,
            c.page_number,
            c.chunk_index,
            c.chunk_metadata
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.chunk_metadata IS NOT NULL
          AND c.chunk_metadata ? 'bm25_terms'
          AND ({term_conditions})
    """)

    try:
        fast_rows = db.execute(fast_sql).fetchall()
    except Exception as e:
        raise RuntimeError(f"[bm25_search] Database query failed: {e}") from e

    if fast_rows:
        print(f"[bm25_search] Fast path: {len(fast_rows)} candidate chunks (JSONB term filter)")
        results = _score_rows(fast_rows, query_terms, top_k)

    else:
        # ------------------------------------------------------------------
        # Step 3 — Fallback: fetch ALL chunks and score in Python
        #
        # This handles small datasets where:
        #   - The query terms don't appear in any chunk's bm25_terms keys
        #     (e.g. very short documents, different tokenization outcomes)
        #   - The chunk_metadata JSONB structure is slightly different
        #
        # We still score by BM25 terms where available; chunks with no
        # matching terms get score=0 but are still returned so the user
        # always sees something.
        # ------------------------------------------------------------------
        print("[bm25_search] Fast path returned 0 — falling back to full table scan")

        fallback_sql = text("""
            SELECT
                c.id            AS chunk_id,
                c.document_id,
                d.name          AS document_name,
                d.type          AS document_type,
                c.content,
                c.page_number,
                c.chunk_index,
                c.chunk_metadata
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            ORDER BY c.chunk_index
        """)

        try:
            all_rows = db.execute(fallback_sql).fetchall()
        except Exception as e:
            raise RuntimeError(f"[bm25_search] Fallback query failed: {e}") from e

        if not all_rows:
            print("[bm25_search] No chunks in database — returning empty")
            return []

        print(f"[bm25_search] Fallback: scoring all {len(all_rows)} chunks")
        results = _score_rows(all_rows, query_terms, top_k)

    # ------------------------------------------------------------------
    # Step 4 — Log and return
    # ------------------------------------------------------------------
    elapsed = round(time.time() - t0, 2)
    print(f"[bm25_search] Found {len(results)} results in {elapsed}s")
    for i, r in enumerate(results):
        print(f"  [{i+1}] chunk_id={r['chunk_id']} doc='{r['document_name']}' "
              f"page={r['page_number']} score={r['score']:.4f} "
              f"terms={r['matched_terms']}")

    return results

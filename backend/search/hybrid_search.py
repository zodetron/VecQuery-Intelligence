"""
search/hybrid_search.py — Reciprocal Rank Fusion (RRF) merge.

Combines results from vector search and BM25 search into a single unified
ranked list using the RRF formula:

    RRF_score(chunk) = Σ 1 / (k + rank_in_list_i)

where:
  - k is a constant (typically 60) to smooth the rank contribution
  - rank_in_list_i is the 1-indexed position of the chunk in each result list

RRF is robust to score scale differences between vector and BM25, and gives
higher weight to chunks that appear near the top of multiple lists.

References:
  - Cormack, Clarke, Buettcher (2009): "Reciprocal Rank Fusion outperforms
    the best system in the majority of topics"
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from search.vector_search import vector_search
from search.bm25_search import bm25_search

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TOP_K = 5
RRF_K = 60  # smoothing constant — standard value from literature


# ---------------------------------------------------------------------------
# Main hybrid search function
# ---------------------------------------------------------------------------

def hybrid_search(
    query: str,
    db: Session,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """
    Run both vector and BM25 search, then merge results using RRF.

    Args:
        query:  The natural language query string.
        db:     SQLAlchemy session.
        top_k:  Number of top results to return after merging (default 5).

    Returns:
        List of result dicts sorted by RRF score descending:
        [
          {
            "chunk_id":      int,
            "document_id":   int,
            "document_name": str,
            "document_type": str,
            "content":       str,
            "page_number":   int | None,
            "chunk_index":   int,
            "score":         float,   # RRF score
            "vector_rank":   int | None,  # 1-indexed rank in vector results (None if not present)
            "bm25_rank":     int | None,  # 1-indexed rank in BM25 results (None if not present)
            "search_type":   "hybrid"
          },
          ...
        ]
    """
    print(f"\n[hybrid_search] Query: '{query[:80]}' | top_k={top_k}")
    t0 = time.time()

    # Step 1 — Run both searches in parallel (conceptually; Python is sequential here)
    # We fetch more results (top_k * 2) from each to increase overlap chances
    fetch_k = max(top_k * 2, 10)

    print(f"[hybrid_search] Running vector search (fetch_k={fetch_k})...")
    vector_results = vector_search(query, db, top_k=fetch_k)

    print(f"[hybrid_search] Running BM25 search (fetch_k={fetch_k})...")
    bm25_results = bm25_search(query, db, top_k=fetch_k)

    # Step 2 — Build rank maps: chunk_id → rank (1-indexed)
    vector_ranks = {r["chunk_id"]: i + 1 for i, r in enumerate(vector_results)}
    bm25_ranks   = {r["chunk_id"]: i + 1 for i, r in enumerate(bm25_results)}

    # Step 3 — Collect all unique chunk IDs from both result sets
    all_chunk_ids = set(vector_ranks.keys()) | set(bm25_ranks.keys())

    print(f"[hybrid_search] Merging {len(vector_results)} vector + {len(bm25_results)} BM25 "
          f"→ {len(all_chunk_ids)} unique chunks")

    # Step 4 — Compute RRF score for each chunk
    rrf_scores: dict[int, float] = {}
    for chunk_id in all_chunk_ids:
        score = 0.0
        if chunk_id in vector_ranks:
            score += 1.0 / (RRF_K + vector_ranks[chunk_id])
        if chunk_id in bm25_ranks:
            score += 1.0 / (RRF_K + bm25_ranks[chunk_id])
        rrf_scores[chunk_id] = score

    # Step 5 — Sort by RRF score descending
    sorted_chunk_ids = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)

    # Step 6 — Build result list by looking up chunk details from either result set
    # (prefer vector results for metadata since they're more complete)
    chunk_map = {r["chunk_id"]: r for r in vector_results}
    chunk_map.update({r["chunk_id"]: r for r in bm25_results})  # BM25 fills in any gaps

    results = []
    for chunk_id in sorted_chunk_ids[:top_k]:
        chunk = chunk_map[chunk_id]
        results.append({
            "chunk_id":      chunk_id,
            "document_id":   chunk["document_id"],
            "document_name": chunk["document_name"],
            "document_type": chunk["document_type"],
            "content":       chunk["content"],
            "page_number":   chunk["page_number"],
            "chunk_index":   chunk["chunk_index"],
            "score":         round(rrf_scores[chunk_id], 6),
            "vector_rank":   vector_ranks.get(chunk_id),
            "bm25_rank":     bm25_ranks.get(chunk_id),
            "search_type":   "hybrid",
        })

    elapsed = round(time.time() - t0, 2)
    print(f"[hybrid_search] Merged to {len(results)} results in {elapsed}s")
    for i, r in enumerate(results):
        print(f"  [{i+1}] chunk_id={r['chunk_id']} doc='{r['document_name']}' "
              f"page={r['page_number']} rrf_score={r['score']:.6f} "
              f"(vector_rank={r['vector_rank']}, bm25_rank={r['bm25_rank']})")

    return results

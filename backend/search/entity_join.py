"""
search/entity_join.py — Cross-document entity joining.

When the query planner flags needs_cross_doc=True, this module:
  1. Takes the named entities extracted from the query
  2. Searches for those entities across chunks from ALL documents
  3. Groups matching chunks by document
  4. Returns a structured result showing which documents share common entities
     and which chunks from each document are most relevant

This enables queries like:
  - "Compare the revenue figures in the Q3 report and the annual summary"
  - "Find all mentions of Acme Corp across both documents"
  - "What does the invoice and the contract say about payment terms?"

The entity search uses PostgreSQL full-text ILIKE for case-insensitive matching,
which is simple and effective for a local system. For production, a GIN index
on the content column would make this faster.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CHUNKS_PER_ENTITY = 3   # max chunks to return per entity per document
MAX_CONTEXT_CHARS = 300     # how many chars of content to include in snippet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snippet(content: str, entity: str, context_chars: int = MAX_CONTEXT_CHARS) -> str:
    """
    Extract a snippet of text around the first occurrence of `entity` in `content`.
    Returns the surrounding context_chars characters, with the entity highlighted
    using >>> markers.
    """
    idx = content.lower().find(entity.lower())
    if idx == -1:
        # Entity not found literally — return start of content
        return content[:context_chars] + ("..." if len(content) > context_chars else "")

    # Center the window around the entity
    half = context_chars // 2
    start = max(0, idx - half)
    end   = min(len(content), idx + len(entity) + half)
    snippet = content[start:end]

    # Add ellipsis if we truncated
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."

    return snippet


# ---------------------------------------------------------------------------
# Main entity join function
# ---------------------------------------------------------------------------

def entity_join(
    entities: list[str],
    db: Session,
    base_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Find chunks across all documents that mention the given entities,
    then group them by document to show cross-document connections.

    Args:
        entities:     List of entity strings extracted by the query planner.
        db:           SQLAlchemy session.
        base_results: The initial search results (from vector/BM25/hybrid).
                      Used to identify which documents are already in scope.

    Returns:
        A dict with:
        {
          "entity_matches": {
            "EntityName": [
              {
                "document_id":   int,
                "document_name": str,
                "chunk_id":      int,
                "page_number":   int | None,
                "snippet":       str,   # text around the entity mention
              },
              ...
            ]
          },
          "document_overlap": [
            {
              "document_id":   int,
              "document_name": str,
              "shared_entities": list[str],  # entities found in this doc
              "chunk_ids":     list[int],
            }
          ],
          "summary": str   # human-readable summary of cross-doc connections
        }
    """
    print(f"\n[entity_join] Searching for entities: {entities}")
    t0 = time.time()

    if not entities:
        print("[entity_join] No entities to search for — skipping")
        return {"entity_matches": {}, "document_overlap": [], "summary": "No entities detected."}

    # Step 1 — For each entity, find chunks that mention it (ILIKE = case-insensitive)
    entity_matches: dict[str, list[dict[str, Any]]] = {}

    for entity in entities:
        # Skip very short entities (single chars, common words) to avoid noise
        if len(entity) < 3:
            continue

        sql = text("""
            SELECT
                c.id            AS chunk_id,
                c.document_id,
                d.name          AS document_name,
                c.content,
                c.page_number,
                c.chunk_index
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.content ILIKE :pattern
            ORDER BY c.document_id, c.chunk_index
            LIMIT :limit
        """)

        try:
            rows = db.execute(sql, {
                "pattern": f"%{entity}%",
                "limit":   MAX_CHUNKS_PER_ENTITY * 10,  # fetch more, then group
            }).fetchall()
        except Exception as e:
            print(f"[entity_join] DB error searching for '{entity}': {e}")
            continue

        if not rows:
            print(f"[entity_join] No matches for entity '{entity}'")
            continue

        # Group by document, keep top MAX_CHUNKS_PER_ENTITY per doc
        doc_chunks: dict[int, list] = {}
        for row in rows:
            doc_id = row.document_id
            if doc_id not in doc_chunks:
                doc_chunks[doc_id] = []
            if len(doc_chunks[doc_id]) < MAX_CHUNKS_PER_ENTITY:
                doc_chunks[doc_id].append({
                    "document_id":   row.document_id,
                    "document_name": row.document_name,
                    "chunk_id":      row.chunk_id,
                    "page_number":   row.page_number,
                    "snippet":       _make_snippet(row.content, entity),
                })

        # Flatten
        matches = []
        for doc_id, chunks in doc_chunks.items():
            matches.extend(chunks)

        entity_matches[entity] = matches
        print(f"[entity_join] Entity '{entity}': found in {len(doc_chunks)} documents, "
              f"{len(matches)} chunk matches")

    # Step 2 — Build document overlap map
    # For each document, which entities appear in it?
    doc_entity_map: dict[int, dict[str, Any]] = {}
    for entity, matches in entity_matches.items():
        for match in matches:
            doc_id = match["document_id"]
            if doc_id not in doc_entity_map:
                doc_entity_map[doc_id] = {
                    "document_id":    doc_id,
                    "document_name":  match["document_name"],
                    "shared_entities": [],
                    "chunk_ids":      [],
                }
            if entity not in doc_entity_map[doc_id]["shared_entities"]:
                doc_entity_map[doc_id]["shared_entities"].append(entity)
            if match["chunk_id"] not in doc_entity_map[doc_id]["chunk_ids"]:
                doc_entity_map[doc_id]["chunk_ids"].append(match["chunk_id"])

    document_overlap = list(doc_entity_map.values())

    # Step 3 — Build a human-readable summary
    if not entity_matches:
        summary = "No entity matches found across documents."
    elif len(document_overlap) == 1:
        doc = document_overlap[0]
        summary = (
            f"Entities {list(entity_matches.keys())} were found only in "
            f"'{doc['document_name']}'. No cross-document connections detected."
        )
    else:
        doc_names = [d["document_name"] for d in document_overlap]
        # Find entities that appear in more than one document
        shared = [
            e for e, matches in entity_matches.items()
            if len({m["document_id"] for m in matches}) > 1
        ]
        if shared:
            summary = (
                f"Cross-document connections found: entities {shared} appear in "
                f"multiple documents: {doc_names}."
            )
        else:
            summary = (
                f"Entities found across {len(document_overlap)} documents "
                f"({doc_names}), but each entity appears in only one document."
            )

    elapsed = round(time.time() - t0, 2)
    print(f"[entity_join] Complete in {elapsed}s — {len(entity_matches)} entities, "
          f"{len(document_overlap)} documents with matches")
    print(f"[entity_join] Summary: {summary}")

    return {
        "entity_matches":   entity_matches,
        "document_overlap": document_overlap,
        "summary":          summary,
    }

"""
query_logs.py — Write query audit records to the query_logs table.

Every query that passes through the /query endpoint is logged here with:
  - The raw query text
  - The planner's strategy decision
  - The list of chunk IDs returned
  - A timestamp (set by the DB default)

This provides a full audit trail and can be used later for:
  - Analytics (most common queries, strategy distribution)
  - Feedback loops (which results were clicked / rated)
  - Debugging (replay a query to see what it returned)
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from database import QueryLog


def log_query(
    db: Session,
    query: str,
    planner_decision: str,
    result_chunk_ids: list[int],
) -> QueryLog:
    """
    Insert a new row into the query_logs table.

    Args:
        db:               SQLAlchemy session (will be committed here).
        query:            The raw user query string.
        planner_decision: The strategy chosen by the planner ("keyword", "semantic", "hybrid").
        result_chunk_ids: List of chunk IDs that were returned to the user.

    Returns:
        The saved QueryLog ORM object (with its auto-assigned id).

    Raises:
        RuntimeError: if the DB insert fails (non-fatal — caller should catch and continue).
    """
    try:
        log_entry = QueryLog(
            query=query,
            planner_decision=planner_decision,
            result_chunk_ids=result_chunk_ids,
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        print(f"[query_log] Logged query id={log_entry.id} strategy={planner_decision} "
              f"chunks={result_chunk_ids}")
        return log_entry

    except Exception as e:
        db.rollback()
        # Logging failure should not crash the query — just warn
        raise RuntimeError(f"[query_log] Failed to write query log: {e}") from e

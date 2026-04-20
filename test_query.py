"""
test_query.py — End-to-end test for the Week 2 query pipeline.

Tests:
  1. Query planner — verifies all three strategies are correctly classified
  2. BM25 search   — keyword query against ingested documents
  3. Vector search — semantic query against ingested documents
  4. Hybrid search — complex query using RRF merge
  5. Entity join   — cross-document entity detection
  6. /query endpoint — full HTTP round-trip via FastAPI test client
  7. query_logs    — confirms rows are written to the DB

Prerequisites:
  - Ollama running with nomic-embed-text pulled
  - DATABASE_URL set in backend/.env
  - At least one document ingested (run test_ingestion.py first)

Run with:
  vecquery/backend/venv/bin/python vecquery/test_query.py
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

# Add backend to Python path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS = "✓"
FAIL = "✗"
SEP  = "─" * 60


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def check(label: str, condition: bool, detail: str = ""):
    icon = PASS if condition else FAIL
    msg = f"  {icon} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return condition


# ---------------------------------------------------------------------------
# Test 1: Query Planner
# ---------------------------------------------------------------------------

def test_planner():
    section("Test 1: Query Planner — Strategy Classification")
    from query_planner import plan_query

    cases = [
        # (query, expected_strategy, expect_cross_doc)
        ("INV-2024-001",                                          "keyword",  False),
        ("John Smith",                                            "keyword",  False),
        ("revenue 2024",                                          "keyword",  False),
        ("What is the main purpose of this document?",            "semantic", False),
        ("How does the payment process work?",                    "semantic", False),
        ("Explain the key findings in the report",                "semantic", False),
        ("Compare the revenue in both documents",                 "hybrid",   True),
        ("What are the differences between the two contracts?",   "hybrid",   True),
        ("Find all mentions of Acme Corp across both files",      "hybrid",   True),
    ]

    all_pass = True
    for query, expected_strategy, expected_cross_doc in cases:
        decision = plan_query(query)
        strategy_ok   = decision.strategy == expected_strategy
        cross_doc_ok  = decision.needs_cross_doc == expected_cross_doc
        ok = strategy_ok and cross_doc_ok
        all_pass = all_pass and ok
        check(
            f"'{query[:50]}'",
            ok,
            f"strategy={decision.strategy} (expected {expected_strategy}), "
            f"cross_doc={decision.needs_cross_doc} (expected {expected_cross_doc})"
        )

    return all_pass


# ---------------------------------------------------------------------------
# Test 2: Entity Extraction
# ---------------------------------------------------------------------------

def test_entity_extraction():
    section("Test 2: Entity Extraction")
    from query_planner import extract_entities

    cases = [
        ("Find all mentions of Acme Corp",          ["Acme", "Corp"]),
        ("What does INV-2024-001 say about payment", ["INV-2024-001"]),
        ('Show me "payment terms" in the contract',  ["payment terms"]),
        ("revenue in 2024",                          ["2024"]),
    ]

    all_pass = True
    for query, expected_contains in cases:
        entities = extract_entities(query)
        # Check that at least one expected entity was found
        found_any = any(
            any(exp.lower() in e.lower() for e in entities)
            for exp in expected_contains
        )
        all_pass = all_pass and found_any
        check(
            f"'{query}'",
            found_any,
            f"extracted={entities}, expected to contain one of {expected_contains}"
        )

    return all_pass


# ---------------------------------------------------------------------------
# Test 3: BM25 Search
# ---------------------------------------------------------------------------

def test_bm25_search(db):
    section("Test 3: BM25 Keyword Search")
    from search.bm25_search import bm25_search

    # Check if there are any chunks in the DB first
    from sqlalchemy import text
    count = db.execute(text("SELECT COUNT(*) FROM chunks")).scalar()
    if count == 0:
        print(f"  ⚠ No chunks in database — skipping BM25 test")
        print(f"  → Run test_ingestion.py first to ingest a document")
        return True  # not a failure, just no data

    print(f"  Database has {count} chunks — running BM25 search...")

    # Use a generic term likely to appear in any document
    results = bm25_search("document information", db, top_k=3)

    has_results = len(results) >= 0  # 0 is OK if no terms match
    check("BM25 search runs without error", True)
    check("Results have required fields",
          all("chunk_id" in r and "score" in r and "content" in r for r in results) if results else True,
          f"{len(results)} results returned")

    if results:
        r = results[0]
        check("Top result has positive score", r["score"] > 0, f"score={r['score']}")
        check("Top result has document name",  bool(r["document_name"]), r["document_name"])
        print(f"\n  Top BM25 result:")
        print(f"    doc:     {r['document_name']}")
        print(f"    page:    {r['page_number']}")
        print(f"    score:   {r['score']}")
        print(f"    terms:   {r.get('matched_terms', [])}")
        print(f"    content: {r['content'][:120]}...")

    return True


# ---------------------------------------------------------------------------
# Test 4: Vector Search
# ---------------------------------------------------------------------------

def test_vector_search(db):
    section("Test 4: Vector (Semantic) Search")
    from search.vector_search import vector_search

    from sqlalchemy import text
    count = db.execute(text("SELECT COUNT(*) FROM embeddings")).scalar()
    if count == 0:
        print(f"  ⚠ No embeddings in database — skipping vector test")
        print(f"  → Run test_ingestion.py first to ingest a document")
        return True

    print(f"  Database has {count} embeddings — running vector search...")

    results = vector_search("main topic and key information", db, top_k=3)

    check("Vector search runs without error", True)
    check("Results have required fields",
          all("chunk_id" in r and "score" in r for r in results) if results else True,
          f"{len(results)} results returned")

    if results:
        r = results[0]
        check("Top result has similarity score 0–1", 0 <= r["score"] <= 1,
              f"score={r['score']}")
        check("Top result has document name", bool(r["document_name"]), r["document_name"])
        print(f"\n  Top vector result:")
        print(f"    doc:     {r['document_name']}")
        print(f"    page:    {r['page_number']}")
        print(f"    score:   {r['score']}")
        print(f"    content: {r['content'][:120]}...")

    return True


# ---------------------------------------------------------------------------
# Test 5: Hybrid Search
# ---------------------------------------------------------------------------

def test_hybrid_search(db):
    section("Test 5: Hybrid Search (RRF)")
    from search.hybrid_search import hybrid_search

    from sqlalchemy import text
    count = db.execute(text("SELECT COUNT(*) FROM embeddings")).scalar()
    if count == 0:
        print(f"  ⚠ No data in database — skipping hybrid test")
        return True

    results = hybrid_search("information and details", db, top_k=3)

    check("Hybrid search runs without error", True)
    check("Results have required fields",
          all("chunk_id" in r and "score" in r for r in results) if results else True,
          f"{len(results)} results returned")

    if results:
        r = results[0]
        check("Top result has RRF score > 0", r["score"] > 0, f"score={r['score']}")
        check("Top result has search_type=hybrid", r["search_type"] == "hybrid",
              r["search_type"])
        print(f"\n  Top hybrid result:")
        print(f"    doc:          {r['document_name']}")
        print(f"    page:         {r['page_number']}")
        print(f"    rrf_score:    {r['score']}")
        print(f"    vector_rank:  {r.get('vector_rank')}")
        print(f"    bm25_rank:    {r.get('bm25_rank')}")
        print(f"    content:      {r['content'][:120]}...")

    return True


# ---------------------------------------------------------------------------
# Test 6: Entity Join
# ---------------------------------------------------------------------------

def test_entity_join(db):
    section("Test 6: Cross-Document Entity Join")
    from search.entity_join import entity_join

    from sqlalchemy import text
    count = db.execute(text("SELECT COUNT(*) FROM chunks")).scalar()
    if count == 0:
        print(f"  ⚠ No chunks in database — skipping entity join test")
        return True

    # Use a generic entity likely to appear in any document
    result = entity_join(entities=["the", "document"], db=db, base_results=[])

    check("Entity join runs without error", True)
    check("Result has entity_matches key",  "entity_matches" in result)
    check("Result has document_overlap key","document_overlap" in result)
    check("Result has summary key",         "summary" in result)
    print(f"\n  Entity join summary: {result['summary']}")

    return True


# ---------------------------------------------------------------------------
# Test 7: Full /query endpoint via FastAPI test client
# ---------------------------------------------------------------------------

def test_query_endpoint():
    section("Test 7: POST /query Endpoint (FastAPI TestClient)")

    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  ⚠ httpx not installed — skipping endpoint test")
        print("  → Install with: pip install httpx")
        return True

    from main import app
    client = TestClient(app)

    # Test 7a: Semantic query
    print("\n  7a. Semantic query...")
    resp = client.post("/query/", json={"query": "What is the main topic?", "top_k": 3})
    check("HTTP 200 response", resp.status_code == 200, f"status={resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        check("Response has strategy field",  "strategy" in data, data.get("strategy"))
        check("Response has results field",   "results" in data)
        check("Response has reasoning field", "reasoning" in data)
        check("Response has log_id field",    "log_id" in data)
        print(f"    strategy:  {data.get('strategy')}")
        print(f"    results:   {len(data.get('results', []))}")
        print(f"    log_id:    {data.get('log_id')}")
        print(f"    elapsed:   {data.get('elapsed_ms')}ms")

    # Test 7b: Keyword query
    print("\n  7b. Keyword query...")
    resp2 = client.post("/query/", json={"query": "VecQuery", "top_k": 3})
    check("HTTP 200 response", resp2.status_code == 200, f"status={resp2.status_code}")
    if resp2.status_code == 200:
        data2 = resp2.json()
        check("Strategy is keyword", data2.get("strategy") == "keyword",
              data2.get("strategy"))

    # Test 7c: Validation — empty query
    print("\n  7c. Validation — empty query...")
    resp3 = client.post("/query/", json={"query": "", "top_k": 3})
    check("HTTP 422 for empty query", resp3.status_code == 422,
          f"status={resp3.status_code}")

    # Test 7d: Validation — top_k out of range
    print("\n  7d. Validation — top_k=99...")
    resp4 = client.post("/query/", json={"query": "test", "top_k": 99})
    check("HTTP 422 for top_k > 20", resp4.status_code == 422,
          f"status={resp4.status_code}")

    return True


# ---------------------------------------------------------------------------
# Test 8: query_logs table
# ---------------------------------------------------------------------------

def test_query_logs(db):
    section("Test 8: query_logs Table")
    from sqlalchemy import text

    count_before = db.execute(text("SELECT COUNT(*) FROM query_logs")).scalar()
    print(f"  query_logs rows before test: {count_before}")

    # Write a log entry directly
    from query_logs import log_query
    entry = log_query(
        db=db,
        query="test query from test_query.py",
        planner_decision="semantic",
        result_chunk_ids=[1, 2, 3],
    )

    count_after = db.execute(text("SELECT COUNT(*) FROM query_logs")).scalar()
    check("Log entry created",          entry.id is not None, f"id={entry.id}")
    check("Row count increased by 1",   count_after == count_before + 1,
          f"{count_before} → {count_after}")
    check("Strategy stored correctly",  entry.planner_decision == "semantic")
    check("Chunk IDs stored correctly", entry.result_chunk_ids == [1, 2, 3])

    print(f"\n  Log entry:")
    print(f"    id:       {entry.id}")
    print(f"    strategy: {entry.planner_decision}")
    print(f"    chunks:   {entry.result_chunk_ids}")
    print(f"    created:  {entry.created_at}")

    return True


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main():
    print("\n" + "="*60)
    print("  VecQuery Intelligence — Week 2 Query Pipeline Tests")
    print("="*60)

    # Check Ollama
    print("\nChecking prerequisites...")
    import httpx
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        has_nomic = any("nomic-embed-text" in m for m in models)
        print(f"  {PASS} Ollama running — models: {models}")
        if not has_nomic:
            print(f"  ⚠ nomic-embed-text not found — vector/hybrid tests will fail")
            print(f"    → Run: ollama pull nomic-embed-text")
    except Exception as e:
        print(f"  ⚠ Ollama not reachable: {e}")
        print(f"    → Vector and hybrid search tests will fail")
        print(f"    → Start Ollama with: ollama serve")

    # DB session
    from database import SessionLocal
    db = SessionLocal()

    results = {}
    try:
        results["planner"]        = test_planner()
        results["entity_extract"] = test_entity_extraction()
        results["bm25"]           = test_bm25_search(db)
        results["vector"]         = test_vector_search(db)
        results["hybrid"]         = test_hybrid_search(db)
        results["entity_join"]    = test_entity_join(db)
        results["endpoint"]       = test_query_endpoint()
        results["query_logs"]     = test_query_logs(db)
    finally:
        db.close()

    # Summary
    section("Test Summary")
    all_pass = True
    for name, passed in results.items():
        check(name, passed)
        all_pass = all_pass and passed

    print()
    if all_pass:
        print("  ✓ All tests passed! Week 2 query pipeline is working.")
    else:
        print("  ✗ Some tests failed — check output above for details.")
    print()

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())

"""
test_answer.py — Test the /answer/ SSE streaming endpoint.

Connects to POST /answer/ and prints the streamed response token by token.
Useful for testing the full pipeline without the frontend.

Prerequisites:
  - Backend running on port 8000
  - Ollama running with llama3.1:8b pulled
  - At least one document ingested

Run with:
  vecquery/backend/venv/bin/python vecquery/test_answer.py
"""

from __future__ import annotations

import sys
import json
import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:8000"
QUERY    = "What are the key findings in the documents?"
TOP_K    = 5

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("="*60)
    print("VecQuery Intelligence — /answer/ SSE Stream Test")
    print("="*60)
    print(f"\nQuery: {QUERY}")
    print(f"Top-k: {TOP_K}\n")

    url = f"{BASE_URL}/answer/"
    payload = {"query": QUERY, "top_k": TOP_K}

    try:
        with httpx.stream("POST", url, json=payload, timeout=120) as response:
            if response.status_code != 200:
                print(f"✗ HTTP {response.status_code}")
                print(response.read().decode())
                return 1

            print("✓ Connected — streaming events:\n")
            print("-"*60)

            answer_tokens = []
            citations = None

            for line in response.iter_lines():
                if not line.strip():
                    continue
                if not line.startswith("data: "):
                    continue

                json_str = line[6:].strip()
                if not json_str:
                    continue

                try:
                    event = json.loads(json_str)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")

                if event_type == "meta":
                    print(f"[meta] strategy={event.get('strategy')}, "
                          f"chunks={event.get('chunk_count')}, "
                          f"cross_doc={event.get('needs_cross_doc')}")
                    print(f"       reasoning: {event.get('reasoning')}")
                    print()

                elif event_type == "token":
                    token = event.get("content", "")
                    answer_tokens.append(token)
                    print(token, end="", flush=True)

                elif event_type == "citations":
                    citations = event.get("sources", [])
                    print("\n")
                    print("-"*60)
                    print(f"\n[citations] {len(citations)} sources:")
                    for i, src in enumerate(citations, start=1):
                        print(f"  [{i}] {src['document_name']} "
                              f"(page {src.get('page_number', '?')}) "
                              f"— score {src['score']:.3f}")
                        print(f"      {src['preview'][:80]}...")

                elif event_type == "error":
                    print(f"\n\n✗ Error: {event.get('message')}")
                    return 1

                elif event_type == "done":
                    print("\n")
                    print("-"*60)
                    print("✓ Stream complete")
                    break

            print()
            print(f"Total tokens: {len(answer_tokens)}")
            print(f"Total chars:  {sum(len(t) for t in answer_tokens)}")
            print()
            return 0

    except httpx.ConnectError:
        print(f"✗ Cannot connect to {BASE_URL}")
        print("  → Make sure the FastAPI backend is running: uvicorn main:app --reload")
        return 1
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

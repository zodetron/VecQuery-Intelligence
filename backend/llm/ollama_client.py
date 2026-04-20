"""
llm/ollama_client.py — Streaming Llama 3.1 client for answer generation.

Responsibilities:
  1. Build a grounded prompt from the query + retrieved chunks
  2. Stream the response token-by-token from Ollama llama3.1:8b
  3. Enforce a context window budget — trim chunks if the prompt would be too long
  4. Yield each token as a string so the SSE router can forward it immediately
  5. Yield a final structured citations object after the stream ends

Prompt design:
  - System message instructs the model to answer ONLY from the provided sources
    and to cite every claim with [Source N]
  - Each chunk is presented as "Source N (document_name, page P):\n<content>"
  - The model is told to say "I don't know" if the answer isn't in the sources
  - This prevents hallucination and keeps answers grounded

Context window management:
  - llama3.1:8b has a 128k token context window, but we stay conservative
  - We estimate ~4 chars per token and cap the total prompt at MAX_PROMPT_CHARS
  - If chunks exceed the budget, we trim from the bottom (lowest-ranked chunks first)
"""

from __future__ import annotations

import json
from typing import Any, Generator

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL   = "http://localhost:11434"
LLM_MODEL         = "llama3.1:8b"
OLLAMA_TIMEOUT    = 120          # seconds — generation can take a while on CPU
MAX_PROMPT_CHARS  = 12000        # ~3000 tokens — conservative budget for M5 8GB
CHARS_PER_TOKEN   = 4            # rough estimate for English text


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(query: str, chunks: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """
    Build the full prompt string and return it along with the chunks that fit.

    The prompt structure:
      [SYSTEM]
      You are a precise document analyst. Answer the user's question using ONLY
      the provided sources. Cite every claim with [Source N]. If the answer is
      not in the sources, say "I don't have enough information in the provided
      documents to answer this question."

      [SOURCES]
      Source 1 (filename.pdf, page 3):
      <chunk content>

      Source 2 (other.csv, page 1):
      <chunk content>

      [QUESTION]
      <user query>

      [ANSWER]

    Returns:
        (prompt_string, trimmed_chunks_list)
        trimmed_chunks_list contains only the chunks that fit in the budget.
    """
    system = (
        "You are a precise document analyst. Answer the user's question using ONLY "
        "the information provided in the sources below. "
        "Cite every factual claim with [Source N] where N is the source number. "
        "If multiple sources support a claim, cite all of them, e.g. [Source 1][Source 2]. "
        "If the answer cannot be found in the provided sources, respond with exactly: "
        "\"I don't have enough information in the provided documents to answer this question.\"\n"
        "Do not use any prior knowledge. Do not make up information."
    )

    # Calculate budget: total chars minus system + query overhead
    overhead = len(system) + len(query) + 200   # 200 for formatting
    source_budget = MAX_PROMPT_CHARS - overhead

    # Build source blocks, trimming from the end if over budget
    source_blocks = []
    used_chars = 0
    included_chunks = []

    for i, chunk in enumerate(chunks, start=1):
        doc_name  = chunk.get("document_name", "unknown")
        page      = chunk.get("page_number")
        content   = chunk.get("content", "")
        page_str  = f", page {page}" if page else ""

        block = f"Source {i} ({doc_name}{page_str}):\n{content}"
        block_chars = len(block)

        if used_chars + block_chars > source_budget:
            # Trim this chunk's content to fit remaining budget
            remaining = source_budget - used_chars - len(f"Source {i} ({doc_name}{page_str}):\n") - 10
            if remaining > 100:   # only include if we can fit a meaningful snippet
                trimmed_content = content[:remaining] + "..."
                block = f"Source {i} ({doc_name}{page_str}):\n{trimmed_content}"
                source_blocks.append(block)
                included_chunks.append(chunk)
            break

        source_blocks.append(block)
        included_chunks.append(chunk)
        used_chars += block_chars

    sources_text = "\n\n".join(source_blocks)

    prompt = (
        f"{system}\n\n"
        f"--- SOURCES ---\n\n"
        f"{sources_text}\n\n"
        f"--- QUESTION ---\n\n"
        f"{query}\n\n"
        f"--- ANSWER ---\n\n"
    )

    return prompt, included_chunks


# ---------------------------------------------------------------------------
# Streaming generator
# ---------------------------------------------------------------------------

def stream_answer(
    query: str,
    chunks: list[dict[str, Any]],
) -> Generator[str, None, None]:
    """
    Stream the LLM answer token by token, then yield a final citations event.

    This is a synchronous generator — the FastAPI SSE router wraps it in
    an async generator using run_in_executor or iterates it directly.

    Yields:
        - For each token: a JSON string like:
            {"type": "token", "content": "word "}
        - After the stream ends: a JSON string like:
            {"type": "citations", "sources": [...], "strategy": "..."}
        - On error: a JSON string like:
            {"type": "error", "message": "..."}

    Args:
        query:  The user's question.
        chunks: List of search result dicts from the query pipeline.
    """
    print(f"\n[llm] Starting answer generation for: '{query[:80]}'")
    print(f"[llm] Input chunks: {len(chunks)}")

    if not chunks:
        yield json.dumps({"type": "token", "content": "No relevant documents found to answer this question."})
        yield json.dumps({"type": "citations", "sources": []})
        return

    # Build prompt
    prompt, included_chunks = _build_prompt(query, chunks)
    print(f"[llm] Prompt built: {len(prompt)} chars, {len(included_chunks)}/{len(chunks)} chunks fit")

    # Build citations list (for the final event)
    citations = []
    for i, chunk in enumerate(included_chunks, start=1):
        citations.append({
            "source_num":    i,
            "document_name": chunk.get("document_name", "unknown"),
            "document_type": chunk.get("document_type", ""),
            "page_number":   chunk.get("page_number"),
            "chunk_id":      chunk.get("chunk_id"),
            "score":         chunk.get("score", 0.0),
            "preview":       chunk.get("content", "")[:150].strip(),
        })

    # Stream from Ollama
    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model":  LLM_MODEL,
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": 0.1,    # low temperature for factual, grounded answers
            "top_p":       0.9,
            "num_predict": 1024,   # max tokens to generate
        },
    }

    token_count = 0
    try:
        with httpx.stream("POST", url, json=payload, timeout=OLLAMA_TIMEOUT) as response:
            if response.status_code != 200:
                error_body = response.read().decode()
                yield json.dumps({
                    "type":    "error",
                    "message": f"Ollama returned HTTP {response.status_code}: {error_body[:200]}",
                })
                return

            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                token = data.get("response", "")
                if token:
                    token_count += 1
                    yield json.dumps({"type": "token", "content": token})

                # Ollama signals end of stream with "done": true
                if data.get("done", False):
                    break

    except httpx.ConnectError:
        yield json.dumps({
            "type":    "error",
            "message": (
                f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. "
                "Make sure Ollama is running: ollama serve"
            ),
        })
        return
    except httpx.TimeoutException:
        yield json.dumps({
            "type":    "error",
            "message": f"Ollama timed out after {OLLAMA_TIMEOUT}s. Try a shorter query or fewer chunks.",
        })
        return
    except Exception as e:
        yield json.dumps({
            "type":    "error",
            "message": f"Unexpected error during generation: {e}",
        })
        return

    print(f"[llm] Stream complete — {token_count} tokens generated")

    # Final event: citations
    yield json.dumps({"type": "citations", "sources": citations})

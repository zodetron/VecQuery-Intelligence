"""
query_planner.py — Query intent classifier and strategy selector.

Analyzes a natural language query and returns a PlannerDecision that tells
the query router which search strategy to use and whether cross-document
entity joining is needed.

Strategy rules (applied in order, first match wins):
  1. hybrid  — query contains comparison/cross-doc signals ("compare", "both",
               "across", "match", "same", "versus", "vs", "difference between",
               "and also", "all documents", "every document")
  2. keyword — query is short (≤ 4 words) OR contains only proper nouns/IDs/
               numbers/dates with no question words
  3. semantic — everything else (how, why, what, explain, describe, summarize,
               tell me about, etc.)

Cross-document join detection:
  Flagged when the query contains signals that suggest the answer requires
  joining information from multiple documents.

File type hints:
  Detects if the query mentions a specific document type ("invoice", "report",
  "spreadsheet", "contract", "resume", "pdf", "csv") to help the router
  optionally filter results by document type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PlannerDecision:
    """
    The output of the query planner.

    Attributes:
        strategy:           One of "keyword", "semantic", "hybrid"
        needs_cross_doc:    True if the query asks about multiple documents
        target_file_types:  List of file type hints extracted from the query
        entities:           Named entities detected in the query (for entity join)
        reasoning:          Human-readable explanation of why this strategy was chosen
    """
    strategy:          str
    needs_cross_doc:   bool
    target_file_types: list[str]
    entities:          list[str]
    reasoning:         str


# ---------------------------------------------------------------------------
# Signal word lists
# ---------------------------------------------------------------------------

# Words that strongly suggest a cross-document comparison or join
CROSS_DOC_SIGNALS = {
    "compare", "comparison", "both", "across", "match", "matches", "matching",
    "same", "similar", "difference", "differences", "versus", "vs",
    "all documents", "every document", "multiple documents", "each document",
    "and also", "between documents", "from both", "in both",
}

# Words that suggest a semantic / conceptual question
SEMANTIC_SIGNALS = {
    "how", "why", "what", "explain", "describe", "summarize", "summary",
    "tell me", "overview", "meaning", "definition", "define", "concept",
    "understand", "analysis", "analyze", "analyse", "insight", "insights",
    "implication", "implications", "impact", "effect", "effects", "cause",
    "causes", "reason", "reasons", "purpose", "significance",
    "elaborate", "clarify", "outline", "review", "assess", "evaluate",
}

# Words that suggest a keyword / lookup query
KEYWORD_SIGNALS = {
    "find", "search", "lookup", "look up", "show", "list", "get",
    "fetch", "retrieve", "where is", "who is", "when was", "which",
}

# File type hints in natural language
FILE_TYPE_HINTS = {
    "invoice":     "pdf",
    "invoices":    "pdf",
    "report":      "pdf",
    "reports":     "pdf",
    "contract":    "pdf",
    "contracts":   "pdf",
    "resume":      "pdf",
    "resumes":     "pdf",
    "cv":          "pdf",
    "spreadsheet": "csv",
    "spreadsheets":"csv",
    "table":       "csv",
    "data":        "csv",
    "dataset":     "csv",
    "document":    "docx",
    "documents":   "docx",
    "letter":      "docx",
    "memo":        "docx",
    "pdf":         "pdf",
    "csv":         "csv",
    "docx":        "docx",
    "txt":         "txt",
    "text file":   "txt",
}


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

def extract_entities(query: str) -> list[str]:
    """
    Extract named entities from the query using simple heuristics:
      - Capitalized words (not at sentence start) → likely proper nouns
      - Numbers and codes (e.g. INV-001, 2024, $500)
      - Quoted strings

    This is intentionally lightweight — no NLP library required.
    For Week 3, this can be upgraded to use spaCy or an LLM.

    Returns a deduplicated list of entity strings.
    """
    entities = []

    # Quoted strings (highest confidence)
    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', query)
    for q in quoted:
        entity = q[0] or q[1]
        if entity:
            entities.append(entity.strip())

    # Capitalized words that are not the first word of the query
    # and not common English words
    COMMON_WORDS = {
        "The", "A", "An", "In", "On", "At", "To", "For", "Of", "And",
        "Or", "But", "Is", "Are", "Was", "Were", "Be", "Been", "Being",
        "Have", "Has", "Had", "Do", "Does", "Did", "Will", "Would",
        "Could", "Should", "May", "Might", "Can", "What", "Which",
        "Who", "When", "Where", "Why", "How", "This", "That", "These",
        "Those", "My", "Your", "His", "Her", "Its", "Our", "Their",
        "All", "Both", "Each", "Every", "Some", "Any", "No", "Not",
        "From", "With", "About", "Into", "Through", "During", "Before",
        "After", "Above", "Below", "Between", "Among", "Find", "Show",
        "List", "Get", "Tell", "Give", "Compare", "Explain", "Describe",
    }
    words = query.split()
    for i, word in enumerate(words):
        # Strip punctuation for matching
        clean = re.sub(r"[^a-zA-Z0-9\-_]", "", word)
        if not clean:
            continue
        # Capitalized but not a common word and not the very first word
        if clean[0].isupper() and clean not in COMMON_WORDS and i > 0:
            entities.append(clean)
        # Alphanumeric codes (e.g. INV-001, ABC123, Q3-2024)
        elif re.match(r"^[A-Z]{2,}[-_]?\w+$", clean):
            entities.append(clean)

    # Numbers and currency amounts
    numbers = re.findall(r"\$[\d,]+\.?\d*|\b\d{4}\b|\b\d+\.\d+\b", query)
    entities.extend(numbers)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for e in entities:
        if e.lower() not in seen:
            seen.add(e.lower())
            unique.append(e)

    return unique


# ---------------------------------------------------------------------------
# Main planner function
# ---------------------------------------------------------------------------

def plan_query(query: str) -> PlannerDecision:
    """
    Analyze the query and return a PlannerDecision.

    Decision logic (applied in order):
      1. If cross-doc signals present → hybrid + needs_cross_doc=True
      2. If query is very short (≤ 4 words) → keyword
      3. If query contains semantic question words → semantic
      4. If query contains keyword lookup words → keyword
      5. Default → semantic (safer for open-ended queries)

    Args:
        query: The raw user query string.

    Returns:
        PlannerDecision with strategy, cross-doc flag, file type hints, entities.
    """
    print(f"\n[planner] Analyzing query: '{query[:100]}'")

    query_lower = query.lower().strip()
    words = query_lower.split()

    # --- Detect cross-document signals ---
    needs_cross_doc = False
    cross_doc_reason = ""
    for signal in CROSS_DOC_SIGNALS:
        if signal in query_lower:
            needs_cross_doc = True
            cross_doc_reason = f"cross-doc signal '{signal}' detected"
            break

    # --- Detect file type hints ---
    target_file_types = []
    for hint, ftype in FILE_TYPE_HINTS.items():
        if hint in query_lower and ftype not in target_file_types:
            target_file_types.append(ftype)

    # --- Extract named entities ---
    entities = extract_entities(query)

    # --- Determine strategy ---

    # Rule 1: Cross-doc signals → always hybrid (needs both search types)
    if needs_cross_doc:
        strategy = "hybrid"
        reasoning = (
            f"Hybrid search selected: {cross_doc_reason}. "
            "Cross-document join will be performed."
        )

    # Rule 2: Very short query (≤ 3 words) → keyword (likely a lookup)
    elif len(words) <= 3:
        strategy = "keyword"
        reasoning = (
            f"Keyword search selected: query is short ({len(words)} words ≤ 3). "
            "Likely a direct lookup or name search."
        )

    # Rule 3: Contains semantic question words → semantic
    elif any(word in SEMANTIC_SIGNALS for word in words):
        matched = [w for w in words if w in SEMANTIC_SIGNALS]
        strategy = "semantic"
        reasoning = (
            f"Semantic search selected: question words {matched} detected. "
            "Query is conceptual/explanatory."
        )

    # Rule 4: Contains keyword lookup words → keyword
    elif any(word in KEYWORD_SIGNALS for word in words):
        matched = [w for w in words if w in KEYWORD_SIGNALS]
        strategy = "keyword"
        reasoning = (
            f"Keyword search selected: lookup words {matched} detected. "
            "Query is a direct retrieval request."
        )

    # Rule 5: Has entities but no question words → keyword
    elif entities and not any(word in SEMANTIC_SIGNALS for word in words):
        strategy = "keyword"
        reasoning = (
            f"Keyword search selected: named entities {entities} detected "
            "with no semantic question words."
        )

    # Default: semantic
    else:
        strategy = "semantic"
        reasoning = (
            "Semantic search selected by default: no strong keyword or "
            "cross-doc signals detected."
        )

    decision = PlannerDecision(
        strategy=strategy,
        needs_cross_doc=needs_cross_doc,
        target_file_types=target_file_types,
        entities=entities,
        reasoning=reasoning,
    )

    print(f"[planner] Strategy: {strategy.upper()}")
    print(f"[planner] Cross-doc join: {needs_cross_doc}")
    print(f"[planner] Entities: {entities}")
    print(f"[planner] File type hints: {target_file_types}")
    print(f"[planner] Reasoning: {reasoning}")

    return decision

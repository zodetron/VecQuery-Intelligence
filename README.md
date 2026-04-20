# VecQuery Intelligence ✅ Complete

VecQuery Intelligence is a cross-document natural language query engine that lets users upload PDFs, CSVs, and DOCX files and ask questions in plain English. It uses a hybrid search strategy combining pgvector (semantic similarity) and BM25 (keyword relevance), a custom query planner that decides which search mode to use, cross-document entity joining to surface answers that span multiple files, and local Llama 3.1 8B via Ollama for answer generation — all with zero API cost.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.9, FastAPI, Uvicorn |
| Database | Supabase (PostgreSQL + pgvector extension) |
| ORM | SQLAlchemy 2.0 |
| DB Driver | psycopg 3.1 (psycopg3) |
| PDF Parsing | PyMuPDF (fitz) |
| DOCX Parsing | python-docx |
| CSV Parsing | Python standard library csv module |
| Embeddings | Ollama — nomic-embed-text (768 dimensions) |
| LLM | Ollama — llama3.1:8b (streaming, local) |
| HTTP Client | httpx |
| Frontend | React 19, Vite 8, axios, react-dropzone |
| Machine | MacBook Air M5, 16 GB RAM |

---

## Folder & File Structure

```
vecquery/
├── README.md                   ← This file
├── test_ingestion.py           ← End-to-end ingestion test script (Week 1)
├── test_query.py               ← End-to-end query pipeline test script (Week 2)
├── test_answer.py              ← SSE streaming answer test script (Week 3)
│
├── backend/
│   ├── .env                    ← DATABASE_URL (Supabase connection string)
│   ├── requirements.txt        ← All Python dependencies with pinned versions
│   ├── main.py                 ← FastAPI app entry point (v0.3.0) — all routers wired
│   ├── database.py             ← SQLAlchemy engine, session, ORM models (Document, Chunk, Embedding, QueryLog)
│   ├── ingestion.py            ← Full ingestion pipeline: parse → chunk → embed → BM25 → store
│   ├── query_planner.py        ← Query intent classifier: keyword / semantic / hybrid + cross-doc detection
│   ├── query_logs.py           ← Writes every query + strategy + result chunk IDs to query_logs table
│   ├── venv/                   ← Python virtual environment (not committed)
│   ├── llm/
│   │   ├── __init__.py         ← Package marker
│   │   └── ollama_client.py    ← Streaming Llama 3.1 client: prompt builder, token streamer, citations
│   ├── routers/
│   │   ├── __init__.py         ← Package marker
│   │   ├── upload.py           ← POST /upload/ + GET /upload/documents/
│   │   ├── query.py            ← POST /query/ — returns structured search results
│   │   └── answer.py           ← POST /answer/ — SSE streaming: search → LLM → citations
│   └── search/
│       ├── __init__.py         ← Package marker
│       ├── vector_search.py    ← pgvector cosine similarity search
│       ├── bm25_search.py      ← BM25 keyword search using pre-computed scores in chunk_metadata
│       ├── hybrid_search.py    ← Reciprocal Rank Fusion (RRF, k=60) merge
│       └── entity_join.py      ← Cross-document entity joining
│
└── frontend/
    ├── package.json            ← Node dependencies
    ├── vite.config.js          ← Vite configuration
    ├── index.html              ← HTML entry point
    └── src/
        ├── main.jsx            ← React entry point
        ├── App.jsx             ← Root component: two-column layout, streaming state management
        ├── App.css             ← All styles — dark theme, CSS variables, no frameworks
        ├── api/
        │   └── client.js       ← uploadDocument, fetchDocuments, queryDocuments, streamAnswer
        └── components/
            ├── UploadZone.jsx  ← Drag-and-drop upload with progress stages
            ├── DocumentList.jsx← Document cards with type badge, chunk count, upload time
            ├── QueryBox.jsx    ← Query textarea, strategy badge, cross-doc badge
            └── ResultsPanel.jsx← Streaming answer display + collapsible source citations
```

---

## What Is Fully Working ✅

### Week 1 — Ingestion Pipeline
- [x] FastAPI backend starts and serves `GET /` → `{"status": "VecQuery running"}`
- [x] CORS configured for Vite dev server (localhost:5173)
- [x] `database.py` — SQLAlchemy ORM models for all 4 tables (Document, Chunk, Embedding, QueryLog)
- [x] `database.py` — psycopg3 connection with auto URL prefix rewriting
- [x] `ingestion.py` — PDF parsing via PyMuPDF (page-by-page text extraction)
- [x] `ingestion.py` — DOCX parsing via python-docx (paragraph grouping into pseudo-pages)
- [x] `ingestion.py` — CSV parsing (row-to-sentence conversion, 50 rows per pseudo-page)
- [x] `ingestion.py` — TXT parsing (500-word pseudo-pages)
- [x] `ingestion.py` — 300-word chunks with 50-word overlap
- [x] `ingestion.py` — Ollama nomic-embed-text embedding (768 dimensions) with progress logging
- [x] `ingestion.py` — BM25 term frequency × IDF scoring stored in chunk metadata
- [x] `ingestion.py` — Single-transaction DB write: Document → Chunks → Embeddings
- [x] `routers/upload.py` — `POST /upload/` with file type validation, 50 MB size limit, temp file cleanup
- [x] `routers/upload.py` — `GET /upload/documents/` returns all documents with chunk counts

### Week 2 — Query Pipeline
- [x] `query_planner.py` — Classifies queries as keyword / semantic / hybrid with full reasoning
- [x] `query_planner.py` — Cross-document join detection (signals: "both", "compare", "across", etc.)
- [x] `query_planner.py` — Named entity extraction (capitalized words, codes, numbers, quoted strings)
- [x] `query_planner.py` — File type hint detection ("invoice" → pdf, "spreadsheet" → csv, etc.)
- [x] `search/vector_search.py` — pgvector cosine similarity search with Ollama query embedding
- [x] `search/bm25_search.py` — BM25 keyword search using pre-computed scores from chunk_metadata JSONB
- [x] `search/hybrid_search.py` — Reciprocal Rank Fusion (RRF, k=60) merge of vector + BM25 results
- [x] `search/entity_join.py` — Cross-document entity joining with snippet extraction and document overlap map
- [x] `query_logs.py` — Writes every query + strategy + result chunk IDs to query_logs table
- [x] `routers/query.py` — `POST /query/` with Pydantic validation, full pipeline orchestration

### Week 3 — LLM Answer Generation + Frontend
- [x] `llm/ollama_client.py` — Streaming Llama 3.1 8B client with grounded prompt builder
- [x] `llm/ollama_client.py` — Context window budget management (trims chunks to fit ~3000 tokens)
- [x] `llm/ollama_client.py` — Every claim cited with [Source N] in the prompt instructions
- [x] `llm/ollama_client.py` — Graceful error handling for Ollama down / timeout
- [x] `routers/answer.py` — `POST /answer/` SSE streaming endpoint
- [x] `routers/answer.py` — Emits: meta → tokens → citations → done events
- [x] `frontend/src/api/client.js` — uploadDocument, fetchDocuments, queryDocuments, streamAnswer
- [x] `frontend/src/components/UploadZone.jsx` — Drag-and-drop, file validation, progress stages
- [x] `frontend/src/components/DocumentList.jsx` — Document cards, auto-refresh after upload
- [x] `frontend/src/components/QueryBox.jsx` — Query input, strategy badge, cross-doc badge
- [x] `frontend/src/components/ResultsPanel.jsx` — Streaming answer, blinking cursor, collapsible citations
- [x] `frontend/src/App.jsx` — Two-column layout, full streaming state management
- [x] `frontend/src/App.css` — Dark theme, CSS variables, no external frameworks, responsive
- [x] `test_answer.py` — CLI test for the /answer/ SSE endpoint

---

## How to Run the Full Project

Run these commands in order in separate terminals:

### 1. Start Ollama (if not already running)
```bash
ollama serve
```

### 2. Start the FastAPI backend
```bash
# From the vecquery/ directory
vecquery/backend/venv/bin/uvicorn main:app --reload --port 8000 --app-dir vecquery/backend
```

Or with the venv activated:
```bash
source vecquery/backend/venv/bin/activate
cd vecquery/backend
uvicorn main:app --reload --port 8000
```

### 3. Start the React frontend
```bash
cd vecquery/frontend
npm run dev
# Opens at http://localhost:5173
```

### 4. Open the app
Navigate to **http://localhost:5173** in your browser.

---

## Environment Variables

`vecquery/backend/.env`:
```env
# Supabase SESSION POOLER connection string (port 5432)
# Get from: Supabase Dashboard → Project Settings → Database
#           → Connection string → Session pooler
#
# The username contains a dot (postgres.PROJECTREF) — this is correct and required.
# Do NOT use the direct URL (db.PROJECTREF.supabase.co) — IPv6-only, fails on most networks.
# Do NOT use the transaction pooler (port 6543) — limited SQL feature support.
DATABASE_URL=postgresql://postgres.MYPROJECTREF:MYPASSWORD@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
```

The app automatically rewrites `postgresql://` to `postgresql+psycopg://` for psycopg3 compatibility.

### Ollama models required
```bash
ollama pull nomic-embed-text   # embedding model (768-dim) — used during ingestion + search
ollama pull llama3.1:8b        # LLM for answer generation — used by /answer/ endpoint
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Health check |
| `POST` | `/upload/` | Upload and ingest a document |
| `GET` | `/upload/documents/` | List all ingested documents with chunk counts |
| `POST` | `/query/` | Run hybrid search, return structured chunks |
| `POST` | `/answer/` | Run search + LLM, stream answer via SSE |

Interactive docs: **http://localhost:8000/docs**

---

## Test Scripts

```bash
# Week 1 — Test ingestion pipeline (requires Ollama + DB)
vecquery/backend/venv/bin/python vecquery/test_ingestion.py

# Week 2 — Test query pipeline (requires Ollama + DB + at least 1 document)
vecquery/backend/venv/bin/python vecquery/test_query.py

# Week 3 — Test /answer/ SSE stream (requires backend running on port 8000)
vecquery/backend/venv/bin/python vecquery/test_answer.py
```

---

## Supabase Database Schema

```sql
-- Enable pgvector
create extension if not exists vector;

create table documents (
  id          serial primary key,
  name        varchar(512) not null,
  type        varchar(32) not null,
  uploaded_at timestamptz default now() not null
);

create table chunks (
  id             serial primary key,
  document_id    integer references documents(id) on delete cascade not null,
  content        text not null,
  page_number    integer,
  chunk_index    integer not null,
  chunk_metadata jsonb
);

create table embeddings (
  id       serial primary key,
  chunk_id integer references chunks(id) on delete cascade not null unique,
  vector   vector(768) not null
);

create table query_logs (
  id               serial primary key,
  query            text not null,
  planner_decision varchar(64),
  result_chunk_ids jsonb,
  created_at       timestamptz default now() not null
);

-- Index for fast vector similarity search (cosine distance)
create index on embeddings using ivfflat (vector vector_cosine_ops) with (lists = 100);

-- Optional: GIN index for fast BM25 JSONB lookups
create index on chunks using gin (chunk_metadata);
```

---

## Demo Script (for interviews)

Use this sequence to demonstrate the full system end-to-end in ~5 minutes:

### Setup (before the demo)
1. Have Ollama running with both models pulled
2. Have the backend and frontend running
3. Have 2–3 sample documents ready (e.g. a PDF report + a CSV dataset)

### Demo flow

**Step 1 — Show the architecture** (30 seconds)
> "This is VecQuery Intelligence — a local, zero-API-cost document Q&A engine. Everything runs on this MacBook: the embeddings, the LLM, the database. No OpenAI, no cloud costs."

**Step 2 — Upload a document** (1 minute)
- Drag a PDF into the upload zone
- Point out the progress stages: Parsing → Chunking → Embedding → Storing
- Show the document appearing in the document list with chunk count
> "The system chunks the document into 300-word overlapping windows, embeds each chunk using nomic-embed-text locally, computes BM25 term scores, and stores everything in Supabase with pgvector."

**Step 3 — Upload a second document** (30 seconds)
- Upload a CSV or second PDF
- Show both documents in the list

**Step 4 — Ask a semantic question** (1 minute)
- Type: `What are the key findings in this report?`
- Point out the **Semantic** badge — vector search was chosen
- Watch the answer stream token by token
- Expand a citation to show the source chunk
> "The query planner classified this as a semantic question and used pgvector cosine similarity to find the most relevant chunks. The LLM then synthesized a grounded answer with citations."

**Step 5 — Ask a keyword question** (30 seconds)
- Type a short query like `revenue 2024` or a specific name/ID
- Point out the **Keyword** badge — BM25 was chosen
> "Short, specific queries route to BM25 keyword search — faster and more precise for exact lookups."

**Step 6 — Ask a cross-document question** (1 minute)
- Type: `Compare the findings across both documents`
- Point out the **Hybrid** badge and **Cross-doc join** badge
- Show the answer referencing both documents
> "Cross-document queries trigger hybrid search — RRF merges vector and BM25 results — plus an entity join that finds common entities across all documents."

**Step 7 — Show the query logs** (optional, 30 seconds)
- Open Supabase dashboard → query_logs table
- Show every query logged with strategy and chunk IDs
> "Every query is logged for analytics and debugging."

### Key talking points
- **Zero API cost** — all models run locally via Ollama
- **Hybrid search** — not just vector search; BM25 handles exact lookups better
- **Query planner** — intelligent routing, not one-size-fits-all
- **Streaming** — SSE for real-time token delivery, same pattern as ChatGPT
- **Grounded answers** — the LLM is instructed to cite every claim and say "I don't know" if the answer isn't in the sources

---

## Week 1 — Ingestion Pipeline ✅ COMPLETE
## Week 2 — Query Planner + Hybrid Search ✅ COMPLETE
## Week 3 — LLM Answer Generation + Frontend ✅ COMPLETE

# VecQuery Intelligence
 
A cross-document natural language query engine. Upload PDFs, CSVs, and DOCX files, ask a question in plain English, and receive a cited answer grounded in your documents. Every component runs locally — no API keys, no cloud costs.
 
---
 
## What It Does
 
- Ingests PDF, CSV, DOCX, and TXT files into a searchable vector database
- Classifies every query and selects the optimal search strategy automatically
- Retrieves the most relevant chunks using hybrid vector + keyword search
- Joins answers across multiple documents when the query spans more than one file
- Streams a grounded, cited answer token by token using a local LLM
---

<img width="720" alt="Screenshot 2026-04-20 at 9 00 25 PM" src="https://github.com/user-attachments/assets/f1076322-10f4-45a3-8e2b-c3f5e3f40896" />
</br>
<img width="720" alt="Screenshot 2026-04-20 at 9 01 39 PM" src="https://github.com/user-attachments/assets/7591558c-bea2-4eff-a0a6-06fbd44f179b" />

 
## How It Works
 
### Ingestion Pipeline
When a file is uploaded, the system parses it into raw text, splits the text into 300-word overlapping chunks (50-word overlap), embeds each chunk into a 768-dimensional vector using **nomic-embed-text** via Ollama, computes BM25 term frequency scores, and stores everything — document metadata, chunks, embeddings, and BM25 index — in PostgreSQL with pgvector in a single transaction.
 
### Query Planner
Before any search runs, the query planner reads the query and classifies it into one of three strategies:
 
- **Keyword** — short, exact queries (names, IDs, numbers, dates) — routes to BM25 search
- **Semantic** — conceptual or descriptive queries — routes to pgvector cosine similarity search
- **Hybrid** — complex, multi-part queries — runs both searches and merges via Reciprocal Rank Fusion
The planner also detects cross-document intent (signals: "compare", "both", "across", "match") and flags which file types are relevant based on query hints.
 
### Hybrid Search
Vector search and BM25 search run in parallel. Results are merged using **Reciprocal Rank Fusion (RRF, k=60)**, which combines ranked lists from both methods into a single unified ranking without requiring score normalization. For datasets under 100 embeddings, the system falls back to exact sequential scan instead of the ivfflat index.
 
### Cross-Document Entity Joining
When cross-document intent is detected, the engine extracts named entities from the query (capitalized words, dates, codes, quoted strings), searches for those entities across chunks from all documents, and surfaces chunks that share common entities — linking answers across files.
 
### Answer Generation
The top-ranked chunks are passed to **Llama 3.1 8B** running locally via Ollama with a grounded prompt that instructs the model to cite every claim as [Source N] and explicitly state when the answer is not found in the provided sources. The response streams token by token to the frontend via **Server-Sent Events (SSE)**.
 
### Query Logging
Every query is logged to a `query_logs` table in PostgreSQL with the raw query text, planner decision, and the chunk IDs that were returned — creating a full audit trail for every search.
 
---

<img width="800" alt="supabase-schema-vdmrmxqwicvuzitfyuiy" src="https://github.com/user-attachments/assets/d989c688-13ee-4eb5-a9fe-9a9b014d32c9" />

 
## Tech Stack
 
| Layer | Technology |
|---|---|
| Backend API | Python 3.9, FastAPI, Uvicorn |
| Database | Supabase — PostgreSQL + pgvector extension |
| ORM | SQLAlchemy 2.0 |
| DB Driver | psycopg 3.1 (psycopg3) |
| PDF Parsing | PyMuPDF (fitz) |
| DOCX Parsing | python-docx |
| CSV Parsing | Python standard library csv module |
| Embeddings | Ollama — nomic-embed-text (768 dimensions) |
| LLM | Ollama — llama3.1:8b (local, streaming) |
| Frontend | React 19, Vite 8, axios, react-dropzone |
 
---
 
## Database Schema
 
```sql
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
 
create index on embeddings using ivfflat (vector vector_cosine_ops) with (lists = 100);
create index on chunks using gin (chunk_metadata);
```
 
---
 
## API Endpoints
 
| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Health check |
| POST | `/upload/` | Upload and ingest a document |
| GET | `/upload/documents/` | List all ingested documents with chunk counts |
| POST | `/query/` | Run hybrid search, return ranked chunks |
| POST | `/answer/` | Run search and stream a cited LLM answer via SSE |
 
Interactive API docs available at **http://localhost:8000/docs**
 
---
 
## Setup and Installation
 
### Prerequisites
 
**1. Install Ollama**
 
Download from [ollama.com](https://ollama.com) and install. Then pull the required models:
 
```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```
 
**2. Create a Supabase project**
 
Create a free project at [supabase.com](https://supabase.com). In the SQL Editor, run the full schema from the Database Schema section above.
 
Get your **Session Pooler** connection string from:
Supabase Dashboard → Connect → Session Pooler
 
It will look like:
```
postgresql://postgres.YOURPROJECTREF:YOURPASSWORD@aws-1-REGION.pooler.supabase.com:5432/postgres
```
 
**Important:** Use the Session Pooler URL, not the direct connection URL. The free tier requires this.
 
---
 
### Backend
 
```bash
cd vecquery/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
 
Create a `.env` file inside `vecquery/backend/`:
 
```env
DATABASE_URL=postgresql://postgres.YOURPROJECTREF:YOURPASSWORD@aws-1-REGION.pooler.supabase.com:5432/postgres
```
 
Start the backend:
 
```bash
uvicorn main:app --reload --port 8000
```
 
---
 
### Frontend
 
```bash
cd vecquery/frontend
npm install
npm run dev
```
 
---
 
### Running the Full Project
 
Open three terminal tabs and run in order:
 
```bash
# Tab 1 — Ollama (skip if already running)
ollama serve
 
# Tab 2 — Backend
cd vecquery/backend && source venv/bin/activate && uvicorn main:app --reload --port 8000
 
# Tab 3 — Frontend
cd vecquery/frontend && npm run dev
```
 
Open **http://localhost:5173** in your browser.
 
---
 
## Project Structure
 
```
vecquery/
├── backend/
│   ├── .env                    — DATABASE_URL (Supabase session pooler)
│   ├── requirements.txt        — Python dependencies
│   ├── main.py                 — FastAPI app entry point
│   ├── database.py             — SQLAlchemy engine, session, ORM models
│   ├── ingestion.py            — Ingestion pipeline: parse, chunk, embed, store
│   ├── query_planner.py        — Query intent classification and routing
│   ├── query_logs.py           — Query audit logging
│   ├── llm/
│   │   └── ollama_client.py    — Streaming Llama 3.1 client with prompt builder
│   ├── routers/
│   │   ├── upload.py           — Upload and document list endpoints
│   │   ├── query.py            — Search endpoint
│   │   └── answer.py           — SSE streaming answer endpoint
│   └── search/
│       ├── vector_search.py    — pgvector cosine similarity search
│       ├── bm25_search.py      — BM25 keyword search
│       ├── hybrid_search.py    — Reciprocal Rank Fusion merge
│       └── entity_join.py      — Cross-document entity joining
│
└── frontend/
    └── src/
        ├── App.jsx             — Root component, two-column layout
        ├── App.css             — Dark theme, CSS variables
        ├── api/
        │   └── client.js       — API client for all endpoints
        └── components/
            ├── UploadZone.jsx  — Drag-and-drop file upload
            ├── DocumentList.jsx— Ingested document cards
            ├── QueryBox.jsx    — Query input with strategy badge
            └── ResultsPanel.jsx— Streaming answer and citations
```
 


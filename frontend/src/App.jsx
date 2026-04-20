/**
 * App.jsx — Root component for VecQuery Intelligence.
 *
 * Layout:
 *   ┌─────────────────────────────────────────────────────┐
 *   │  Header: VecQuery Intelligence                       │
 *   ├──────────────────────┬──────────────────────────────┤
 *   │  Left panel          │  Right panel                 │
 *   │  ─────────────────   │  ──────────────────────────  │
 *   │  UploadZone          │  QueryBox                    │
 *   │  DocumentList        │  ResultsPanel                │
 *   └──────────────────────┴──────────────────────────────┘
 *
 * State management:
 *   - uploadRefresh: incremented after each upload to trigger DocumentList refresh
 *   - answer:        accumulated LLM answer text (built token by token)
 *   - citations:     final citations array from the "citations" SSE event
 *   - isStreaming:   true while the SSE stream is open
 *   - strategy:      planner decision from the "meta" SSE event
 *   - needsCrossDoc: cross-doc join flag from the "meta" SSE event
 *   - reasoning:     planner reasoning string
 *   - queryError:    error message from the stream
 *   - hasQueried:    true after the first query is submitted
 */

import { useState, useCallback } from 'react';
import UploadZone    from './components/UploadZone';
import DocumentList  from './components/DocumentList';
import QueryBox      from './components/QueryBox';
import ResultsPanel  from './components/ResultsPanel';
import { streamAnswer } from './api/client';
import './App.css';

export default function App() {
  // Upload state
  const [uploadRefresh, setUploadRefresh] = useState(0);

  // Query / answer state
  const [answer,       setAnswer]       = useState('');
  const [citations,    setCitations]    = useState(null);
  const [isStreaming,  setIsStreaming]  = useState(false);
  const [strategy,     setStrategy]    = useState(null);
  const [needsCrossDoc,setNeedsCrossDoc]= useState(false);
  const [reasoning,    setReasoning]   = useState('');
  const [queryError,   setQueryError]  = useState('');
  const [hasQueried,   setHasQueried]  = useState(false);

  // Called by UploadZone after a successful upload
  function handleUploadSuccess() {
    setUploadRefresh(n => n + 1);
  }

  // Called by QueryBox when the user submits a query
  const handleQuery = useCallback(async (query) => {
    // Reset answer state for the new query
    setAnswer('');
    setCitations(null);
    setQueryError('');
    setStrategy(null);
    setNeedsCrossDoc(false);
    setReasoning('');
    setIsStreaming(true);
    setHasQueried(true);

    await streamAnswer(query, 5, {
      onMeta: (meta) => {
        setStrategy(meta.strategy);
        setNeedsCrossDoc(meta.needs_cross_doc || false);
        setReasoning(meta.reasoning || '');
      },
      onToken: (token) => {
        // Append each token to the answer string
        setAnswer(prev => prev + token);
      },
      onCitations: (sources) => {
        setCitations(sources);
      },
      onError: (message) => {
        setQueryError(message);
        setIsStreaming(false);
      },
      onDone: () => {
        setIsStreaming(false);
      },
    });
  }, []);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="app">
      {/* ── Header ── */}
      <header className="app__header">
        <div className="app__header-inner">
          <span className="app__logo" aria-hidden="true">⚡</span>
          <h1 className="app__title">VecQuery Intelligence</h1>
          <span className="app__subtitle">
            Cross-document natural language search · Hybrid pgvector + BM25 · Local Llama 3.1
          </span>
        </div>
      </header>

      {/* ── Main two-column layout ── */}
      <main className="app__main">
        {/* Left panel: upload + document list */}
        <aside className="app__left-panel" aria-label="Document management">
          <section className="panel">
            <h2 className="panel__title">Upload Documents</h2>
            <UploadZone onUploadSuccess={handleUploadSuccess} />
          </section>

          <section className="panel">
            <DocumentList refreshTrigger={uploadRefresh} />
          </section>
        </aside>

        {/* Right panel: query + results */}
        <section className="app__right-panel" aria-label="Query and results">
          <div className="panel">
            <h2 className="panel__title">Ask a Question</h2>
            <QueryBox
              onSubmit={handleQuery}
              isLoading={isStreaming}
              strategy={strategy}
              needsCrossDoc={needsCrossDoc}
              reasoning={reasoning}
            />
          </div>

          <div className="panel panel--results">
            <ResultsPanel
              answer={answer}
              citations={citations}
              isStreaming={isStreaming}
              error={queryError}
              hasQueried={hasQueried}
            />
          </div>
        </section>
      </main>
    </div>
  );
}

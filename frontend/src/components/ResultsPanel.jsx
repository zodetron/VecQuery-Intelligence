/**
 * ResultsPanel.jsx — Streams and displays the LLM answer with source citations.
 *
 * Features:
 *   - Streams tokens as they arrive and appends them to the answer text
 *   - Shows a blinking cursor while streaming
 *   - After streaming completes, shows collapsible source citations
 *   - Each citation shows: source number, document name, page, score, content preview
 *   - Error state with clear message
 *   - Empty/idle state with a prompt
 *
 * Props:
 *   answer      — string, the accumulated answer text so far
 *   citations   — array of citation objects (from the "citations" SSE event)
 *   isStreaming — boolean, true while tokens are arriving
 *   error       — string | null, error message to display
 *   hasQueried  — boolean, true after the first query has been submitted
 */

import { useState } from 'react';

// ---------------------------------------------------------------------------
// Citation card
// ---------------------------------------------------------------------------

function CitationCard({ citation, index }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <li className="citation-card">
      <button
        className="citation-card__header"
        onClick={() => setExpanded(e => !e)}
        aria-expanded={expanded}
        aria-controls={`citation-body-${index}`}
      >
        <span className="citation-card__num" aria-label={`Source ${citation.source_num}`}>
          [{citation.source_num}]
        </span>
        <span className="citation-card__doc-name" title={citation.document_name}>
          {citation.document_name}
        </span>
        {citation.page_number != null && (
          <span className="citation-card__page">p.{citation.page_number}</span>
        )}
        <span className={`badge badge--type-${citation.document_type || 'txt'}`}>
          {(citation.document_type || 'txt').toUpperCase()}
        </span>
        <span className="citation-card__score" aria-label={`Relevance score ${citation.score}`}>
          {(citation.score * 100).toFixed(1)}%
        </span>
        <span className="citation-card__chevron" aria-hidden="true">
          {expanded ? '▲' : '▼'}
        </span>
      </button>

      {expanded && (
        <div
          id={`citation-body-${index}`}
          className="citation-card__body"
          role="region"
          aria-label={`Source ${citation.source_num} content`}
        >
          <p className="citation-card__preview">
            {citation.preview}
            {citation.preview && citation.preview.length >= 150 ? '…' : ''}
          </p>
        </div>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function ResultsPanel({ answer, citations, isStreaming, error, hasQueried }) {

  // Idle state — nothing has been queried yet
  if (!hasQueried) {
    return (
      <div className="results-panel results-panel--idle">
        <div className="results-panel__idle-prompt">
          <span aria-hidden="true" className="results-panel__idle-icon">🔍</span>
          <p>Ask a question to get an answer from your documents.</p>
          <p className="results-panel__idle-hint">
            The engine will search across all uploaded files and generate a cited answer.
          </p>
        </div>
      </div>
    );
  }

  // Error state
  if (error && !answer) {
    return (
      <div className="results-panel results-panel--error">
        <div className="results-panel__error" role="alert">
          <span aria-hidden="true">⚠️</span>
          <div>
            <strong>Something went wrong</strong>
            <p>{error}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="results-panel">
      {/* Answer section */}
      <div className="results-panel__answer" aria-live="polite" aria-label="Answer">
        {answer ? (
          <>
            <div className="results-panel__answer-text">
              {/* Render answer preserving newlines */}
              {answer.split('\n').map((line, i) => (
                <span key={i}>
                  {line}
                  {i < answer.split('\n').length - 1 && <br />}
                </span>
              ))}
              {/* Blinking cursor while streaming */}
              {isStreaming && (
                <span className="results-panel__cursor" aria-hidden="true">▌</span>
              )}
            </div>

            {/* Non-fatal error shown alongside partial answer */}
            {error && (
              <div className="results-panel__error results-panel__error--inline" role="alert">
                <span aria-hidden="true">⚠️</span> {error}
              </div>
            )}
          </>
        ) : (
          isStreaming && (
            <div className="results-panel__thinking" aria-label="Generating answer">
              <span className="spinner" aria-hidden="true" />
              <span>Generating answer…</span>
            </div>
          )
        )}
      </div>

      {/* Citations section — shown after streaming completes */}
      {!isStreaming && citations && citations.length > 0 && (
        <div className="results-panel__citations">
          <h4 className="results-panel__citations-title">
            Sources
            <span className="doc-list__count">{citations.length}</span>
          </h4>
          <ul className="citations-list" role="list">
            {citations.map((citation, i) => (
              <CitationCard key={citation.chunk_id || i} citation={citation} index={i} />
            ))}
          </ul>
        </div>
      )}

      {/* No results message */}
      {!isStreaming && !error && answer && citations && citations.length === 0 && (
        <p className="results-panel__no-sources">
          No source citations available for this answer.
        </p>
      )}
    </div>
  );
}

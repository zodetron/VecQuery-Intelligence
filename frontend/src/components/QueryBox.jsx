/**
 * QueryBox.jsx — Natural language query input.
 *
 * Features:
 *   - Text input (textarea) for the query
 *   - Submit button (also triggered by Ctrl+Enter / Cmd+Enter)
 *   - Strategy badge: keyword / semantic / hybrid (shown after first query)
 *   - Cross-doc join badge when the planner detects cross-document signals
 *   - Loading spinner while the LLM is streaming
 *   - Disabled state during streaming to prevent double-submit
 *
 * Props:
 *   onSubmit(query)  — called when the user submits a query
 *   isLoading        — true while the answer is streaming
 *   strategy         — "keyword" | "semantic" | "hybrid" | null
 *   needsCrossDoc    — boolean
 *   reasoning        — string explaining the planner's decision
 */

import { useState, useRef } from 'react';

// ---------------------------------------------------------------------------
// Strategy badge config
// ---------------------------------------------------------------------------

const STRATEGY_META = {
  keyword:  { label: 'Keyword',  cls: 'badge--keyword',  title: 'BM25 keyword search' },
  semantic: { label: 'Semantic', cls: 'badge--semantic', title: 'Vector similarity search' },
  hybrid:   { label: 'Hybrid',   cls: 'badge--hybrid',   title: 'RRF merge of vector + BM25' },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function QueryBox({ onSubmit, isLoading, strategy, needsCrossDoc, reasoning }) {
  const [query, setQuery] = useState('');
  const textareaRef = useRef(null);

  function handleSubmit(e) {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || isLoading) return;
    onSubmit(trimmed);
  }

  // Allow Ctrl+Enter / Cmd+Enter to submit
  function handleKeyDown(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      handleSubmit(e);
    }
  }

  const stratMeta = strategy ? STRATEGY_META[strategy] : null;

  return (
    <div className="query-box">
      <form className="query-box__form" onSubmit={handleSubmit} noValidate>
        <label htmlFor="query-input" className="query-box__label">
          Ask a question across your documents
        </label>

        <div className="query-box__input-row">
          <textarea
            id="query-input"
            ref={textareaRef}
            className="query-box__textarea"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="e.g. What are the key findings? Compare revenue across both reports."
            rows={3}
            disabled={isLoading}
            aria-label="Query input"
            aria-describedby="query-hint"
          />
        </div>

        <div className="query-box__footer">
          <span id="query-hint" className="query-box__hint">
            Ctrl+Enter to submit
          </span>

          <button
            type="submit"
            className="btn btn--primary"
            disabled={!query.trim() || isLoading}
            aria-busy={isLoading}
          >
            {isLoading ? (
              <>
                <span className="spinner" aria-hidden="true" />
                Thinking…
              </>
            ) : (
              'Ask'
            )}
          </button>
        </div>
      </form>

      {/* Strategy badges — shown after a query has been run */}
      {stratMeta && (
        <div className="query-box__badges" role="status" aria-live="polite">
          <span
            className={`badge ${stratMeta.cls}`}
            title={stratMeta.title}
            aria-label={`Search strategy: ${stratMeta.label}`}
          >
            {stratMeta.label}
          </span>

          {needsCrossDoc && (
            <span
              className="badge badge--crossdoc"
              title="Cross-document entity join was performed"
              aria-label="Cross-document join"
            >
              Cross-doc join
            </span>
          )}

          {reasoning && (
            <span className="query-box__reasoning" title={reasoning}>
              {reasoning.length > 80 ? reasoning.slice(0, 80) + '…' : reasoning}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

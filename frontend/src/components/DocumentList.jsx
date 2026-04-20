/**
 * DocumentList.jsx — Shows all ingested documents as cards.
 *
 * Features:
 *   - Fetches from GET /upload/documents/ on mount and after each upload
 *   - Shows document name, type badge, chunk count, upload time
 *   - Refreshes when the `refreshTrigger` prop changes
 *   - Loading skeleton while fetching
 *   - Empty state when no documents exist
 *   - Error state if the fetch fails
 */

import { useState, useEffect } from 'react';
import { fetchDocuments } from '../api/client';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format an ISO timestamp to a readable relative time or date */
function formatDate(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  const now  = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1)   return 'just now';
  if (diffMins < 60)  return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return date.toLocaleDateString();
}

/** Map file type to a display label and color class */
const TYPE_META = {
  pdf:  { label: 'PDF',  cls: 'badge--pdf'  },
  docx: { label: 'DOCX', cls: 'badge--docx' },
  csv:  { label: 'CSV',  cls: 'badge--csv'  },
  txt:  { label: 'TXT',  cls: 'badge--txt'  },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DocumentList({ refreshTrigger }) {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');

  // Fetch documents whenever refreshTrigger changes (e.g. after a new upload)
  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError('');
      try {
        const docs = await fetchDocuments();
        if (!cancelled) setDocuments(docs);
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [refreshTrigger]);

  // ---------------------------------------------------------------------------
  // Render states
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="doc-list">
        <h3 className="doc-list__title">Documents</h3>
        <div className="doc-list__skeleton" aria-busy="true" aria-label="Loading documents">
          {[1, 2, 3].map(i => (
            <div key={i} className="doc-card doc-card--skeleton" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="doc-list">
        <h3 className="doc-list__title">Documents</h3>
        <div className="doc-list__error" role="alert">
          <span aria-hidden="true">⚠️</span> {error}
        </div>
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="doc-list">
        <h3 className="doc-list__title">Documents</h3>
        <div className="doc-list__empty">
          <span aria-hidden="true">📭</span>
          <p>No documents yet.</p>
          <p className="doc-list__empty-hint">Upload a PDF, DOCX, CSV, or TXT file to get started.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="doc-list">
      <h3 className="doc-list__title">
        Documents
        <span className="doc-list__count" aria-label={`${documents.length} documents`}>
          {documents.length}
        </span>
      </h3>

      <ul className="doc-list__items" role="list">
        {documents.map(doc => {
          const typeMeta = TYPE_META[doc.type] || { label: doc.type.toUpperCase(), cls: 'badge--txt' };
          return (
            <li key={doc.id} className="doc-card">
              <div className="doc-card__header">
                <span className="doc-card__name" title={doc.name}>
                  {doc.name}
                </span>
                <span className={`badge ${typeMeta.cls}`} aria-label={`File type: ${typeMeta.label}`}>
                  {typeMeta.label}
                </span>
              </div>
              <div className="doc-card__meta">
                <span className="doc-card__chunks" aria-label={`${doc.chunk_count} chunks`}>
                  {doc.chunk_count} chunks
                </span>
                <span className="doc-card__time" title={doc.uploaded_at}>
                  {formatDate(doc.uploaded_at)}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * DocumentList.jsx — Shows all ingested documents as cards.
 *
 * Features:
 *   - Fetches from GET /upload/documents/ on mount and after each upload
 *   - Shows document name, type badge, chunk count, upload time
 *   - Delete button on each card — first click shows a confirm state,
 *     second click calls DELETE /upload/documents/{id} and removes the card
 *   - Refreshes when the `refreshTrigger` prop changes
 *   - Loading skeleton while fetching
 *   - Empty state when no documents exist
 *   - Error state if the fetch fails
 */

import { useState, useEffect } from 'react';
import { fetchDocuments, deleteDocument } from '../api/client';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  const now  = new Date();
  const diffMs   = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1)   return 'just now';
  if (diffMins < 60)  return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return date.toLocaleDateString();
}

const TYPE_META = {
  pdf:  { label: 'PDF',  cls: 'badge--pdf'  },
  docx: { label: 'DOCX', cls: 'badge--docx' },
  csv:  { label: 'CSV',  cls: 'badge--csv'  },
  txt:  { label: 'TXT',  cls: 'badge--txt'  },
};

// ---------------------------------------------------------------------------
// DocCard — single document row with delete button
// ---------------------------------------------------------------------------

function DocCard({ doc, onDeleted }) {
  // confirmId tracks which card is in "are you sure?" state.
  // We keep it local to each card so only one card can be in confirm at a time.
  const [confirming, setConfirming] = useState(false);
  const [deleting,   setDeleting]   = useState(false);
  const [error,      setError]      = useState('');

  const typeMeta = TYPE_META[doc.type] || { label: doc.type.toUpperCase(), cls: 'badge--txt' };

  async function handleDeleteClick() {
    if (!confirming) {
      // First click — enter confirm state
      setConfirming(true);
      setError('');
      return;
    }

    // Second click — confirmed, do the delete
    setDeleting(true);
    try {
      await deleteDocument(doc.id);
      onDeleted(doc.id);   // tell the parent to remove this card from state
    } catch (err) {
      setError(err.message);
      setDeleting(false);
      setConfirming(false);
    }
  }

  function handleCancelDelete() {
    setConfirming(false);
    setError('');
  }

  return (
    <li className={`doc-card ${confirming ? 'doc-card--confirming' : ''}`}>
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

      {/* Delete controls */}
      <div className="doc-card__actions">
        {error && (
          <span className="doc-card__delete-error" role="alert">{error}</span>
        )}

        {confirming ? (
          <>
            <span className="doc-card__confirm-label">Delete?</span>
            <button
              className="btn-icon btn-icon--confirm"
              onClick={handleDeleteClick}
              disabled={deleting}
              aria-label={`Confirm delete ${doc.name}`}
              title="Yes, delete"
            >
              {deleting ? '…' : '✓'}
            </button>
            <button
              className="btn-icon btn-icon--cancel"
              onClick={handleCancelDelete}
              disabled={deleting}
              aria-label="Cancel delete"
              title="Cancel"
            >
              ✕
            </button>
          </>
        ) : (
          <button
            className="btn-icon btn-icon--delete"
            onClick={handleDeleteClick}
            aria-label={`Delete ${doc.name}`}
            title="Delete document"
          >
            🗑
          </button>
        )}
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// DocumentList
// ---------------------------------------------------------------------------

export default function DocumentList({ refreshTrigger }) {
  const [documents, setDocuments] = useState([]);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState('');

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

  // Remove a card from local state immediately after successful delete
  // so the UI updates without a round-trip refetch.
  function handleDeleted(deletedId) {
    setDocuments(prev => prev.filter(d => d.id !== deletedId));
  }

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
        {documents.map(doc => (
          <DocCard key={doc.id} doc={doc} onDeleted={handleDeleted} />
        ))}
      </ul>
    </div>
  );
}

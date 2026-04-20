/**
 * UploadZone.jsx — Drag-and-drop file upload component.
 *
 * Features:
 *   - Drag-and-drop zone using react-dropzone
 *   - Accepts PDF, CSV, DOCX, TXT only
 *   - Shows file name + size after selection
 *   - Upload button triggers POST /upload/
 *   - Progress stages: Uploading → Parsing → Chunking → Embedding → Done
 *   - Error message on failure
 *   - Success message with chunk count
 *   - Calls onUploadSuccess(result) when done so DocumentList can refresh
 */

import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { uploadDocument } from '../api/client';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ACCEPTED_TYPES = {
  'application/pdf':                                                          ['.pdf'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'text/csv':                                                                 ['.csv'],
  'text/plain':                                                               ['.txt'],
};

const STAGES = ['Uploading', 'Parsing', 'Chunking', 'Embedding', 'Storing'];

// Rough time estimates per stage (ms) — used to animate progress
const STAGE_DURATIONS = [500, 1000, 1500, 8000, 500];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function UploadZone({ onUploadSuccess }) {
  const [file, setFile]           = useState(null);
  const [status, setStatus]       = useState('idle');   // idle | uploading | success | error
  const [stageIndex, setStageIndex] = useState(0);
  const [error, setError]         = useState('');
  const [result, setResult]       = useState(null);

  // Handle file drop / selection
  const onDrop = useCallback((acceptedFiles, rejectedFiles) => {
    setError('');
    setResult(null);
    setStatus('idle');
    setStageIndex(0);

    if (rejectedFiles.length > 0) {
      const reasons = rejectedFiles[0].errors.map(e => e.message).join(', ');
      setError(`File rejected: ${reasons}`);
      return;
    }
    if (acceptedFiles.length > 0) {
      setFile(acceptedFiles[0]);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept:    ACCEPTED_TYPES,
    maxFiles:  1,
    maxSize:   50 * 1024 * 1024,  // 50 MB
    multiple:  false,
  });

  // Animate through stages while upload is in progress
  function animateStages() {
    let idx = 0;
    function advance() {
      idx++;
      if (idx < STAGES.length) {
        setStageIndex(idx);
        setTimeout(advance, STAGE_DURATIONS[idx]);
      }
    }
    setTimeout(advance, STAGE_DURATIONS[0]);
  }

  // Handle upload button click
  async function handleUpload() {
    if (!file) return;
    setStatus('uploading');
    setStageIndex(0);
    setError('');
    setResult(null);
    animateStages();

    try {
      const data = await uploadDocument(file, () => {});
      setStatus('success');
      setResult(data);
      setFile(null);
      if (onUploadSuccess) onUploadSuccess(data);
    } catch (err) {
      setStatus('error');
      setError(err.message);
    }
  }

  function handleClear() {
    setFile(null);
    setStatus('idle');
    setError('');
    setResult(null);
    setStageIndex(0);
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="upload-zone-wrapper">
      {/* Drop area */}
      <div
        {...getRootProps()}
        className={[
          'dropzone',
          isDragActive ? 'dropzone--active' : '',
          file          ? 'dropzone--has-file' : '',
        ].join(' ')}
        aria-label="File upload area"
      >
        <input {...getInputProps()} aria-label="File input" />

        {!file && !isDragActive && (
          <div className="dropzone__prompt">
            <span className="dropzone__icon" aria-hidden="true">📄</span>
            <p className="dropzone__text">Drop a file here, or click to browse</p>
            <p className="dropzone__hint">PDF · DOCX · CSV · TXT · max 50 MB</p>
          </div>
        )}

        {isDragActive && (
          <div className="dropzone__prompt">
            <span className="dropzone__icon" aria-hidden="true">⬇️</span>
            <p className="dropzone__text">Drop it!</p>
          </div>
        )}

        {file && !isDragActive && (
          <div className="dropzone__file-info">
            <span className="dropzone__file-icon" aria-hidden="true">
              {file.name.endsWith('.pdf')  ? '📕' :
               file.name.endsWith('.docx') ? '📘' :
               file.name.endsWith('.csv')  ? '📊' : '📄'}
            </span>
            <div>
              <p className="dropzone__file-name">{file.name}</p>
              <p className="dropzone__file-size">{formatBytes(file.size)}</p>
            </div>
          </div>
        )}
      </div>

      {/* Error message */}
      {error && (
        <div className="upload-error" role="alert">
          <span aria-hidden="true">⚠️</span> {error}
        </div>
      )}

      {/* Success message */}
      {status === 'success' && result && (
        <div className="upload-success" role="status">
          <span aria-hidden="true">✅</span>{' '}
          <strong>{result.file_name}</strong> ingested —{' '}
          <strong>{result.chunk_count}</strong> chunks stored
        </div>
      )}

      {/* Progress stages */}
      {status === 'uploading' && (
        <div className="upload-progress" role="status" aria-live="polite">
          <div className="upload-progress__stages">
            {STAGES.map((stage, i) => (
              <span
                key={stage}
                className={[
                  'upload-progress__stage',
                  i < stageIndex  ? 'upload-progress__stage--done' : '',
                  i === stageIndex ? 'upload-progress__stage--active' : '',
                ].join(' ')}
                aria-current={i === stageIndex ? 'step' : undefined}
              >
                {i < stageIndex ? '✓ ' : i === stageIndex ? '⟳ ' : ''}{stage}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Action buttons */}
      <div className="upload-actions">
        {file && status !== 'uploading' && (
          <button
            className="btn btn--primary"
            onClick={handleUpload}
            disabled={status === 'uploading'}
          >
            Upload &amp; Ingest
          </button>
        )}
        {(file || status === 'success' || status === 'error') && status !== 'uploading' && (
          <button className="btn btn--ghost" onClick={handleClear}>
            Clear
          </button>
        )}
      </div>
    </div>
  );
}

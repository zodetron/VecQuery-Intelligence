/**
 * api/client.js — Axios API client for VecQuery Intelligence.
 *
 * Provides three functions:
 *   uploadDocument(file, onProgress) — POST /upload/ with FormData
 *   queryDocuments(query, topK)      — POST /query/ and return structured result
 *   streamAnswer(query, topK, callbacks) — POST /answer/ and stream SSE tokens
 *
 * All functions throw a plain Error with a human-readable message on failure,
 * so components can catch and display it directly.
 */

import axios from 'axios';

// ---------------------------------------------------------------------------
// Base configuration
// ---------------------------------------------------------------------------

const BASE_URL = 'http://localhost:8000';

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,  // 30s for regular requests; streaming has its own timeout
});

// ---------------------------------------------------------------------------
// Error normalizer — turns any axios error into a plain readable message
// ---------------------------------------------------------------------------

function normalizeError(err) {
  if (err.response) {
    // Server responded with a non-2xx status
    const detail = err.response.data?.detail;
    if (typeof detail === 'string') return new Error(detail);
    if (Array.isArray(detail)) {
      // Pydantic validation errors come as an array
      return new Error(detail.map(d => d.msg).join('; '));
    }
    return new Error(`Server error ${err.response.status}: ${err.response.statusText}`);
  }
  if (err.request) {
    // Request was made but no response received (backend down, CORS, etc.)
    return new Error(
      'Cannot reach the backend. Make sure the FastAPI server is running on port 8000.'
    );
  }
  return new Error(err.message || 'Unknown error');
}

// ---------------------------------------------------------------------------
// uploadDocument — POST /upload/
// ---------------------------------------------------------------------------

/**
 * Upload a file to the ingestion pipeline.
 *
 * @param {File}     file        — The File object from the dropzone
 * @param {Function} onProgress  — Called with (percent: number) during upload
 * @returns {Promise<{document_id, chunk_count, file_name, message}>}
 */
export async function uploadDocument(file, onProgress) {
  const formData = new FormData();
  formData.append('file', file);

  try {
    const response = await api.post('/upload/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event) => {
        if (event.total && onProgress) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      },
      // Ingestion can take a while (embedding all chunks)
      timeout: 300000,  // 5 minutes
    });
    return response.data;
  } catch (err) {
    throw normalizeError(err);
  }
}

// ---------------------------------------------------------------------------
// fetchDocuments — GET /upload/documents/
// ---------------------------------------------------------------------------

/**
 * Fetch the list of all ingested documents.
 *
 * @returns {Promise<Array<{id, name, type, uploaded_at, chunk_count}>>}
 */
export async function fetchDocuments() {
  try {
    const response = await api.get('/upload/documents/');
    return response.data;
  } catch (err) {
    throw normalizeError(err);
  }
}

// ---------------------------------------------------------------------------
// queryDocuments — POST /query/
// ---------------------------------------------------------------------------

/**
 * Run a search query and return structured chunk results (no LLM).
 * Useful for showing raw search results alongside the LLM answer.
 *
 * @param {string} query  — Natural language question
 * @param {number} topK   — Number of chunks to return (default 5)
 * @returns {Promise<{query, strategy, reasoning, results, entity_join, log_id, elapsed_ms}>}
 */
export async function queryDocuments(query, topK = 5) {
  try {
    const response = await api.post('/query/', { query, top_k: topK });
    return response.data;
  } catch (err) {
    throw normalizeError(err);
  }
}

// ---------------------------------------------------------------------------
// streamAnswer — POST /answer/ with SSE
// ---------------------------------------------------------------------------

/**
 * Stream an LLM answer from the /answer/ endpoint using the Fetch API.
 * (We use fetch instead of axios because axios doesn't support streaming.)
 *
 * @param {string}   query      — Natural language question
 * @param {number}   topK       — Number of source chunks to feed the LLM
 * @param {object}   callbacks  — Event handlers:
 *   onMeta(meta)       — Called once with {strategy, reasoning, chunk_count, ...}
 *   onToken(token)     — Called for each streamed token string
 *   onCitations(srcs)  — Called once with the final citations array
 *   onError(message)   — Called if an error event is received
 *   onDone()           — Called when the stream is complete
 */
export async function streamAnswer(query, topK = 5, callbacks = {}) {
  const { onMeta, onToken, onCitations, onError, onDone } = callbacks;

  let response;
  try {
    response = await fetch(`${BASE_URL}/answer/`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ query, top_k: topK }),
    });
  } catch (err) {
    const msg = 'Cannot reach the backend. Make sure the FastAPI server is running on port 8000.';
    if (onError) onError(msg);
    return;
  }

  if (!response.ok) {
    let msg = `Server error ${response.status}`;
    try {
      const body = await response.json();
      msg = body.detail || msg;
    } catch (_) {}
    if (onError) onError(msg);
    return;
  }

  // Read the SSE stream line by line
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by double newlines
      const parts = buffer.split('\n\n');
      // Keep the last incomplete part in the buffer
      buffer = parts.pop() || '';

      for (const part of parts) {
        // Each part may have multiple lines; find the "data: " line
        for (const line of part.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          let event;
          try {
            event = JSON.parse(jsonStr);
          } catch (_) {
            continue;
          }

          switch (event.type) {
            case 'meta':
              if (onMeta) onMeta(event);
              break;
            case 'token':
              if (onToken) onToken(event.content);
              break;
            case 'citations':
              if (onCitations) onCitations(event.sources);
              break;
            case 'error':
              if (onError) onError(event.message);
              break;
            case 'done':
              if (onDone) onDone();
              break;
            default:
              break;
          }
        }
      }
    }
  } catch (err) {
    if (onError) onError(`Stream read error: ${err.message}`);
  } finally {
    reader.releaseLock();
  }
}

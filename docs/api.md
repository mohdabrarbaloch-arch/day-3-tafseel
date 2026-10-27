# API Reference

Base URL: `http://localhost:8000` (or your deployment).

All endpoints except `/api/health` and the auth pair require
`Authorization: Bearer <token>`.

Errors are always JSON: `{"detail": "..."}`. Validation errors return FastAPI's standard
422 array.

---

## Meta

### `GET /api/health`

No auth. Returns service and database status.

```json
{
  "status": "ok",
  "app": "Tafseel",
  "version": "1.0.0",
  "database": "ok",
  "environment": "development"
}
```

`status` is `degraded` if the database ping fails.

---

## Auth

### `POST /api/auth/register`

```json
{ "email": "you@example.com", "password": "at-least-8-chars" }
```

**201** → `{ "access_token": "...", "token_type": "bearer", "expires_in": 86400 }`

| Code | When |
|---|---|
| 409 | Email already registered |
| 422 | Password under 8 characters, or invalid email |
| 429 | Rate limited (10/minute) |

### `POST /api/auth/login`

Same body. **200** on success, **401** on bad credentials. Unknown email and wrong password
return the identical message — no user enumeration.

### `GET /api/auth/me`

**200** → `{ "id", "email", "created_at" }`. **401** without a valid token.

---

## Documents

### `POST /api/documents`

```json
{ "title": "Procurement policy", "content": "Full text here..." }
```

**201** →

```json
{
  "id": "a1b2c3...",
  "title": "Procurement policy",
  "source_type": "text",
  "char_count": 18422,
  "token_estimate": 4606,
  "chunk_count": 7,
  "redaction_count": 2,
  "created_at": "2026-10-28T00:12:00Z"
}
```

| Code | When |
|---|---|
| 413 | Over `MAX_DOCUMENT_CHARS` |
| 422 | Empty content, or the guardrail refused it |
| 429 | Rate limited |

### `POST /api/documents/upload`

`multipart/form-data` with `file` (required) and `title` (optional).

Accepted: `.pdf`, `.txt`, `.md`, `.csv`, `.json`, `.log`. Max 10 MB.

| Code | When |
|---|---|
| 413 | File over 10 MB |
| 415 | Unsupported extension |
| 422 | Empty file, unreadable PDF, or a PDF with no extractable text (scanned) |

### `GET /api/documents`

**200** → array of document objects (no `content` field), newest first.

### `GET /api/documents/{id}`

**200** → document object **including** `content`. **404** if it does not exist *or* belongs
to another user — deliberately the same response, so the API never confirms that someone
else's document exists.

### `DELETE /api/documents/{id}`

**204** on success. **404** under the same ownership rule. Cascades to chunks.

---

## Analysis

### `POST /api/analysis`

```json
{
  "question": "What are the approval thresholds?",
  "document_ids": ["a1b2c3...", "d4e5f6..."]
}
```

**201** →

```json
{
  "id": "...",
  "question": "What are the approval thresholds?",
  "summary": "Approvals above PKR 500,000 require the finance director...",
  "status": "completed",
  "document_count": 2,
  "chunk_count": 41,
  "tokens_in": 18400,
  "tokens_out": 210,
  "compression_ratio": 0.9886,
  "safety_verdict": "allow",
  "duration_ms": 84,
  "created_at": "2026-10-28T00:14:00Z",
  "steps": [
    {
      "sequence": 0,
      "phase": "ingest",
      "title": "Loaded 2 document(s)",
      "detail": "73,600 characters across 2 file(s), split into 41 overlapping chunks...",
      "tokens_in": 18400,
      "tokens_out": 0
    }
  ]
}
```

`status` is `completed` when a summary was produced, `empty` when nothing matched.

| Code | When |
|---|---|
| 404 | A document ID does not exist or is not yours |
| 422 | Question under 3 chars, more than 12 documents, or the guardrail refused it |
| 429 | Rate limited (20/minute) |

### `GET /api/analysis`

**200** → last 50 analyses for the current user, newest first, each with its full trace.

### `GET /api/analysis/{id}`

**200** → one analysis with trace. **404** under the ownership rule.

### `POST /api/analysis/safety-check`

Dry-run the guardrails. Stores nothing.

```json
{ "text": "email me at test@example.com" }
```

**200** →

```json
{
  "verdict": "redact",
  "category": "pii",
  "reason": "Removed 1 piece(s) of personal data before processing: email.",
  "redactions": 1,
  "redacted_text": "email me at [REDACTED_EMAIL]"
}
```

`verdict` is `allow`, `redact`, or `refuse`.

---

## Rate limits

| Route group | Limit |
|---|---|
| `/api/auth/*` | 10/minute per IP |
| `/api/documents*`, `/api/analysis*` | 20/minute per IP |

Exceeding a limit returns **429** with `Retry-After: 60`.

## Security headers

Every response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, and a restrictive `Permissions-Policy`.

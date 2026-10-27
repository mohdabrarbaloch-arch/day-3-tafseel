# Architecture — Tafseel

Tafseel is a long-context reasoning assistant. You give it a stack of documents and one
question; it chunks them, summarises each chunk on its own, merges the results, and shows
you every step it took. A deterministic guardrail layer runs before anything is stored.

## Why this is not Day 1 or Day 2

| | Day 1 — NeuraChat | Day 2 — Aurora | **Day 3 — Tafseel** |
|---|---|---|---|
| Core job | Conversational chat | Document Q&A with citations | **Long-context reasoning over many docs** |
| Input shape | One message | One question, many files | **Many files, one question, arbitrarily long** |
| Technique | Streaming chat | Retrieval + extractive answer | **Chunked map-reduce summarisation** |
| Visible work | Token stream | Source cards | **Full reasoning trace, phase by phase** |
| Safety | Basic validation | Grounding refusal | **Input classification + PII redaction + refusal paths** |

Aurora answers *"what does this document say about X"*. Tafseel answers *"what do these
forty documents collectively say about X, and how did you work that out"*.

## System diagram

```
                        ┌──────────────────────────────┐
                        │   Browser (vanilla JS SPA)   │
                        │  vault · composer · trace    │
                        └──────────────┬───────────────┘
                                       │ JSON over HTTPS
                                       │ Bearer JWT
                        ┌──────────────▼───────────────┐
                        │        FastAPI app           │
                        │  ┌────────────────────────┐  │
                        │  │ security headers (mw)  │  │
                        │  │ CORS allow-list        │  │
                        │  │ slowapi rate limiting  │  │
                        │  └───────────┬────────────┘  │
                        │              │               │
                        │   ┌──────────▼──────────┐    │
                        │   │  GUARDRAILS         │    │
                        │   │  classify()         │    │
                        │   │  ├ refuse: 5 rules  │    │
                        │   │  └ redact: 5 PII    │    │
                        │   └──────────┬──────────┘    │
                        │              │ clean text    │
                        │   ┌──────────▼──────────┐    │
                        │   │  ENGINE             │    │
                        │   │  1 ingest  → chunk  │    │
                        │   │  2 plan    → idf    │    │
                        │   │  3 MAP     → per-ch │    │
                        │   │  4 REDUCE  → merge  │    │
                        │   │  5 attribute        │    │
                        │   └──────────┬──────────┘    │
                        └──────────────┼───────────────┘
                                       │
                        ┌──────────────▼───────────────┐
                        │  SQLAlchemy 2.0 ORM          │
                        │  users · documents · chunks  │
                        │  analyses · reasoning_steps  │
                        │  safety_events               │
                        └──────────────┬───────────────┘
                                       │
                     ┌─────────────────┴─────────────────┐
                     │                                   │
              SQLite (dev / Vercel /tmp)        PostgreSQL 16 (compose)
```

## Data flow, end to end

1. **Upload.** `POST /api/documents` (JSON) or `/api/documents/upload` (multipart).
   PDFs go through `pypdf`; text formats are decoded as UTF-8 with a replacement fallback.
2. **Guardrail.** `sanitize_for_storage()` classifies the text. A refusal returns 422 and
   stores nothing. PII is replaced with typed placeholders (`[REDACTED_CNIC]`) *before*
   the row is written, so the raw value never reaches the database.
3. **Chunk.** `chunk_text()` splits on sentence boundaries into ~700-token windows with
   80 tokens of overlap. Overlap is the point: a fact sitting on a boundary would
   otherwise be cut in half and lost by both chunks.
4. **Persist.** The document row plus one `chunks` row per chunk.
5. **Ask.** `POST /api/analysis` with a question and a list of document IDs.
6. **Map.** Each chunk is scored sentence-by-sentence against the question using IDF
   weights, and its best sentences are kept. **No chunk sees any other chunk** — that is
   what makes input length irrelevant.
7. **Reduce.** Chunk summaries are ranked by relevance, near-duplicates from the overlap
   window are removed, and the top N sentences form the final summary.
8. **Trace.** Every phase appends a `ReasoningStep` with real token counts. The UI renders
   these as a timeline. Nothing in the trace is decorative — each line describes work that
   actually ran.
9. **Return.** Summary, stats, safety verdict, and the full step list in one response.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI 0.115 | Typed request/response models, automatic OpenAPI |
| ORM | SQLAlchemy 2.0 (typed `Mapped`) | Works on SQLite and Postgres unchanged |
| Validation | Pydantic v2 | Field-level constraints, no hand-rolled checks |
| Auth | JWT (HS256) + bcrypt (12 rounds) | Stateless, no session store needed |
| Rate limit | slowapi | Per-IP, per-route, disabled under test |
| PDF | pypdf 5.1 | Pure Python, no system dependencies |
| Frontend | Vanilla JS, no build step | Ships as static files, zero toolchain |
| Tests | pytest | 53 tests across engine, guardrails, API, packaging |

## The engine, precisely

**Token estimate.** `ceil(len(text) / 4)`. Not a real tokenizer — a real one would add a
heavy dependency for a number that only needs to be roughly right for chunk sizing.

**Chunking.** Sentences are accumulated until the character budget (`tokens × 4`) is hit,
then flushed. The tail of each chunk is carried into the next as overlap. A single
sentence longer than the budget is hard-split so no chunk can ever exceed the limit.

**Scoring.** `sum(idf[term] for term in sentence if term in query) / sqrt(len(words))`.
The `sqrt` normalisation stops a long sentence from winning purely by being long. IDF is
computed once across all chunks, so a term appearing everywhere contributes almost nothing.

**Reduce.** Sorted by relevance, then de-duplicated on the first eight content words of
each sentence. That fingerprint is what removes the overlap duplicates.

**Determinism.** Same input, same output, every time. That is a deliberate trade against
using a hosted model: the trace is truthful, the tests are stable, and there is no API key
between a user and their own documents.

## Safety layer

Two independent mechanisms, both deterministic and both unit-tested.

**Refusal rules** (5 categories): credential theft, malware, self-harm, weapons, prompt
injection. A hit refuses the whole request with a human-readable reason and stores a
`safety_events` row.

**PII redaction** (5 patterns): CNIC, email, IBAN, card number, Pakistani phone. Ordered
most-specific-first so a CNIC is not half-eaten by the phone rule. Redaction happens before
storage, not on read.

Every decision — including `allow` — is logged to `safety_events`. A guardrail you cannot
audit is a guardrail you cannot trust.

## Scaling notes

**Where it breaks first.** The engine is CPU-bound and runs inside the request. At ~2M
characters a single analysis takes a few seconds. Past that, move the map phase to a
background worker and return a job ID.

**Chunk storage.** Chunks are persisted, so a re-analysis does not re-chunk. At scale,
`chunks` becomes the largest table; index on `document_id` (already done) and consider
partitioning by `created_at`.

**Vector search.** The current scoring is lexical, so a paraphrased question can miss.
The natural upgrade is pgvector embeddings alongside the IDF score, blended — not replaced,
because lexical still wins on exact identifiers like a CNIC or a part number.

**Horizontal scale.** The app is stateless apart from the database, so it scales by adding
instances. Rate limiting is in-process, which means N instances allow N× the limit; move
the limiter to Redis before running more than one.

**Vercel specifics.** SQLite lives at `/tmp` and is per-instance and ephemeral — fine for a
demo, wrong for production. Set `DATABASE_URL` to Postgres for anything real.

## Deployment

```
vercel.json
  functions: api/index.py  includeFiles: app/**
  rewrites:  /(.*) → /api/index.py
```

`includeFiles` is not optional. Without it the function bundle contains only
`api/index.py`, the `from app.main import app` import fails, and every `/api/*` route
returns 500 while `/` still serves HTML. That exact bug shipped on Day 1 and is now
covered by three tests in `tests/test_packaging.py`.

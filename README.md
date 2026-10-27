# Tafseel · تفصیل

**Long-context reasoning over your own documents — with the working shown.**

Tafseel takes a stack of long documents and one question. It splits them into overlapping
chunks, summarises each chunk on its own, merges the results, and then shows you every step
it took. A deterministic guardrail layer runs before anything is stored.

`tafseel` means *detail* or *elaboration* in Urdu. That's the whole idea: not just an answer,
but the detail of how the answer was reached.

[![Python](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Tests](https://img.shields.io/badge/tests-53%20passing-6F9E7C)](#tests)
[![Ruff](https://img.shields.io/badge/ruff-clean-D98B4A)](https://docs.astral.sh/ruff/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

---

## The problem it solves

Every "chat with your documents" tool hits the same wall: the document is longer than the
context window. The usual workaround is retrieval — find the three most similar paragraphs
and hope the answer is in one of them. That works for a lookup. It falls apart when the
question needs the whole document, or several documents at once.

Tafseel does the other thing. It reads everything, in pieces, and then combines the pieces.
Length stops being the limit.

## What makes it different from a chat app

| | Typical doc-chat | **Tafseel** |
|---|---|---|
| Long input | Truncated or retrieved | **Chunked, every chunk read** |
| Method | One model call | **Map-reduce across chunks** |
| Visible work | A spinner | **Five-phase trace with real token counts** |
| Safety | Post-hoc filter | **Classification + redaction before storage** |
| Failure mode | Confident wrong answer | **Empty summary, `status: "empty"`** |

## Features

**Long-context engine**
- Sentence-aware chunking with configurable overlap, so a fact on a boundary isn't lost
- Map phase summarises each chunk independently — input length becomes irrelevant
- Reduce phase ranks, de-duplicates overlap repeats, and merges
- IDF-weighted sentence scoring, normalised so long sentences don't win by length
- Per-document attribution of findings

**Visible reasoning**
- Every analysis returns five phases: `ingest → plan → map → reduce → attribute`
- Each step carries real token counts, not decorative text
- Compression ratio and wall-clock duration reported per run

**Safety guardrails**
- Five refusal categories: credential theft, malware, self-harm, weapons, prompt injection
- Five PII patterns redacted *before* the database write: CNIC, email, IBAN, card, phone
- Every decision logged to `safety_events` — including the ones that allowed the request
- Dry-run endpoint so the UI can preview a verdict without storing anything

**The rest**
- JWT auth with bcrypt (12 rounds), no user enumeration on login
- PDF, text, markdown, CSV and JSON ingestion
- Per-IP rate limiting, CORS allow-list, security headers
- Mobile-first dark UI, no build step, no framework
- 53 tests, ruff clean, black clean

## Screenshots

Captured from a real local run: three documents loaded, one question asked, 84% compression.

| Vault + composer | Reasoning trace |
|---|---|
| ![Vault](https://static.teamily.ai/sites/a36062a5-94f0-4879-bbed-66b664fb5f06/documents/vault/vault.png) | ![Trace](https://static.teamily.ai/sites/a36062a5-94f0-4879-bbed-66b664fb5f06/documents/trace/trace.png) |

Sign-in screen: [auth.png](https://static.teamily.ai/sites/a36062a5-94f0-4879-bbed-66b664fb5f06/documents/auth/auth.png)

The trace shot is the point of the whole project — five phases, each with the token
accounting that phase actually produced (`998 → 0`, `998 → 249`, `249 → 157`).

## Live demo

**Not deployed yet.** No `VERCEL_TOKEN` was available in the build environment, so there is
no live URL and I'm not going to invent one. The repo ships `vercel.json`, a serverless
entrypoint, a Dockerfile and a health-checked compose stack — with a token it goes live in
about two minutes:

```bash
npm i -g vercel
vercel --prod
```

Then set `SECRET_KEY` and `DATABASE_URL` in the project settings.

## Quick start

```bash
git clone https://github.com/mohdabrarbaloch-arch/day-3-tafseel.git
cd day-3-tafseel

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into SECRET_KEY

uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000>. API docs at <http://localhost:8000/api/docs>.

### With Docker + Postgres

```bash
docker compose up --build
```

## How it works

```
documents ──► guardrail ──► chunk ──► MAP (per chunk) ──► REDUCE ──► summary
                 │                        │                  │
             refuse/redact            score sentences    rank + dedupe
                 │                        │                  │
                 └──────────── every phase logged as a ReasoningStep ────────┘
```

1. **Guardrail.** Classify the input. Refuse hard-rule hits; redact PII. Nothing is stored
   until this passes.
2. **Chunk.** Split on sentence boundaries into ~700-token windows with 80 tokens of
   overlap. A single oversized sentence is hard-split so no chunk can exceed the budget.
3. **Map.** Score every sentence in a chunk against the question's IDF-weighted terms and
   keep the best. No chunk sees any other chunk.
4. **Reduce.** Rank chunk summaries by relevance, drop near-duplicates from the overlap
   window, keep the top N.
5. **Attribute.** Map the result back to source documents.

Full detail in [ARCHITECTURE.md](ARCHITECTURE.md).

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Service + database status |
| `POST` | `/api/auth/register` | Create account, returns JWT |
| `POST` | `/api/auth/login` | Sign in |
| `GET` | `/api/auth/me` | Current user |
| `POST` | `/api/documents` | Add a document from text |
| `POST` | `/api/documents/upload` | Upload a file |
| `GET` | `/api/documents` | List your documents |
| `GET` | `/api/documents/{id}` | One document with content |
| `DELETE` | `/api/documents/{id}` | Delete |
| `POST` | `/api/analysis` | Run map-reduce, get summary + trace |
| `GET` | `/api/analysis` | Recent analyses |
| `POST` | `/api/analysis/safety-check` | Dry-run the guardrails |

Full reference: [docs/api.md](docs/api.md).

## Tests

```bash
pip install -r requirements-dev.txt
PYTHONPATH=$PWD pytest
```

```
53 passed
```

Coverage is deliberately weighted toward the parts that can silently be wrong:

- **`test_engine.py`** (18) — chunking, overlap, IDF weighting, map-reduce phases,
  compression ratio, deduplication
- **`test_guardrails.py`** (13) — every refusal category, every PII pattern, ordering
- **`test_api.py`** (16) — auth, ownership (404 not 403), validation, trace shape
- **`test_packaging.py`** (6) — the Vercel bundle rules that broke Day 1

## Lint

```bash
ruff check app tests api     # All checks passed!
black --check app tests api  # 20 files would be left unchanged
```

## A note on the deployment bug

Day 1 of this challenge shipped with a bug worth documenting. `vercel.json` used the legacy
`builds` block, which compiled only `api/index.py`. The `app/` package was never bundled, so
`from app.main import app` failed at import time and every `/api/*` route returned 500 —
while `/` still served a friendly HTML page, because a catch-all rewrite swallowed the error.

The site looked healthy. It wasn't.

Tafseel closes that hole three ways, and `tests/test_packaging.py` asserts all three:

1. `includeFiles: "app/**"` ships the whole package with the function
2. No static catch-all — unknown paths return JSON 404, so a broken import is visible
3. `init_db()` runs at import time, because Vercel never fires lifespan events

## Tech stack

FastAPI 0.115 · SQLAlchemy 2.0 · Pydantic v2 · python-jose · bcrypt · pypdf · slowapi ·
SQLite (dev) / PostgreSQL 16 (compose) · vanilla JS frontend

## License

MIT — see [LICENSE](LICENSE).

---

Built by [ABraz Baloch](https://github.com/mohdabrarbaloch-arch) as Day 3 of a 30-day
build challenge. Day 1 was a chat assistant, Day 2 was document Q&A with citations, and
this one is the long-context reasoning layer that neither of them had.

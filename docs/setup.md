# Setup

## Requirements

- Python 3.11+
- pip
- Optional: Docker + Docker Compose (for the Postgres path)

## Local, SQLite (fastest)

```bash
cd project-day-3-tafseel
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Generate a real key -- the dev default is rejected in production
python -c "import secrets; print(secrets.token_urlsafe(48))"
# paste it into .env as SECRET_KEY

uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000. The API docs are at http://localhost:8000/api/docs.

## Local, PostgreSQL

```bash
docker compose up --build
```

That starts Postgres 16 and the app on port 8000, with a healthcheck on both. The app
waits for the database to report ready before it starts.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | dev placeholder | **Required in production.** JWT signing key. |
| `DATABASE_URL` | SQLite | On Vercel the default becomes `sqlite:////tmp/tafseel.db`. |
| `ENVIRONMENT` | `development` | `production` enforces the secret check. |
| `DEBUG` | `false` | |
| `ACCESS_TOKEN_MINUTES` | `1440` | JWT lifetime. |
| `CHUNK_SIZE_TOKENS` | `700` | Approximate tokens per chunk. |
| `CHUNK_OVERLAP_TOKENS` | `80` | Overlap carried into the next chunk. |
| `MAX_DOCUMENT_CHARS` | `2000000` | Hard cap per document. |
| `MAX_DOCUMENTS_PER_ANALYSIS` | `12` | Documents per analysis pass. |
| `SUMMARY_SENTENCES` | `7` | Sentences in the reduced summary. |
| `CORS_ORIGINS` | localhost | Comma-separated allow-list. Never `*` in production. |
| `RATE_LIMIT_ANALYSIS` | `20/minute` | |
| `RATE_LIMIT_AUTH` | `10/minute` | |

## Tests

```bash
pip install -r requirements-dev.txt
PYTHONPATH=$PWD pytest
```

53 tests. Rate limiting is automatically disabled when `ENVIRONMENT=test`, so the suite
does not trip its own auth limit.

## Lint and format

```bash
ruff check app tests api
black --check app tests api
```

## Deploying to Vercel

```bash
npm i -g vercel
vercel --prod
```

Set `SECRET_KEY` and `DATABASE_URL` in the Vercel project settings. **Do not rely on the
SQLite default in production** — `/tmp` is per-instance and wiped between cold starts.

## Troubleshooting

**`/api/*` returns 500 but `/` loads.** The function bundle is missing the `app` package.
Check that `vercel.json` has `includeFiles: "app/**"` and no legacy `builds` block.

**`unable to open database file`.** SQLite is pointing at a read-only path. On Vercel it
must be `/tmp`; the app does this automatically when it detects `VERCEL`.

**`Directory 'app/static' does not exist`.** The static mount is unguarded. It must be
wrapped in `if STATIC_DIR.is_dir():`.

**429 on every request.** You are hitting the rate limit. Raise `RATE_LIMIT_*` or set
`ENVIRONMENT=test` locally.

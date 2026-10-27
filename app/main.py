"""Tafseel -- long-context reasoning assistant.

Vercel notes (learned the hard way on Days 1 and 2):
  * init_db() runs at import time. Vercel never fires lifespan events.
  * The static mount is guarded by a directory check, because StaticFiles raises at
    import time if the directory is missing -- which turns every /api/* route into a
    500 before FastAPI even finishes constructing.
  * Unknown paths return JSON 404 rather than a friendly HTML shell, so a broken
    import surfaces as a visible error instead of a healthy-looking page.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import init_db
from app.limiter import limiter
from app.routers import analysis, auth, documents
from app.schemas import HealthResponse

# Import-time table creation -- required on Vercel.
init_db()

app = FastAPI(
    title=f"{settings.app_name} API",
    version=settings.version,
    description=(
        "Long-context reasoning over your own documents: chunked map-reduce "
        "summarisation with a visible reasoning trace and a deterministic safety layer."
    ),
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Slow down a little and try again."},
        headers={"Retry-After": "60"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(analysis.router)


@app.api_route("/api/health", methods=["GET", "HEAD"], response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    database = "ok"
    try:
        from sqlalchemy import text

        from app.database import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - only on a genuinely broken DB
        database = "error"

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        app=settings.app_name,
        version=settings.version,
        database=database,
        environment=settings.environment,
    )


# --- Static frontend ---------------------------------------------------------
STATIC_DIR = Path(__file__).parent / "static"

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

else:  # pragma: no cover - only when the frontend is not bundled

    @app.get("/", include_in_schema=False)
    def index_missing() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "Frontend assets are not bundled in this deployment."},
        )


@app.exception_handler(404)
def _not_found(request: Request, exc) -> JSONResponse:
    """JSON 404 -- never a catch-all HTML shell that hides a broken backend."""
    return JSONResponse(status_code=404, content={"detail": "Not found", "path": request.url.path})

"""Documents: upload text or PDF, list, read, delete.

Every document passes through the guardrail layer before it is stored, so PII never
lands in the database in the first place.
"""

import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.engine import chunk_text, estimate_tokens
from app.guardrails import sanitize_for_storage
from app.limiter import limiter
from app.models import Chunk, Document, SafetyEvent, User
from app.schemas import DocumentCreate, DocumentDetail, DocumentOut
from app.security import get_current_user

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _extract_pdf(raw: bytes) -> str:
    """Pull text out of a PDF. Raises 422 with a useful message on failure."""
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dependency is pinned
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="PDF support is not installed"
        ) from None

    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Could not read that PDF: {exc}"
        ) from exc

    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That PDF has no extractable text -- it is probably a scan. OCR is not enabled.",
        )
    return text


def _store_document(db: Session, user: User, title: str, text: str, source_type: str) -> Document:
    if len(text) > settings.max_document_chars:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Document is {len(text):,} characters; the limit is "
                f"{settings.max_document_chars:,}. Split it into parts."
            ),
        )

    clean_text, verdict = sanitize_for_storage(text)
    db.add(
        SafetyEvent(
            owner_id=user.id,
            direction="input",
            verdict=verdict.verdict,
            category=verdict.category,
            reason=verdict.reason,
            redactions=verdict.redactions,
        )
    )
    if verdict.blocked:
        db.commit()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=verdict.reason)

    chunks = chunk_text(clean_text)
    document = Document(
        owner_id=user.id,
        title=title.strip()[:255],
        source_type=source_type,
        char_count=len(clean_text),
        token_estimate=estimate_tokens(clean_text),
        chunk_count=len(chunks),
        redaction_count=verdict.redactions,
        content=clean_text,
    )
    db.add(document)
    db.flush()

    for chunk in chunks:
        db.add(
            Chunk(
                document_id=document.id,
                index=chunk.index,
                text=chunk.text,
                token_estimate=chunk.token_estimate,
            )
        )

    db.commit()
    db.refresh(document)
    return document


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_analysis)
def create_document(
    request: Request,
    payload: DocumentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Document:
    return _store_document(db, current_user, payload.title, payload.content, "text")


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_analysis)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Document:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The file is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File is {len(raw) / 1_048_576:.1f} MB; the limit is 10 MB.",
        )

    filename = file.filename or "untitled"
    lowered = filename.lower()
    if lowered.endswith(".pdf"):
        text = _extract_pdf(raw)
        source_type = "pdf"
    elif lowered.endswith((".txt", ".md", ".csv", ".json", ".log")):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        source_type = "text"
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Supported file types: .pdf, .txt, .md, .csv, .json, .log",
        )

    return _store_document(db, current_user, title or filename, text, source_type)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[Document]:
    return list(
        db.scalars(
            select(Document).where(Document.owner_id == current_user.id).order_by(Document.created_at.desc())
        )
    )


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Document:
    document = db.get(Document, document_id)
    # 404 rather than 403: never confirm that someone else's document exists.
    if document is None or document.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    document = db.get(Document, document_id)
    if document is None or document.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    db.delete(document)
    db.commit()

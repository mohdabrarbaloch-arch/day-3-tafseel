"""Analysis: run the map-reduce pass and return the reasoning trace."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.engine import analyse
from app.guardrails import classify
from app.limiter import limiter
from app.models import Analysis, Document, ReasoningStep, SafetyEvent, User
from app.schemas import AnalysisOut, AnalysisRequest, SafetyCheckRequest, SafetyCheckResponse
from app.security import get_current_user

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.post("", response_model=AnalysisOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_analysis)
def create_analysis(
    request: Request,
    payload: AnalysisRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Analysis:
    # --- Guardrail the question first -------------------------------------
    verdict = classify(payload.question)
    db.add(
        SafetyEvent(
            owner_id=current_user.id,
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
    question = verdict.redacted_text or payload.question

    # --- Load the requested documents, scoped to the owner -----------------
    if len(payload.document_ids) > settings.max_documents_per_analysis:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"At most {settings.max_documents_per_analysis} documents per analysis.",
        )

    documents = list(
        db.scalars(
            select(Document).where(
                Document.id.in_(payload.document_ids), Document.owner_id == current_user.id
            )
        )
    )
    if len(documents) != len(set(payload.document_ids)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more documents were not found",
        )

    # --- Run the engine ----------------------------------------------------
    result = analyse([(d.title, d.content) for d in documents], question)

    analysis = Analysis(
        owner_id=current_user.id,
        question=question,
        summary=result.summary,
        status="completed" if result.summary else "empty",
        document_count=len(documents),
        chunk_count=result.chunk_count,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        compression_ratio=result.compression_ratio,
        safety_verdict=verdict.verdict,
        duration_ms=result.duration_ms,
    )
    db.add(analysis)
    db.flush()

    for index, step in enumerate(result.steps):
        db.add(
            ReasoningStep(
                analysis_id=analysis.id,
                sequence=index,
                phase=step.phase,
                title=step.title,
                detail=step.detail,
                tokens_in=step.tokens_in,
                tokens_out=step.tokens_out,
            )
        )

    db.commit()
    db.refresh(analysis)
    return analysis


@router.get("", response_model=list[AnalysisOut])
def list_analyses(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[Analysis]:
    return list(
        db.scalars(
            select(Analysis)
            .where(Analysis.owner_id == current_user.id)
            .order_by(Analysis.created_at.desc())
            .limit(50)
        )
    )


@router.get("/{analysis_id}", response_model=AnalysisOut)
def get_analysis(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Analysis:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or analysis.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return analysis


@router.post("/safety-check", response_model=SafetyCheckResponse)
@limiter.limit(settings.rate_limit_analysis)
def safety_check(
    request: Request, payload: SafetyCheckRequest, current_user: User = Depends(get_current_user)
) -> SafetyCheckResponse:
    """Dry-run the guardrails without storing anything. Useful for the UI preview."""
    verdict = classify(payload.text)
    return SafetyCheckResponse(
        verdict=verdict.verdict,
        category=verdict.category,
        reason=verdict.reason,
        redactions=verdict.redactions,
        redacted_text=verdict.redacted_text or payload.text,
    )

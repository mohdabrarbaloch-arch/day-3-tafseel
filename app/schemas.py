"""Request/response contracts. Pydantic does the validation so routers stay thin."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    created_at: datetime


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    source_type: str
    char_count: int
    token_estimate: int
    chunk_count: int
    redaction_count: int
    created_at: datetime


class DocumentDetail(DocumentOut):
    content: str


class AnalysisRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    document_ids: list[str] = Field(min_length=1, max_length=12)


class ReasoningStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    phase: str
    title: str
    detail: str
    tokens_in: int
    tokens_out: int


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    question: str
    summary: str
    status: str
    document_count: int
    chunk_count: int
    tokens_in: int
    tokens_out: int
    compression_ratio: float
    safety_verdict: str
    duration_ms: int
    created_at: datetime
    steps: list[ReasoningStepOut] = []


class SafetyCheckRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class SafetyCheckResponse(BaseModel):
    verdict: str
    category: str
    reason: str
    redactions: int
    redacted_text: str


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    database: str
    environment: str

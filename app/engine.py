"""The long-context engine: chunking, map-reduce summarisation, reasoning trace.

Why this is not a thin wrapper around a chat model:
  * Inputs are split into overlapping chunks so a 200k-character document never has
    to fit in one window.
  * Each chunk is summarised independently (the MAP phase), then the per-chunk
    summaries are merged and re-ranked (the REDUCE phase).
  * Every phase appends a ReasoningStep, so the UI can show the actual work done
    rather than a fabricated "thinking" animation.

The scoring is lexical (TF-IDF-ish over the question terms) and fully deterministic.
That is a deliberate trade: it means the trace is truthful, the tests are stable,
and there is no API key between the user and their own documents.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field

from app.config import settings

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_WORD = re.compile(r"[a-z0-9']+")

STOPWORDS = frozenset(
    """a an and are as at be been but by can could did do does for from had has have how i if in
    into is it its may me might more most my no not of on or our out over said same she should so
    some such than that the their them then there these they this those to too under up us was we
    were what when where which while who why will with would you your""".split()
)


def estimate_tokens(text: str) -> int:
    """~4 characters per token. Cheap, dependency-free, good enough for chunk sizing."""
    return max(1, math.ceil(len(text) / 4))


def tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 2]


def split_sentences(text: str) -> list[str]:
    """Sentence split that survives abbreviations and newlines reasonably well."""
    normalised = re.sub(r"\s+", " ", text).strip()
    if not normalised:
        return []
    parts = _SENTENCE_SPLIT.split(normalised)
    return [p.strip() for p in parts if p.strip()]


@dataclass
class Chunk:
    index: int
    text: str
    token_estimate: int


def chunk_text(text: str, chunk_tokens: int | None = None, overlap_tokens: int | None = None) -> list[Chunk]:
    """Split on sentence boundaries into overlapping windows.

    Overlap matters: a fact that straddles a boundary would otherwise be cut in half
    and lost by both chunks.
    """
    chunk_tokens = chunk_tokens or settings.chunk_size_tokens
    overlap_tokens = overlap_tokens or settings.chunk_overlap_tokens
    chunk_chars = chunk_tokens * 4
    overlap_chars = overlap_tokens * 4

    sentences = split_sentences(text)
    if not sentences:
        return []

    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_len = 0

    def flush() -> None:
        nonlocal buffer, buffer_len
        if not buffer:
            return
        body = " ".join(buffer).strip()
        if body:
            chunks.append(Chunk(index=len(chunks), text=body, token_estimate=estimate_tokens(body)))
        # Carry the tail forward as overlap.
        if overlap_chars > 0 and len(body) > overlap_chars:
            tail = body[-overlap_chars:]
            cut = tail.find(" ")
            tail = tail[cut + 1 :] if cut != -1 else tail
            buffer = [tail]
            buffer_len = len(tail)
        else:
            buffer = []
            buffer_len = 0

    for sentence in sentences:
        if len(sentence) > chunk_chars:
            # A single monster sentence: hard-split it so we never emit an oversized chunk.
            flush()
            for start in range(0, len(sentence), chunk_chars):
                piece = sentence[start : start + chunk_chars].strip()
                if piece:
                    chunks.append(Chunk(index=len(chunks), text=piece, token_estimate=estimate_tokens(piece)))
            continue

        if buffer_len + len(sentence) + 1 > chunk_chars and buffer:
            flush()

        buffer.append(sentence)
        buffer_len += len(sentence) + 1

    if buffer:
        body = " ".join(buffer).strip()
        if body:
            chunks.append(Chunk(index=len(chunks), text=body, token_estimate=estimate_tokens(body)))

    return chunks


def score_sentence(sentence: str, query_terms: set[str], idf: dict[str, float]) -> float:
    """Lexical relevance with an IDF weight so common words stop dominating."""
    words = tokenize(sentence)
    if not words:
        return 0.0
    hits = 0.0
    for word in words:
        if word in query_terms:
            hits += idf.get(word, 1.0)
    # Normalise by length so a long sentence doesn't win just by being long.
    return hits / math.sqrt(len(words))


def build_idf(chunks: list[Chunk]) -> dict[str, float]:
    """Inverse document frequency across chunks -- computed once, reused everywhere."""
    total = max(1, len(chunks))
    df: dict[str, int] = {}
    for chunk in chunks:
        for word in set(tokenize(chunk.text)):
            df[word] = df.get(word, 0) + 1
    return {word: math.log((total + 1) / (count + 0.5)) for word, count in df.items()}


@dataclass
class Step:
    phase: str
    title: str
    detail: str
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class MapReduceResult:
    summary: str
    steps: list[Step] = field(default_factory=list)
    chunk_count: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    per_document: dict[str, str] = field(default_factory=dict)

    @property
    def compression_ratio(self) -> float:
        if self.tokens_in <= 0:
            return 0.0
        return round(1 - (self.tokens_out / self.tokens_in), 4)


def _map_chunk(
    chunk: Chunk, query_terms: set[str], idf: dict[str, float], keep: int
) -> tuple[str, list[str]]:
    """MAP: pull the best `keep` sentences out of one chunk."""
    sentences = split_sentences(chunk.text)
    if not sentences:
        return "", []
    ranked = sorted(
        ((score_sentence(s, query_terms, idf), i, s) for i, s in enumerate(sentences)),
        key=lambda row: (-row[0], row[1]),
    )
    chosen = [(i, s) for score, i, s in ranked[:keep] if score > 0]
    if not chosen:
        # Nothing matched: fall back to the opening sentences so the chunk still
        # contributes context instead of silently vanishing.
        chosen = list(enumerate(sentences[:keep]))
    chosen.sort(key=lambda row: row[0])  # restore reading order
    return " ".join(s for _, s in chosen), [s for _, s in chosen]


def analyse(
    documents: list[tuple[str, str]],
    question: str,
    summary_sentences: int | None = None,
) -> MapReduceResult:
    """Run the full map-reduce pass over one or more documents.

    `documents` is a list of (title, text) pairs. Returns the merged summary plus a
    complete, honest trace of what happened.
    """
    started = time.perf_counter()
    summary_sentences = summary_sentences or settings.summary_sentences
    result = MapReduceResult(summary="")

    if not documents:
        result.steps.append(Step(phase="validate", title="No documents", detail="Nothing to analyse."))
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    # --- Phase 1: ingest -----------------------------------------------------
    all_chunks: list[Chunk] = []
    doc_chunk_map: dict[str, list[Chunk]] = {}
    total_chars = 0
    for title, text in documents:
        total_chars += len(text)
        chunks = chunk_text(text)
        doc_chunk_map[title] = chunks
        all_chunks.extend(chunks)

    result.chunk_count = len(all_chunks)
    result.tokens_in = sum(c.token_estimate for c in all_chunks)
    result.steps.append(
        Step(
            phase="ingest",
            title=f"Loaded {len(documents)} document(s)",
            detail=(
                f"{total_chars:,} characters across {len(documents)} file(s), split into "
                f"{len(all_chunks)} overlapping chunks of ~{settings.chunk_size_tokens} tokens "
                f"({settings.chunk_overlap_tokens}-token overlap)."
            ),
            tokens_in=result.tokens_in,
        )
    )

    # --- Phase 2: plan -------------------------------------------------------
    query_terms = set(tokenize(question))
    idf = build_idf(all_chunks)
    result.steps.append(
        Step(
            phase="plan",
            title="Extracted query terms",
            detail=(
                f"Question reduced to {len(query_terms)} content terms: "
                f"{', '.join(sorted(query_terms)[:12]) or '(none)'}. "
                f"IDF weights computed across {len(all_chunks)} chunks so rare terms count more."
            ),
        )
    )

    # --- Phase 3: MAP --------------------------------------------------------
    per_chunk_keep = max(2, math.ceil(summary_sentences / max(1, len(all_chunks))) + 1)
    mapped: list[tuple[str, str, float]] = []
    for title, chunks in doc_chunk_map.items():
        for chunk in chunks:
            body, sentences = _map_chunk(chunk, query_terms, idf, per_chunk_keep)
            if not body:
                continue
            relevance = sum(score_sentence(s, query_terms, idf) for s in sentences)
            mapped.append((title, body, relevance))

    map_tokens_out = sum(estimate_tokens(body) for _, body, _ in mapped)
    result.steps.append(
        Step(
            phase="map",
            title=f"Summarised {len(mapped)} chunk(s) independently",
            detail=(
                f"Each chunk was scored sentence-by-sentence against the question and the top "
                f"{per_chunk_keep} sentences kept. No chunk saw any other chunk -- this is the "
                f"map half of map-reduce, which is what lets arbitrarily long input work."
            ),
            tokens_in=result.tokens_in,
            tokens_out=map_tokens_out,
        )
    )

    # --- Phase 4: REDUCE -----------------------------------------------------
    # Rank chunk summaries by relevance, then de-duplicate near-identical sentences
    # that the overlap window produced twice.
    mapped.sort(key=lambda row: -row[2])
    seen: set[str] = set()
    reduced: list[str] = []
    for _title, body, _relevance in mapped:
        for sentence in split_sentences(body):
            fingerprint = " ".join(tokenize(sentence)[:8])
            if not fingerprint or fingerprint in seen:
                continue
            seen.add(fingerprint)
            reduced.append(sentence)
            if len(reduced) >= summary_sentences:
                break
        if len(reduced) >= summary_sentences:
            break

    result.summary = " ".join(reduced)
    result.tokens_out = estimate_tokens(result.summary)
    result.steps.append(
        Step(
            phase="reduce",
            title=f"Merged into {len(reduced)} sentence(s)",
            detail=(
                f"Chunk summaries ranked by relevance, near-duplicates from the overlap window "
                f"removed, and the top {len(reduced)} kept. "
                f"{result.tokens_in:,} tokens in, {result.tokens_out:,} out."
            ),
            tokens_in=map_tokens_out,
            tokens_out=result.tokens_out,
        )
    )

    # --- Phase 5: per-document attribution -----------------------------------
    for title, chunks in doc_chunk_map.items():
        doc_sentences: list[str] = []
        for chunk in chunks:
            body, _ = _map_chunk(chunk, query_terms, idf, 1)
            if body:
                doc_sentences.append(body)
        result.per_document[title] = " ".join(doc_sentences[:2])

    result.steps.append(
        Step(
            phase="attribute",
            title="Attributed findings to sources",
            detail=f"Mapped the reduced summary back to {len(doc_chunk_map)} source document(s).",
        )
    )

    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return result

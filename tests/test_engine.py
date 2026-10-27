"""Chunking, token estimation and map-reduce behaviour."""

from app.engine import (
    analyse,
    build_idf,
    chunk_text,
    estimate_tokens,
    score_sentence,
    split_sentences,
    tokenize,
)

LONG_DOC = " ".join(
    f"Sentence number {i} explains that the western rivers include the Indus and Jhelum {i}."
    for i in range(1, 120)
)


def test_estimate_tokens_is_roughly_four_chars():
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens("") == 1  # never returns zero


def test_tokenize_drops_stopwords_and_short_words():
    words = tokenize("The treaty was signed by the World Bank in 1960")
    assert "the" not in words
    assert "was" not in words
    assert "treaty" in words
    assert "1960" in words


def test_split_sentences_handles_multiple():
    sentences = split_sentences("First one here. Second one there. Third one now.")
    assert len(sentences) == 3


def test_split_sentences_on_empty_input():
    assert split_sentences("   ") == []


def test_chunk_text_produces_multiple_chunks_for_long_input():
    chunks = chunk_text(LONG_DOC, chunk_tokens=100, overlap_tokens=10)
    assert len(chunks) > 3
    assert all(c.token_estimate > 0 for c in chunks)


def test_chunk_indices_are_sequential():
    chunks = chunk_text(LONG_DOC, chunk_tokens=100, overlap_tokens=10)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunks_overlap_so_boundaries_are_not_lost():
    chunks = chunk_text(LONG_DOC, chunk_tokens=100, overlap_tokens=20)
    assert len(chunks) >= 2
    # The closing words of one chunk should reappear at the start of the next.
    tail_words = set(chunks[0].text.split()[-8:])
    head_words = set(chunks[1].text.split()[:20])
    assert tail_words & head_words


def test_chunk_text_returns_empty_for_blank_input():
    assert chunk_text("    ") == []


def test_giant_single_sentence_is_hard_split():
    monster = "word " * 5000
    chunks = chunk_text(monster, chunk_tokens=50, overlap_tokens=0)
    assert len(chunks) > 1
    assert all(len(c.text) <= 50 * 4 + 10 for c in chunks)


def test_build_idf_downweights_common_terms():
    """A term in every chunk must score lower than a term in only one."""
    body = "common scaffold text here. " * 60
    chunks = chunk_text(
        body + " The word zygomorphic appears exactly once.", chunk_tokens=50, overlap_tokens=0
    )
    idf = build_idf(chunks)
    assert "zygomorphic" in idf
    # "scaffold" shows up everywhere, so its IDF weight must be far lower.
    assert idf["scaffold"] < idf["zygomorphic"]


def test_score_sentence_favours_matching_text():
    idf = {"treaty": 2.0, "banana": 2.0}
    relevant = score_sentence("The treaty was signed", {"treaty"}, idf)
    irrelevant = score_sentence("A banana is yellow", {"treaty"}, idf)
    assert relevant > irrelevant


def test_analyse_returns_summary_and_steps():
    result = analyse([("rivers.txt", LONG_DOC)], "Which rivers are in the west?")
    assert result.summary
    assert result.chunk_count > 1
    phases = [s.phase for s in result.steps]
    assert phases == ["ingest", "plan", "map", "reduce", "attribute"]


def test_analyse_compression_ratio_is_between_zero_and_one():
    result = analyse([("rivers.txt", LONG_DOC)], "Which rivers are in the west?")
    assert 0.0 <= result.compression_ratio <= 1.0


def test_analyse_with_no_documents_is_handled():
    result = analyse([], "anything")
    assert result.summary == ""
    assert result.steps[0].phase == "validate"


def test_analyse_across_multiple_documents():
    doc_a = "The Indus is the longest river in Pakistan. It flows south to the Arabian Sea."
    doc_b = "The Jhelum joins the Chenab in Punjab. Both are western rivers."
    result = analyse([("a.txt", doc_a), ("b.txt", doc_b)], "western rivers")
    assert result.summary
    assert len(result.per_document) == 2


def test_summary_respects_requested_sentence_count():
    result = analyse([("rivers.txt", LONG_DOC)], "rivers", summary_sentences=3)
    assert len(split_sentences(result.summary)) <= 4


def test_map_phase_records_token_accounting():
    result = analyse([("rivers.txt", LONG_DOC)], "rivers")
    map_step = next(s for s in result.steps if s.phase == "map")
    assert map_step.tokens_in > 0
    assert map_step.tokens_out > 0


def test_reduce_deduplicates_overlap_repeats():
    """Overlap can hand the same sentence to two chunks; the reduce step must dedupe."""
    doc = "Alpha beta gamma. " * 40
    result = analyse([("repeats.txt", doc)], "alpha beta", summary_sentences=6)
    sentences = split_sentences(result.summary)
    assert len(sentences) == len(set(sentences))

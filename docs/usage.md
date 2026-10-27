# Usage

## The short version

1. Create an account.
2. Drop in a few documents — PDFs, text, markdown, CSV, JSON.
3. Tick the ones you want to reason over.
4. Ask one question.
5. Read the summary, then read the trace underneath it.

## What the trace is telling you

Every analysis returns five phases. They are not decoration — each one describes work that
actually ran, with real token counts.

| Phase | What happened |
|---|---|
| `ingest` | Your documents were split into overlapping chunks. |
| `plan` | Your question was reduced to content terms and weighted by rarity. |
| `map` | Each chunk was summarised **independently**. |
| `reduce` | Chunk summaries were ranked, de-duplicated, and merged. |
| `attribute` | Findings were mapped back to their source documents. |

If a summary looks wrong, the trace usually tells you why. A `map` step reporting one
chunk means your document was short. A `reduce` step that kept only two sentences means
nothing else cleared the relevance bar.

## Reading the stats

- **in / out** — estimated tokens before and after. `in` is the total across all chunks.
- **saved** — the compression ratio. 85% means the summary is 15% the size of the input.
- **took** — wall-clock milliseconds for the whole pass.

## The guardrail strip

Three states:

- **clear** — nothing found, nothing changed.
- **sanitised** — personal data was removed before processing. The original never left
your browser's request.
- **blocked** — the request was refused and nothing was stored.

## Worked example

Upload a PDF of a 60-page procurement policy and ask:

> What are the approval thresholds, and who signs off above them?

You get back a short summary naming the thresholds, plus a trace showing the document was
split into ~40 chunks, each summarised separately, then merged. The `saved` figure is
typically 90%+ on a document that long.

## Tips that actually matter

**Ask one question at a time.** The engine scores sentences against your question's terms.
Two unrelated questions in one prompt split the relevance signal and both answers get weaker.

**Select only the documents you need.** Every selected document contributes chunks, and
chunks compete for the same summary slots. Adding an irrelevant file dilutes the result.

**Use exact identifiers when you have them.** The scoring is lexical, so a part number, a
CNIC, or a contract clause reference will match precisely. Paraphrases may not — that is
the known limitation, and it is why the trace is visible.

**Long documents are fine.** That is the whole point. A 200,000-character document becomes
~70 chunks and the map phase handles them one at a time.

## What it will not do

- It will not invent an answer. If nothing matches, the summary is empty and the status is
  `empty` rather than a confident guess.
- It will not paraphrase. The summary is composed of sentences from your own documents.
- It will not process a scanned PDF. There is no OCR — you get a clear 422 explaining that.
- It will not store PII. Redaction happens before the database write.

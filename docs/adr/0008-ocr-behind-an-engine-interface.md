# ADR-0008 — OCR behind an engine interface, with Tesseract as the first implementation

Status:
Accepted

Date:
2026-08-25

Relates to:
ADR-0001 (package boundaries), ADR-0003 (work the API does not do itself).
Implemented by [Phase 14](../development/tasks/phase-14-scanned-document-ingestion.md).

## Context

`infrastructure/extraction/text.py` has always named this gap in its own opening
paragraph:

> A document with no text layer — a scan, a photo of a printout — is a real and
> common case. It is reported as `CONTENT_UNAVAILABLE` and never retried: the
> bytes will not grow words on a second attempt.

And the message the user receives asks them to go and solve it:

```text
No readable text was found in this document.
If it is a scan or a photo, upload a text-based PDF or a DOCX instead.
```

A PDF is a drawing format, not a text format. A PDF produced by a word processor
carries a text layer — the glyphs plus their Unicode code points — and `pypdf`
reads it directly. A PDF produced by a scanner or a phone carries one image per
page and no code points at all. The two are the same file extension and look
identical on screen, which is why the failure surprises people.

Recovering text from the second kind is optical character recognition, and it is
a genuinely different pipeline: render the page to a bitmap, find the text on it,
and recognise the characters. That is a third-party concern with several viable
implementations and real trade-offs between them, so the choice belongs in an
ADR rather than in a function.

## Decision

**An `OcrEngine` protocol in `infrastructure/extraction/`, with `TesseractEngine`
as the first implementation.**

The protocol takes page bitmaps and returns recognised text with a confidence
figure. It does not know about documents, resumes, or the pipeline; the pipeline
does not know which engine it has.

This follows the shape the codebase already uses for every third-party concern:
`ObjectStorage` is an interface with a local and an S3 implementation,
`LLMProvider` is an interface, and `packages/job-sources/base.py` is a protocol
with Greenhouse, Ashby and Lever behind it. Nothing here is a new pattern.

**Rasterisation with `pypdfium2`.** PDFium is Chrome's PDF engine; the binding
ships wheels, so it needs no system package. The common alternative,
`pdf2image`, shells out to poppler, which would be a second system dependency
on top of Tesseract's.

## Why Tesseract first

Three candidates were considered seriously.

**Tesseract** is the field's baseline — OCR papers are written as "we beat
Tesseract by *x*". Since version 4 its recogniser is an LSTM over text lines
rather than the per-character classifier it used before. It emits per-word
confidence, which is what lets a caller distinguish "read this cleanly" from
"guessed". It needs the `tesseract-ocr` system binary, which is a Dockerfile
change, and it has an official Hebrew language pack.

**RapidOCR / PaddleOCR** is the cleaner install — pip only, ONNX runtime, small
models, no system binary — and generally better on photographs and skewed input,
because detection is a segmentation network rather than classical layout
analysis. Its shipped models cover Chinese and English. Hebrew is not among
them.

**Azure Document Intelligence** is what this class of product usually runs on in
production, and it does far more than OCR: key-value extraction, tables, reading
order. It also costs money per page, and extraction currently sits *before* the
point in `run_import` where the pipeline is allowed to spend anything — DEV-020
marks that line deliberately. Turning every upload into a billable call is a
product decision, not an implementation detail.

Tesseract wins on two grounds that outrank the install cost. It has a Hebrew
language pack and the alternative does not, in a product whose users are largely
Israeli. And its weaknesses are the ones the industry has written down, so
"improve the accuracy of this pipeline" is a tractable task against it rather
than a guess.

The Dockerfile risk is real — a Dockerfile change already reached a person
rather than a red check once, and CI cannot build images at all while the
billing outage lasts. It is bounded: `docker compose build api` is one command,
run by hand before merge.

## Consequences

**A second engine becomes cheap, and that is the point.** Behind the protocol,
adding RapidOCR is a small class and a config value, and then two engines can be
measured against the same fixtures. Comparing them is the work; importing one of
them is not.

**Azure stays available as a later choice rather than a rewrite.** If per-page
cost is ever accepted, it is a third implementation.

**The image is larger.** `tesseract-ocr` plus `eng` and `heb` traineddata is
roughly 50–80 MB depending on which `tessdata` variant is installed. The
`tessdata_fast` variant is the default choice; `tessdata_best` is slower and more
accurate and is a tuning decision to make against measurements, not in advance.

**OCR output must be marked as OCR output.** The platform's central rule is that
derived text never becomes career data without review. Text recovered from a
scan is less reliable than a text layer, and the screen where a person confirms
it has to say where it came from. This is a schema change, not only a label.

**`looks_like_a_resume.check()` becomes the risk.** It runs on the extracted text
*before* the model sees it, and OCR text is noisier than a text layer. If its
signal thresholds were tuned against clean text, it may begin refusing valid
scans — a refusal that would read to the user as "we do not think this is a
resume" when the truth is "we read it badly". That is measured in Phase 14, not
assumed.

## Alternatives rejected

**OCR in the API request, synchronously.** Recognition is CPU-heavy and takes
seconds per page. It belongs where the rest of the import already runs, which is
the worker (ADR-0003).

**Calling the LLM with the page image instead.** Modern vision models read
scanned documents well, and this would need no new dependency. It is rejected for
the same reason as Azure — it moves a free step onto the paid path — and for a
sharper one: `_ensure_text` runs *before* `looks_like_a_resume`, which exists so
that a document that is not a resume is refused without paying for a model call.
Making extraction itself a model call removes the gate that protects the gate.

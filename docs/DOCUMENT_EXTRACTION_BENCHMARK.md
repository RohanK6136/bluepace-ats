# BluePace Document Extraction Benchmark

## Purpose

Compare Docling with the legacy pypdf/python-docx path on the document shapes most relevant to the ATS.

## Test matrix

| Fixture | Expected focus |
|---|---|
| Normal text PDF | baseline text fidelity and latency |
| Normal DOCX | paragraph/heading extraction |
| Multi-column PDF | reading order |
| Table-heavy JD | table structure and text preservation |
| Scanned PDF | OCR coverage |
| 5 MB boundary PDF/DOCX | upload-limit enforcement |
| >5 MB PDF/DOCX | authoritative rejection |

## Run

```bash
python backend/scripts/benchmark_document_extraction.py \
  fixtures/normal_resume.pdf \
  fixtures/normal_resume.docx \
  fixtures/multi_column_resume.pdf \
  fixtures/table_heavy_jd.pdf \
  fixtures/scanned_resume.pdf
```

The script reports engine, latency, extracted characters and rough field coverage. It does not upload or persist documents.

## Acceptance criteria

- Files at or below 5 MiB are accepted by the application layer.
- Files above 5 MiB are rejected before document processing.
- Docling is the first extraction attempt.
- pypdf/python-docx remain available as fallback.
- Multi-column reading order should be coherent enough for BluePace section parsing.
- Table text must remain discoverable for JD/resume normalization.
- Scanned PDFs should either extract through OCR or fail with an explicit extraction warning rather than silently producing an empty profile.

## Interpretation

Treat extraction latency and field coverage separately. A slower engine is acceptable when it materially improves structure, reading order or OCR coverage. Matching and hiring decisions must not depend on a single extraction engine without review.

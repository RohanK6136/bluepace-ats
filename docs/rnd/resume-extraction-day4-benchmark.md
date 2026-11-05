# BluePace ATS — Resume Extraction Benchmark (Day 4)

**Scope:** Repeatable, provider-free evaluation of the deterministic pypdf/python-docx extraction path  
**Base:** \`feature/resume-extraction-date-intelligence\`  
**Branch:** \`feature/resume-extraction-benchmark\`  
**Status:** Implemented; CI verification pending

## 1. Purpose

Add a repeatable evaluation harness before further changing the resume parser. The harness generates synthetic resume documents in memory, sends their bytes through the existing extractor, and compares returned fields with known expected values.

It does not use real candidate CVs, write candidate records, save uploaded documents, or call a hosted AI provider.

## 2. Synthetic corpus

The first corpus contains three cases:

1. Text-based single-column PDF generated with ReportLab.
2. DOCX containing experience and education tables generated with python-docx.
3. Text-based two-column PDF generated with ReportLab.

Each document uses synthetic identity/contact values and known skills, experience and education values. The harness evaluates name, email, phone, skills, experience and education.

## 3. Metrics

For each field and document, the harness reports:

- True positives, false positives and false negatives.
- Precision, recall and F1.
- Expected and actual item counts.
- Per-document extraction engine and elapsed milliseconds.

Aggregate scores are micro-aggregated from field-level item counts. This avoids averaging document scores with different numbers of expected values.

## 4. Running the benchmark

From the repository's backend directory:

\`\`\`powershell
$env:APP_ENV = "test"
python scripts/resume_extraction_benchmark.py
\`\`\`

The command prints a JSON report. It forces the deterministic pypdf/python-docx path, disables Docling fallback and LLM enrichment for the benchmark process, and restores the caller's environment afterward.

The report deliberately identifies its corpus as synthetic and its provider call count as zero.

## 5. Limitations

- The corpus is small and synthetic; the scores are regression indicators, not production accuracy claims.
- It does not evaluate OCR or scanned/image-only PDFs.
- It does not measure Docling conversion quality or model latency.
- Local timing is not representative of hosted production latency.
- The gold values are exact synthetic strings; real-world aliases, abbreviations, typography and date ambiguity need a consented/de-identified gold corpus.

A second benchmark stage should add an approved real-world, de-identified corpus and a separate Docling/OCR evaluation path. Accuracy targets should be set only after that baseline exists.

## 6. Acceptance status

- [x] Generate text PDF, DOCX-table and two-column PDF fixtures in memory.
- [x] Exercise the existing extractor instead of bypassing document parsing.
- [x] Score scalar and list/entity fields using precision, recall and F1.
- [x] Report per-document and aggregate timings.
- [x] Force zero hosted provider calls and restore environment variables.
- [x] Add regression tests for benchmark coverage and known single-column/DOCX fields.
- [ ] Complete GitHub backend and frontend CI.
- [ ] Run locally and review per-case multi-column results.
- [ ] Add a separately governed Docling/OCR corpus and evaluation.

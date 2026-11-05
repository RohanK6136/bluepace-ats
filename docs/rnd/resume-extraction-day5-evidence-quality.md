# BluePace ATS — Resume Evidence Quality (Day 5)

**Scope:** Improve source-line matching and evidence coverage in deterministic resume extraction  
**Base:** `feature/resume-extraction-benchmark`  
**Branch:** `feature/resume-extraction-evidence-quality`  
**Status:** Implemented; CI verification pending

## 1. Problem

The previous evidence matcher used substring checks. That could treat a short value such as `Go` as supported by `Google`, or `SQL` as supported by `NoSQL`. For structured experience and education records, a single matching component could also make the full record appear supported.

## 2. Changes

- Match complete values with word boundaries rather than arbitrary substrings.
- Normalize whitespace for matching and support profile URLs with or without an HTTP(S) scheme.
- For structured records, calculate coverage from concise components such as title, company, date range, degree, institution and graduation year. Long free-text descriptions are excluded from the coverage denominator.
- Add `evidence_coverage`, `matched_value_count` and `total_value_count` to each field evidence entry.
- Derive the existing confidence value from coverage bands. Values remain extraction heuristics only; they are not probabilities, candidate-quality scores or job-fit scores.
- Preserve the existing source-line and confidence fields, and keep years-of-experience derivation separate.

## 3. Regression coverage

Tests cover:
- Preventing false matches for `Go` in `Google` and `SQL` in `NoSQL` / `PostgreSQL`.
- Matching complete skill tokens.
- Reducing evidence coverage when only one component of an experience record is found.
- Collecting evidence when experience components appear on separate source lines.
- Matching LinkedIn URLs with or without a scheme.

Run from the backend directory:

```powershell
$env:APP_ENV = "test"
python -m pytest tests/test_resume_extraction_intelligence.py -q
```

## 4. Limitations

- Evidence matching is text-based and deterministic; it does not prove that extracted information is true.
- It does not yet preserve source page/paragraph coordinates or visual bounding boxes.
- Confidence bands are heuristic and are not calibrated against a real-world, consented/de-identified CV corpus.
- OCR and Docling evidence alignment remain out of scope.

## 5. Acceptance status

- [x] Prevent substring-based evidence matches.
- [x] Measure evidence coverage for scalar and structured fields.
- [x] Add regression tests for false positives and split-line evidence.
- [x] Document semantics and limitations.
- [ ] Complete GitHub backend and frontend CI.

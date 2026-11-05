# BluePace ATS — Native Docling Source Provenance (Day 7)

**Scope:** Preserve Docling item/page provenance alongside existing resume extraction evidence.  
**Branch:** `feature/resume-extraction-docling-provenance`  
**Base:** `feature/resume-extraction-source-traceability`

## What changed

The document-intelligence adapter continues to use Docling's existing plain-text and Markdown exports. It additionally walks Docling document items and reads their native provenance when available.

Each matched evidence location can include:
- `source_type: docling_item`
- 1-based `page_number` from Docling's `page_no`
- the Docling item label (for example, title or paragraph)
- the item's bounding box coordinates and coordinate origin, when present

The source-line map follows non-empty lines in the existing plain-text export. Matching is exact after whitespace normalization and case folding. It does not fuzzy-match, infer pages, or assign a neighbouring block's location. If an exported line cannot be mapped exactly, its location remains empty. Repeated identical lines are mapped only when the exported occurrences and Docling item occurrences are unambiguous.

The candidate profile displays Docling page/item locators and offers the existing authenticated PDF page-open action when the current CV is a PDF. The bounding box is retained as evidence metadata; this change does not yet draw an on-page highlight.

## Compatibility and safety

- The exported text, Markdown, parsing logic, and extraction engine choice are unchanged.
- No new package or database migration is introduced.
- Existing pypdf page locators and python-docx paragraph/table locators remain unchanged.
- Older Docling test doubles that provide only text/Markdown default to no source locations.
- A missing or unsupported Docling item API does not fail document conversion; provenance is reported unavailable.
- Existing 5 MB upload validation remains in force.
- This is recruiter-facing evidence navigation, not an automated candidate decision.

## Tests

Synthetic unit tests cover:
- page and bounding-box extraction from Docling-like item provenance;
- ambiguous duplicate lines remaining unlocated;
- source locations reaching email and skills extraction evidence.

The real Docling model/conversion pipeline is not invoked by these unit tests, avoiding downloads and hosted inference.

## Remaining work

- Render bounding-box highlights in the PDF viewer.
- Add a visual DOCX navigation strategy; DOCX does not have stable page layout in the current python-docx extraction path.
- Validate provenance against an opt-in, locally available set of synthetic PDF/DOCX documents after the pinned Docling runtime is installed.


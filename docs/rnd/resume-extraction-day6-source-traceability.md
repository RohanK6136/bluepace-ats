# BluePace ATS — Resume Source Traceability (Day 6)

**Scope:** Preserve source-document locations for deterministic resume extraction evidence  
**Base:** `feature/resume-extraction-evidence-quality`  
**Branch:** `feature/resume-extraction-source-traceability`  
**Status:** Implemented; CI verification pending

## 1. Purpose

Resume extraction already returns evidence snippets. This increment attaches the source location that produced each evidence snippet so a recruiter or a later profile-review UI can navigate back to the original document.

The change keeps the existing `source_lines`, field values and confidence fields. It adds `source_locations` to each extraction-evidence item and document-level location availability metadata.

## 2. Location formats

### PDF via pypdf

Each non-empty extracted page contributes a page locator:

```json
{
  "source_type": "pdf_page",
  "page_number": 2
}
```

Page numbers are 1-based.

### DOCX via python-docx

Paragraph evidence includes the document part and 1-based paragraph position:

```json
{
  "source_type": "docx_paragraph",
  "part": "body",
  "paragraph_index": 4,
  "section": "Experience"
}
```

Table evidence points to the table row and the non-empty cell positions:

```json
{
  "source_type": "docx_table_row",
  "part": "body",
  "table_index": 1,
  "row_index": 2,
  "cell_indices": [1, 2, 3],
  "section": "Experience"
}
```

The `part` is `body`, `header`, or `footer`. Header and footer locators also carry the 1-based `section_index`. Paragraph and table indexes are local to their DOCX part/container. A section label is attached when a preceding paragraph uses a Heading or Title style.

### Docling

The current Docling adapter exports flattened text and does not return page/paragraph layout data. Such results are marked with `document_source_location_status = "unavailable"`, and evidence `source_locations` remain empty. The system does not invent a page or section.

## 3. Evidence payload

Each evidence item retains the existing `field`, `value`, `source_lines` and `confidence` fields, and adds `source_locations`. The top-level resume payload includes:

- `document_source_location_status`: `available` or `unavailable`.
- `document_source_line_count`: number of non-empty extracted lines that have aligned source locators.
- `resume_intelligence_version`: incremented to 6.

For date-derived `years_of_experience`, the evidence locations point to the employment-duration lines rather than implying the total was directly stated.

## 4. Regression coverage

The tests generate synthetic documents in memory and exercise the real extraction path:
- A two-page PDF verifies that email evidence maps to page 1 and skills to page 2.
- A DOCX verifies paragraph position and table-row/heading metadata.
- A derived experience total verifies that its source maps to the employment row.
- Flattened Docling text verifies that unavailable coordinates are reported honestly.
- A line-map unit test verifies alignment when segments contain blank lines.

Run from the backend directory:

```powershell
$env:APP_ENV = "test"
python -m pytest tests/test_resume_source_traceability.py -q
```

## 5. Limitations

- This stores page/paragraph/table locators, not PDF bounding boxes, rendered highlights or DOCX character offsets.
- DOCX section labels depend on semantic Heading/Title paragraph styles. Documents that use visual formatting without heading styles may have no section label; paragraph/table positions remain available.
- A repeated identical line may resolve to the first matching occurrence because evidence matching currently resolves one source line per extracted component.
- OCR/Docling source locations remain unavailable until the document-intelligence adapter exposes structured page/layout metadata.
- The candidate profile displays source locators beside extracted evidence. For the current PDF version, recruiters can open the original file directly at the referenced page. DOCX paragraph/table positions are displayed; recruiters can use CV history to download that source. Text-level highlights and PDF bounding boxes are not implemented.

## 6. Acceptance status

- [x] Preserve PDF page numbers.
- [x] Preserve DOCX paragraph and table-row positions.
- [x] Attach nearest semantic heading where available.
- [x] Trace date-derived experience totals to employment-duration evidence.
- [x] Mark flattened Docling text as location-unavailable.
- [x] Add real-byte PDF and DOCX regression fixtures.
- [x] Display source locators beside recruiter-facing extraction evidence.
- [x] Identify the current CV version without exposing private storage keys.
- [x] Open the current PDF at its referenced page.
- [ ] Add rendered DOCX navigation and text-level highlighting.
- [ ] Complete GitHub backend and frontend CI.

# BluePace ATS — Recruiter PDF Evidence Highlights (Day 8)

**Scope:** Open an authenticated, highlighted copy of a candidate's current PDF resume from Docling extraction evidence.  
**Branch:** `feature/resume-extraction-pdf-evidence-highlights`  
**Base:** `feature/resume-extraction-docling-provenance-clean`

## What changed

The existing Docling evidence locator now includes the source page dimensions along with the page number, item label, and bounding box. A new backend helper turns supported source rectangles into PDF highlight annotations in a new in-memory PDF copy.

The candidate profile adds a **Highlight** action beside Docling evidence items that have both a bounding box and a page size. The action requests an authenticated preview from the ATS and opens it at the corresponding page. The original stored CV object is never modified.

## Security and validation

- The preview route requires the normal authenticated recruiter/read role.
- Candidate and document lookup are scoped to the current organisation.
- Only the current CV version can be highlighted; older CV history returns HTTP 409.
- The requested locators must exactly match source locations already stored in the candidate's current extraction evidence. Client-supplied arbitrary rectangles are rejected.
- Only PDF documents are accepted. The 5 MB maximum is checked against both the document record and the bytes read from private storage.
- Preview responses use `private, no-store`, `nosniff`, an inline PDF filename based only on the candidate ID, and no storage key.
- Annotation happens in memory and does not update the original source file, candidate profile, or database.

## Coordinate behavior

Docling bounding boxes are scaled from the recorded page size to the PDF MediaBox. Both `TOPLEFT` and `BOTTOMLEFT` origins are handled. Invalid, non-finite, out-of-page, duplicate, and unsupported coordinates are skipped. Rotated pages are currently skipped rather than risking a misplaced highlight.

The highlight covers a Docling text/layout item, not an individual word or character. A PDF viewer may render annotation appearance differently, but the source PDF contains standard highlight annotations.

## Tests

Synthetic PDFs cover:
- top-left and bottom-left coordinate conversion;
- annotation subtype, content, rectangle, and quadrilateral coordinates;
- duplicate suppression;
- invalid, out-of-page, and unsupported locations;
- authenticated endpoint response and exact stored-evidence allowlisting;
- rejection of client-forged locations and previous CV versions.

No hosted AI inference or additional frontend package is required. The implementation uses the existing pypdf dependency.

## Known limitations

- Only Docling locations with bounding boxes and page dimensions can be highlighted.
- Text-level highlighting is not available when source location metadata is absent or ambiguous.
- Rotated PDFs and word-level character-range highlights are not supported yet.
- This feature does not apply to DOCX documents; their paragraph/table locators remain visible in the recruiter profile.

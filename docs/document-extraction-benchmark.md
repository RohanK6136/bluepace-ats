# Document extraction benchmark

Use this benchmark after changing the document layer. Keep a representative fixture set locally or in a non-sensitive test bucket; do not commit real candidate resumes.

Suggested cases:

| Case | What to verify |
| --- | --- |
| Normal PDF | Title, sections, skills, reading order |
| Normal DOCX | Paragraphs, headings, lists |
| Multi-column PDF | Left-to-right/top-to-bottom reading order |
| Table-heavy JD | Table rows/cells remain understandable and in order |
| Scanned PDF | OCR recovers readable text |
| 5 MB boundary | A document at or below 5 MiB is accepted |
| 5 MB overflow | A document over 5 MiB is rejected before extraction |

Run:

```bash
python backend/scripts/benchmark_document_extraction.py samples/*.pdf samples/*.docx
```

For CI or downstream analysis:

```bash
python backend/scripts/benchmark_document_extraction.py --json samples/*.pdf samples/*.docx
```

The benchmark compares the preferred Docling path with the legacy pypdf/python-docx path. The benchmark is evidence gathering, not an automatic quality gate: review extracted structure for the multi-column, table, and OCR cases.

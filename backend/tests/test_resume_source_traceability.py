from io import BytesIO

from docx import Document
from reportlab.pdfgen import canvas

from app.services.extractor import DocumentExtractor


def _pdf_with_two_pages():
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)

    first_page = pdf.beginText(50, 780)
    first_page.textLine("Aarav Mehta")
    first_page.textLine("aarav.mehta@example.test")
    first_page.textLine("415-555-0132")
    pdf.drawText(first_page)
    pdf.showPage()

    second_page = pdf.beginText(50, 780)
    second_page.textLine("Skills")
    second_page.textLine("Python, FastAPI")
    pdf.drawText(second_page)
    pdf.save()

    return buffer.getvalue()


def _docx_with_heading_and_table():
    document = Document()
    document.add_paragraph("Aarav Mehta")
    document.add_paragraph("aarav.mehta@example.test")
    document.add_heading("Experience", level=1)

    table = document.add_table(rows=1, cols=3)
    table.cell(0, 0).text = "Software Engineer"
    table.cell(0, 1).text = "Acme Labs"
    table.cell(0, 2).text = "Jan 2020 - Dec 2022"

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_pdf_extraction_records_page_location_for_each_evidence_field(monkeypatch):
    monkeypatch.setenv("DOCUMENT_EXTRACTION_ENGINE", "legacy")
    monkeypatch.setenv("DOCUMENT_EXTRACTION_FALLBACK_ENGINE", "disabled")
    monkeypatch.setenv("ENABLE_LLM_RESUME_ENRICHMENT", "false")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    result = DocumentExtractor().extract_to_json(_pdf_with_two_pages(), "resume.pdf")
    evidence = {item["field"]: item for item in result["extraction_evidence"]}

    assert result["document_source_location_status"] == "available"
    assert result["document_source_line_count"] > 0
    assert evidence["email"]["source_locations"] == [
        {"source_type": "pdf_page", "page_number": 1}
    ]
    assert evidence["skills"]["source_locations"] == [
        {"source_type": "pdf_page", "page_number": 2}
    ]


def test_docx_extraction_records_paragraph_and_table_section_locations(monkeypatch):
    monkeypatch.setenv("DOCUMENT_EXTRACTION_ENGINE", "legacy")
    monkeypatch.setenv("DOCUMENT_EXTRACTION_FALLBACK_ENGINE", "disabled")
    monkeypatch.setenv("ENABLE_LLM_RESUME_ENRICHMENT", "false")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    result = DocumentExtractor().extract_to_json(
        _docx_with_heading_and_table(), "resume.docx"
    )
    evidence = {item["field"]: item for item in result["extraction_evidence"]}

    assert result["document_source_location_status"] == "available"
    assert evidence["email"]["source_locations"] == [
        {
            "source_type": "docx_paragraph",
            "part": "body",
            "paragraph_index": 2,
        }
    ]
    assert evidence["experience"]["source_locations"] == [
        {
            "source_type": "docx_table_row",
            "part": "body",
            "table_index": 1,
            "row_index": 1,
            "cell_indices": [1, 2, 3],
            "section": "Experience",
        }
    ]


def test_source_line_locations_follow_nonempty_segment_line_order():
    segments = [
        {
            "text": "First line\n\nSecond line",
            "location": {"source_type": "pdf_page", "page_number": 1},
        },
        {
            "text": "Third line",
            "location": {
                "source_type": "docx_paragraph",
                "part": "body",
                "paragraph_index": 3,
            },
        },
    ]

    assert DocumentExtractor._source_line_locations(segments) == [
        {"source_type": "pdf_page", "page_number": 1},
        {"source_type": "pdf_page", "page_number": 1},
        {
            "source_type": "docx_paragraph",
            "part": "body",
            "paragraph_index": 3,
        },
    ]

from io import BytesIO
from types import SimpleNamespace

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

def test_docx_date_derived_experience_total_points_to_employment_row():
    raw_text = "Software Engineer | Acme Labs | Jan 2020 - Dec 2022"
    location = {
        "source_type": "docx_table_row",
        "part": "body",
        "table_index": 1,
        "row_index": 1,
    }

    evidence, confidence = DocumentExtractor._evidence_and_confidence(
        raw_text,
        {
            "years_of_experience": 3.0,
            "experience": [{"duration": "Jan 2020 - Dec 2022"}],
        },
        [location],
    )

    years_evidence = next(
        item for item in evidence if item["field"] == "years_of_experience"
    )
    assert years_evidence["derivation"] == "employment_dates"
    assert years_evidence["source_lines"] == [raw_text]
    assert years_evidence["source_locations"] == [location]
    assert confidence["years_of_experience"] == 0.84


def test_docling_flat_text_is_explicitly_marked_location_unavailable(monkeypatch):
    from app.services.document_intelligence import (
        DocumentIntelligenceResult,
        document_intelligence_service,
    )

    monkeypatch.setenv("DOCUMENT_EXTRACTION_ENGINE", "docling")
    monkeypatch.setenv("ENABLE_LLM_RESUME_ENRICHMENT", "false")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        document_intelligence_service,
        "extract",
        lambda _content, _filename: DocumentIntelligenceResult(
            text="Aarav Mehta\naarav.mehta@example.test\nPython FastAPI",
            markdown="Aarav Mehta",
            engine="docling",
        ),
    )

    result = DocumentExtractor().extract_to_json(b"synthetic bytes", "resume.pdf")
    evidence = {item["field"]: item for item in result["extraction_evidence"]}

    assert result["document_extraction_engine"] == "docling"
    assert result["document_source_location_status"] == "unavailable"
    assert result["document_source_line_count"] == 0
    assert evidence["email"]["source_locations"] == []



def test_docling_native_page_and_bounding_box_provenance_maps_exact_lines():
    from app.services.document_intelligence import DocumentIntelligenceService

    def provenance(page_number, left, top, right, bottom):
        return SimpleNamespace(
            page_no=page_number,
            bbox=SimpleNamespace(
                l=left,
                t=top,
                r=right,
                b=bottom,
                coord_origin=SimpleNamespace(value="TOPLEFT"),
            ),
        )

    items = [
        (
            SimpleNamespace(
                text="Aarav Mehta",
                label=SimpleNamespace(value="title"),
                prov=[provenance(1, 10, 20, 100, 40)],
            ),
            0,
        ),
        (
            SimpleNamespace(
                text="aarav.mehta@example.test",
                label=SimpleNamespace(value="paragraph"),
                prov=[provenance(1, 10, 50, 180, 65)],
            ),
            0,
        ),
        (
            SimpleNamespace(
                text="Python FastAPI",
                label=SimpleNamespace(value="paragraph"),
                prov=[provenance(2, 12, 70, 150, 85)],
            ),
            0,
        ),
    ]
    document = SimpleNamespace(iterate_items=lambda: iter(items))

    locations = DocumentIntelligenceService._docling_source_line_locations(
        document,
        "Aarav Mehta\naarav.mehta@example.test\nPython FastAPI",
    )

    assert locations == [
        {
            "source_type": "docling_item",
            "page_number": 1,
            "item_label": "title",
            "bbox": {
                "l": 10.0,
                "t": 20.0,
                "r": 100.0,
                "b": 40.0,
                "coord_origin": "TOPLEFT",
            },
        },
        {
            "source_type": "docling_item",
            "page_number": 1,
            "item_label": "paragraph",
            "bbox": {
                "l": 10.0,
                "t": 50.0,
                "r": 180.0,
                "b": 65.0,
                "coord_origin": "TOPLEFT",
            },
        },
        {
            "source_type": "docling_item",
            "page_number": 2,
            "item_label": "paragraph",
            "bbox": {
                "l": 12.0,
                "t": 70.0,
                "r": 150.0,
                "b": 85.0,
                "coord_origin": "TOPLEFT",
            },
        },
    ]


def test_docling_provenance_leaves_ambiguous_repeated_lines_unlocated():
    from app.services.document_intelligence import DocumentIntelligenceService

    items = [
        (
            SimpleNamespace(
                text="Same line",
                label="paragraph",
                prov=[SimpleNamespace(page_no=1, bbox=None)],
            ),
            0,
        ),
        (
            SimpleNamespace(
                text="Another line",
                label="paragraph",
                prov=[SimpleNamespace(page_no=2, bbox=None)],
            ),
            0,
        ),
    ]
    document = SimpleNamespace(iterate_items=lambda: iter(items))

    locations = DocumentIntelligenceService._docling_source_line_locations(
        document, "Same line\nSame line\nAnother line"
    )

    assert locations[0] is None
    assert locations[1] is None
    assert locations[2] == {
        "source_type": "docling_item",
        "page_number": 2,
        "item_label": "paragraph",
    }


def test_docling_native_provenance_flows_into_resume_extraction_evidence(monkeypatch):
    from app.services.document_intelligence import (
        DocumentIntelligenceResult,
        document_intelligence_service,
    )

    monkeypatch.setenv("DOCUMENT_EXTRACTION_ENGINE", "docling")
    monkeypatch.setenv("ENABLE_LLM_RESUME_ENRICHMENT", "false")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    locations = [
        {"source_type": "docling_item", "page_number": 1, "item_label": "title"},
        {"source_type": "docling_item", "page_number": 1, "item_label": "paragraph"},
        {"source_type": "docling_item", "page_number": 2, "item_label": "paragraph"},
    ]
    monkeypatch.setattr(
        document_intelligence_service,
        "extract",
        lambda _content, _filename: DocumentIntelligenceResult(
            text="Aarav Mehta\\naarav.mehta@example.test\\nPython FastAPI",
            markdown="Aarav Mehta",
            engine="docling",
            source_line_locations=locations,
        ),
    )

    result = DocumentExtractor().extract_to_json(b"synthetic bytes", "resume.pdf")
    evidence = {item["field"]: item for item in result["extraction_evidence"]}

    assert result["document_extraction_engine"] == "docling"
    assert result["document_source_location_status"] == "available"
    assert result["document_source_line_count"] == 3
    assert evidence["email"]["source_locations"] == [locations[1]]
    assert evidence["skills"]["source_locations"] == [locations[2]]

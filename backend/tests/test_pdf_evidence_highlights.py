from io import BytesIO

import pytest
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from app.services.pdf_evidence_highlights import (
    PdfEvidenceHighlightError,
    annotate_pdf_with_evidence,
)


def _pdf_page(width=600, height=800):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    pdf.drawString(40, height - 50, "Synthetic candidate resume")
    pdf.save()
    return buffer.getvalue()


def _location(bbox, *, page=1, width=600, height=800):
    return {
        "source_type": "docling_item",
        "page_number": page,
        "item_label": "paragraph",
        "bbox": bbox,
        "page_size": {"width": width, "height": height},
    }


def _annotations(pdf_bytes):
    reader = PdfReader(BytesIO(pdf_bytes))
    annotations = reader.pages[0].get("/Annots") or []
    return [annotation.get_object() for annotation in annotations]


def test_docling_top_left_bbox_creates_pdf_highlight_annotation():
    source = _pdf_page()
    location = _location(
        {"l": 10, "t": 50, "r": 200, "b": 90, "coord_origin": "TOPLEFT"}
    )

    highlighted = annotate_pdf_with_evidence(source, [location])
    annotations = _annotations(highlighted)

    assert len(annotations) == 1
    annotation = annotations[0]
    assert str(annotation["/Subtype"]) == "/Highlight"
    assert str(annotation["/Contents"]) == "BluePace ATS recruiter evidence highlight"
    rect = [float(value) for value in annotation["/Rect"]]
    assert rect == pytest.approx([10, 710, 200, 750])
    quad_points = [float(value) for value in annotation["/QuadPoints"]]
    assert quad_points == pytest.approx([10, 710, 200, 710, 10, 750, 200, 750])


def test_docling_bottom_left_bbox_creates_pdf_highlight_annotation():
    source = _pdf_page()
    location = _location(
        {"l": 10, "t": 90, "r": 200, "b": 50, "coord_origin": "BOTTOMLEFT"}
    )

    highlighted = annotate_pdf_with_evidence(source, [location])
    annotation = _annotations(highlighted)[0]

    assert str(annotation["/Subtype"]) == "/Highlight"
    assert [float(value) for value in annotation["/Rect"]] == pytest.approx(
        [10, 50, 200, 90]
    )


def test_duplicate_source_locations_create_only_one_annotation():
    source = _pdf_page()
    location = _location(
        {"l": 10, "t": 50, "r": 200, "b": 90, "coord_origin": "TOPLEFT"}
    )

    highlighted = annotate_pdf_with_evidence(source, [location, location])

    assert len(_annotations(highlighted)) == 1


@pytest.mark.parametrize(
    "location",
    [
        _location({"l": 10, "t": 50, "r": 200, "b": 90, "coord_origin": "UNKNOWN"}),
        _location({"l": 200, "t": 50, "r": 10, "b": 90, "coord_origin": "TOPLEFT"}),
        _location({"l": 10, "t": 50, "r": 900, "b": 90, "coord_origin": "TOPLEFT"}),
        _location({"l": float("nan"), "t": 50, "r": 200, "b": 90, "coord_origin": "TOPLEFT"}),
        _location({"l": 10, "t": 50, "r": 200, "b": 90, "coord_origin": "TOPLEFT"}, page=3),
    ],
)
def test_invalid_or_out_of_page_source_locations_are_not_highlighted(location):
    with pytest.raises(PdfEvidenceHighlightError):
        annotate_pdf_with_evidence(_pdf_page(), [location])


def test_empty_or_non_docling_locations_do_not_create_annotations():
    with pytest.raises(PdfEvidenceHighlightError):
        annotate_pdf_with_evidence(
            _pdf_page(),
            [{"source_type": "pdf_page", "page_number": 1}],
        )

"""Create recruiter-only PDF previews with Docling evidence rectangles."""

from __future__ import annotations

from io import BytesIO
import math
from typing import Any


class PdfEvidenceHighlightError(ValueError):
    """Raised when source evidence cannot be safely rendered on the PDF."""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    resolved = float(value)
    return resolved if math.isfinite(resolved) else None


def annotate_pdf_with_evidence(
    pdf_bytes: bytes,
    source_locations: list[dict],
) -> bytes:
    """Return an in-memory PDF copy with supported Docling blocks highlighted.

    Docling coordinates are scaled by the stored page size to the PDF MediaBox.
    Pages with a non-zero /Rotate value are deliberately skipped until rotated
    page coordinate mapping has dedicated coverage. No source file is mutated.
    """
    if not pdf_bytes:
        raise PdfEvidenceHighlightError("The source PDF is empty.")

    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.annotations import Highlight
        from pypdf.generic import ArrayObject, FloatObject, NameObject, TextStringObject
    except Exception as error:
        raise PdfEvidenceHighlightError("PDF annotation support is unavailable.") from error

    try:
        reader = PdfReader(BytesIO(pdf_bytes), strict=False)
        if reader.is_encrypted:
            raise PdfEvidenceHighlightError("Encrypted PDFs cannot be highlighted.")

        writer = PdfWriter()
        writer.append(reader)
        seen: set[tuple[int, float, float, float, float]] = set()
        added = 0

        for location in source_locations or []:
            if not isinstance(location, dict) or location.get("source_type") != "docling_item":
                continue

            page_number = location.get("page_number")
            if isinstance(page_number, bool) or not isinstance(page_number, int):
                continue
            if page_number < 1 or page_number > len(reader.pages):
                continue

            bbox = location.get("bbox")
            page_size = location.get("page_size")
            if not isinstance(bbox, dict) or not isinstance(page_size, dict):
                continue

            source_width = _number(page_size.get("width"))
            source_height = _number(page_size.get("height"))
            left = _number(bbox.get("l"))
            top = _number(bbox.get("t"))
            right = _number(bbox.get("r"))
            bottom = _number(bbox.get("b"))
            if (
                source_width is None
                or source_height is None
                or source_width <= 0
                or source_height <= 0
                or None in (left, top, right, bottom)
            ):
                continue

            if not (0 <= left < right <= source_width):
                continue

            origin = str(bbox.get("coord_origin") or "TOPLEFT").upper()
            if origin == "TOPLEFT":
                if not (0 <= top < bottom <= source_height):
                    continue
            elif origin == "BOTTOMLEFT":
                if not (0 <= bottom < top <= source_height):
                    continue
            else:
                continue

            source_page = reader.pages[page_number - 1]
            rotation = int(getattr(source_page, "rotation", 0) or 0) % 360
            if rotation:
                continue

            media_box = source_page.mediabox
            media_left = float(media_box.left)
            media_bottom = float(media_box.bottom)
            media_width = float(media_box.width)
            media_height = float(media_box.height)
            if media_width <= 0 or media_height <= 0:
                continue

            scale_x = media_width / source_width
            scale_y = media_height / source_height
            x0 = media_left + left * scale_x
            x1 = media_left + right * scale_x
            if origin == "TOPLEFT":
                y0 = media_bottom + (source_height - bottom) * scale_y
                y1 = media_bottom + (source_height - top) * scale_y
            else:
                y0 = media_bottom + bottom * scale_y
                y1 = media_bottom + top * scale_y

            if not (x0 < x1 and y0 < y1):
                continue

            key = (
                page_number - 1,
                round(x0, 3),
                round(y0, 3),
                round(x1, 3),
                round(y1, 3),
            )
            if key in seen:
                continue
            seen.add(key)

            rect = (x0, y0, x1, y1)
            quad_points = ArrayObject([
                FloatObject(x0), FloatObject(y0),
                FloatObject(x1), FloatObject(y0),
                FloatObject(x0), FloatObject(y1),
                FloatObject(x1), FloatObject(y1),
            ])
            annotation = Highlight(
                rect=rect,
                quad_points=quad_points,
                highlight_color="fff2a8",
            )
            annotation[NameObject("/Contents")] = TextStringObject(
                "BluePace ATS recruiter evidence highlight"
            )
            writer.add_annotation(page_number=page_number - 1, annotation=annotation)
            added += 1

        if added == 0:
            raise PdfEvidenceHighlightError(
                "No supported source bounding boxes were available for this PDF page."
            )

        output = BytesIO()
        writer.write(output)
        return output.getvalue()
    except PdfEvidenceHighlightError:
        raise
    except Exception as error:
        raise PdfEvidenceHighlightError(
            "The source PDF could not be prepared for evidence highlighting."
        ) from error

"""Step 3 — Segment: classify body lines into blocks, assign sections and groups."""

from __future__ import annotations

from app.config import Settings
from app.features.jd_standardizer.pipeline.models import LIST_SECTIONS, Block, CleanResult, Segmentation
from app.features.jd_standardizer.pipeline.policy import Policy
from app.features.jd_standardizer.pipeline.textutil import (
    has_marker,
    heading_text,
    match_kv,
    match_section_heading,
    word_count,
)

KV_SECTION = {
    "fact_location": "additional_info",
    "info_schedule": "additional_info",
    "info_other": "additional_info",
}
_GROUP_TERMINAL = (".", ":", ";", "!", "?", ",")


def _bullet_like(text: str | None) -> bool:
    if text is None:
        return False
    return has_marker(text) or word_count(text) >= 6 or text.rstrip().endswith(".")


def looks_group_heading(text: str, next_text: str | None) -> bool:
    if has_marker(text):
        return False
    words = text.split()
    if not 1 <= len(words) <= 5 or text.rstrip().endswith(_GROUP_TERMINAL):
        return False
    caps = sum(1 for w in words if w[:1].isupper())
    if not ("&" in text or caps / len(words) >= 0.5):
        return False
    return _bullet_like(next_text)


def segment(cleaned: CleanResult, policy: Policy, settings: Settings) -> Segmentation:
    chrome = set(cleaned.chrome_ids)
    header = set(cleaned.header_ids)
    body = [ln for ln in cleaned.lines if ln.id not in chrome and ln.id not in header]

    company_names = {settings.COMPANY_NAME.casefold(), "blupace"}
    blocks: list[Block] = []
    foreign: list[str] = []
    current: str | None = None
    current_heading: str | None = None
    group: str | None = None

    for i, line in enumerate(body):
        text = line.text
        nxt = body[i + 1].text if i + 1 < len(body) else None
        bid = f"B{len(blocks) + 1:02d}"

        section, company = match_section_heading(text, policy)
        if section:
            current, current_heading, group = section, heading_text(text), None
            if company and company.casefold() not in company_names and company not in foreign:
                foreign.append(company)
            blocks.append(Block(id=bid, kind="section_heading", line_ids=[line.id], text=text, section=section,
                                section_source="alias", source_heading=current_heading))
            continue

        kv = match_kv(text, policy)
        if kv:
            key, value, kind = kv
            kv_section = KV_SECTION.get(kind)
            blocks.append(Block(id=bid, kind="kv", line_ids=[line.id], text=text, key=key, value=value,
                                kv_kind=kind, section=kv_section,
                                section_source="alias" if kv_section else "none"))
            continue

        if current in LIST_SECTIONS and looks_group_heading(text, nxt):
            group = heading_text(text)
            blocks.append(Block(id=bid, kind="group_heading", line_ids=[line.id], text=text, section=current,
                                section_source="inherit", group=group, source_heading=current_heading))
            continue

        blocks.append(Block(
            id=bid,
            kind="bullet" if has_marker(text) else "paragraph",
            line_ids=[line.id],
            text=text,
            section=current,
            section_source="inherit" if current else "none",
            group=group if current in LIST_SECTIONS else None,
            source_heading=current_heading,
        ))

    # Source headings become groups when a list section has ≥ 2 of them.
    headings_per_section: dict[str, list[str]] = {}
    for b in blocks:
        if b.kind == "section_heading" and b.section in LIST_SECTIONS and b.source_heading:
            hs = headings_per_section.setdefault(b.section, [])
            if b.source_heading not in hs:
                hs.append(b.source_heading)
    blocks = [
        b.model_copy(update={"group": b.source_heading})
        if b.kind in ("bullet", "paragraph") and b.group is None and b.section in LIST_SECTIONS
        and len(headings_per_section.get(b.section, [])) >= 2
        else b
        for b in blocks
    ]

    unresolved = [b.id for b in blocks if b.kind in ("bullet", "paragraph") and b.section is None]
    relabel = (
        [b.id for b in blocks if b.kind == "paragraph" and b.section in LIST_SECTIONS
         and word_count(b.text) >= settings.LONG_PARAGRAPH_WORDS]
        if settings.LABEL_LONG_PARAGRAPHS else []
    )
    return Segmentation(blocks=blocks, unresolved_ids=unresolved, relabel_ids=relabel,
                        header_lines=list(cleaned.header_ids), foreign_employer_candidates=foreign)

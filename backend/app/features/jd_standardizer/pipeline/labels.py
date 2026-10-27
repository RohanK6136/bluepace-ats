"""Step 5 — Label unresolved / long-paragraph blocks with the LLM (conditional)."""

from __future__ import annotations

from typing import Any

from app.core.errors import LLMBudgetExceeded, LLMStepFailed
from app.features.jd_standardizer.llm_schemas import labels_schema
from app.features.jd_standardizer.pipeline.llmstep import StepLLM
from app.features.jd_standardizer.pipeline.models import Block, Segmentation, StepTrace
from app.features.jd_standardizer.pipeline.textutil import heading_text


def label_targets(seg: Segmentation) -> list[str]:
    seen: list[str] = []
    for bid in [*seg.unresolved_ids, *seg.relabel_ids]:
        if bid not in seen:
            seen.append(bid)
    return seen


def _payload(seg: Segmentation, ids: list[str], max_chars: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    prev_heading: str | None = None
    wanted = set(ids)
    for b in seg.blocks:
        if b.kind in ("section_heading", "group_heading"):
            prev_heading = heading_text(b.text)
            continue
        if b.id in wanted:
            out.append({"id": b.id, "text": b.text[:max_chars], "current_section": b.section,
                        "previous_heading": prev_heading})
    return out


def apply_labels(seg: Segmentation, labels: dict[str, str], targets: list[str]) -> tuple[Segmentation, bool]:
    """labels: block id → label. Missing ids → keep (had section) else unclassified."""
    target_set = set(targets)
    changed = False
    blocks: list[Block] = []
    for b in seg.blocks:
        if b.id not in target_set:
            blocks.append(b)
            continue
        label = labels.get(b.id) or ("keep" if b.section else "unclassified")
        if label == "keep" and b.section:
            blocks.append(b)
            continue
        if label == "keep":
            label = "unclassified"
        changed = changed or label != b.section
        blocks.append(b.model_copy(update={"section": label, "section_source": "llm",
                                           "group": b.group if label == b.section else None}))
    return seg.model_copy(update={"blocks": blocks, "unresolved_ids": [], "relabel_ids": []}), changed


async def label_blocks(seg: Segmentation, step_llm: StepLLM | None) -> tuple[Segmentation, bool, StepTrace]:
    """step_llm=None → degraded (unresolved → unclassified, relabel → keep)."""
    targets = label_targets(seg)
    trace = StepTrace(name="labels", input_summary={"targets": len(targets)})
    if not targets:
        trace.notes.append("skipped: nothing to label")
        return seg, False, trace
    labels: dict[str, str] = {}
    if step_llm is None:
        trace.notes.append("degraded: no LLM")
    else:
        n0 = len(step_llm.ctx.records)
        s = step_llm.settings
        chunk = s.LABELS_MAX_BLOCKS_PER_CALL
        for i in range(0, len(targets), chunk):
            ids = targets[i:i + chunk]
            payload = _payload(seg, ids, s.LABELS_MAX_BLOCK_CHARS)
            try:
                res = await step_llm.call("labels", "labels", {"blocks": payload}, labels_schema(len(ids)),
                                          24 * len(ids) + 64)
            except (LLMStepFailed, LLMBudgetExceeded) as e:
                trace.notes.append(f"degraded chunk {i // chunk}: {e}")
                continue
            for item in res.parsed.get("labels", []):
                if item["block"] in ids and item["block"] not in labels:
                    labels[item["block"]] = item["section"]
        trace.llm_call_ids = step_llm.call_ids_since(n0)
    new_seg, changed = apply_labels(seg, labels, targets)
    trace.output_summary = {"labels": dict(sorted(labels.items())), "changed": changed}
    return new_seg, changed, trace

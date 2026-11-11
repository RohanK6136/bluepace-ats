"""Publication policy regression tests for source-based JD drafts."""

from app.features.jd_standardizer.pipeline.assemble import (
    compute_status,
    llm_unavailable_warning,
    publish_gate,
)
from app.features.jd_standardizer.pipeline.models import (
    FACT_FIELDS,
    Fact,
    Flag,
    Item,
    SectionResult,
    ShortDescription,
)
from app.features.jd_standardizer.pipeline.policy import load_policy


def _source_complete_draft():
    policy = load_policy()
    fields = {
        name: Fact(value="verified from source", status="verified", source="regex")
        for name in FACT_FIELDS
    }
    sections = [
        SectionResult(
            id="requirements",
            heading="Qualifications",
            status="provided",
            items=[Item(text="Python", origin="source", lines=["L001"])],
        )
    ]
    short = ShortDescription(text="Role summary from the source JD.", origin="template")
    return policy, fields, sections, short


def test_llm_unavailable_is_a_review_warning_not_a_publication_blocker():
    policy, fields, sections, short = _source_complete_draft()
    warning = llm_unavailable_warning("AI provider unavailable; rules-based extraction was used")

    assert warning.code == "llm_unavailable"
    assert warning.severity == "warn"
    assert "review all extracted facts" in warning.message
    assert publish_gate(fields, sections, [warning], short, policy) == []
    # Keep the degraded status for monitoring; only the publication gate changes.
    assert compute_status(llm_unavailable=True, needs_input=[], sections=sections, flags=[warning]) == "llm_unavailable"


def test_llm_warning_does_not_bypass_missing_requirements_or_hard_blockers():
    policy, fields, sections, short = _source_complete_draft()
    warning = llm_unavailable_warning("AI provider unavailable")

    blockers = publish_gate(fields, [], [warning], short, policy)
    assert "requirements: empty" in blockers

    hard_blocker = Flag(code="source_integrity_failure", severity="block", message="Invalid source evidence")
    blockers = publish_gate(fields, sections, [warning, hard_blocker], short, policy)
    assert "flag: source_integrity_failure" in blockers

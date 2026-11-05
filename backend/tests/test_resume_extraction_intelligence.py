from datetime import datetime

import pytest

from app.services.extractor import DocumentExtractor


AS_OF = datetime(2024, 1, 15)


@pytest.mark.parametrize(
    "durations, expected",
    [
        (["Jan 2020 - Dec 2020"], 1.0),
        (["2020 - 2022"], 2.0),
        (["05/2020 - 08/2022"], 2.3),
        (["2020/05 - 2021/04"], 1.0),
        (["May'20 - Jun'22"], 2.2),
        (["January 2020 to March 2022"], 2.2),
        (["2018 - 2020", "2021 - 2023"], 4.0),
        (["Jan 2020 - Dec 2021", "Jan 2021 - Dec 2022"], 3.0),
        (["Jan 2018 - Dec 2018; Jan 2020 - Dec 2020"], 2.0),
        (["Jan 2021 - Present"], 3.0),
    ],
)
def test_experience_years_supports_resume_date_formats_and_deduplicates_overlap(
    durations, expected
):
    experience = [{"duration": duration} for duration in durations]

    assert DocumentExtractor._experience_years_from_entries(
        experience, as_of=AS_OF
    ) == expected


def test_experience_years_caps_future_end_date_at_reference_month():
    experience = [{"duration": "Jan 2023 - Dec 2028"}]

    assert DocumentExtractor._experience_years_from_entries(
        experience, as_of=AS_OF
    ) == 1.0


@pytest.mark.parametrize(
    "duration",
    [
        "",
        "duration not stated",
        "2025 - Present",
        "Dec 2021 - Jan 2020",
        "May 2020",
    ],
)
def test_experience_years_ignores_missing_reversed_or_future_date_ranges(duration):
    experience = [{"duration": duration}]

    assert DocumentExtractor._experience_years_from_entries(
        experience, as_of=AS_OF
    ) is None


def test_experience_years_ignores_non_dictionary_entries():
    assert DocumentExtractor._experience_years_from_entries(
        ["Jan 2020 - Dec 2020", None], as_of=AS_OF
    ) is None

@pytest.mark.parametrize(
    "raw_text, skills",
    [
        ("Google Cloud and NoSQL database experience", ["Go", "SQL"]),
        ("Golang services and SQL queries", ["Go", "SQL"]),
    ],
)
def test_extraction_evidence_does_not_match_skill_substrings(raw_text, skills):
    evidence, confidence = DocumentExtractor._evidence_and_confidence(
        raw_text, {"skills": skills}
    )

    skill_evidence = next(item for item in evidence if item["field"] == "skills")
    assert skill_evidence["source_lines"] == []
    assert skill_evidence["evidence_coverage"] == 0.0
    assert skill_evidence["matched_value_count"] == 0
    assert confidence["skills"] < 0.88


def test_extraction_evidence_matches_complete_skill_tokens():
    evidence, confidence = DocumentExtractor._evidence_and_confidence(
        "Skills: Go, SQL, NoSQL, and Golang",
        {"skills": ["Go", "SQL"]},
    )

    skill_evidence = next(item for item in evidence if item["field"] == "skills")
    assert skill_evidence["source_lines"] == ["Skills: Go, SQL, NoSQL, and Golang"]
    assert skill_evidence["evidence_coverage"] == 1.0
    assert skill_evidence["matched_value_count"] == 2
    assert skill_evidence["total_value_count"] == 2
    assert confidence["skills"] == 0.88


def test_extraction_evidence_requires_all_experience_components_for_full_coverage():
    evidence, confidence = DocumentExtractor._evidence_and_confidence(
        "Senior Engineer",
        {
            "experience": [
                {
                    "title": "Senior Engineer",
                    "company": "Acme Labs",
                    "duration": "Jan 2020 - Dec 2022",
                    "description": "Led a team",
                }
            ]
        },
    )

    experience_evidence = next(item for item in evidence if item["field"] == "experience")
    assert experience_evidence["source_lines"] == ["Senior Engineer"]
    assert experience_evidence["evidence_coverage"] == pytest.approx(1 / 3, abs=0.001)
    assert experience_evidence["matched_value_count"] == 1
    assert experience_evidence["total_value_count"] == 3
    assert confidence["experience"] == 0.68


def test_extraction_evidence_tracks_components_across_multiple_source_lines():
    evidence, confidence = DocumentExtractor._evidence_and_confidence(
        "Role: Senior Engineer\nCompany: Acme Labs\nDates: Jan 2020 - Dec 2022",
        {
            "experience": [
                {
                    "title": "Senior Engineer",
                    "company": "Acme Labs",
                    "duration": "Jan 2020 - Dec 2022",
                }
            ]
        },
    )

    experience_evidence = next(item for item in evidence if item["field"] == "experience")
    assert experience_evidence["source_lines"] == [
        "Role: Senior Engineer",
        "Company: Acme Labs",
        "Dates: Jan 2020 - Dec 2022",
    ]
    assert experience_evidence["evidence_coverage"] == 1.0
    assert confidence["experience"] == 0.88


def test_extraction_evidence_matches_profile_urls_with_or_without_scheme():
    evidence, confidence = DocumentExtractor._evidence_and_confidence(
        "linkedin.com/in/aarav-mehta",
        {"linkedin": "https://www.linkedin.com/in/aarav-mehta"},
    )

    linkedin_evidence = next(item for item in evidence if item["field"] == "linkedin")
    assert linkedin_evidence["source_lines"] == ["linkedin.com/in/aarav-mehta"]
    assert linkedin_evidence["evidence_coverage"] == 1.0
    assert confidence["linkedin"] == 0.99

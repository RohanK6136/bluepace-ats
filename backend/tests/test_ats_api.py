        "Senior Engineer | Acme Labs | Jan 2021 - Present",
        "Education",
        "M.Tech Computer Science | State University | 2020",
        "Certifications: AWS Certified Cloud Practitioner, Google Cloud Digital Leader",
        "Projects",
        "Recruiting Automation Platform",
    ]:
        document.add_paragraph(paragraph)
    content = BytesIO()
    document.save(content)

    parsed = extractor_service.extract_to_json(content.getvalue(), "alex.docx")

    assert parsed["linkedin"] == "https://linkedin.com/in/alex-morgan"
    assert parsed["github"] == "https://github.com/alexmorgan"
    assert parsed["current_location"] == "Hyderabad, India"
    assert parsed["preferred_location"] == "Bengaluru, India"
    assert parsed["notice_period"] == "30 days"
    assert parsed["work_authorization"] == "Authorized to work in India"
    assert parsed["certifications"]
    assert parsed["companies"] == ["Acme Labs"]
    assert parsed["job_titles"] == ["Senior Engineer"]
    assert parsed["resume_intelligence_version"] == 6
    assert "disclaimer" in parsed["resume_quality"]
    assert "linkedin" not in parsed["resume_quality"]["missing_fields"]
    assert "GitHub" not in parsed["resume_quality"]["optional_missing_fields"]


def test_jd_parser_extracts_preferred_skill_before_sentence_punctuation():
    from app.services.matching import CandidateMatcher

    matcher = CandidateMatcher()
    analysis = matcher.parse_job_description(
        "Python Engineer",
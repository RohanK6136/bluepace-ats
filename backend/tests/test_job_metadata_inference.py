import app.main as api


def test_employment_type_is_normalized_from_job_board_values():
    assert api._normalize_employment_type("FULL_TIME") == "Full-time"
    assert api._normalize_employment_type("PART_TIME") == "Part-time"
    assert api._normalize_employment_type("CONTRACTOR") == "Contract"
    assert api._normalize_employment_type("INTERN") == "Internship"


def test_employment_type_is_inferred_only_when_explicit_in_description():
    assert api._infer_employment_type("This is a 12-month fixed-term role.") == "Contract"
    assert api._infer_employment_type("Join our summer internship programme.") == "Internship"
    assert api._infer_employment_type("Collaborate with our engineering team.") is None


def test_work_mode_detection_prefers_hybrid_when_both_terms_appear():
    assert api._infer_work_mode("This is a hybrid role with some remote flexibility.") == "hybrid"
    assert api._infer_work_mode("Work from home; telecommute.") == "remote"


def test_department_is_inferred_from_role_title_and_structured_industry():
    assert api._infer_job_department("Machine Learning Engineer", "Build models.") == "Data & AI"
    assert api._infer_job_department("Product Manager", "Own the roadmap.") == "Product"
    assert api._infer_job_department("Generalist", "Technology team.", "Information Technology") == "Information Technology"


def test_salary_metadata_handles_missing_values():
    assert api._salary_from_jobposting({}) is None
    assert api._salary_from_jobposting({
        "baseSalary": {
            "currency": "INR",
            "value": {"minValue": 1000000, "unitText": "YEAR"},
        }
    }) == {"currency": "INR", "unit": "YEAR", "minimum": 1000000}



def test_explicit_job_location_wins_over_education_phrase():
    description = (
        "Location: Hyderabad\n"
        "Requirements include Python and SQL.\n"
        "Bachelor's degree in Computer Science preferred."
    )
    analysis = api.matching_service.parse_job_description(
        "Python Platform Engineer",
        description,
        use_llm=False,
    )

    assert analysis["location"] == "Hyderabad"

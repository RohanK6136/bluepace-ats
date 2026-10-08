from app.main import _infer_department, _infer_employment_type


def test_infer_department_from_engineering_role():
    assert _infer_department("Senior Backend Engineer", "Build Python APIs with PostgreSQL.") == "Engineering"


def test_infer_department_prefers_explicit_department():
    assert _infer_department("Analytics Lead", "Department: Finance\nBuild reporting models.") == "Finance"


def test_infer_employment_type_detects_contract():
    assert _infer_employment_type("This is a 12-month fixed-term contract.") == "Contract"


def test_infer_employment_type_detects_internship():
    assert _infer_employment_type("We are hiring a software engineering intern.") == "Internship"


def test_infer_employment_type_returns_none_when_unspecified():
    assert _infer_employment_type("Join our team as a backend engineer.") is None

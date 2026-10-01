from types import SimpleNamespace

from app.routers.merge_center import _candidate_score, _name_score


def candidate(first, last, email, phone):
    return SimpleNamespace(first_name=first, last_name=last, email=email, phone=phone)


def test_name_similarity_detects_close_names():
    assert _name_score("Rohan Kumar", "Rohan Kummar") >= 90


def test_duplicate_score_matches_email_and_phone():
    left = candidate("Rohan Kumar", "", "rohan@example.com", "+91 98765 43210")
    right = candidate("Rohan K", "", "rohan@example.com", "919876543210")
    score, matched = _candidate_score(left, right)
    assert score == 100
    assert "email" in matched
    assert "phone" in matched


def test_duplicate_score_can_match_name_without_exact_contact():
    left = candidate("Aisha Sharma", "", "aisha.one@example.com", "1111111111")
    right = candidate("Aisha Sharm", "", "aisha.two@example.com", "2222222222")
    score, matched = _candidate_score(left, right)
    assert score >= 70
    assert "name" in matched
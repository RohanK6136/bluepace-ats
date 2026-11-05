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
        (["January 2020 to March 2022"], 2.3),
        (["2018 - 2020", "2021 - 2023"], 4.0),
        (["Jan 2020 - Dec 2021", "Jan 2021 - Dec 2022"], 3.0),
        (["Jan 2018 - Dec 2018; Jan 2020 - Dec 2020"], 2.0),
        (["Jan 2021 - Present"], 3.1),
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
    ) == 1.1


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

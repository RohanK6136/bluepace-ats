from datetime import datetime, timezone

from app.services.calendar import _event_payload


class Obj:
    pass


def make_interview():
    interview = Obj()
    interview.starts_at = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    interview.duration_minutes = 60
    interview.round_name = "Technical Interview"
    interview.round_number = 2
    interview.round_type = "technical"
    interview.mode = "online"
    interview.location = None
    interview.meeting_url = None
    return interview


def make_application():
    candidate = Obj()
    candidate.first_name = "Test"
    candidate.last_name = "Candidate"
    job = Obj()
    job.title = "Python Developer"
    application = Obj()
    application.candidate = candidate
    application.job = job
    return application


def test_google_payload_requests_unique_meet_conference():
    payload = _event_payload(
        make_interview(),
        make_application(),
        "google",
        [{"email": "interviewer@example.com", "name": "Interviewer"}],
        generate_meeting=True,
    )
    assert payload["summary"] == "Technical Interview — Python Developer"
    assert payload["attendees"][0]["email"] == "interviewer@example.com"
    assert payload["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"] == "hangoutsMeet"
    assert payload["conferenceData"]["createRequest"]["requestId"]


def test_microsoft_payload_generates_teams_meeting():
    payload = _event_payload(
        make_interview(),
        make_application(),
        "microsoft",
        [{"email": "interviewer@example.com", "name": "Interviewer"}],
        generate_meeting=True,
    )
    assert payload["isOnlineMeeting"] is True
    assert payload["onlineMeetingProvider"] == "teamsForBusiness"
    assert payload["attendees"][0]["emailAddress"]["address"] == "interviewer@example.com"


def test_existing_meeting_url_is_preserved():
    interview = make_interview()
    interview.meeting_url = "https://example.com/meeting"
    payload = _event_payload(
        interview,
        make_application(),
        "google",
        [],
        generate_meeting=True,
    )
    assert payload["conferenceData"]["entryPoints"][0]["uri"] == "https://example.com/meeting"
    assert "createRequest" not in payload["conferenceData"]

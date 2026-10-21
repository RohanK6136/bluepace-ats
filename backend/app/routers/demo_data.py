"""Safe, idempotent demo-data population for the authenticated ATS workspace.

All records created here are synthetic. The endpoint deliberately avoids outbound email,
published jobs, real candidate files, and reminder-triggered notifications.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Application,
    AutomationRule,
    Candidate,
    CandidateComment,
    CandidateDocumentRequest,
    CandidateFollower,
    CandidateJobMatch,
    CandidatePortalQuestion,
    CandidateTag,
    Email,
    Interview,
    InterviewAvailability,
    InterviewParticipant,
    Job,
    Note,
    Offer,
    Role,
    Scorecard,
    Stage,
    TalentPool,
    TalentPoolMembership,
    User,
)
from app.security import require_roles
from app.services.workflow import ensure_job_stages, record_audit

router = APIRouter()
WRITE_ROLES = (Role.admin, Role.recruiter)

JOB_FIXTURES = [
    {
        "title": "Senior Python Engineer",
        "department": "Engineering",
        "location": "Hyderabad, India",
        "work_mode": "hybrid",
        "skills": ["Python", "FastAPI", "PostgreSQL", "REST APIs", "Docker"],
        "experience": 4,
        "description": "DEMO DATA — Build and maintain Python services, design reliable REST APIs, improve database performance, and collaborate with product and platform teams. This synthetic job remains in draft and is not publicly advertised.",
    },
    {
        "title": "Full Stack Developer",
        "department": "Engineering",
        "location": "Bengaluru, India",
        "work_mode": "hybrid",
        "skills": ["React", "TypeScript", "Node.js", "SQL", "Testing"],
        "experience": 3,
        "description": "DEMO DATA — Deliver accessible React interfaces, maintain TypeScript and Node.js services, write tests, and work with design and product partners. This synthetic job remains in draft and is not publicly advertised.",
    },
    {
        "title": "Data Scientist",
        "department": "AI & Data",
        "location": "Remote — India",
        "work_mode": "remote",
        "skills": ["Python", "SQL", "Machine Learning", "Pandas", "Model Evaluation"],
        "experience": 2,
        "description": "DEMO DATA — Explore structured datasets, build reproducible machine-learning experiments, evaluate model quality, and communicate evidence-based findings. This synthetic job remains in draft and is not publicly advertised.",
    },
    {
        "title": "Cloud & DevOps Engineer",
        "department": "Platform",
        "location": "Pune, India",
        "work_mode": "hybrid",
        "skills": ["AWS", "Docker", "Kubernetes", "CI/CD", "Monitoring"],
        "experience": 3,
        "description": "DEMO DATA — Improve deployment automation, container reliability, infrastructure observability, and incident response in a cloud platform environment. This synthetic job remains in draft and is not publicly advertised.",
    },
    {
        "title": "Product Designer",
        "department": "Product",
        "location": "Bengaluru, India",
        "work_mode": "onsite",
        "skills": ["Figma", "UX Research", "Prototyping", "Design Systems", "Accessibility"],
        "experience": 3,
        "description": "DEMO DATA — Turn research into clear user flows, maintain a reusable design system, prototype product concepts, and partner with engineering on accessibility. This synthetic job remains in draft and is not publicly advertised.",
    },
    {
        "title": "Talent Acquisition Partner",
        "department": "People",
        "location": "Hyderabad, India",
        "work_mode": "hybrid",
        "skills": ["Sourcing", "Interview Coordination", "Stakeholder Management", "ATS", "Reporting"],
        "experience": 2,
        "description": "DEMO DATA — Coordinate full-cycle hiring, maintain a high-quality ATS pipeline, support structured interviews, and share clear hiring metrics with stakeholders. This synthetic job remains in draft and is not publicly advertised.",
    },
]

CANDIDATE_FIXTURES = [
    ("Aisha", "Shah", ["Python", "FastAPI", "PostgreSQL", "Docker"], 5, "Hyderabad, India", "Senior Backend Engineer"),
    ("Ravi", "Menon", ["React", "TypeScript", "Node.js", "Testing"], 4, "Bengaluru, India", "Full Stack Developer"),
    ("Kavya", "Rao", ["Python", "SQL", "Machine Learning", "Pandas"], 3, "Hyderabad, India", "Data Scientist"),
    ("Dev", "Patel", ["AWS", "Docker", "Kubernetes", "CI/CD"], 4, "Pune, India", "DevOps Engineer"),
    ("Nisha", "Reddy", ["Figma", "UX Research", "Prototyping", "Accessibility"], 4, "Bengaluru, India", "Product Designer"),
    ("Arjun", "Mehta", ["Python", "FastAPI", "REST APIs", "PostgreSQL"], 3, "Pune, India", "Python Developer"),
    ("Meera", "Iyer", ["Python", "SQL", "Pandas", "Model Evaluation"], 2, "Chennai, India", "Data Analyst"),
    ("Karan", "Gill", ["React", "TypeScript", "Node.js", "SQL"], 5, "Gurugram, India", "Frontend Engineer"),
    ("Priya", "Nair", ["Sourcing", "Interview Coordination", "ATS", "Reporting"], 4, "Hyderabad, India", "Talent Acquisition Specialist"),
    ("Vikram", "Das", ["AWS", "Docker", "Monitoring", "CI/CD"], 5, "Bengaluru, India", "Platform Engineer"),
    ("Sana", "Khan", ["Python", "SQL", "Machine Learning", "Statistics"], 3, "Mumbai, India", "Machine Learning Engineer"),
    ("Aditya", "Kulkarni", ["Figma", "Design Systems", "Prototyping", "Accessibility"], 3, "Pune, India", "UX Designer"),
]

# Candidate index, job index, pipeline stage.
APPLICATION_FIXTURES = [
    (0, 0, "Applied"),
    (5, 0, "Screening"),
    (1, 1, "Interview"),
    (7, 1, "Rejected"),
    (2, 2, "Interview"),
    (6, 2, "Offer"),
    (3, 3, "Offer"),
    (9, 3, "Interview"),
    (4, 4, "Hired"),
    (11, 4, "Screening"),
    (8, 5, "Applied"),
    (10, 2, "Rejected"),
    (0, 2, "Screening"),
    (5, 3, "Applied"),
    (1, 0, "Interview"),
    (2, 5, "Applied"),
]


def _first(db: Session, model, *conditions):
    return db.scalar(select(model).where(*conditions).limit(1))


@router.post("/demo-data/populate")
def populate_demo_data(
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Populate the current organization with safe demo records; repeat calls do not duplicate them."""
    org_id = user.organization_id
    now = datetime.now(timezone.utc)
    created = {
        "jobs": 0,
        "candidates": 0,
        "stages": 0,
        "applications": 0,
        "candidate_matches": 0,
        "candidate_tags": 0,
        "candidate_comments": 0,
        "candidate_followers": 0,
        "interviews": 0,
        "interview_participants": 0,
        "scorecards": 0,
        "offers": 0,
        "notes": 0,
        "talent_pools": 0,
        "talent_pool_memberships": 0,
        "automation_rules": 0,
        "email_drafts": 0,
        "interview_availability": 0,
        "candidate_portal_questions": 0,
        "candidate_document_requests": 0,
    }

    try:
        jobs = []
        for index, item in enumerate(JOB_FIXTURES):
            title = f"[DEMO] {item['title']}"
            job = _first(db, Job, Job.organization_id == org_id, Job.title == title)
            if job is None:
                job = Job(
                    organization_id=org_id,
                    created_by_id=user.id,
                    owner_id=user.id,
                    title=title,
                    description=item["description"],
                    department=item["department"],
                    location=item["location"],
                    employment_type="Full-time",
                    work_mode=item["work_mode"],
                    status="draft",
                    required_skills=item["skills"],
                    minimum_experience_years=item["experience"],
                    fresher_allowed=False,
                    tags=["DEMO DATA", item["department"]],
                    starred=index == 0,
                    priority="high" if index < 2 else "normal",
                )
                db.add(job)
                db.flush()
                created["jobs"] += 1
            elif job.status != "draft":
                # Demo fixtures are internal-only and must never be publicly advertised.
                job.status = "draft"
            stages_before = db.query(Stage).filter_by(job_id=job.id).count()
            stage_map = ensure_job_stages(db, job)
            created["stages"] += max(0, len(stage_map) - stages_before)
            jobs.append(job)

        candidates = []
        for index, item in enumerate(CANDIDATE_FIXTURES, start=1):
            first_name, last_name, skills, years, location, job_title = item
            email = f"demo.candidate{index:02d}@example.com"
            candidate = _first(db, Candidate, Candidate.organization_id == org_id, Candidate.email == email)
            if candidate is None:
                candidate = Candidate(
                    organization_id=org_id,
                    created_by_id=user.id,
                    owner_id=user.id,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone=f"DEMO-ATS-{index:04d}",
                    source="DEMO DATA — synthetic profile",
                    resume_data={
                        "name": f"{first_name} {last_name}",
                        "email": email,
                        "skills": skills,
                        "years_of_experience": years,
                        "current_location": location,
                        "preferred_location": location,
                        "job_titles": [job_title],
                        "companies": ["Sample Systems (fictional)"],
                        "experience": [{"company": "Sample Systems (fictional)", "title": job_title, "years": years}],
                        "education": [{"institution": "Example University (fictional)", "degree": "B.Tech"}],
                        "highest_education": "B.Tech",
                        "notice_period": ["Immediate", "30 days", "60 days"][index % 3],
                        "work_authorization": "India",
                        "projects": [f"DEMO DATA: sample {skills[0]} project"],
                        "certifications": [],
                        "resume_quality": {"score": 92, "label": "Synthetic demo profile"},
                        "extraction_confidence": {"overall": 1.0, "mode": "demo_fixture"},
                        "resume_intelligence_version": 3,
                        "is_fresher": False,
                        "raw_text_length": 0,
                    },
                    cv_summary=[
                        f"DEMO DATA — {years} years of sample experience",
                        f"Skills: {', '.join(skills)}",
                        f"Target role: {job_title}",
                    ],
                    tags=["DEMO DATA", skills[0]],
                    starred=index in (1, 3, 6),
                    needs_review=index == 10,
                    priority="high" if index in (1, 3, 10) else "normal",
                )
                db.add(candidate)
                db.flush()
                created["candidates"] += 1
            candidates.append(candidate)

            for tag_name, color in [("DEMO DATA", "#64748b"), (skills[0], "#2563eb")]:
                tag = _first(
                    db,
                    CandidateTag,
                    CandidateTag.organization_id == org_id,
                    CandidateTag.candidate_id == candidate.id,
                    CandidateTag.name == tag_name,
                )
                if tag is None:
                    db.add(CandidateTag(
                        organization_id=org_id,
                        candidate_id=candidate.id,
                        name=tag_name,
                        color=color,
                    ))
                    created["candidate_tags"] += 1

            follower = _first(
                db,
                CandidateFollower,
                CandidateFollower.organization_id == org_id,
                CandidateFollower.candidate_id == candidate.id,
                CandidateFollower.user_id == user.id,
            )
            if index <= 5 and follower is None:
                db.add(CandidateFollower(
                    organization_id=org_id,
                    candidate_id=candidate.id,
                    user_id=user.id,
                ))
                created["candidate_followers"] += 1

            if index in (1, 3, 6, 9):
                comment_body = f"DEMO DATA — Initial review note for {first_name}'s synthetic {job_title} profile."
                comment = _first(
                    db,
                    CandidateComment,
                    CandidateComment.organization_id == org_id,
                    CandidateComment.candidate_id == candidate.id,
                    CandidateComment.author_id == user.id,
                    CandidateComment.body == comment_body,
                )
                if comment is None:
                    db.add(CandidateComment(
                        organization_id=org_id,
                        candidate_id=candidate.id,
                        author_id=user.id,
                        body=comment_body,
                        mentions=[],
                    ))
                    created["candidate_comments"] += 1

        stage_maps = {job.id: ensure_job_stages(db, job) for job in jobs}
        applications = []
        application_stages = []
        for app_index, (candidate_index, job_index, stage_name) in enumerate(APPLICATION_FIXTURES):
            job = jobs[job_index]
            candidate = candidates[candidate_index]
            application = _first(
                db,
                Application,
                Application.organization_id == org_id,
                Application.job_id == job.id,
                Application.candidate_id == candidate.id,
            )
            if application is None:
                status_value = "hired" if stage_name == "Hired" else "rejected" if stage_name == "Rejected" else "active"
                application = Application(
                    organization_id=org_id,
                    job_id=job.id,
                    candidate_id=candidate.id,
                    stage_id=stage_maps[job.id][stage_name].id,
                    status=status_value,
                    applied_at=now - timedelta(days=(app_index * 2) % 25),
                    updated_at=now - timedelta(days=(app_index * 2) % 25),
                )
                db.add(application)
                db.flush()
                created["applications"] += 1
            applications.append(application)
            application_stages.append(stage_name)

            score = 68 + ((candidate_index * 7 + job_index * 5) % 29)
            skill_set = {str(skill).casefold() for skill in (candidate.resume_data or {}).get("skills", [])}
            matched = [skill for skill in (job.required_skills or []) if skill.casefold() in skill_set]
            gaps = [skill for skill in (job.required_skills or []) if skill.casefold() not in skill_set]
            match = _first(
                db,
                CandidateJobMatch,
                CandidateJobMatch.organization_id == org_id,
                CandidateJobMatch.job_id == job.id,
                CandidateJobMatch.candidate_id == candidate.id,
            )
            if match is None:
                db.add(CandidateJobMatch(
                    organization_id=org_id,
                    job_id=job.id,
                    candidate_id=candidate.id,
                    model_score=score,
                    score_breakdown={
                        "required_skill_coverage": score,
                        "preferred_skill_coverage": min(100, score + 3),
                        "experience_alignment": max(45, score - 7),
                        "education_alignment": max(55, score - 4),
                        "location_alignment": 82,
                        "work_mode_alignment": 88,
                        "project_evidence": max(50, score - 2),
                        "semantic_similarity": max(45, score - 5),
                    },
                    matched_skills=matched,
                    skill_gaps=gaps,
                    explanations=["DEMO DATA — synthetic illustrative match signal; not a hiring recommendation."],
                    semantic_mode="demo_fixture",
                ))
                created["candidate_matches"] += 1

            note_body = f"DEMO DATA — Example recruiter note: review {candidate.first_name}'s evidence for the {stage_name} stage. No real hiring decision is represented."
            note = _first(
                db,
                Note,
                Note.organization_id == org_id,
                Note.application_id == application.id,
                Note.author_id == user.id,
                Note.body == note_body,
            )
            if note is None:
                db.add(Note(
                    organization_id=org_id,
                    application_id=application.id,
                    author_id=user.id,
                    body=note_body,
                ))
                created["notes"] += 1

            if stage_name == "Interview":
                round_name = "[DEMO] Technical screen"
                interview = _first(
                    db,
                    Interview,
                    Interview.application_id == application.id,
                    Interview.round_name == round_name,
                )
                if interview is None:
                    interview_date = (now + timedelta(days=2 + app_index % 5)).replace(hour=5, minute=30, second=0, microsecond=0)
                    interview = Interview(
                        application_id=application.id,
                        interviewer_id=user.id,
                        starts_at=interview_date,
                        duration_minutes=45,
                        status="scheduled",
                        mode="online",
                        location=None,
                        meeting_url=f"https://example.com/demo-interview/{application.id}",
                        reminder_24_sent=True,
                        reminder_1h_sent=True,
                        round_name=round_name,
                        round_type="technical",
                        round_number=1,
                        feedback_deadline=interview_date + timedelta(days=2),
                    )
                    db.add(interview)
                    db.flush()
                    created["interviews"] += 1
                participant = _first(
                    db,
                    InterviewParticipant,
                    InterviewParticipant.interview_id == interview.id,
                    InterviewParticipant.user_id == user.id,
                )
                if participant is None:
                    db.add(InterviewParticipant(interview_id=interview.id, user_id=user.id))
                    created["interview_participants"] += 1
                scorecard = _first(
                    db,
                    Scorecard,
                    Scorecard.application_id == application.id,
                    Scorecard.interviewer_id == user.id,
                )
                if scorecard is None:
                    db.add(Scorecard(
                        application_id=application.id,
                        interviewer_id=user.id,
                        ratings={
                            "technical_skills": 4,
                            "problem_solving": 4 if score >= 78 else 3,
                            "communication": 4,
                            "role_alignment": 4 if len(matched) >= 2 else 3,
                        },
                        recommendation="yes" if score >= 78 else "mixed",
                        submitted_at=now - timedelta(hours=6),
                    ))
                    created["scorecards"] += 1

            if stage_name == "Offer":
                offer = _first(db, Offer, Offer.application_id == application.id)
                if offer is None:
                    db.add(Offer(
                        organization_id=org_id,
                        application_id=application.id,
                        position_title=job.title,
                        annual_ctc="1800000" if job_index in (0, 1) else "1500000",
                        currency="INR",
                        status="internal_review" if app_index % 2 == 0 else "draft",
                        notes="DEMO DATA — fictional offer details for interface testing only. Not approved or sent.",
                        ctc_breakdown={"base": "1200000", "variable": "300000", "allowances": "300000"},
                        benefits=["DEMO — health cover", "DEMO — learning allowance"],
                        probation_period="6 months (sample)",
                        expires_at=now + timedelta(days=30),
                        created_by_id=user.id,
                    ))
                    created["offers"] += 1

            email_subject = f"[DEMO] Application update preview — {job.title}"
            draft = _first(
                db,
                Email,
                Email.organization_id == org_id,
                Email.application_id == application.id,
                Email.subject == email_subject,
            )
            if draft is None and app_index in (0, 2, 4, 6, 8, 10):
                db.add(Email(
                    organization_id=org_id,
                    application_id=application.id,
                    recipient=candidate.email,
                    subject=email_subject,
                    body=(
                        "DEMO DATA — This is a preview record only. It has not been sent. "
                        f"Sample stage: {stage_name}. Sample role: {job.title}."
                    ),
                    status="draft",
                    error_message=None,
                ))
                created["email_drafts"] += 1

        pool_fixtures = [
            ("DEMO — Engineering Talent", "Synthetic backend, frontend, and platform profiles.", [0, 1, 3, 5, 7, 9]),
            ("DEMO — AI & Data", "Synthetic analytics and machine-learning profiles.", [2, 6, 10]),
            ("DEMO — Product & People", "Synthetic design and talent-acquisition profiles.", [4, 8, 11]),
        ]
        for name, description, member_indexes in pool_fixtures:
            pool = _first(db, TalentPool, TalentPool.organization_id == org_id, TalentPool.name == name)
            if pool is None:
                pool = TalentPool(
                    organization_id=org_id,
                    name=name,
                    description=description,
                    created_by_id=user.id,
                )
                db.add(pool)
                db.flush()
                created["talent_pools"] += 1
            for candidate_index in member_indexes:
                candidate = candidates[candidate_index]
                membership = _first(
                    db,
                    TalentPoolMembership,
                    TalentPoolMembership.pool_id == pool.id,
                    TalentPoolMembership.candidate_id == candidate.id,
                )
                if membership is None:
                    db.add(TalentPoolMembership(
                        pool_id=pool.id,
                        candidate_id=candidate.id,
                        added_by_id=user.id,
                    ))
                    created["talent_pool_memberships"] += 1

        automation_fixtures = [
            ("[DEMO] Application received email preview", "Applied", "Application received — {{job_title}}"),
            ("[DEMO] Interview preparation checklist", "Interview", "Interview details — {{job_title}}"),
            ("[DEMO] Offer stage review reminder", "Offer", "Offer review needed — {{job_title}}"),
        ]
        for name, trigger_stage, subject in automation_fixtures:
            rule = _first(
                db,
                AutomationRule,
                AutomationRule.organization_id == org_id,
                AutomationRule.name == name,
            )
            if rule is None:
                db.add(AutomationRule(
                    organization_id=org_id,
                    created_by_id=user.id,
                    name=name,
                    trigger_event="stage_changed",
                    trigger_stage=trigger_stage,
                    action_type="send_email",
                    action_value=None,
                    subject=subject,
                    body="DEMO DATA — disabled example automation. Review and configure before enabling.",
                    enabled=False,
                ))
                created["automation_rules"] += 1

        for day_offset in (2, 4, 6, 8):
            start = (now + timedelta(days=day_offset)).replace(hour=7, minute=0, second=0, microsecond=0)
            slot = _first(
                db,
                InterviewAvailability,
                InterviewAvailability.organization_id == org_id,
                InterviewAvailability.user_id == user.id,
                InterviewAvailability.starts_at == start,
            )
            if slot is None:
                db.add(InterviewAvailability(
                    organization_id=org_id,
                    user_id=user.id,
                    starts_at=start,
                    ends_at=start + timedelta(hours=1),
                    status="available",
                    note="DEMO DATA — sample availability, not a real commitment.",
                ))
                created["interview_availability"] += 1

        # Populate candidate self-service queues without issuing real portal links or documents.
        question_application = next(
            (app for app, stage in zip(applications, application_stages) if stage in ("Interview", "Screening")),
            None,
        )
        if question_application is not None:
            question = _first(
                db,
                CandidatePortalQuestion,
                CandidatePortalQuestion.organization_id == org_id,
                CandidatePortalQuestion.application_id == question_application.id,
                CandidatePortalQuestion.subject == "[DEMO] Interview availability",
            )
            if question is None:
                db.add(CandidatePortalQuestion(
                    organization_id=org_id,
                    application_id=question_application.id,
                    candidate_id=question_application.candidate_id,
                    subject="[DEMO] Interview availability",
                    question="DEMO DATA — Please confirm whether the proposed interview window works for you.",
                    answer=None,
                    status="open",
                ))
                created["candidate_portal_questions"] += 1

            doc_request = _first(
                db,
                CandidateDocumentRequest,
                CandidateDocumentRequest.organization_id == org_id,
                CandidateDocumentRequest.application_id == question_application.id,
                CandidateDocumentRequest.name == "[DEMO] Portfolio sample",
            )
            if doc_request is None:
                db.add(CandidateDocumentRequest(
                    organization_id=org_id,
                    application_id=question_application.id,
                    candidate_id=question_application.candidate_id,
                    requested_by_id=user.id,
                    name="[DEMO] Portfolio sample",
                    description="Synthetic placeholder request for previewing candidate document workflows.",
                    required=False,
                    status="pending",
                    due_at=now + timedelta(days=14),
                ))
                created["candidate_document_requests"] += 1

        record_audit(
            db,
            user,
            "demo_data.populated",
            "demo_data",
            user.id,
            after={"created": created, "synthetic": True},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    total_created = sum(created.values())
    return {
        "status": "ready",
        "message": (
            "Synthetic demo records are ready. Jobs remain draft, automation examples are disabled, "
            "email records are drafts, and no outbound email or real interview reminder was sent."
        ),
        "created": created,
        "total_created": total_created,
        "already_populated": total_created == 0,
    }

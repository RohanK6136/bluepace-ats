import enum
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Role(str, enum.Enum):
    admin = "admin"
    recruiter = "recruiter"
    hiring_manager = "hiring_manager"
    interviewer = "interviewer"
    candidate = "candidate"


def utc_now():
    return datetime.now(timezone.utc)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email_templates: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    users: Mapped[list["User"]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(500))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), default=Role.recruiter)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    organization: Mapped[Organization] = relationship(back_populates="users")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    work_mode: Mapped[str] = mapped_column(String(20), default="onsite", server_default="onsite")
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    required_skills: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    minimum_experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fresher_allowed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    jd_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536).with_variant(JSON(), "sqlite"), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, default=list, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    starred: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="normal", server_default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (UniqueConstraint("organization_id", "email", name="uq_candidate_org_email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resume_storage_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    resume_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cv_summary: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536).with_variant(JSON(), "sqlite"), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, default=list, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    starred: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="normal", server_default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Stage(Base):
    __tablename__ = "stages"
    __table_args__ = (UniqueConstraint("job_id", "position", name="uq_stage_job_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_id", "candidate_id", name="uq_application_job_candidate"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    assigned_interviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=True)
    job: Mapped[Job] = relationship()
    candidate: Mapped[Candidate] = relationship()
    stage: Mapped[Stage | None] = relationship()


class CandidateJobMatch(Base):
    __tablename__ = "candidate_job_matches"
    __table_args__ = (UniqueConstraint("job_id", "candidate_id", name="uq_candidate_job_match"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    model_score: Mapped[int] = mapped_column(Integer)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    matched_skills: Mapped[list] = mapped_column(JSON, default=list)
    skill_gaps: Mapped[list] = mapped_column(JSON, default=list)
    explanations: Mapped[list] = mapped_column(JSON, default=list)
    semantic_mode: Mapped[str] = mapped_column(String(30), default="lexical_fallback")
    recruiter_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recruiter_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    job: Mapped[Job] = relationship()
    candidate: Mapped[Candidate] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    before_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class CandidateMergeAudit(Base):
    __tablename__ = "candidate_merge_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    survivor_candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    merged_candidate_id: Mapped[int] = mapped_column(Integer, index=True)
    field_choices: Mapped[dict] = mapped_column(JSON, default=dict)
    before_survivor: Mapped[dict] = mapped_column(JSON, default=dict)
    before_merged: Mapped[dict] = mapped_column(JSON, default=dict)
    after_survivor: Mapped[dict] = mapped_column(JSON, default=dict)
    merge_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class CandidateTag(Base):
    __tablename__ = "candidate_tags"
    __table_args__ = (UniqueConstraint("candidate_id", "name", name="uq_candidate_tag_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(20), default="#1769d3", server_default="#1769d3")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CandidateComment(Base):
    __tablename__ = "candidate_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class CandidateFollower(Base):
    __tablename__ = "candidate_followers"
    __table_args__ = (UniqueConstraint("candidate_id", "user_id", name="uq_candidate_follower"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Scorecard(Base):
    __tablename__ = "scorecards"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    interviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    ratings: Mapped[dict] = mapped_column(JSON, default=dict)
    recommendation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Interview(Base):
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    interviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    status: Mapped[str] = mapped_column(String(30), default="scheduled")
    mode: Mapped[str] = mapped_column(String(20), default="online", server_default="online")
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    meeting_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reminder_24_sent: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    reminder_1h_sent: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    round_name: Mapped[str] = mapped_column(String(100), default="Interview", server_default="Interview")
    round_type: Mapped[str] = mapped_column(String(30), default="technical", server_default="technical")
    round_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    feedback_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class InterviewParticipant(Base):
    __tablename__ = "interview_participants"
    __table_args__ = (UniqueConstraint("interview_id", "user_id", name="uq_interview_participant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class InterviewAvailability(Base):
    __tablename__ = "interview_availability"
    __table_args__ = (UniqueConstraint("user_id", "starts_at", name="uq_interviewer_availability_slot"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="available")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)


class TalentPool(Base):
    __tablename__ = "talent_pools"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TalentPoolMembership(Base):
    __tablename__ = "talent_pool_memberships"
    __table_args__ = (UniqueConstraint("pool_id", "candidate_id", name="uq_pool_candidate"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("talent_pools.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    added_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), unique=True, index=True)
    position_title: Mapped[str] = mapped_column(String(200))
    annual_ctc: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    joining_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offer_letter_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    ctc_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    benefits: Mapped[list | None] = mapped_column(JSON, nullable=True)
    probation_period: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    trigger_event: Mapped[str] = mapped_column(String(50), default="stage_changed")
    trigger_stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action_type: Mapped[str] = mapped_column(String(50), default="send_email")
    action_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class RagChunk(Base):
    __tablename__ = "rag_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(30), index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True)
    field: Mapped[str] = mapped_column(String(100), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536).with_variant(JSON(), "sqlite"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ResumeProcessingJob(Base):
    __tablename__ = "resume_processing_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(1000))
    content_type: Mapped[str] = mapped_column(String(200), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", server_default="queued", index=True)
    result_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CandidateDocument(Base):
    __tablename__ = "candidate_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(1000))
    content_type: Mapped[str] = mapped_column(String(200), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CandidatePortalQuestion(Base):
    __tablename__ = "candidate_portal_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open", server_default="open")
    answered_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CandidateDocumentRequest(Base):
    __tablename__ = "candidate_document_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending")
    document_id: Mapped[int | None] = mapped_column(ForeignKey("candidate_documents.id", ondelete="SET NULL"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Email(Base):
    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="SET NULL"), nullable=True)
    recipient: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
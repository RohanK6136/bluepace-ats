from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Role


class OrganizationRegistration(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class UserCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    role: Role = Role.recruiter


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    full_name: str
    email: EmailStr
    role: Role
    is_active: bool


class TokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    department: Optional[str] = Field(default=None, max_length=200)
    location: Optional[str] = Field(default=None, max_length=200)
    employment_type: Optional[str] = Field(default=None, max_length=50)
    work_mode: str = Field(default="onsite", pattern="^(remote|hybrid|onsite)$")
    status: str = Field(default="draft", pattern="^(draft|open|paused|closed|archived)$")
    required_skills: list[str] = Field(default_factory=list, max_length=100)
    minimum_experience_years: Optional[int] = Field(default=None, ge=0, le=60)
    fresher_allowed: bool = False


class JobUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, min_length=1)
    department: Optional[str] = Field(default=None, max_length=200)
    location: Optional[str] = Field(default=None, max_length=200)
    employment_type: Optional[str] = Field(default=None, max_length=50)
    work_mode: Optional[str] = Field(default=None, pattern="^(remote|hybrid|onsite)$")
    status: Optional[str] = Field(default=None, pattern="^(draft|open|paused|closed|archived)$")
    required_skills: Optional[list[str]] = Field(default=None, max_length=100)
    minimum_experience_years: Optional[int] = Field(default=None, ge=0, le=60)
    fresher_allowed: Optional[bool] = None


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_by_id: int
    title: str
    description: str
    department: Optional[str]
    location: Optional[str]
    employment_type: Optional[str]
    work_mode: str
    status: str
    required_skills: Optional[list[str]]
    minimum_experience_years: Optional[int]
    fresher_allowed: bool
    jd_analysis: Optional[dict]
    created_at: datetime
    updated_at: datetime


class CandidateCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=50)
    linkedin_url: Optional[str] = Field(default=None, max_length=500)
    source: Optional[str] = Field(default=None, max_length=100)
    resume_storage_key: Optional[str] = Field(default=None, max_length=1000)
    resume_data: Optional[dict] = None


class CandidateUpdate(BaseModel):
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    linkedin_url: Optional[str] = Field(default=None, max_length=500)
    source: Optional[str] = Field(default=None, max_length=100)
    resume_storage_key: Optional[str] = Field(default=None, max_length=1000)
    resume_data: Optional[dict] = None


class CandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_by_id: int
    first_name: str
    last_name: str
    email: str
    phone: Optional[str]
    linkedin_url: Optional[str]
    source: Optional[str]
    resume_storage_key: Optional[str]
    resume_data: Optional[dict]
    cv_summary: Optional[list[str]]
    tags: Optional[list[str]] = None
    archived: bool = False
    merged_into_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class ApplicationCreate(BaseModel):
    job_id: int
    candidate_id: int


class CandidateSummary(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    source: Optional[str]
    resume_data: Optional[dict]


class ApplicationRead(BaseModel):
    id: int
    job_id: int
    candidate_id: int
    job_title: str
    stage_id: Optional[int]
    stage_name: Optional[str]
    status: str
    applied_at: datetime
    updated_at: Optional[datetime]
    candidate: CandidateSummary


class ApplicationStageUpdate(BaseModel):
    stage_name: str = Field(pattern="^(Applied|Screening|Interview|Offer|Hired|Rejected)$")
    interview_starts_at: Optional[datetime] = None
    interview_duration_minutes: int = Field(default=60, ge=15, le=480)
    interview_mode: str = Field(default="online", pattern="^(online|offline)$")
    interview_location: Optional[str] = Field(default=None, max_length=500)
    interview_meeting_url: Optional[str] = Field(default=None, max_length=1000)


class BulkApplicationUpdate(BaseModel):
    application_ids: list[int] = Field(min_length=1, max_length=100)
    stage_name: str = Field(pattern="^(Applied|Screening|Interview|Offer|Hired|Rejected)$")


class MatchFeedbackUpdate(BaseModel):
    recruiter_override: Optional[int] = Field(default=None, ge=0, le=100)
    recruiter_note: Optional[str] = Field(default=None, max_length=2000)


class CandidateMatchRead(BaseModel):
    id: int
    job_id: int
    candidate_id: int
    candidate_name: str
    candidate_email: str
    model_score: int
    effective_score: int
    recruiter_override: Optional[int]
    recruiter_note: Optional[str]
    score_breakdown: dict
    matched_skills: list[str]
    skill_gaps: list[str]
    explanations: list[str]
    semantic_mode: str
    cv_summary: list[str]

class Experience(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[str] = None
    description: Optional[str] = None

class Education(BaseModel):
    degree: Optional[str] = None
    university: Optional[str] = None
    cgpa: Optional[str] = None
    graduation_year: Optional[str] = None

class ResumeData(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    skills: List[str] = []
    experience: List[Experience] = []
    education: List[Education] = []
    hobbies: List[str] = []
    university_projects: List[str] = []
    highest_education: Optional[str] = None
    is_fresher: bool = False
    raw_text_length: int = 0

class ScorecardCreate(BaseModel):
    ratings: dict = Field(default_factory=dict)
    recommendation: Optional[str] = Field(default=None, max_length=50)


class ScorecardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    interviewer_id: int
    ratings: dict
    recommendation: Optional[str]
    submitted_at: Optional[datetime]


class EmailTemplate(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=10000)


class EmailTemplateUpdate(BaseModel):
    templates: dict[str, EmailTemplate]


class EmailTemplateTestRequest(BaseModel):
    template_name: str = Field(min_length=1, max_length=100)
    recipient: str = Field(min_length=3, max_length=320)


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class NoteRead(BaseModel):
    id: int
    application_id: int
    author_id: int
    author_name: str
    body: str
    created_at: datetime


class TalentPoolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)


class TalentPoolRead(BaseModel):
    id: int
    name: str
    description: Optional[str]
    candidate_count: int
    created_at: datetime


class TalentPoolCandidateRequest(BaseModel):
    candidate_id: int


class OfferCreate(BaseModel):
    position_title: str = Field(min_length=1, max_length=200)
    annual_ctc: Optional[str] = Field(default=None, max_length=100)
    currency: str = Field(default="INR", min_length=3, max_length=10)
    joining_date: Optional[datetime] = None
    offer_letter_url: Optional[str] = Field(default=None, max_length=1000)
    notes: Optional[str] = Field(default=None, max_length=5000)


class OfferUpdate(BaseModel):
    annual_ctc: Optional[str] = Field(default=None, max_length=100)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=10)
    joining_date: Optional[datetime] = None
    offer_letter_url: Optional[str] = Field(default=None, max_length=1000)
    status: Optional[str] = Field(default=None, pattern="^(draft|sent|viewed|accepted|declined|expired)$")
    notes: Optional[str] = Field(default=None, max_length=5000)


class OfferRead(BaseModel):
    id: int
    application_id: int
    position_title: str
    annual_ctc: Optional[str]
    currency: str
    joining_date: Optional[datetime]
    offer_letter_url: Optional[str]
    status: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class InterviewCreate(BaseModel):
    starts_at: datetime
    duration_minutes: int = Field(default=60, ge=15, le=480)
    mode: str = Field(default="online", pattern="^(online|offline)$")
    location: Optional[str] = Field(default=None, max_length=500)
    meeting_url: Optional[str] = Field(default=None, max_length=1000)
    round_name: str = Field(default="Interview", min_length=1, max_length=100)


class InterviewStatusUpdate(BaseModel):
    status: str = Field(pattern="^(scheduled|completed|cancelled|no_show)$")


class InterviewRead(BaseModel):
    id: int
    application_id: int
    interviewer_id: int
    starts_at: datetime
    duration_minutes: int
    status: str
    mode: str
    location: Optional[str]
    meeting_url: Optional[str]
    round_name: str
    round_number: int


class CandidateComparisonRead(BaseModel):
    application_id: int
    job_title: str
    score: int
    matched_skills: list[str]
    missing_skills: list[str]
    experience_required: Optional[int]
    experience_estimated: float
    education_requirement: str
    education_evidence: list[str]
    project_evidence: list[str]
    gaps: list[str]

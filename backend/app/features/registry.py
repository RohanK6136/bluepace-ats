"""Catalogue of platform features. The launcher page and GET /v1/features are built from this list."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class FeatureInfo(BaseModel):
    id: str
    name: str
    tagline: str
    description: str
    status: Literal["available", "beta", "coming_soon"]
    ui_route: str | None = None  # hash route in the web app
    api_prefix: str | None = None
    capabilities: list[str] = []


FEATURES: list[FeatureInfo] = [
    FeatureInfo(
        id="jd_standardizer",
        name="JD Standardizer",
        tagline="Any job description or rough role notes → a publish-ready Blupace Tech JD",
        description="Parses recruiter text with rules, writes only what is missing with one streamed model call, "
                    "and never invents facts. AI-written text is marked for review.",
        status="available",
        ui_route="#/features/jd-standardizer",
        api_prefix="/v1/jd",
        capabilities=["PDF / DOCX / TXT input", "Streaming output", "Fact grounding", "Model choice"],
    ),
    FeatureInfo(
        id="applicant_match",
        name="Application Assessment",
        tagline="Check resumes against a job's requirements, with the evidence for every number",
        description="Builds a reviewable rubric from a JD, redacts personal details, finds evidence for each "
                    "requirement in the resume and computes a transparent match score in code. Decision support "
                    "only: recruiters make every decision.",
        status="available",
        ui_route="#/features/application-assessment",
        api_prefix="/v1/match",
        capabilities=["PDF / DOCX resumes", "Editable rubric", "Evidence per requirement", "Redaction first"],
    ),
]


def get_feature(feature_id: str) -> FeatureInfo | None:
    return next((f for f in FEATURES if f.id == feature_id), None)

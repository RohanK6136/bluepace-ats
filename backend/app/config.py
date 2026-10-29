"""Application settings (environment / .env). Model endpoints live in config/models.yaml, not here."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent

DEFAULT_SECTION_HEADINGS: dict[str, str] = {
    "about_role": "About the Role",
    "responsibilities": "Key Responsibilities",
    "requirements": "Requirements",
    "nice_to_have": "Nice to Have",
    "offer": "What We Offer",
    "additional_info": "Additional Information",
    "about_company": "About {company}",
    "legal": "Equal Opportunity",
    # fast-mode headings (OpenAI-style layout, Blupace branding)
    "about_team": "About the Team",
    "about_the_role": "About the Role",
    "qualifications": "Qualifications",
    "preferred_skills": "Preferred Skills",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- platform
    APP_NAME: str = "Blupace AI Lab"
    APP_VERSION: str = "0.3.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    LOG_LEVEL: str = "INFO"
    API_KEYS: str = ""  # comma-separated; empty disables auth (development only)
    DB_PATH: str = "./data/app.sqlite"
    STORE_PAYLOADS: bool = True  # keep full inputs/outputs/prompts for runs (turn off for sensitive data)
    # 0 disables automatic payload expiry; choose a retention period only after policy/legal approval.
    PAYLOAD_RETENTION_DAYS: int = 0
    REQUEST_TIMEOUT_S: float = 300.0

    # ---- LLM gateway
    MODELS_FILE: str = str(PROJECT_DIR / "config" / "models.yaml")
    LLM_PROFILE: str = ""  # overrides default_profile in models.yaml
    READYZ_PROBE_TIMEOUT_S: float = 8.0
    CHARS_PER_TOKEN: float = 3.2  # token estimate when a provider reports no usage
    MAX_REPAIR_RETRIES: int = 1

    # ---- inputs
    MAX_INPUT_CHARS: int = 60000
    MAX_UPLOAD_MB: float = 5.0
    MAX_DOCX_UNCOMPRESSED_MB: float = 50.0
    MIN_TEXT_CHARS_PASTED: int = 15
    MIN_TEXT_CHARS_FILE: int = 100

    # ---- feature: JD Standardizer
    COMPANY_NAME: str = "Blupace Tech"
    DEFAULT_MODE: Literal["verbatim", "light", "rewrite"] = "light"
    LABEL_LONG_PARAGRAPHS: bool = True
    LONG_PARAGRAPH_WORDS: int = 20
    LONG_SECTION_ITEMS: int = 12
    HEADER_MAX_LINES: int = 15
    OFFER_BLOCK_ENABLED: bool = False
    PIPELINE_VERSION: str = "0.3.0"
    SECTION_HEADINGS: dict[str, str] = DEFAULT_SECTION_HEADINGS
    LABELS_MAX_BLOCKS_PER_CALL: int = 20
    LABELS_MAX_BLOCK_CHARS: int = 400
    FACTS_MAX_HEADER_LINES: int = 20
    FACTS_FIRST_BODY_LINES: int = 12
    FACTS_MAX_TOKENS: int = 700
    SUMMARY_MAX_CHARS: int = 160
    SUMMARY_MAX_TOKENS: int = 120
    SUMMARY_ABOUT_CHARS: int = 600
    GAPFILL_ABOUT_MAX_TOKENS: int = 220

    @property
    def api_keys(self) -> set[str]:
        return {k.strip() for k in self.API_KEYS.split(",") if k.strip()}


@lru_cache
def get_settings() -> Settings:
    # config/models.yaml and provider API keys read os.environ, so .env must reach the process environment too.
    # Variables already set in the real environment win.
    load_dotenv(".env", override=False)
    return Settings()

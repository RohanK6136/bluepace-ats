"""Privacy-minimised, durable AI usage telemetry for FastAPI AI endpoints.

Only operational metadata and provider-reported token counts are stored here.
Prompts, resume content, raw model output, and credentials are intentionally excluded.
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AIUsageEvent(Base):
    __tablename__ = "ai_usage_events"
    __table_args__ = (
        CheckConstraint("provider_cost_usd IS NULL OR provider_cost_usd >= 0", name="ck_ai_usage_provider_cost_nonnegative"),
        Index("idx_ai_usage_events_task_model_time", "task", "provider", "model", "occurred_at"),
        Index("idx_ai_usage_events_tenant_time", "tenant_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Provider-reported cost is available for some providers (for example OpenRouter).
    # NULL means the provider did not report a cost; it does not mean the call was free.
    provider_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)

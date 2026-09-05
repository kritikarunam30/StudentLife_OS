from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Float, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ActiveJobPipeline(Base):
    __tablename__ = "active_job_pipeline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(100), default="manual", nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Scoring & Matching
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    readiness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    role_match: Mapped[str | None] = mapped_column(String(50), default="inferred", nullable=True)
    matched_role: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # DSA Explainability Breakdown
    required_skills: Mapped[str | None] = mapped_column(Text, nullable=True)
    technical_strengths: Mapped[str | None] = mapped_column(Text, nullable=True)
    developing_topics: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SOP Draft & Explainability
    sop_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    sop_status: Mapped[str] = mapped_column(String(50), default="not_generated", nullable=False, index=True)
    sop_generated_from: Mapped[str | None] = mapped_column(Text, nullable=True)
    student_preferences: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Extracted Job Metadata
    experience_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    responsibilities: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_values: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

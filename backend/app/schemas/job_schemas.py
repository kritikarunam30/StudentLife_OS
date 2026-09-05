from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class JobParseResult(BaseModel):
    role_title: str = Field(..., description="Normalized or extracted job role title")
    company: str = Field(..., description="Company or organization offering the role")
    required_skills: list[str] = Field(default_factory=list, description="Explicit technical skills and tools required")
    required_experience_level: str = Field(default="Internship / Entry Level", description="Target experience level")
    key_responsibilities: list[str] = Field(default_factory=list, description="Core responsibilities extracted from the posting")
    company_values_and_mission: str | None = Field(default="", description="Mission or cultural values language from the posting")
    application_deadline: str | None = Field(default=None, description="Explicit deadline date/time if mentioned")
    overall_match_score: float = Field(default=75.0, description="Estimated profile fit percentage based on skills (0-100)")


class SOPGenerateResult(BaseModel):
    sop_text: str = Field(..., description="Tailored, personalized Statement of Purpose draft")
    tone: str = Field(default="confident_achievement", description="Tone adopted: 'confident_achievement' or 'growth_trajectory'")
    generated_from: list[str] = Field(default_factory=list, description="Provenance list of fields used to construct the SOP")
    key_strengths_highlighted: list[str] = Field(default_factory=list, description="Verified student strengths explicitly cited")
    growth_areas_framed: list[str] = Field(default_factory=list, description="Developing topics framed as active learning trajectory")


class JobProcessInput(BaseModel):
    job_text: str = Field(..., min_length=10, description="Raw job description or announcement text")
    company: str | None = Field(default=None, description="Optional company name override")
    title: str | None = Field(default=None, description="Optional job title override")
    tone_preference: str = Field(default="formal", description="Style preference: 'formal' or 'conversational'")
    specific_points: str | None = Field(default=None, description="Optional custom points/achievements to emphasize")
    source: str = Field(default="manual", description="Source of the job posting: 'manual', 'email', 'scraper'")
    url: str | None = Field(default=None, description="Job listing URL")


class UpdateSOPInput(BaseModel):
    sop_draft: str = Field(..., description="Updated Statement of Purpose text edited by the student")
    sop_status: str | None = Field(default="reviewed", description="Status e.g. 'drafted', 'reviewed', 'applied'")


class RegenerateSOPInput(BaseModel):
    tone_preference: str | None = Field(default=None, description="Updated tone preference")
    specific_points: str | None = Field(default=None, description="Additional custom notes to emphasize")


class ActiveJobResponse(BaseModel):
    id: int
    user_id: int
    title: str
    company: str
    description: str
    source: str = "manual"
    url: str | None = None
    match_score: float | None = None
    readiness_score: float | None = None
    role_match: str | None = "inferred"
    matched_role: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    technical_strengths: list[str] = Field(default_factory=list)
    developing_topics: list[str] = Field(default_factory=list)
    sop_draft: str | None = None
    sop_status: str = "not_generated"
    sop_generated_from: list[str] = Field(default_factory=list)
    student_preferences: dict[str, Any] | None = None
    experience_level: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    company_values: str | None = None
    deadline: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    model_config = ConfigDict(from_attributes=True)

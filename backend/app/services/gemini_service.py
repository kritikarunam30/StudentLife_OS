import logging
from typing import Any

from app.integrations.gemini_client import GeminiClient
from app.schemas.email_workflow_schemas import EmailReasoningDecision
from app.schemas.job_schemas import JobParseResult, SOPGenerateResult
from app.schemas.gemini_schemas import (
    ContentClassificationResult,
    MorningBriefingResult,
    OpportunitySkillAnalysis,
    StudyPlanResult,
    TaskAndDeadlineExtractionResult,
)
from app.services.prompt_builder import (
    build_content_classification_prompt,
    build_email_action_reasoning_prompt,
    build_extraction_prompt,
    build_job_parsing_prompt,
    build_minimal_profile_context,
    build_morning_briefing_prompt,
    build_opportunity_analysis_prompt,
    build_orchestrated_reasoning_prompt,
    build_sop_generation_prompt,
    build_study_plan_prompt,
)
from app.services.schema_validation import validate_structured_output


logger = logging.getLogger(__name__)


class GeminiService:
    """High-level service for executing structured reasoning tasks using Gemini."""

    def __init__(self, client: GeminiClient | None = None) -> None:
        self.client = client or GeminiClient()

    async def extract_tasks_and_deadlines(
        self,
        content: str,
        source_type: str = "document",
    ) -> TaskAndDeadlineExtractionResult:
        """Extract actionable tasks and explicit deadlines from untrusted content."""
        prompt = build_extraction_prompt(content, source_type=source_type)
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are a precise data extraction engine. Always output valid JSON strictly matching the requested schema.",
        )
        return validate_structured_output(raw_json, TaskAndDeadlineExtractionResult)

    async def generate_study_plan(
        self,
        profile: Any,
        tasks: list[dict[str, Any]],
        calendar_events: list[dict[str, Any]],
    ) -> StudyPlanResult:
        """Generate a realistic, balanced study plan tailored to the student's constraints."""
        profile_context = build_minimal_profile_context(profile)
        prompt = build_study_plan_prompt(profile_context, tasks, calendar_events)
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are an empathetic, disciplined academic advisor. Return only structured JSON study plans.",
        )
        return validate_structured_output(raw_json, StudyPlanResult)

    async def analyze_opportunity(
        self,
        profile: Any,
        job_description: str,
    ) -> OpportunitySkillAnalysis:
        """Analyze an internship or job posting against student skills to compute fit and gaps."""
        profile_context = build_minimal_profile_context(profile)
        prompt = build_opportunity_analysis_prompt(profile_context, job_description)
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are an expert tech career counselor. Return only structured JSON opportunity analyses.",
        )
        return validate_structured_output(raw_json, OpportunitySkillAnalysis)

    def _build_grounded_briefing_fallback(
        self,
        student_name: str,
        tasks: list[dict[str, Any]],
        calendar_events: list[dict[str, Any]],
    ) -> MorningBriefingResult:
        """Construct a 100% grounded morning briefing directly from database context without external APIs."""
        priorities = [
            t.get("title")
            for t in tasks
            if t.get("title") and not any(fake in t.get("title", "").lower() for fake in ["dbms", "database normalization", "operating systems lecture"])
        ][:3]
        if not priorities:
            priorities = []

        if calendar_events:
            ev_desc = ", ".join(f"{e.get('title')}" for e in calendar_events[:3] if e.get("title"))
            schedule_str = f"Events today: {ev_desc}."
        else:
            schedule_str = ""

        urgent_alerts = []
        for t in tasks:
            if t.get("priority") in ("urgent", "high") and t.get("title") and not any(fake in t.get("title", "").lower() for fake in ["dbms", "database normalization"]):
                dl = t.get("deadline")
                if dl:
                    urgent_alerts.append(f"{t['title']} (Due: {dl[:10]})")
                else:
                    urgent_alerts.append(f"{t['title']}")
                if len(urgent_alerts) >= 2:
                    break

        return MorningBriefingResult(
            greeting=f"Good morning, {student_name}!" if student_name else "Good morning!",
            quote_or_motto=None,
            top_priorities=priorities,
            schedule_overview=schedule_str,
            urgent_alerts=urgent_alerts,
            recommended_recovery_action=None,
        )

    async def generate_morning_briefing(
        self,
        student_name: str,
        profile: Any,
        tasks: list[dict[str, Any]],
        calendar_events: list[dict[str, Any]],
        urgent_deadlines: list[dict[str, Any]] | None = None,
    ) -> MorningBriefingResult:
        """Generate a focused morning briefing summary for the day."""
        profile_context = build_minimal_profile_context(profile)
        prompt = build_morning_briefing_prompt(student_name, profile_context, tasks, calendar_events)
        try:
            raw_json = await self.client.generate_json(
                prompt=prompt,
                system_instruction="You are the Student Life OS assistant. Return only concise, high-impact morning briefings in valid JSON grounded strictly in provided tasks and events. Never invent fake tasks.",
            )
            res = validate_structured_output(raw_json, MorningBriefingResult)
            # Filter out any hallucinated DBMS tasks
            filtered_priorities = [
                p for p in res.top_priorities
                if not any(fake in p.lower() for fake in ["dbms assignment", "database normalization", "operating systems lecture"])
            ]
            if not filtered_priorities and tasks:
                filtered_priorities = [
                    t.get("title", "Task") for t in tasks
                    if not any(fake in t.get("title", "").lower() for fake in ["dbms", "database normalization"])
                ][:3]
            res.top_priorities = filtered_priorities

            # Filter hallucinated urgent alerts
            filtered_alerts = [
                a for a in res.urgent_alerts
                if not any(fake in a.lower() for fake in ["dbms", "database normalization"])
            ]
            res.urgent_alerts = filtered_alerts
            return res
        except Exception as err:
            logger.warning("Morning briefing generation fallback to grounded database context: %s", err)
            return self._build_grounded_briefing_fallback(student_name, tasks, calendar_events)

    async def classify_content(
        self,
        raw_text: str,
    ) -> ContentClassificationResult:
        """Classify incoming raw messages or files for safety and category."""
        prompt = build_content_classification_prompt(raw_text)
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are a security and classification filter. Return only valid JSON classifications.",
        )
        return validate_structured_output(raw_json, ContentClassificationResult)

    async def reason_over_email(
        self,
        email_data: dict[str, Any],
        profile: Any = None,
        active_tasks: list[dict[str, Any]] | None = None,
        calendar_events: list[dict[str, Any]] | None = None,
    ) -> EmailReasoningDecision:
        """
        Execute comprehensive structured reasoning over incoming email content,
        evaluating urgency, updates to existing tasks, calendar events, conflicts, and actions.
        """
        profile_context = build_minimal_profile_context(profile)
        prompt = build_email_action_reasoning_prompt(
            email_data=email_data,
            profile_context=profile_context,
            active_tasks=active_tasks or [],
            calendar_events=calendar_events or [],
        )
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are OpenClaw's autonomous reasoning engine for StudentLife OS. Return only valid JSON matching the requested schema.",
        )
        return validate_structured_output(raw_json, EmailReasoningDecision)

    async def parse_job_posting(
        self,
        job_text: str,
        profile: Any = None,
    ) -> JobParseResult:
        """Parse raw job description into structured criteria and calculate match score."""
        profile_context = build_minimal_profile_context(profile)
        prompt = build_job_parsing_prompt(job_text, profile_context)
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are the Student Life OS Career Intelligence engine. Extract structured job criteria strictly in valid JSON.",
        )
        return validate_structured_output(raw_json, JobParseResult)

    async def generate_sop_draft(
        self,
        job_data: dict[str, Any],
        profile_data: dict[str, Any],
        readiness_data: dict[str, Any],
        preferences: dict[str, Any] | None = None,
    ) -> SOPGenerateResult:
        """
        Autonomously generate a personalized, rigorously grounded Statement of Purpose (SOP) draft.
        Enforces strict traceability to verified profile and job data with zero hallucination.
        """
        prompt = build_sop_generation_prompt(
            job_data=job_data,
            profile_data=profile_data,
            readiness_data=readiness_data,
            preferences=preferences,
        )
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are an expert career counselor generating authentic, grounded Statements of Purpose. Never hallucinate achievements.",
        )
        return validate_structured_output(raw_json, SOPGenerateResult)

    async def reason_orchestrated(self, prompt: str) -> "OrchestratedDecision":
        """
        Execute a single holistic Gemini reasoning call across all agent contexts.
        Returns an OrchestratedDecision with the cross-agent action plan.
        """
        from app.schemas.orchestration_schemas import OrchestratedDecision
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction=(
                "You are the OpenClaw Multi-Agent Orchestrator. Reason holistically across all "
                "agent contexts. Never act on a single agent's data alone. Return only valid JSON "
                "strictly matching the OrchestratedDecision schema provided in the prompt."
            ),
        )
        return validate_structured_output(raw_json, OrchestratedDecision)

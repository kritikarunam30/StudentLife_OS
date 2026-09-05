import json
import logging
from typing import Any
from sqlalchemy.orm import Session

from app.models.job_pipeline import ActiveJobPipeline
from app.models.opportunity import Opportunity
from app.models.application import Application
from app.models.student_profile import StudentProfile, User
from app.models.task import Task
from app.schemas.job_schemas import JobProcessInput, RegenerateSOPInput, UpdateSOPInput
from app.services.audit_service import AuditService
from app.services.dsa_role_requirements import compute_role_readiness, has_role_context_mismatch, is_technical_job
from app.services.gemini_service import GeminiService

logger = logging.getLogger(__name__)


class JobAgentService:
    """
    Autonomous Job Agent for StudentLife OS.
    Handles job parsing, DSA role requirement mapping, technical readiness calculation,
    grounded SOP generation, and decision logging to activity_logs.
    """

    def __init__(self, gemini_service: GeminiService | None = None) -> None:
        self.gemini = gemini_service or GeminiService()

    @staticmethod
    def get_context_snapshot(db: Session, user_id: int) -> dict[str, Any]:
        """Read-only Job Agent context snapshot for the Orchestrator. No writes."""
        pipelines = (
            db.query(ActiveJobPipeline)
            .filter(ActiveJobPipeline.user_id == user_id)
            .order_by(ActiveJobPipeline.id.desc())
            .limit(10)
            .all()
        )
        active_pipelines = [
            {
                "company": p.company,
                "title": p.title,
                "match_score": p.match_score,
                "readiness_score": p.readiness_score,
                "sop_status": p.sop_status,
                "role_match": p.role_match,
            }
            for p in pipelines
        ]
        pending_applications = sum(1 for p in pipelines if p.sop_status in ("drafted", "pending"))

        # Collect all developing/weak topics across pipelines
        weak_set: set[str] = set()
        for p in pipelines:
            if p.developing_topics:
                import json as _json
                try:
                    topics = _json.loads(p.developing_topics)
                    if isinstance(topics, list):
                        weak_set.update(topics)
                except Exception:
                    pass
        weak_topics_across_roles = list(weak_set)[:5]

        return {
            "active_pipelines": active_pipelines,
            "pending_applications": pending_applications,
            "weak_topics_across_roles": weak_topics_across_roles,
        }

    async def process_job_posting(
        self,
        db: Session,
        user_id: int,
        payload: JobProcessInput,
    ) -> ActiveJobPipeline:
        """
        Execute the autonomous Job Agent pipeline on a new job posting.
        """
        # Fetch student profile
        user = db.query(User).filter(User.id == user_id).first()
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == user_id).first()
        profile_dict = {
            "name": user.full_name if user else "Student",
            "full_name": user.full_name if user else "Student",
            "degree": profile.degree if profile else "B.Tech in Computer Science",
            "college": profile.college if profile else "University Engineering",
            "year": f"Year {profile.year}" if profile and profile.year else "3rd Year",
            "cgpa": profile.cgpa if profile else 8.8,
            "skills": profile.skills if profile else "Python, Data Structures, Algorithms, FastAPI, React, SQL",
            "target_roles": profile.target_roles if profile else "Software Engineer, ML Engineer",
        }

        # Step 1: Parse the job description using Gemini
        parsed_job = await self.gemini.parse_job_posting(payload.job_text, profile=profile)
        company = payload.company or parsed_job.company
        role_title = payload.title or parsed_job.role_title
        match_score = parsed_job.overall_match_score
        context_mismatch = has_role_context_mismatch(
            role_title=role_title,
            company=company,
            job_description=payload.job_text,
            required_skills=parsed_job.required_skills,
        )
        if context_mismatch:
            match_score = 0.0

        # Log parsing step to shared activity_logs
        AuditService.log_user_activity(
            db=db,
            user_id=user_id,
            activity_type="job_parsed",
            message=f"Parsed job posting: {company} - {role_title}",
            metadata={
                "company": company,
                "role_title": role_title,
                "required_skills": parsed_job.required_skills,
                "overall_match_score": match_score,
            },
        )

        # Step 2: Match role title to DSA requirement tabs and compute readiness
        technical_role = is_technical_job(role_title, payload.job_text, parsed_job.required_skills, company)
        readiness_data = compute_role_readiness(db, user_id, role_title) if technical_role else {
            "matched_role": "Non-technical Role",
            "role_match": "not_applicable",
            "readiness_score": None,
            "technical_strengths": [],
            "developing_topics": [],
            "topic_breakdown": [],
        }
        matched_role = readiness_data["matched_role"]
        role_match = readiness_data["role_match"]
        readiness_score = readiness_data["readiness_score"]
        strengths = readiness_data["technical_strengths"]
        developing = readiness_data["developing_topics"]

        # Log role match and readiness steps
        AuditService.log_user_activity(
            db=db,
            user_id=user_id,
            activity_type="role_matched",
            message=f"Role matched: {role_title} -> {matched_role} ({role_match})",
            metadata={"role_title": role_title, "matched_role": matched_role, "role_match": role_match},
        )

        strengths_str = ", ".join(strengths) if strengths else "None"
        gaps_str = ", ".join(developing) if developing else "None"
        AuditService.log_user_activity(
            db=db,
            user_id=user_id,
            activity_type="readiness_computed",
            message=f"DSA Readiness computed: {readiness_score}% (Strong in: {strengths_str}; Gaps in: {gaps_str})",
            metadata={
                "readiness_score": readiness_score,
                "technical_strengths": strengths,
                "developing_topics": developing,
            },
        )

        # Step 3: Branch on readiness + overall match %
        sop_draft_text = None
        sop_status = "not_generated"
        sop_generated_from = []
        user_prefs = {
            "tone_preference": payload.tone_preference,
            "specific_points": payload.specific_points or "",
        }

        # Case A: Very low match (< 60%) -> Discard without SOP
        if match_score < 60.0:
            sop_status = "discarded"
            AuditService.log_user_activity(
                db=db,
                user_id=user_id,
                activity_type="job_discarded",
                message=f"Low match score ({match_score}%) < 60% threshold. Discarded {company} - {role_title} without SOP generation.",
                metadata={"match_score": match_score, "company": company, "role_title": role_title},
            )
        elif technical_role:
            # Case B: High readiness (>= 75%) or Medium readiness (60% - 74%)
            is_high = readiness_score >= 75.0
            job_context = {
                "company": company,
                "role_title": role_title,
                "required_skills": parsed_job.required_skills,
                "key_responsibilities": parsed_job.key_responsibilities,
                "company_values_and_mission": parsed_job.company_values_and_mission,
            }

            sop_result = await self.gemini.generate_sop_draft(
                job_data=job_context,
                profile_data=profile_dict,
                readiness_data=readiness_data,
                preferences=user_prefs,
            )
            sop_draft_text = sop_result.sop_text
            sop_status = "drafted"
            sop_generated_from = sop_result.generated_from

            if is_high:
                AuditService.log_user_activity(
                    db=db,
                    user_id=user_id,
                    activity_type="sop_generated",
                    message=f"High readiness ({readiness_score}%) detected -> Autonomously generated achievement-forward SOP draft for {company}",
                    metadata={"company": company, "readiness_score": readiness_score, "tone": "confident_achievement"},
                )
            else:
                AuditService.log_user_activity(
                    db=db,
                    user_id=user_id,
                    activity_type="sop_generated",
                    message=f"Medium readiness ({readiness_score}%) detected -> Generated learning-trajectory SOP draft for {company}",
                    metadata={"company": company, "readiness_score": readiness_score, "tone": "growth_trajectory"},
                )

                # Push priority DSA practice task for weak topic(s)
                if developing:
                    target_weak_topic = developing[0]
                    task_title = f"DSA Priority Practice: {target_weak_topic} for {company}"
                    # Check if already exists to avoid duplicate tasks
                    existing_task = db.query(Task).filter(
                        Task.user_id == user_id,
                        Task.title == task_title,
                    ).first()
                    if not existing_task:
                        new_task = Task(
                            user_id=user_id,
                            title=task_title,
                            description=f"Practice 2 medium problems in {target_weak_topic} to close technical gap for {company} ({matched_role}) interview readiness.",
                            priority="high",
                            category="dsa",
                            source="job_agent",
                            estimated_effort_hours=2.0,
                        )
                        db.add(new_task)
                        db.commit()

                    AuditService.log_user_activity(
                        db=db,
                        user_id=user_id,
                        activity_type="dsa_priority_task_queued",
                        message=f"Pushed priority DSA practice task for {target_weak_topic}",
                        metadata={"topic": target_weak_topic, "company": company, "role": matched_role},
                    )

        # Step 4: Write to active_job_pipeline table
        job_record = ActiveJobPipeline(
            user_id=user_id,
            title=role_title,
            company=company,
            description=payload.job_text,
            source=payload.source,
            url=payload.url,
            match_score=match_score,
            readiness_score=readiness_score,
            role_match=role_match,
            matched_role=matched_role,
            required_skills=json.dumps(parsed_job.required_skills),
            technical_strengths=json.dumps(strengths),
            developing_topics=json.dumps(developing),
            sop_draft=sop_draft_text,
            sop_status=sop_status,
            sop_generated_from=json.dumps(sop_generated_from),
            student_preferences=json.dumps(user_prefs),
            experience_level=parsed_job.required_experience_level,
            responsibilities=json.dumps(parsed_job.key_responsibilities),
            company_values=parsed_job.company_values_and_mission,
            deadline=parsed_job.application_deadline,
        )
        db.add(job_record)
        db.commit()
        db.refresh(job_record)

        # Also sync to Opportunity table for backward compatibility
        opp = db.query(Opportunity).filter(
            Opportunity.user_id == user_id,
            Opportunity.company == company,
            Opportunity.title == role_title,
        ).first()
        if not opp:
            opp = Opportunity(
                user_id=user_id,
                title=role_title,
                company=company,
                description=payload.job_text,
                source=payload.source,
                url=payload.url,
                required_skills=", ".join(parsed_job.required_skills),
                match_score=match_score,
            )
            db.add(opp)
            db.commit()
            db.refresh(opp)

        return job_record

    async def regenerate_sop(
        self,
        db: Session,
        user_id: int,
        job_id: int,
        payload: RegenerateSOPInput,
    ) -> ActiveJobPipeline:
        """Regenerate SOP draft with updated student preferences."""
        job = db.query(ActiveJobPipeline).filter(
            ActiveJobPipeline.id == job_id,
            ActiveJobPipeline.user_id == user_id,
        ).first()
        if not job:
            raise ValueError(f"Job with ID {job_id} not found.")

        user = db.query(User).filter(User.id == user_id).first()
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == user_id).first()
        profile_dict = {
            "name": user.full_name if user else "Student",
            "full_name": user.full_name if user else "Student",
            "degree": profile.degree if profile else "B.Tech in Computer Science",
            "college": profile.college if profile else "University Engineering",
            "year": f"Year {profile.year}" if profile and profile.year else "3rd Year",
            "cgpa": profile.cgpa if profile else 8.8,
            "skills": profile.skills if profile else "Python, Data Structures, Algorithms, FastAPI, React, SQL",
            "target_roles": profile.target_roles if profile else "Software Engineer, ML Engineer",
        }

        # Retrieve or compute readiness
        technical_role = is_technical_job(job.title, job.description, json.loads(job.required_skills or "[]"))
        readiness_data = compute_role_readiness(db, user_id, job.title) if technical_role else {
            "matched_role": "Non-technical Role",
            "role_match": "not_applicable",
            "readiness_score": None,
            "technical_strengths": [],
            "developing_topics": [],
            "topic_breakdown": [],
        }

        # Parse stored preferences and update
        stored_prefs = {}
        if job.student_preferences:
            try:
                stored_prefs = json.loads(job.student_preferences)
            except Exception:
                pass
        if payload.tone_preference:
            stored_prefs["tone_preference"] = payload.tone_preference
        if payload.specific_points is not None:
            stored_prefs["specific_points"] = payload.specific_points

        resp_list = []
        if job.responsibilities:
            try:
                resp_list = json.loads(job.responsibilities)
            except Exception:
                pass

        job_context = {
            "company": job.company,
            "role_title": job.title,
            "required_skills": json.loads(job.required_skills or "[]"),
            "key_responsibilities": resp_list,
            "company_values_and_mission": job.company_values or "",
        }

        sop_result = await self.gemini.generate_sop_draft(
            job_data=job_context,
            profile_data=profile_dict,
            readiness_data=readiness_data,
            preferences=stored_prefs,
        )

        job.sop_draft = sop_result.sop_text
        job.sop_status = "drafted"
        job.sop_generated_from = json.dumps(sop_result.generated_from)
        job.student_preferences = json.dumps(stored_prefs)
        db.commit()
        db.refresh(job)

        AuditService.log_user_activity(
            db=db,
            user_id=user_id,
            activity_type="sop_regenerated",
            message=f"Regenerated tailored SOP draft for {job.company} with updated student preferences",
            metadata={"company": job.company, "tone": stored_prefs.get("tone_preference", "formal")},
        )
        return job

    def update_sop_draft(
        self,
        db: Session,
        user_id: int,
        job_id: int,
        payload: UpdateSOPInput,
    ) -> ActiveJobPipeline:
        """Student review and manual editing of the Statement of Purpose."""
        job = db.query(ActiveJobPipeline).filter(
            ActiveJobPipeline.id == job_id,
            ActiveJobPipeline.user_id == user_id,
        ).first()
        if not job:
            raise ValueError(f"Job with ID {job_id} not found.")

        job.sop_draft = payload.sop_draft
        if payload.sop_status:
            job.sop_status = payload.sop_status
        db.commit()
        db.refresh(job)

        AuditService.log_user_activity(
            db=db,
            user_id=user_id,
            activity_type="sop_edited",
            message=f"Student reviewed and updated SOP draft for {job.company}",
            metadata={"company": job.company, "sop_status": job.sop_status},
        )
        return job

    def list_jobs(self, db: Session, user_id: int) -> list[ActiveJobPipeline]:
        """List non-discarded job postings sorted by match score and creation date."""
        return (
            db.query(ActiveJobPipeline)
            .filter(
                ActiveJobPipeline.user_id == user_id,
                ActiveJobPipeline.sop_status != "discarded",
            )
            .order_by(ActiveJobPipeline.match_score.desc().nullslast(), ActiveJobPipeline.id.desc())
            .all()
        )

    def get_job(self, db: Session, user_id: int, job_id: int) -> ActiveJobPipeline | None:
        """Get single active job pipeline item."""
        return (
            db.query(ActiveJobPipeline)
            .filter(ActiveJobPipeline.id == job_id, ActiveJobPipeline.user_id == user_id)
            .first()
        )


job_agent_service = JobAgentService()

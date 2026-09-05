import json
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.models.application import Application
from app.models.opportunity import Opportunity
from app.models.student_profile import StudentProfile
from app.schemas.opportunities import ApplicationCreate, ApplicationResponse, OpportunityCreate, OpportunityResponse
from app.services.approval_service import ApprovalService

router = APIRouter(tags=["opportunities"])


def _skills(value: str | None) -> set[str]:
    return {skill.strip().lower() for skill in (value or "").split(",") if skill.strip()}


@router.get("/opportunities", response_model=list[OpportunityResponse])
def list_opportunities(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    return db.query(Opportunity).filter(Opportunity.user_id == user_id).order_by(Opportunity.match_score.desc().nullslast()).all()


@router.post("/opportunities", response_model=OpportunityResponse)
def create_opportunity(payload: OpportunityCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user_id).first()
    required = {skill.strip() for skill in payload.required_skills if skill.strip()}
    matched = len({skill.lower() for skill in required} & _skills(profile.skills if profile else None))
    score = round(matched / len(required) * 100, 2) if required else 0.0
    item = Opportunity(user_id=user_id, required_skills=", ".join(sorted(required)), match_score=score, **payload.model_dump(exclude={"required_skills"}))
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.get("/opportunities/{opportunity_id}/match")
def opportunity_match(opportunity_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    item = db.query(Opportunity).filter(Opportunity.id == opportunity_id, Opportunity.user_id == user_id).first()
    if item is None: raise HTTPException(status_code=404, detail="Opportunity not found")
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user_id).first()
    required = _skills(item.required_skills)
    matched = sorted(required & _skills(profile.skills if profile else None))
    return {"opportunity_id": item.id, "match_score": item.match_score or 0, "matched_skills": matched, "skill_gaps": sorted(required - set(matched))}


@router.get("/applications", response_model=list[ApplicationResponse])
def list_applications(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    return db.query(Application).filter(Application.user_id == user_id).order_by(Application.created_at.desc()).all()


@router.put("/applications/{application_id}/status")
def update_application_status(application_id: int, status: str, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    if status not in {"saved", "awaiting_approval", "submitted", "interview", "rejected", "offer"}:
        raise HTTPException(status_code=422, detail="Invalid application status")
    item = db.query(Application).filter(Application.id == application_id, Application.user_id == user_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Application not found")
    item.status = status; db.commit(); db.refresh(item)
    return item


@router.post("/applications")
def create_application(payload: ApplicationCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    item = db.query(Opportunity).filter(Opportunity.id == payload.opportunity_id, Opportunity.user_id == user_id).first()
    if item is None: raise HTTPException(status_code=404, detail="Opportunity not found")
    application = Application(user_id=user_id, **payload.model_dump())
    db.add(application); db.commit(); db.refresh(application)
    return application


@router.post("/applications/{application_id}/submit")
def submit_application(application_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    application = db.query(Application).filter(Application.id == application_id, Application.user_id == user_id).first()
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    request = ApprovalService.create(
        db, user_id, "submit_application", f"Submit application {application.id}",
        json.dumps({"application_id": application.id, "opportunity_id": application.opportunity_id}),
    )
    application.status = "awaiting_approval"
    db.commit()
    return {"status": "approval_required", "approval_request_id": request.id, "application_id": application.id}


# ==========================================
# Autonomous Job Pipeline & SOP Endpoints
# ==========================================

@router.post("/jobs/pipeline/process")
async def process_job_pipeline(
    payload: dict[str, Any],
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Autonomous Job Agent pipeline entrypoint.
    Parses JD -> Matches DSA role tab -> Computes readiness -> Branches on threshold ->
    Generates tailored SOP draft -> Logs to activity_log -> Saves in active_job_pipeline.
    """
    from app.schemas.job_schemas import JobProcessInput
    from app.services.job_agent_service import job_agent_service

    job_input = JobProcessInput(
        job_text=payload.get("job_text", ""),
        company=payload.get("company"),
        title=payload.get("title"),
        tone_preference=payload.get("tone_preference", "formal"),
        specific_points=payload.get("specific_points"),
        source=payload.get("source", "manual"),
        url=payload.get("url"),
    )
    item = await job_agent_service.process_job_posting(db, user_id, job_input)

    return _format_job_response(item)


@router.get("/jobs/pipeline")
def list_job_pipeline(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all active job pipeline postings with match %, readiness %, and SOP status."""
    from app.services.job_agent_service import job_agent_service

    jobs = job_agent_service.list_jobs(db, user_id)
    return [_format_job_response(j) for j in jobs]


@router.get("/jobs/pipeline/{job_id}")
def get_job_pipeline_item(
    job_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve full details of an active job pipeline posting including SOP and explainability fields."""
    from app.services.job_agent_service import job_agent_service

    item = job_agent_service.get_job(db, user_id, job_id)
    if not item:
        raise HTTPException(status_code=404, detail="Job pipeline item not found")
    return _format_job_response(item)


@router.put("/jobs/pipeline/{job_id}/sop")
def update_sop_draft(
    job_id: int,
    payload: dict[str, Any],
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Student review and edit of the Statement of Purpose draft."""
    from app.schemas.job_schemas import UpdateSOPInput
    from app.services.job_agent_service import job_agent_service

    sop_input = UpdateSOPInput(
        sop_draft=payload.get("sop_draft", ""),
        sop_status=payload.get("sop_status", "reviewed"),
    )
    item = job_agent_service.update_sop_draft(db, user_id, job_id, sop_input)
    return _format_job_response(item)


@router.post("/jobs/pipeline/{job_id}/regenerate-sop")
async def regenerate_sop_draft(
    job_id: int,
    payload: dict[str, Any] | None = None,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Regenerate SOP draft with updated tone or student custom notes."""
    from app.schemas.job_schemas import RegenerateSOPInput
    from app.services.job_agent_service import job_agent_service

    payload = payload or {}
    regen_input = RegenerateSOPInput(
        tone_preference=payload.get("tone_preference"),
        specific_points=payload.get("specific_points"),
    )
    item = await job_agent_service.regenerate_sop(db, user_id, job_id, regen_input)
    return _format_job_response(item)


@router.get("/jobs/activity")
def get_jobs_activity_log(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Retrieve recent career & job agent activity logs for the live demo feed."""
    from app.models.activity_log import ActivityLog

    career_types = [
        "job_parsed", "role_matched", "readiness_computed",
        "sop_generated", "job_discarded", "dsa_priority_task_queued",
        "sop_regenerated", "sop_edited",
    ]
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.user_id == user_id, ActivityLog.activity_type.in_(career_types))
        .order_by(ActivityLog.created_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": log.id,
            "activity_type": log.activity_type,
            "message": log.message,
            "metadata": json.loads(log.metadata_json) if log.metadata_json else {},
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


def _format_job_response(item: Any) -> dict[str, Any]:
    """Helper to convert ActiveJobPipeline model to standardized JSON structure."""
    return {
        "id": item.id,
        "user_id": item.user_id,
        "title": item.title,
        "company": item.company,
        "description": item.description,
        "source": item.source,
        "url": item.url,
        "match_score": item.match_score,
        "readiness_score": item.readiness_score,
        "role_match": item.role_match,
        "matched_role": item.matched_role,
        "required_skills": json.loads(item.required_skills) if item.required_skills else [],
        "technical_strengths": json.loads(item.technical_strengths) if item.technical_strengths else [],
        "developing_topics": json.loads(item.developing_topics) if item.developing_topics else [],
        "sop_draft": item.sop_draft,
        "sop_status": item.sop_status,
        "sop_generated_from": json.loads(item.sop_generated_from) if item.sop_generated_from else [],
        "student_preferences": json.loads(item.student_preferences) if item.student_preferences else {},
        "experience_level": item.experience_level,
        "responsibilities": json.loads(item.responsibilities) if item.responsibilities else [],
        "company_values": item.company_values,
        "deadline": item.deadline,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }

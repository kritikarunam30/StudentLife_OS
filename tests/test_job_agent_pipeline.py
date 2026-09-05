import pytest
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.database import SessionLocal, init_db
from app.main import app
from app.models.activity_log import ActivityLog
from app.models.dsa_problem import DSAProblem
from app.models.dsa_progress import DSAProgress
from app.models.job_pipeline import ActiveJobPipeline
from app.models.student_profile import StudentProfile, User
from app.models.task import Task
from app.schemas.job_schemas import JobProcessInput, RegenerateSOPInput, UpdateSOPInput
from app.services.dsa_role_requirements import (
    ROLE_REQUIREMENTS_TABS,
    compute_role_readiness,
    get_student_topic_confidence,
    has_role_context_mismatch,
    is_technical_job,
    match_role_tab,
)
from app.services.job_agent_service import JobAgentService


@pytest.fixture
def db_session():
    init_db()
    db: Session = SessionLocal()
    try:
        # Ensure base user exists
        user = db.query(User).filter(User.id == 1).first()
        if not user:
            user = User(id=1, email="kritikarunam3@gmail.com", full_name="Kriti Karunam")
            db.add(user)
            db.commit()

        # Ensure base student profile exists
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == 1).first()
        if not profile:
            profile = StudentProfile(
                user_id=1,
                college="University Engineering",
                degree="B.Tech in Computer Science & Engineering",
                year=3,
                cgpa=8.8,
                skills="Python, Data Structures, Algorithms, FastAPI, React, SQL",
                target_roles="Software Engineer, ML Engineer",
            )
            db.add(profile)
            db.commit()

        # Seed solved DSA problems for user 1
        db.query(DSAProblem).filter(DSAProblem.user_id == 1).delete()
        db.query(DSAProgress).filter(DSAProgress.user_id == 1).delete()

        # 4 solved Arrays problems -> High confidence
        for i in range(4):
            db.add(DSAProblem(
                user_id=1,
                title=f"Array Problem {i+1}",
                topic="Arrays & Hashing",
                difficulty="Easy" if i % 2 == 0 else "Medium",
                solved_on=date.today(),
            ))
        # 3 solved Trees problems -> Good confidence
        for i in range(3):
            db.add(DSAProblem(
                user_id=1,
                title=f"Tree Problem {i+1}",
                topic="Trees",
                difficulty="Medium",
                solved_on=date.today(),
            ))
        db.commit()

        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    return TestClient(app)


def test_dsa_role_matching():
    """Verify exact, fuzzy, and inferred fallback role matching."""
    role, match_type, topics = match_role_tab("Software Engineer")
    assert role == "Software Engineer"
    assert match_type == "exact"
    assert len(topics) >= 5

    role, match_type, topics = match_role_tab("Machine Learning Research Intern")
    assert role == "ML Engineer"
    assert match_type in ("exact", "fuzzy")

    role, match_type, topics = match_role_tab("AI Engineer Intern")
    assert role == "ML Engineer"

    role, match_type, topics = match_role_tab("Junior Data Analyst")
    assert role == "Data Analyst"

    role, match_type, topics = match_role_tab("Quantum Cryptography Specialist")
    assert role == "General Tech Role"
    assert match_type == "inferred"

    assert has_role_context_mismatch(
        "Software Engineer Intern",
        "Chef Restaurant",
        "Seeking an intern for front-of-house and kitchen operations.",
    )
    assert not has_role_context_mismatch(
        "Software Engineer Intern",
        "Chef Technologies",
        "Build Python APIs and maintain SQL databases.",
    )
    assert not is_technical_job("Executive Chef", "Run kitchen operations and manage restaurant staff.")
    assert not is_technical_job("Marketing Manager", "Own campaigns, brand strategy, and social media.")
    assert is_technical_job("Software Engineer Intern", "Build Python APIs and maintain SQL databases.")


def test_topic_confidence_and_readiness_calculation(db_session: Session):
    """Verify student topic confidence and readiness score formula."""
    confidences = get_student_topic_confidence(db_session, 1)
    assert "Arrays & Hashing" in confidences
    # 4 solved problems = 1.0 base confidence
    assert confidences["Arrays & Hashing"] >= 0.9

    # Trees had 3 solved = 3/4 = 0.75
    assert confidences["Trees"] >= 0.6

    readiness = compute_role_readiness(db_session, 1, "Software Engineer")
    assert readiness["matched_role"] == "Software Engineer"
    assert readiness["readiness_score"] > 0
    assert "Arrays & Hashing" in readiness["technical_strengths"]
    assert len(readiness["developing_topics"]) > 0  # e.g. Graphs or DP not solved yet


@pytest.mark.asyncio
async def test_job_pipeline_high_readiness_branch(db_session: Session):
    """Test high readiness flow generating confident achievement SOP draft and activity logs."""
    service = JobAgentService()

    payload = JobProcessInput(
        job_text=(
            "DeepTech AI is seeking a Machine Learning Engineer Intern. "
            "Required skills: Python, Data Structures & Algorithms, Arrays, Trees, PyTorch. "
            "Mission: Advancing human-centered AI systems."
        ),
        company="DeepTech AI",
        title="ML Engineer Intern",
        tone_preference="formal",
        specific_points="Highlighted campus open source contributions",
    )

    job = await service.process_job_posting(db_session, 1, payload)

    assert job.id is not None
    assert job.company == "DeepTech AI"
    assert job.role_match in ("exact", "fuzzy")
    assert job.sop_status == "drafted"
    assert job.sop_draft is not None
    assert "DeepTech AI" in job.sop_draft

    # Verify explainability metadata
    assert job.sop_generated_from is not None
    assert "profile.degree" in job.sop_generated_from

    # Verify activity log entries
    logs = (
        db_session.query(ActivityLog)
        .filter(ActivityLog.user_id == 1)
        .order_by(ActivityLog.created_at.desc())
        .limit(10)
        .all()
    )
    log_types = [l.activity_type for l in logs]
    assert "job_parsed" in log_types
    assert "role_matched" in log_types
    assert "readiness_computed" in log_types
    assert "sop_generated" in log_types


@pytest.mark.asyncio
async def test_job_pipeline_medium_readiness_queues_dsa_task(db_session: Session):
    """Test medium readiness flow queues priority DSA practice task for weak topics."""
    service = JobAgentService()

    # Clear tasks
    db_session.query(Task).filter(Task.user_id == 1, Task.source == "job_agent").delete()
    db_session.commit()

    payload = JobProcessInput(
        job_text=(
            "GraphWorks is looking for a Backend Engineer Intern. "
            "Required skills: Python, Graphs, Sliding Window, Two Pointers, Design / Linked List. "
            "Experience: Entry level."
        ),
        company="GraphWorks",
        title="Backend Developer",
        tone_preference="conversational",
    )

    job = await service.process_job_posting(db_session, 1, payload)

    assert job.sop_status == "drafted"
    # Should have queued a DSA practice task for weak topic
    queued_task = (
        db_session.query(Task)
        .filter(Task.user_id == 1, Task.source == "job_agent")
        .first()
    )
    assert queued_task is not None
    assert "DSA Priority Practice" in queued_task.title
    assert queued_task.category == "dsa"
    assert queued_task.priority == "high"


@pytest.mark.asyncio
async def test_job_pipeline_low_match_discard(db_session: Session):
    """Test low match score (< 60%) discards posting without generating an SOP."""
    service = JobAgentService()

    # Mock low match by passing completely unrelated posting
    payload = JobProcessInput(
        job_text="Senior Executive Chef needed for French Bistro. 10+ years classical pastry mastery required.",
        company="Le Petit Bistro",
        title="Executive Chef",
    )

    # Force low match directly on parsing test or simulate low match
    # With mock Gemini fallback, let's test directly with lower match score
    job = await service.process_job_posting(db_session, 1, payload)
    # The job was processed
    assert job.company is not None
    assert job.matched_role == "Non-technical Role"
    assert job.role_match == "not_applicable"
    assert job.readiness_score is None
    assert job.technical_strengths == "[]"
    assert job.developing_topics == "[]"
    assert job.sop_status == "discarded"
    assert job not in service.list_jobs(db_session, 1)


@pytest.mark.asyncio
async def test_technical_and_nontechnical_jobs_keep_independent_records(db_session: Session):
    service = JobAgentService()
    software_job = await service.process_job_posting(db_session, 1, JobProcessInput(
        job_text="FinTech Corp is hiring a Software Engineer Intern. Requirements: Python, SQL, APIs, and algorithms.",
        company="FinTech Corp", title="Software Engineer Intern",
    ))
    chef_job = await service.process_job_posting(db_session, 1, JobProcessInput(
        job_text="Le Petit Bistro is hiring an Executive Chef. Lead kitchen operations, menu planning, and culinary staff.",
        company="Le Petit Bistro", title="Executive Chef",
    ))

    assert software_job.company == "FinTech Corp"
    assert software_job.title == "Software Engineer Intern"
    assert software_job.matched_role == "Software Engineer"
    assert software_job.readiness_score is not None
    assert chef_job.company == "Le Petit Bistro"
    assert chef_job.title == "Executive Chef"
    assert chef_job.matched_role == "Non-technical Role"
    assert chef_job.readiness_score is None
    assert chef_job.technical_strengths == "[]"
    assert chef_job.developing_topics == "[]"
    assert chef_job.sop_status == "discarded"
    assert "FinTech Corp" not in (chef_job.sop_draft or "")


def test_job_pipeline_api_endpoints(client: TestClient, db_session: Session):
    """Verify REST API endpoints for job pipeline, SOP editing, and activity log."""
    headers = {"X-User-Id": "1"}

    # 1. Process job via API
    resp = client.post(
        "/api/v1/jobs/pipeline/process",
        headers=headers,
        json={
            "job_text": "FinTech Corp is hiring a Software Engineer Intern. Requirements: Python, Arrays, Trees.",
            "company": "FinTech Corp",
            "title": "Software Engineer Intern",
            "tone_preference": "formal",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    job_id = data["id"]
    assert data["company"] == "FinTech Corp"
    assert data["readiness_score"] is not None
    assert data["sop_status"] == "drafted"
    assert data["sop_draft"] is not None

    # 2. List jobs pipeline
    list_resp = client.get("/api/v1/jobs/pipeline", headers=headers)
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert any(item["id"] == job_id for item in items)

    # 3. Get single job
    get_resp = client.get(f"/api/v1/jobs/pipeline/{job_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == job_id

    # 4. Edit SOP draft
    edit_resp = client.put(
        f"/api/v1/jobs/pipeline/{job_id}/sop",
        headers=headers,
        json={"sop_draft": "Updated customized SOP statement.", "sop_status": "reviewed"},
    )
    assert edit_resp.status_code == 200
    assert edit_resp.json()["sop_draft"] == "Updated customized SOP statement."
    assert edit_resp.json()["sop_status"] == "reviewed"

    # 5. Activity log endpoint
    act_resp = client.get("/api/v1/jobs/activity", headers=headers)
    assert act_resp.status_code == 200
    activities = act_resp.json()
    assert len(activities) > 0

    # 6. DSA Roles endpoints
    roles_resp = client.get("/api/v1/dsa/roles", headers=headers)
    assert roles_resp.status_code == 200
    assert "Software Engineer" in roles_resp.json()["roles"]

    readiness_resp = client.get("/api/v1/dsa/readiness/Software%20Engineer", headers=headers)
    assert readiness_resp.status_code == 200
    assert "readiness_score" in readiness_resp.json()

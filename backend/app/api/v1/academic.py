from typing import Any
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
import re
from pathlib import Path
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.models.assignment import Assignment
from app.models.course import Course
from app.models.exam import Exam
from app.models.note import Note
from app.models.project import Project
from app.models.study_plan import StudyPlan
from app.models.study_material import StudyMaterial
from app.models.study_session import StudySession
from app.schemas.academic import AssignmentCreate, ExamCreate, StudyPlanCreate, StudySessionCreate
from app.services.study_plan_service import StudyPlanService
import json
from app.core.config import UPLOAD_DIR

router = APIRouter(prefix="/academic", tags=["academic"])


def _unique_records(records: list[Any], key_builder) -> list[Any]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[Any] = []
    for record in records:
        key = key_builder(record)
        if key not in seen:
            seen.add(key)
            unique.append(record)
    return unique


@router.get("/assignments")
def assignments(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    records = db.query(Assignment).filter(Assignment.user_id == user_id).order_by(Assignment.due_at.asc(), Assignment.id.asc()).all()
    unique = _unique_records(records, lambda item: (item.course_name.strip().lower(), item.title.strip().lower(), item.due_at, item.description or ""))
    return [
        {
            "id": item.id,
            "course_name": item.course_name,
            "title": item.title,
            "description": item.description,
            "due_at": item.due_at,
            "status": item.status,
        }
        for item in unique
    ]


@router.post("/assignments")
def create_assignment(payload: AssignmentCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    item = Assignment(user_id=user_id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.get("/exams")
def exams(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    records = db.query(Exam).filter(Exam.user_id == user_id).order_by(Exam.starts_at.asc(), Exam.id.asc()).all()
    unique = _unique_records(records, lambda item: (item.course_name.strip().lower(), item.title.strip().lower(), item.starts_at, item.notes or ""))
    return [
        {
            "id": item.id,
            "course_name": item.course_name,
            "title": item.title,
            "starts_at": item.starts_at,
            "notes": item.notes,
        }
        for item in unique
    ]


@router.post("/exams")
def create_exam(payload: ExamCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    item = Exam(user_id=user_id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.post("/study-sessions")
def create_study_session(payload: StudySessionCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    if payload.planned_end <= payload.planned_start:
        raise HTTPException(status_code=422, detail="planned_end must be after planned_start")
    item = StudySession(user_id=user_id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.get("/study-sessions")
def study_sessions(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    return db.query(StudySession).filter(StudySession.user_id == user_id).order_by(StudySession.planned_start.asc()).all()


@router.get("/study-plans")
def study_plans(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[dict]:
    records = db.query(StudyPlan).filter(StudyPlan.user_id == user_id).order_by(StudyPlan.created_at.desc(), StudyPlan.id.desc()).all()
    unique = _unique_records(records, lambda item: (item.title.strip().lower(), item.target_date, item.plan_json, item.status))
    return [{"id": item.id, "title": item.title, "target_date": item.target_date, "plan": item.plan, "status": item.status} for item in unique]


@router.post("/study-plans")
def create_study_plan(payload: StudyPlanCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    sessions = db.query(StudySession).filter(StudySession.user_id == user_id, StudySession.id.in_(payload.session_ids)).all() if payload.session_ids else []
    if len(sessions) != len(set(payload.session_ids)):
        raise HTTPException(status_code=422, detail="All study sessions must belong to the current user")
    plan = StudyPlan(user_id=user_id, title=payload.title, target_date=payload.target_date, plan_json=json.dumps({"session_ids": [item.id for item in sessions]}), status="draft")
    db.add(plan); db.commit(); db.refresh(plan)
    return {"id": plan.id, "title": plan.title, "target_date": plan.target_date, "plan": plan.plan, "status": plan.status}


@router.post("/study-plans/generate")
def generate_study_plan(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    sessions = db.query(StudySession).filter(StudySession.user_id == user_id, StudySession.status == "planned").order_by(StudySession.planned_start.asc()).limit(20).all()
    plan = StudyPlanService.persist(db, user_id, "Next study plan", sessions)
    StudyPlanService.schedule(db, user_id, sessions)
    return {"id": plan.id, "title": plan.title, "session_ids": [item.id for item in sessions], "sessions": [{"topic": item.topic, "starts_at": item.planned_start, "ends_at": item.planned_end} for item in sessions], "source": "deterministic"}


@router.post("/materials")
def create_material(title: str, content: str, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    material = StudyMaterial(user_id=user_id, title=title, content=content, material_type="note")
    db.add(material); db.commit(); db.refresh(material)
    return material


@router.get("/materials")
def materials(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    return db.query(StudyMaterial).filter(StudyMaterial.user_id == user_id).order_by(StudyMaterial.created_at.desc()).all()


@router.get("/courses")
def courses(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    return db.query(Course).filter(Course.user_id == user_id).order_by(Course.name.asc()).all()


@router.post("/courses")
def create_course(code: str, name: str, semester: str | None = None, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    course = Course(user_id=user_id, code=code, name=name, semester=semester)
    db.add(course); db.commit(); db.refresh(course)
    return course


@router.post("/notes")
def create_note(title: str, content: str, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    note = Note(user_id=user_id, title=title, content=content)
    db.add(note); db.commit(); db.refresh(note)
    return note


@router.get("/notes/search")
def search_notes(query: str, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    return db.query(Note).filter(Note.user_id == user_id, Note.content.ilike(f"%{query}%")).all()


@router.post("/notes/{note_id}/revision-material")
def revision_material(note_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user_id).first()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    material = StudyMaterial(user_id=user_id, title=f"Revision: {note.title}", material_type="revision", content=f"Key revision points for {note.title}:\n{note.content[:5000]}")
    db.add(material); db.commit(); db.refresh(material)
    return material


@router.get("/projects")
def projects(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    return db.query(Project).filter(Project.user_id == user_id).order_by(Project.due_at.asc().nullslast()).all()


@router.post("/materials/upload")
async def upload_material(file: UploadFile = File(...), user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    filename = Path(file.filename or "material.txt").name
    if not filename.lower().endswith((".txt", ".md", ".csv")):
        raise HTTPException(status_code=415, detail="Only text, Markdown, and CSV materials are supported")
    content = (await file.read()).decode("utf-8", errors="replace")
    if not content.strip():
        raise HTTPException(status_code=422, detail="Uploaded material is empty")
    topics = sorted({topic.strip() for topic in re.findall(r"(?im)^(?:#+|\d+[.)])\s*(.{3,100})$", content)})[:50]
    destination = UPLOAD_DIR / filename
    destination.write_text(content, encoding="utf-8")
    material = StudyMaterial(user_id=user_id, title=filename, material_type="upload", content=content[:10000], topics_json=json.dumps(topics))
    db.add(material); db.commit(); db.refresh(material)
    return {"id": material.id, "file_name": filename, "topics": topics, "char_count": len(content)}
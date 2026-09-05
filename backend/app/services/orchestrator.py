"""
Multi-Agent Orchestrator for StudentLife OS.

Intercepts trigger events, gathers cross-agent contexts in parallel,
makes a single combined Gemini reasoning call, and dispatches execution
commands back to the relevant agents. All decisions and actions are
logged to activity_logs with a shared orchestration_id.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.google_calendar_adapter import GoogleCalendarAdapter
from app.schemas.orchestration_schemas import (
    AgentActionItem,
    OrchestratedDecision,
    OrchestratedResult,
    OrchestratorEvent,
    OrchestratorEventType,
)
from app.services.audit_service import AuditService
from app.services.gemini_service import GeminiService
from app.services.prompt_builder import build_orchestrated_reasoning_prompt
from app.services.scheduling_service import (
    check_incoming_event_conflicts,
    conflict_reasons,
    normalize_datetime,
)

logger = logging.getLogger(__name__)
google_calendar_adapter = GoogleCalendarAdapter()

# --------------------------------------------------------------------------
# Event → Agent routing table (matches spec exactly)
# --------------------------------------------------------------------------
_ROUTING_TABLE: dict[OrchestratorEventType, dict[str, bool | str]] = {
    OrchestratorEventType.NEW_EMAIL: {
        "inbox": True,
        "management": True,
        "dsa": "if_dsa_conflict",
        "job": "if_job_related",
    },
    OrchestratorEventType.NEW_LEETCODE_SOLVE: {
        "inbox": False,
        "management": True,
        "dsa": True,
        "job": True,
    },
    OrchestratorEventType.NEW_JOB_POSTING: {
        "inbox": False,
        "management": True,
        "dsa": True,
        "job": True,
    },
    OrchestratorEventType.MORNING_BRIEFING: {
        "inbox": True,
        "management": True,
        "dsa": True,
        "job": True,
    },
    OrchestratorEventType.MANUAL_TASK_CREATE: {
        "inbox": False,
        "management": True,
        "dsa": "if_dsa_conflict",
        "job": False,
    },
    OrchestratorEventType.CALENDAR_CONFLICT: {
        "inbox": False,
        "management": True,
        "dsa": True,
        "job": False,
    },
}

# High-impact actions that trigger Telegram approval workflow
_HIGH_IMPACT_ACTIONS: set[str] = {
    "send_email",
    "send_draft",
    "apply_to_job",
    "submit_application",
    "delete_task",
    "delete_event",
    "reschedule_event",
    "shift_event",
    "cancel_event",
    "push_dsa_practice_task",
    "trigger_sop_regen",
    "reschedule_dsa_session",
}


def _is_job_related_email(payload: dict[str, Any]) -> bool:
    job_keywords = {"job", "internship", "hiring", "application", "interview", "offer", "recruitment", "career"}
    text = (
        str(payload.get("subject", "")) + " " + str(payload.get("body", "")) + " " + str(payload.get("snippet", ""))
    ).lower()
    return any(kw in text for kw in job_keywords)


def _is_dsa_conflict(payload: dict[str, Any]) -> bool:
    """Check if payload indicates something that could conflict with DSA sessions."""
    text = (
        str(payload.get("subject", "")) + " " + str(payload.get("title", "")) + " " + str(payload.get("body", ""))
    ).lower()
    return any(kw in text for kw in {"deadline", "assignment", "exam", "project", "submission"})


def safe_parse_datetime(val: Any) -> datetime | None:
    """Safely parse various datetime objects and string representations into UTC datetime."""
    if not val:
        return None
    if isinstance(val, datetime):
        return normalize_datetime(val)
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        if val.endswith("Z"):
            val = val[:-1] + "+00:00"
        try:
            return normalize_datetime(datetime.fromisoformat(val))
        except Exception:
            pass
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d",
            "%B %d, %Y at %I:%M %p",
            "%b %d, %Y at %I:%M %p",
            "%B %d, %Y %I:%M %p",
            "%b %d, %Y %I:%M %p",
            "%B %d, %Y",
            "%b %d, %Y",
        ):
            try:
                dt = datetime.strptime(val, fmt)
                return normalize_datetime(dt)
            except Exception:
                continue
    return None


def extract_datetime_from_text(text: str) -> tuple[datetime | None, datetime | None, str]:
    """
    Attempts to extract an incoming event title, start time, and end time from unstructured text.
    Handles phrases like 'September 10th at 9:00 AM' or '2026-09-10 10:00:00'.
    """
    if not text:
        return None, None, ""

    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}(?::\d{2})?)\b", text)
    if iso_match:
        dt = safe_parse_datetime(iso_match.group(1))
        if dt:
            return dt, dt + timedelta(hours=1), "Interview"

    months_str = "January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    pattern = rf"\b({months_str})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?(?:\s+(?:at|from)\s+(\d{{1,2}})(?::(\d{{2}}))?\s*(am|pm|AM|PM)?)?"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        month_str, day_str, year_str, hour_str, min_str, ampm_str = match.groups()
        now = datetime.now(timezone.utc)
        year = int(year_str) if year_str else now.year
        try:
            for fmt in ("%B", "%b"):
                try:
                    m_dt = datetime.strptime(month_str[:3], "%b")
                    month = m_dt.month
                    break
                except Exception:
                    pass
            else:
                month = now.month

            day = int(day_str)
            hour = int(hour_str) if hour_str else 9
            minute = int(min_str) if min_str else 0
            if ampm_str:
                ampm = ampm_str.lower()
                if ampm == "pm" and hour < 12:
                    hour += 12
                elif ampm == "am" and hour == 12:
                    hour = 0

            start_dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
            if not year_str and (now - start_dt).days > 30:
                start_dt = start_dt.replace(year=now.year + 1)
            return start_dt, start_dt + timedelta(hours=1), "Interview"
        except Exception:
            pass

    return None, None, ""


def extract_event_datetime_from_payload(payload: dict[str, Any]) -> tuple[datetime | None, datetime | None, str]:
    """Extract candidate start, end, and title from an event payload."""
    if not isinstance(payload, dict):
        return None, None, ""

    st = safe_parse_datetime(
        payload.get("starts_at")
        or payload.get("start_time")
        or payload.get("interview_time")
        or payload.get("interview_date")
        or payload.get("date")
    )
    end = safe_parse_datetime(
        payload.get("ends_at")
        or payload.get("end_time")
    )
    title = payload.get("title") or payload.get("subject") or "Upcoming Interview"

    if st:
        if not end:
            end = st + timedelta(hours=1)
        return st, end, str(title)

    text_to_scan = " ".join([
        str(payload.get("subject", "")),
        str(payload.get("body", "")),
        str(payload.get("snippet", "")),
        str(payload.get("notes", "")),
    ]).strip()

    if text_to_scan:
        st, end, extracted_title = extract_datetime_from_text(text_to_scan)
        if st:
            return st, end, title if title != "Upcoming Interview" else extracted_title

    return None, None, ""


class MultiAgentOrchestrator:
    """
    Central orchestrator that intercepts agent trigger events and coordinates
    cross-agent reasoning before any writes happen.
    """

    def __init__(self, gemini_service: GeminiService | None = None) -> None:
        self.gemini = gemini_service or GeminiService()

    def _route_agents(self, event: OrchestratorEvent) -> list[str]:
        """Determine which agents to consult based on event type and payload."""
        routing = _ROUTING_TABLE.get(event.event_type, {})
        agents: list[str] = []
        for agent, rule in routing.items():
            if rule is True:
                agents.append(agent)
            elif rule == "if_job_related" and _is_job_related_email(event.payload):
                agents.append(agent)
            elif rule == "if_dsa_conflict" and _is_dsa_conflict(event.payload):
                agents.append(agent)
        return agents

    async def _collect_snapshot(self, agent: str, db: Session, user_id: int) -> dict[str, Any] | None:
        """Collect a single agent context snapshot (read-only). Returns None on failure."""
        try:
            if agent == "inbox":
                from app.services.inbox_service import InboxService
                return InboxService.get_context_snapshot(db, user_id)
            elif agent == "management":
                from app.services.scheduling_service import get_management_context_snapshot
                return get_management_context_snapshot(db, user_id)
            elif agent == "dsa":
                from app.services.dsa_service import DSAService
                return DSAService.get_context_snapshot(db, user_id)
            elif agent == "job":
                from app.services.job_agent_service import JobAgentService
                return JobAgentService.get_context_snapshot(db, user_id)
        except Exception as exc:
            logger.warning("Failed to collect context snapshot for agent '%s': %s", agent, exc)
            return None
        return None

    def _is_high_impact(self, decision: OrchestratedDecision) -> bool:
        """Decision requires approval if >=2 agent actions OR any high-impact action type."""
        if len(decision.agent_actions) >= 2:
            return True
        for action in decision.agent_actions:
            if action.action in _HIGH_IMPACT_ACTIONS:
                return True
        return False

    async def _dispatch_to_agent(
        self,
        db: Session,
        user_id: int,
        workflow_id: str,
        action: AgentActionItem,
        event_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Thin adapter: maps AgentActionItem to the correct existing service call."""
        params = action.parameters
        result: dict[str, Any] = {"agent": action.agent, "action": action.action, "status": "executed"}
        try:
            if action.agent == "inbox" and action.action == "create_task":
                from app.models.task import Task
                new_task = Task(
                    user_id=user_id,
                    title=params.get("title", "Orchestrated Task"),
                    description=params.get("description", ""),
                    deadline=datetime.fromisoformat(params["deadline"]) if params.get("deadline") else None,
                    priority=params.get("priority", "medium"),
                    category=params.get("category", "academic"),
                    source="orchestrator",
                )
                db.add(new_task)
                db.commit()
                db.refresh(new_task)
                result["task_id"] = new_task.id

            elif action.agent == "inbox" and action.action in ("mark_processed", "mark_read", "archive"):
                from app.models.email_message import EmailMessage
                email_id = params.get("email_id")
                if email_id:
                    email = (
                        db.query(EmailMessage)
                        .filter(EmailMessage.user_id == user_id, (EmailMessage.id == email_id) | (EmailMessage.thread_id == email_id))
                        .first()
                    )
                    if email:
                        email.is_processed = True
                        db.commit()
                        result["email_id"] = email.id
                result["note"] = "Email marked as processed"

            elif action.agent == "management" and action.action in ("reschedule_event", "update_event", "shift_event"):
                from app.models.calendar_event import CalendarEvent
                from app.schemas.calendar import CalendarEventUpdate
                from app.services.scheduling_service import get_event_for_user, update_event
                event_id = params.get("event_id")
                event_title = params.get("event_title") or params.get("title") or ""
                new_start_str = params.get("new_start") or params.get("starts_at") or params.get("new_starts_at")
                new_end_str = params.get("new_end") or params.get("ends_at") or params.get("new_ends_at")

                event = None
                if event_id:
                    try:
                        event = db.query(CalendarEvent).filter(CalendarEvent.id == int(event_id), CalendarEvent.user_id == user_id).first()
                    except (ValueError, TypeError):
                        pass
                if not event and event_title:
                    event = (
                        db.query(CalendarEvent)
                        .filter(
                            CalendarEvent.user_id == user_id,
                            CalendarEvent.title.ilike(f"%{event_title}%"),
                        )
                        .first()
                    )

                if event and new_start_str:
                    new_start = safe_parse_datetime(new_start_str)
                    if not new_start:
                        new_start = normalize_datetime(datetime.fromisoformat(str(new_start_str)))
                    if new_end_str:
                        new_end = safe_parse_datetime(new_end_str)
                        if not new_end:
                            new_end = normalize_datetime(datetime.fromisoformat(str(new_end_str)))
                    else:
                        duration = event.ends_at - event.starts_at
                        new_end = new_start + duration

                    old_start_str = event.starts_at.strftime("%a %b %d, %I:%M %p")
                    new_start_formatted = new_start.strftime("%a %b %d, %I:%M %p")
                    payload_update = CalendarEventUpdate(
                        title=event.title,
                        starts_at=new_start,
                        ends_at=new_end,
                        description=event.description,
                        task_id=event.task_id,
                    )
                    reasons = conflict_reasons(
                        db,
                        event.user_id,
                        new_start,
                        new_end,
                        exclude_event_id=event.id,
                        task_id=event.task_id,
                    )
                    if reasons:
                        result["status"] = "error"
                        result["error"] = "; ".join(reasons)
                        return result
                    if event.google_event_id:
                        google_result = google_calendar_adapter.update_event(
                            event_id=event.google_event_id,
                            starts_at=new_start,
                            ends_at=new_end,
                        )
                        if google_result.get("status") != "success":
                            logger.error(
                                "Google Calendar reschedule failed for local event %s: %s",
                                event.id,
                                google_result.get("error", "unknown error"),
                            )
                            result["status"] = "error"
                            result["error"] = (
                                f"Google Calendar update failed for event '{event.title}': "
                                f"{google_result.get('error', 'unknown error')}"
                            )
                            return result
                    update_event(db, event, payload_update)
                    result["event_id"] = event.id
                    result["event_title"] = event.title
                    result["old_start"] = old_start_str
                    result["new_start"] = new_start_formatted
                    result["note"] = f"Shifted '{event.title}' to {new_start_formatted} (Free Day)"

                    # If linked to a task, synchronize the task deadline if needed
                    if event.task_id:
                        from app.models.task import Task
                        linked_task = db.query(Task).filter(Task.id == event.task_id, Task.user_id == user_id).first()
                        if linked_task and linked_task.deadline and linked_task.deadline < new_end:
                            linked_task.deadline = new_end
                            db.commit()
                            result["task_updated"] = linked_task.id
                elif not event:
                    result["status"] = "error"
                    result["error"] = f"Event '{event_title or event_id}' not found"
                else:
                    result["status"] = "error"
                    result["error"] = "Missing new_start parameter for reschedule"

            elif action.agent == "management" and action.action in ("create_event", "add_event", "schedule_event"):
                from app.models.calendar_event import CalendarEvent
                from app.schemas.calendar import CalendarEventInput
                from app.services.scheduling_service import create_event
                title = params.get("title", "Orchestrated Event")
                starts_at = safe_parse_datetime(params.get("starts_at") or params.get("start_time")) or datetime.now(timezone.utc)
                ends_at = safe_parse_datetime(params.get("ends_at") or params.get("end_time")) or (starts_at + timedelta(hours=1))
                event_type = params.get("event_type") or ("career" if any(k in title.lower() for k in ("interview", "job", "recruiter", "onsite")) else "academic")

                # Check for existing event to avoid duplicates
                existing = (
                    db.query(CalendarEvent)
                    .filter(
                        CalendarEvent.user_id == user_id,
                        CalendarEvent.title.ilike(f"%{title}%"),
                        CalendarEvent.starts_at == starts_at,
                    )
                    .first()
                )
                if existing:
                    result["event_id"] = existing.id
                    result["note"] = "Event already scheduled"
                else:
                    try:
                        evt_input = CalendarEventInput(
                            title=title,
                            starts_at=starts_at,
                            ends_at=ends_at,
                            description=params.get("description", ""),
                            task_id=params.get("task_id"),
                            event_type=event_type,
                        )
                        new_event = create_event(db, user_id, evt_input)
                        result["event_id"] = new_event.id
                        result["note"] = f"Scheduled '{title}' on {starts_at.strftime('%a %b %d at %I:%M %p')}"
                    except ValueError as ve:
                        logger.warning("create_event validation warning: %s. Overriding for approved plan.", ve)
                        new_event = CalendarEvent(
                            user_id=user_id,
                            title=title,
                            starts_at=normalize_datetime(starts_at),
                            ends_at=normalize_datetime(ends_at),
                            description=params.get("description", ""),
                            task_id=params.get("task_id"),
                            event_type=event_type,
                        )
                        db.add(new_event)
                        db.commit()
                        db.refresh(new_event)
                        result["event_id"] = new_event.id
                        result["note"] = f"Scheduled '{title}' on {starts_at.strftime('%a %b %d at %I:%M %p')} (approved override)"
            elif action.agent == "management" and action.action in ("reschedule_event", "shift_event", "update_event"):
                from app.models.calendar_event import CalendarEvent
                from app.schemas.calendar import CalendarEventUpdate
                from app.services.scheduling_service import update_event

                event_id = params.get("event_id")
                event_title = params.get("event_title")
                new_start_str = params.get("new_start") or params.get("new_starts_at") or params.get("starts_at")
                new_end_str = params.get("new_end") or params.get("new_ends_at") or params.get("ends_at")

                target_ev = None
                if event_id:
                    try:
                        target_ev = db.query(CalendarEvent).filter(
                            CalendarEvent.id == int(event_id),
                            CalendarEvent.user_id == user_id,
                        ).first()
                    except Exception:
                        pass
                if not target_ev and event_title:
                    target_ev = db.query(CalendarEvent).filter(
                        CalendarEvent.user_id == user_id,
                        CalendarEvent.title.ilike(f"%{event_title}%"),
                    ).first()

                if target_ev and new_start_str:
                    new_start = safe_parse_datetime(new_start_str)
                    if new_end_str:
                        new_end = safe_parse_datetime(new_end_str)
                    else:
                        duration = target_ev.ends_at - target_ev.starts_at
                        new_end = new_start + duration

                    payload_update = CalendarEventUpdate(
                        title=target_ev.title,
                        starts_at=new_start,
                        ends_at=new_end,
                        description=target_ev.description,
                        task_id=target_ev.task_id,
                    )
                    update_event(db, target_ev, payload_update)
                    result["event_id"] = target_ev.id
                    result["note"] = f"Shifted '{target_ev.title}' to {new_start.strftime('%a %b %d at %I:%M %p')}"
                elif not target_ev:
                    result["status"] = "error"
                    result["error"] = f"Event to reschedule not found (id={event_id}, title={event_title})"

            elif action.agent == "management" and action.action in ("create_task", "add_task"):
                from app.models.task import Task
                title = params.get("title", "Orchestrated Task")
                existing = db.query(Task).filter(Task.user_id == user_id, Task.title.ilike(f"%{title}%")).first()
                if existing:
                    result["task_id"] = existing.id
                    result["note"] = "Task already exists"
                else:
                    new_task = Task(
                        user_id=user_id,
                        title=title,
                        description=params.get("description", ""),
                        deadline=datetime.fromisoformat(params["deadline"]) if params.get("deadline") else None,
                        priority=params.get("priority", "high"),
                        category=params.get("category", "career"),
                        source="orchestrator",
                    )
                    db.add(new_task)
                    db.commit()
                    db.refresh(new_task)
                    result["task_id"] = new_task.id

            elif action.agent == "management" and action.action in ("update_task_priority", "update_task"):
                from app.models.task import Task
                task_id = params.get("task_id")
                new_priority = params.get("priority", "high")
                if task_id:
                    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
                    if task:
                        task.priority = new_priority
                        db.commit()
                        result["task_id"] = task_id

            elif action.agent == "management" and action.action in ("update_schedule", "block_time", "reserve_time"):
                from app.models.calendar_event import CalendarEvent
                from app.schemas.calendar import CalendarEventInput
                from app.services.scheduling_service import create_event
                time_slots = params.get("time_slots", [])
                created_event_ids = []
                for slot in time_slots:
                    try:
                        slot_start = datetime.fromisoformat(slot)
                        slot_end = slot_start + timedelta(hours=2)
                        evt_input = CalendarEventInput(
                            title="Protected Study Block: High-Priority Prep",
                            starts_at=slot_start,
                            ends_at=slot_end,
                            description="Dedicated study window allocated by Multi-Agent Orchestrator.",
                            event_type="study",
                        )
                        ev = create_event(db, user_id, evt_input)
                        created_event_ids.append(ev.id)
                    except Exception:
                        pass
                result["event_ids"] = created_event_ids
                result["note"] = f"Allocated {len(created_event_ids)} schedule block(s)"

            elif action.agent == "dsa" and action.action in ("reschedule_dsa_session", "reschedule_session"):
                from app.models.calendar_event import CalendarEvent
                from app.schemas.calendar import CalendarEventUpdate
                from app.services.scheduling_service import update_event
                new_start_str = params.get("new_start")
                session_title = params.get("session_title", "DSA")
                if new_start_str:
                    event = (
                        db.query(CalendarEvent)
                        .filter(
                            CalendarEvent.user_id == user_id,
                            CalendarEvent.title.ilike(f"%{session_title}%"),
                        )
                        .first()
                    )
                    if event:
                        new_start = datetime.fromisoformat(new_start_str)
                        duration = event.ends_at - event.starts_at
                        new_end = new_start + duration
                        payload_update = CalendarEventUpdate(
                            title=event.title,
                            starts_at=new_start,
                            ends_at=new_end,
                            description=event.description,
                            task_id=event.task_id,
                        )
                        update_event(db, event, payload_update)
                        result["event_id"] = event.id

            elif action.agent == "dsa" and action.action in ("update_session_goal", "sync_progress"):
                from app.services.dsa_service import DSAService
                DSAService.sync_progress(db, user_id)
                result["note"] = "DSA progress synced"

            elif action.agent == "dsa" and action.action in ("schedule_sessions", "schedule_session", "plan_sessions"):
                from app.models.task import Task
                sessions = params.get("sessions")
                if not sessions and "session" in params:
                    sessions = [params["session"]]
                if not sessions:
                    sessions = [{"title": params.get("title", "DSA Practice Session"), "duration_minutes": params.get("duration_minutes", 60)}]
                created_ids = []
                for s in sessions:
                    s_title = s.get("title", "DSA Practice Session")
                    existing = db.query(Task).filter(Task.user_id == user_id, Task.title.ilike(f"%{s_title}%")).first()
                    if existing:
                        created_ids.append(existing.id)
                    else:
                        new_task = Task(
                            user_id=user_id,
                            title=s_title,
                            description=f"Targeted DSA preparation session ({s.get('duration_minutes', 60)} mins).",
                            priority="high",
                            category="dsa",
                            source="orchestrator",
                            estimated_effort_hours=float(s.get("duration_minutes", 60)) / 60.0,
                        )
                        db.add(new_task)
                        db.commit()
                        db.refresh(new_task)
                        created_ids.append(new_task.id)
                result["task_ids"] = created_ids
                result["note"] = f"Scheduled {len(created_ids)} DSA session task(s)"

            elif action.agent == "dsa" and action.action in ("queue_dsa_prep", "create_dsa_task", "add_dsa_task"):
                from app.models.task import Task
                title = params.get("title", f"DSA Prep: {params.get('topic', 'Practice')}")
                existing = db.query(Task).filter(Task.user_id == user_id, Task.title.ilike(f"%{title}%")).first()
                if existing:
                    result["task_id"] = existing.id
                else:
                    new_task = Task(
                        user_id=user_id,
                        title=title,
                        description=params.get("description", "Targeted DSA practice session."),
                        priority="high",
                        category="dsa",
                        source="orchestrator",
                    )
                    db.add(new_task)
                    db.commit()
                    db.refresh(new_task)
                    result["task_id"] = new_task.id

            elif action.agent == "job" and action.action in (
                "update_pipeline",
                "add_to_pipeline",
                "track_opportunity",
                "create_job_pipeline",
                "create_pipeline",
            ):
                from app.models.job_pipeline import ActiveJobPipeline
                from app.models.task import Task
                from app.models.opportunity import Opportunity
                from app.models.application import Application
                from app.models.job_dsa_plan import JobDSAPlanProblem
                from app.services.dsa_role_requirements import compute_role_readiness

                company = params.get("company") or params.get("company_name")
                if not company or company == "Company":
                    if event_payload:
                        company = event_payload.get("company")
                    if not company:
                        search_text = " ".join([
                            str(event_payload.get("subject", "") if event_payload else ""),
                            str(event_payload.get("body", "") if event_payload else ""),
                            str(action.rationale),
                            str(params.get("title", "")),
                        ])
                        for comp in ["Infosys", "Google", "Microsoft", "Amazon", "Meta", "Adobe", "Apple", "Uber", "Goldman Sachs", "Cisco", "Oracle"]:
                            if comp.lower() in search_text.lower():
                                company = comp
                                break
                    if not company:
                        company = "Company"

                role_title = params.get("title") or params.get("role_title") or params.get("role")
                if not role_title or role_title in ("Software Engineer", "Orchestrated Event"):
                    if event_payload:
                        combined = (str(event_payload.get("subject", "")) + " " + str(event_payload.get("body", ""))).lower()
                        if "frontend" in combined:
                            role_title = "Frontend Engineer"
                        elif "backend" in combined:
                            role_title = "Backend Engineer"
                        elif "full stack" in combined or "fullstack" in combined:
                            role_title = "Full Stack Engineer"
                        elif "software" in combined or "developer" in combined:
                            role_title = "Software Engineer"
                    if not role_title:
                        role_title = "Software Engineer"

                stage = params.get("status") or params.get("stage") or "interview_scheduled"
                date_str = params.get("date") or params.get("deadline")

                # Evaluate DSA readiness for the role
                readiness_data = compute_role_readiness(db, user_id, role_title)
                matched_role = readiness_data["matched_role"]
                role_match = readiness_data["role_match"]
                readiness_score = readiness_data["readiness_score"]
                strengths = readiness_data["technical_strengths"]
                developing = readiness_data["developing_topics"]

                # Upsert into active_job_pipeline
                existing_pipeline = (
                    db.query(ActiveJobPipeline)
                    .filter(
                        ActiveJobPipeline.user_id == user_id,
                        ActiveJobPipeline.company.ilike(f"%{company}%"),
                    )
                    .first()
                )
                if existing_pipeline:
                    existing_pipeline.title = role_title
                    existing_pipeline.sop_status = stage
                    existing_pipeline.readiness_score = readiness_score
                    if date_str:
                        existing_pipeline.deadline = str(date_str)
                    db.commit()
                    result["pipeline_id"] = existing_pipeline.id
                    result["note"] = f"Updated pipeline stage to {stage} for {company}"
                else:
                    new_pipeline = ActiveJobPipeline(
                        user_id=user_id,
                        title=role_title,
                        company=company,
                        description=f"Confirmed {role_title} interview with {company} on {date_str or 'upcoming'}.",
                        source="orchestrator",
                        match_score=float(params.get("match_score", 88.0)),
                        readiness_score=float(readiness_score),
                        role_match=role_match,
                        matched_role=matched_role,
                        technical_strengths=json.dumps(strengths),
                        developing_topics=json.dumps(developing),
                        sop_status=stage,
                        deadline=str(date_str) if date_str else None,
                    )
                    db.add(new_pipeline)
                    db.commit()
                    db.refresh(new_pipeline)
                    result["pipeline_id"] = new_pipeline.id
                    result["note"] = f"Tracked interview pipeline for {company} ({role_title})"

                # Also synchronize with Opportunity, Application, and JobDSAPlanProblem for DSA Job Prep tab
                existing_opp = db.query(Opportunity).filter(
                    Opportunity.user_id == user_id,
                    Opportunity.company.ilike(f"%{company}%")
                ).first()
                if not existing_opp:
                    existing_opp = Opportunity(
                        user_id=user_id,
                        title=role_title,
                        company=company,
                        description=f"Confirmed {role_title} interview opportunity with {company}.",
                        required_skills="Data Structures, Algorithms, System Design, Python",
                        match_score=float(params.get("match_score", 88.0)),
                    )
                    db.add(existing_opp)
                    db.commit()
                    db.refresh(existing_opp)

                existing_app = db.query(Application).filter(
                    Application.user_id == user_id,
                    Application.opportunity_id == existing_opp.id
                ).first()
                if not existing_app:
                    existing_app = Application(
                        user_id=user_id,
                        opportunity_id=existing_opp.id,
                        status="interview",
                        notes=f"Interview scheduled for {role_title} on {date_str or 'upcoming'}.",
                    )
                    db.add(existing_app)
                    db.commit()
                    db.refresh(existing_app)
                else:
                    existing_app.status = "interview"
                    db.commit()

                result["application_id"] = existing_app.id

                # Queue a dedicated DSA preparation task for the interview's weak topic
                weak_topic = developing[0] if developing else "System Design & Algorithms"
                dsa_task_title = f"DSA Priority Practice: {weak_topic} for {company} Interview"
                existing_dsa_task = (
                    db.query(Task)
                    .filter(
                        Task.user_id == user_id,
                        Task.title.ilike(f"%{company}%"),
                        Task.category == "dsa",
                    )
                    .first()
                )
                if not existing_dsa_task:
                    dsa_task = Task(
                        user_id=user_id,
                        title=dsa_task_title,
                        description=f"Targeted preparation on {weak_topic} to ensure peak technical readiness for upcoming {company} ({role_title}) interview.",
                        priority="urgent",
                        category="dsa",
                        source="orchestrator",
                        estimated_effort_hours=2.5,
                    )
                    db.add(dsa_task)
                    db.commit()
                    db.refresh(dsa_task)
                    result["dsa_prep_task_id"] = dsa_task.id
                    result["dsa_prep_topic"] = weak_topic

            elif action.agent == "job" and action.action == "push_dsa_practice_task":
                from app.models.task import Task
                new_task = Task(
                    user_id=user_id,
                    title=params.get("title", f"DSA Practice: {params.get('topic', 'General')}"),
                    description=params.get("description", ""),
                    priority="high",
                    category="dsa",
                    source="orchestrator",
                )
                db.add(new_task)
                db.commit()
                db.refresh(new_task)
                result["task_id"] = new_task.id

            elif action.agent == "job" and action.action == "trigger_sop_regen":
                result["note"] = "SOP regeneration flagged — requires manual trigger via /api/v1/jobs endpoint"

            else:
                result["status"] = "unhandled"
                result["note"] = f"No dispatch handler for agent='{action.agent}' action='{action.action}'"

        except Exception as exc:
            logger.warning("Dispatch error for %s/%s: %s", action.agent, action.action, exc)
            result["status"] = "error"
            result["error"] = str(exc)

        return result

    async def execute_approved_plan(
        self,
        db: Session,
        user_id: int,
        approval_req: Any,
    ) -> list[dict[str, Any]]:
        """
        Execute all agent actions stored in an approved OrchestratedPlan ApprovalRequest.
        """
        meta = json.loads(approval_req.metadata_json or "{}")
        workflow_id = meta.get("orchestration_id", f"orch-approved-{approval_req.id}")
        event_payload = meta.get("event_payload", {})
        raw_actions = meta.get("agent_actions", [])

        # Ensure rescheduling / shifting actions execute BEFORE create_event actions
        # so conflicting slots are freed up before new events are inserted into the calendar.
        def _action_sort_key(act_dict: dict) -> int:
            action = act_dict.get("action", "")
            if action in ("reschedule_event", "shift_event", "update_event", "reschedule_dsa_session"):
                return 0
            if action in ("create_event", "add_event", "schedule_event"):
                return 2
            return 1

        sorted_actions = sorted(raw_actions, key=_action_sort_key)

        execution_log = []
        for act_dict in sorted_actions:
            action_item = AgentActionItem(
                agent=act_dict.get("agent", "management"),
                action=act_dict.get("action", "noop"),
                parameters=act_dict.get("parameters", {}),
                rationale=act_dict.get("rationale", ""),
            )
            res = await self._dispatch_to_agent(db, user_id, workflow_id, action_item, event_payload=event_payload)
            execution_log.append(res)

            AuditService.log_user_activity(
                db=db,
                user_id=user_id,
                activity_type="orchestration_action_executed",
                message=f"[{workflow_id}] Approved Action: {action_item.agent}/{action_item.action}: {action_item.rationale}",
                metadata={"orchestration_id": workflow_id, "dispatch_result": res},
            )

        return execution_log

    async def run(self, event: OrchestratorEvent, db: Session) -> OrchestratedResult:
        """
        Main orchestration flow:
        1. Route agents
        2. Gather contexts in parallel (read-only)
        3. Build merged prompt
        4. Single Gemini call → OrchestratedDecision
        5. Approval gate (high-impact) or autonomous dispatch (low-impact)
        6. Log everything with shared orchestration_id
        """
        workflow_id = event.workflow_id
        user_id = event.user_id

        # Step 1: Route
        agents_to_consult = self._route_agents(event)
        if not agents_to_consult:
            return OrchestratedResult(
                orchestration_id=workflow_id,
                event_type=event.event_type.value,
                status="skipped",
                agents_consulted=[],
            )

        # Step 2: Gather contexts in parallel
        try:
            snapshot_coros = [self._collect_snapshot(agent, db, user_id) for agent in agents_to_consult]
            snapshots_list = await asyncio.gather(*snapshot_coros, return_exceptions=False)
            # Build merged context dict (agent_name → snapshot or None)
            merged_context: dict[str, Any | None] = {
                agent: snapshot for agent, snapshot in zip(agents_to_consult, snapshots_list)
            }

            # Check for incoming event conflicts if event payload specifies dates/times
            if "management" in merged_context and isinstance(merged_context["management"], dict):
                inc_start, inc_end, inc_title = extract_event_datetime_from_payload(event.payload)
                if inc_start:
                    incoming_conflicts = check_incoming_event_conflicts(
                        db=db,
                        user_id=user_id,
                        starts_at=inc_start,
                        ends_at=inc_end or (inc_start + timedelta(hours=1)),
                        incoming_title=inc_title or "Upcoming Interview",
                    )
                    merged_context["management"]["incoming_interview_conflicts"] = incoming_conflicts
        except Exception as exc:
            logger.error("Orchestrator context gather failed: %s", exc)
            AuditService.log_user_activity(
                db=db,
                user_id=user_id,
                activity_type="orchestration_fallback",
                message=f"Context gather error: {exc}",
                metadata={"orchestration_id": workflow_id, "event_type": event.event_type.value},
            )
            return OrchestratedResult(
                orchestration_id=workflow_id,
                event_type=event.event_type.value,
                status="fallback",
                fallback_reason=str(exc),
            )

        # Step 3: Build merged prompt
        prompt = build_orchestrated_reasoning_prompt(
            event={"event_type": event.event_type.value, "payload": event.payload},
            merged_context=merged_context,
        )

        # Step 4: Single Gemini call
        try:
            decision: OrchestratedDecision = await self.gemini.reason_orchestrated(prompt)
        except Exception as exc:
            logger.error("Orchestrator Gemini call failed: %s", exc)
            AuditService.log_user_activity(
                db=db,
                user_id=user_id,
                activity_type="orchestration_fallback",
                message=f"Gemini reasoning error: {exc}",
                metadata={"orchestration_id": workflow_id, "event_type": event.event_type.value},
            )
            return OrchestratedResult(
                orchestration_id=workflow_id,
                event_type=event.event_type.value,
                agents_consulted=agents_to_consult,
                status="fallback",
                fallback_reason=str(exc),
            )

        # Post-Reasoning Conflict Resolution & Free Day Shifting:
        # If any action schedules an event, or if incoming event payload contains an interview/exam,
        # verify if it directly conflicts with existing low-priority learning plans.
        # If conflicts exist, automatically propose shifting them to free days and require user approval.
        events_to_schedule = [
            a for a in decision.agent_actions
            if a.agent == "management" and a.action in ("add_event", "create_event", "schedule_event")
        ]
        if not events_to_schedule:
            inc_start, inc_end, inc_title = extract_event_datetime_from_payload(event.payload)
            if inc_start and any(k in inc_title.lower() for k in ("interview", "exam", "assessment", "onsite")):
                interview_action = AgentActionItem(
                    agent="management",
                    action="add_event",
                    parameters={
                        "title": inc_title,
                        "starts_at": inc_start.isoformat(),
                        "ends_at": (inc_end or inc_start + timedelta(hours=1)).isoformat(),
                        "event_type": "career",
                    },
                    rationale=f"Schedule confirmed high-priority {inc_title}",
                )
                decision.agent_actions.append(interview_action)
                events_to_schedule.append(interview_action)

        for act in events_to_schedule:
            starts_at_val = act.parameters.get("starts_at") or act.parameters.get("start_time")
            ends_at_val = act.parameters.get("ends_at") or act.parameters.get("end_time")
            st_dt = safe_parse_datetime(starts_at_val)
            if st_dt:
                end_dt = safe_parse_datetime(ends_at_val) or (st_dt + timedelta(hours=1))
                ev_title = act.parameters.get("title") or "Upcoming Interview"

                conflicts = check_incoming_event_conflicts(
                    db=db,
                    user_id=user_id,
                    starts_at=st_dt,
                    ends_at=end_dt,
                    incoming_title=ev_title,
                )

                for conf in conflicts:
                    already_rescheduled = any(
                        a.agent == "management"
                        and a.action in ("reschedule_event", "shift_event", "update_event")
                        and (
                            str(a.parameters.get("event_id")) == str(conf["event_id"])
                            or (a.parameters.get("event_title") and conf["event_title"].lower() in str(a.parameters.get("event_title")).lower())
                        )
                        for a in decision.agent_actions
                    )
                    if not already_rescheduled:
                        rec_start_dt = safe_parse_datetime(conf["recommended_new_start"])
                        rec_formatted = rec_start_dt.strftime("%a %b %d at %I:%M %p") if rec_start_dt else conf["recommended_new_start"]
                        reschedule_action = AgentActionItem(
                            agent="management",
                            action="reschedule_event",
                            parameters={
                                "event_id": conf["event_id"],
                                "event_title": conf["event_title"],
                                "new_start": conf["recommended_new_start"],
                                "new_end": conf["recommended_new_end"],
                            },
                            rationale=(
                                f"Shift clashing low-priority '{conf['event_title']}' to {conf['target_day_name']} "
                                f"({rec_formatted}) to clear calendar for high-priority '{conf['incoming_title']}'"
                            ),
                        )
                        decision.agent_actions.append(reschedule_action)

                        shift_mention = (
                            f"⚠️ Conflict detected: Clashes with existing low-priority '{conf['event_title']}'. "
                            f"Proposing to shift '{conf['event_title']}' to {conf['target_day_name']} ({rec_formatted}) "
                            f"so the interview can be scheduled without losing study progress."
                        )
                        if conf["event_title"] not in decision.telegram_summary:
                            decision.telegram_summary = (
                                f"{decision.telegram_summary} {shift_mention}".strip()
                            )
                        if conf["event_title"] not in decision.reasoning:
                            decision.reasoning += (
                                f"\n\n[Calendar Conflict Resolution] Direct clash detected between incoming "
                                f"high-priority '{conf['incoming_title']}' and '{conf['event_title']}'. "
                                f"Proposed shift of '{conf['event_title']}' to {conf['target_day_name']} ({rec_formatted}) "
                                f"to protect student's interview focus and maintain study continuity."
                            )

        # Step 5: Log the decision
        AuditService.log_user_activity(
            db=db,
            user_id=user_id,
            activity_type="orchestration_decision",
            message=f"[{workflow_id}] {decision.telegram_summary}",
            metadata={
                "orchestration_id": workflow_id,
                "event_type": event.event_type.value,
                "agents_consulted": agents_to_consult,
                "agent_actions": [a.model_dump() for a in decision.agent_actions],
                "reasoning": decision.reasoning[:500],
            },
        )

        # Step 6: High-impact gate
        execution_log: list[dict[str, Any]] = []
        agents_executed: list[str] = []

        if self._is_high_impact(decision):
            # Create approval request
            from app.services.approval_service import ApprovalService
            from app.models.approval_request import ApprovalRequest

            # Deduplication: check if an identical event already has an active pending approval request
            existing_pending_list = (
                db.query(ApprovalRequest)
                .filter(
                    ApprovalRequest.user_id == user_id,
                    ApprovalRequest.status == "pending",
                    ApprovalRequest.action_type == "orchestrated_plan",
                )
                .all()
            )
            for pending_req in existing_pending_list:
                try:
                    p_meta = json.loads(pending_req.metadata_json or "{}")
                    p_payload = p_meta.get("event_payload", {})
                    has_same_msg_id = (
                        event.payload.get("message_id")
                        and p_payload.get("message_id") == event.payload.get("message_id")
                    )
                    has_same_gmail_id = (
                        event.payload.get("id")
                        and p_payload.get("id") == event.payload.get("id")
                    )
                    has_same_subject = (
                        bool(event.payload.get("subject"))
                        and p_payload.get("subject") == event.payload.get("subject")
                    )
                    if has_same_msg_id or has_same_gmail_id or has_same_subject:
                        logger.info(
                            "Found existing pending approval request #%s for event '%s'. Skipping duplicate creation.",
                            pending_req.id, event.payload.get("subject"),
                        )
                        return OrchestratedResult(
                            orchestration_id=workflow_id,
                            event_type=event.event_type.value,
                            agents_consulted=agents_to_consult,
                            status="pending_approval",
                            approval_id=pending_req.id,
                        )
                except Exception:
                    pass

            plan_lines = [
                f"  {i+1}. [{a.agent.upper()}] {a.action} — {a.rationale}"
                for i, a in enumerate(decision.agent_actions)
            ]
            description = (
                f"🤖 Orchestrator Plan ({workflow_id})\n\n"
                f"📋 Reasoning:\n{decision.reasoning[:400]}\n\n"
                f"📌 Planned Actions:\n" + "\n".join(plan_lines)
            )
            approval_req = ApprovalService.create(
                db=db,
                user_id=user_id,
                action_type="orchestrated_plan",
                description=description,
                metadata_json=json.dumps(
                    {
                        "orchestration_id": workflow_id,
                        "event_type": event.event_type.value,
                        "event_payload": event.payload,
                        "agent_actions": [a.model_dump() for a in decision.agent_actions],
                        "telegram_summary": decision.telegram_summary,
                    },
                    default=str,
                ),
            )

            # Send Telegram plan preview
            try:
                from app.integrations.telegram_adapter import TelegramAdapter
                from app.core.config import get_settings
                telegram = TelegramAdapter(get_settings())
                plan_text = (
                    f"🤖 *Orchestrator Plan — Awaiting Your Approval*\n"
                    f"Approval ID: #{approval_req.id}\n\n"
                    f"📋 *Reasoning:*\n{decision.reasoning[:400]}\n\n"
                    f"📌 *Planned Actions:*\n" + "\n".join(plan_lines) + "\n\n"
                    f"Reply `/approve {approval_req.id}` to execute all actions, or `/reject {approval_req.id}` to cancel."
                )
                await telegram.send_message(plan_text)
            except Exception as telegram_exc:
                logger.warning("Failed to send Telegram approval plan: %s", telegram_exc)

            return OrchestratedResult(
                orchestration_id=workflow_id,
                event_type=event.event_type.value,
                agents_consulted=agents_to_consult,
                agents_executed=[],
                decision=decision,
                execution_log=[],
                status="pending_approval",
                approval_id=approval_req.id,
            )
        else:
            # Low-impact: execute autonomously
            for action in decision.agent_actions:
                dispatch_result = await self._dispatch_to_agent(db, user_id, workflow_id, action, event_payload=event.payload)
                execution_log.append(dispatch_result)
                if dispatch_result.get("status") == "executed":
                    agents_executed.append(action.agent)
                AuditService.log_user_activity(
                    db=db,
                    user_id=user_id,
                    activity_type="orchestration_action_executed",
                    message=f"[{workflow_id}] {action.agent}/{action.action}: {action.rationale}",
                    metadata={"orchestration_id": workflow_id, "dispatch_result": dispatch_result},
                )

            # Send consolidated Telegram summary
            if decision.telegram_summary:
                try:
                    from app.integrations.telegram_adapter import TelegramAdapter
                    from app.core.config import get_settings
                    telegram = TelegramAdapter(get_settings())
                    await telegram.send_message(f"🤖 {decision.telegram_summary}")
                except Exception as telegram_exc:
                    logger.warning("Failed to send Telegram summary: %s", telegram_exc)

            return OrchestratedResult(
                orchestration_id=workflow_id,
                event_type=event.event_type.value,
                agents_consulted=agents_to_consult,
                agents_executed=list(set(agents_executed)),
                decision=decision,
                execution_log=execution_log,
                status="executed",
            )


# Singleton instance (lazy init — same pattern as existing services)
multi_agent_orchestrator = MultiAgentOrchestrator()

import csv
import io
from collections import Counter
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.models.application import Application
from app.models.dsa_problem import DSAProblem
from app.models.dsa_progress import DSAProgress
from app.models.job_dsa_plan import JobDSAPlanProblem
from app.models.leetcode_state import LeetCodeState
from app.models.opportunity import Opportunity

class DSAService:
    @staticmethod
    def summary(db: Session, user_id: int) -> dict:
        items = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).all()
        lc_state = db.query(LeetCodeState).filter(LeetCodeState.user_id == user_id).first()

        days = {item.solved_on for item in items if item.solved_on}
        streak = lc_state.streak if (lc_state and lc_state.streak > 0) else 0
        if streak == 0 and days:
            today = date.today()
            if today in days:
                cursor = today
            elif (today - timedelta(days=1)) in days:
                cursor = today - timedelta(days=1)
            else:
                cursor = max(days)

            while cursor in days:
                streak += 1
                cursor -= timedelta(days=1)

        topics = Counter(item.topic for item in items)

        total_solved = lc_state.total_solved if (lc_state and lc_state.total_solved > 0) else len(items)
        easy_solved = lc_state.easy_solved if lc_state else sum(1 for i in items if i.difficulty.lower() == "easy")
        medium_solved = lc_state.medium_solved if lc_state else sum(1 for i in items if i.difficulty.lower() == "medium")
        hard_solved = lc_state.hard_solved if lc_state else sum(1 for i in items if i.difficulty.lower() == "hard")
        active_days = lc_state.active_days if lc_state else len(days)
        ranking = lc_state.ranking if lc_state else None
        username = lc_state.leetcode_username if lc_state else None
        last_polled_at = lc_state.last_polled_at.isoformat() if (lc_state and lc_state.last_polled_at) else None

        return {
            "username": username,
            "total": total_solved,
            "easy_solved": easy_solved,
            "medium_solved": medium_solved,
            "hard_solved": hard_solved,
            "streak": streak,
            "active_days": active_days,
            "ranking": ranking,
            "last_polled_at": last_polled_at,
            "topics": dict(topics),
            "weak_topics": sorted(topic for topic, count in topics.items() if count < 3),
        }

    @staticmethod
    def get_context_snapshot(db: Session, user_id: int) -> dict:
        """Read-only DSA context snapshot for the Orchestrator. No writes."""
        from app.models.calendar_event import CalendarEvent
        summary = DSAService.summary(db, user_id)
        weak_topics = summary.get("weak_topics", [])
        streak = summary.get("streak", 0)
        total = summary.get("total", 0)

        # Active DSA tasks from tasks table
        from app.models.task import Task
        active_dsa_tasks = (
            db.query(Task)
            .filter(Task.user_id == user_id, Task.category == "dsa", Task.status == "pending")
            .order_by(Task.deadline.asc().nullslast())
            .limit(5)
            .all()
        )
        active_dsa_tasks_data = [
            {"id": t.id, "title": t.title, "priority": t.priority, "deadline": t.deadline.isoformat() if t.deadline else None}
            for t in active_dsa_tasks
        ]

        # Scheduled DSA calendar sessions
        scheduled_sessions = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.user_id == user_id,
                CalendarEvent.title.ilike("%DSA%"),
            )
            .order_by(CalendarEvent.starts_at.asc())
            .limit(5)
            .all()
        )
        scheduled_sessions_data = [
            {"id": e.id, "title": e.title, "starts_at": e.starts_at.isoformat(), "ends_at": e.ends_at.isoformat()}
            for e in scheduled_sessions
        ]

        # Job application readiness from dsa_progress
        from app.services.dsa_role_requirements import match_role_tab, compute_role_readiness
        readiness_entries = []
        from app.models.application import Application
        applications = db.query(Application).filter(Application.user_id == user_id).limit(5).all()
        for app_obj in applications:
            opp = app_obj.opportunity if hasattr(app_obj, "opportunity") else None
            role_title = getattr(opp, "role_title", "") if opp else ""
            if role_title:
                role_info = match_role_tab(role_title)
                readiness = compute_role_readiness(db, user_id, role_info["topics"])
                readiness_entries.append({
                    "role": role_title,
                    "readiness_score": readiness["readiness_score"],
                    "weak_topics": readiness["developing_topics"],
                })

        return {
            "dsa_summary": {
                "total": total,
                "streak": streak,
                "weak_topics": weak_topics,
            },
            "job_application_readiness": readiness_entries,
            "scheduled_dsa_sessions": scheduled_sessions_data,
            "active_dsa_tasks": active_dsa_tasks_data,
        }

    @staticmethod
    def sync_progress(db: Session, user_id: int) -> None:

        items = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).all()
        grouped: dict[str, list[DSAProblem]] = {}
        for item in items:
            grouped.setdefault(item.topic, []).append(item)

        existing_progress = db.query(DSAProgress).filter(DSAProgress.user_id == user_id).all()
        for topic, values in grouped.items():
            progress = db.query(DSAProgress).filter(DSAProgress.user_id == user_id, DSAProgress.topic == topic).first()
            if progress is None:
                progress = DSAProgress(user_id=user_id, topic=topic)
                db.add(progress)
            progress.solved_count = len(values)
            progress.revision_count = sum(item.needs_revision for item in values)

        # Remove records for topics that no longer have solved problems
        for p in existing_progress:
            if p.topic not in grouped:
                db.delete(p)

        db.commit()

    @staticmethod
    def ensure_job_applications_and_plans(db: Session, user_id: int) -> list[Application]:
        """Return only applications already persisted for this user."""
        opportunities = db.query(Opportunity).filter(Opportunity.user_id == user_id).all()

        applications = []
        for opp in opportunities:
            app = db.query(Application).filter(Application.user_id == user_id, Application.opportunity_id == opp.id).first()
            if app:
                applications.append(app)

        return applications

    @staticmethod
    def _normalize_title(title: str) -> str:
        return title.strip().lower().replace("-", " ").replace("_", " ")

    @staticmethod
    def get_job_applications_dsa_summary(db: Session, user_id: int) -> list[dict]:
        """
        Get all job applications with DSA preparation metrics calculated dynamically
        against the user's actual solved LeetCode problems.
        """
        # Get solved problems for user (by title slug and normalized title)
        solved_problems = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).all()
        solved_slugs = {p.leetcode_submission_id: p for p in solved_problems if p.leetcode_submission_id}
        solved_title_map = {DSAService._normalize_title(p.title): p for p in solved_problems}

        applications = db.query(Application).filter(Application.user_id == user_id).all()
        results = []

        for app in applications:
            opp = db.query(Opportunity).filter(Opportunity.id == app.opportunity_id).first()
            company = opp.company if opp else "Company"
            title = opp.title if opp else "Job Position"

            planned_problems = db.query(JobDSAPlanProblem).filter(JobDSAPlanProblem.application_id == app.id).all()
            total_planned = len(planned_problems)

            solved_count = 0
            for item in planned_problems:
                item_slug = item.title_slug.strip().lower()
                norm_title = DSAService._normalize_title(item.title)

                # Check if solved either by slug or title match
                is_solved = (item_slug in solved_slugs) or (norm_title in solved_title_map)
                if is_solved:
                    solved_count += 1

            completion_percentage = round((solved_count / total_planned * 100), 1) if total_planned > 0 else 0.0

            results.append({
                "application_id": app.id,
                "opportunity_id": app.opportunity_id,
                "company": company,
                "role": title,
                "status": app.status,
                "total_planned": total_planned,
                "solved_count": solved_count,
                "remaining_count": total_planned - solved_count,
                "completion_percentage": completion_percentage,
            })

        return results

    @staticmethod
    def get_job_dsa_plan(db: Session, user_id: int, application_id: int) -> dict:
        """Get detailed DSA preparation plan for a specific job application with solved/remaining breakdowns."""
        app = db.query(Application).filter(Application.id == application_id, Application.user_id == user_id).first()
        if not app:
            return {}

        opp = db.query(Opportunity).filter(Opportunity.id == app.opportunity_id).first()
        company = opp.company if opp else "Company"
        role = opp.title if opp else "Job Position"

        solved_problems = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).all()
        solved_title_map = {DSAService._normalize_title(p.title): p for p in solved_problems}

        planned_problems = db.query(JobDSAPlanProblem).filter(JobDSAPlanProblem.application_id == app.id).all()

        planned_items = []
        solved_items = []
        remaining_items = []

        for p in planned_problems:
            norm_title = DSAService._normalize_title(p.title)
            solved_match = solved_title_map.get(norm_title)
            is_solved = solved_match is not None
            solved_on_str = solved_match.solved_on.isoformat() if (solved_match and solved_match.solved_on) else None

            item_dict = {
                "id": p.id,
                "title": p.title,
                "title_slug": p.title_slug,
                "topic": p.topic,
                "difficulty": p.difficulty,
                "company": p.company,
                "notes": p.notes,
                "is_solved": is_solved,
                "solved_on": solved_on_str,
                "leetcode_url": f"https://leetcode.com/problems/{p.title_slug}/" if p.title_slug else None,
            }

            planned_items.append(item_dict)
            if is_solved:
                solved_items.append(item_dict)
            else:
                remaining_items.append(item_dict)

        total_planned = len(planned_items)
        solved_count = len(solved_items)
        completion_percentage = round((solved_count / total_planned * 100), 1) if total_planned > 0 else 0.0

        return {
            "application_id": app.id,
            "opportunity_id": app.opportunity_id,
            "company": company,
            "role": role,
            "status": app.status,
            "total_planned": total_planned,
            "solved_count": solved_count,
            "remaining_count": len(remaining_items),
            "completion_percentage": completion_percentage,
            "planned_problems": planned_items,
            "solved_problems": solved_items,
            "remaining_problems": remaining_items,
        }

    @staticmethod
    def import_csv(db: Session, user_id: int, content: str) -> int:
        rows = csv.DictReader(io.StringIO(content))
        required = {"title", "topic", "difficulty", "solved_on"}
        if not rows.fieldnames or not required.issubset(set(rows.fieldnames)):
            raise ValueError("CSV requires title, topic, difficulty, and solved_on columns")
        items = [DSAProblem(user_id=user_id, title=row["title"].strip(), topic=row["topic"].strip(), difficulty=row["difficulty"].strip(), attempts=int(row.get("attempts") or 1), solved_on=date.fromisoformat(row["solved_on"]), needs_revision=str(row.get("needs_revision", "false")).lower() == "true") for row in rows]
        db.add_all(items); db.commit(); DSAService.sync_progress(db, user_id)
        return len(items)

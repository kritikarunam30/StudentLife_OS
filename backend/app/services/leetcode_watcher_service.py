import asyncio
from datetime import date, datetime, timezone
import logging
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import SessionLocal
from app.integrations.leetcode_query import LeetCodeQueryClient
from app.models.dsa_problem import DSAProblem
from app.models.leetcode_state import LeetCodeState
from app.models.student_profile import StudentProfile, User
from app.services.dsa_service import DSAService
from openclaw.workflows.dsa_workflow import DSARecommendationWorkflow

logger = logging.getLogger(__name__)


class LeetCodeWatcherService:
    """
    Autonomous background watcher service for LeetCode profile & submission tracking.
    Polls LeetCode's GraphQL API periodically, performs change detection against SQLite state,
    records newly solved problems, syncs DSA progress, and triggers OpenClaw recommendation workflows.
    """

    def __init__(self, interval_seconds: int | None = None) -> None:
        self.settings = get_settings()
        self.interval_seconds = interval_seconds or self.settings.leetcode_poll_interval_seconds
        self.query_client = LeetCodeQueryClient()
        self.dsa_workflow = DSARecommendationWorkflow()
        self.is_running = False

    async def start_periodic_sync(self) -> None:
        """Start the continuous background polling loop."""
        if not self.settings.leetcode_enabled:
            logger.info("LeetCodeWatcherService is disabled in settings.")
            return

        self.is_running = True
        logger.info("LeetCodeWatcherService started (polling interval: %ds).", self.interval_seconds)

        while self.is_running:
            try:
                db: Session = SessionLocal()
                try:
                    user = db.query(User).first()
                    if user:
                        await self.check_user_leetcode_updates(db=db, user_id=user.id)
                finally:
                    db.close()
            except asyncio.CancelledError:
                logger.info("LeetCodeWatcherService task cancelled.")
                break
            except Exception as err:
                logger.error("Error in LeetCodeWatcherService iteration: %s", err, exc_info=True)

            await asyncio.sleep(self.interval_seconds)

    def stop(self) -> None:
        """Stop the background polling loop."""
        self.is_running = False
        logger.info("LeetCodeWatcherService stopped.")

    def get_configured_username(self, db: Session, user_id: int) -> str:
        """Resolve the target LeetCode username from StudentProfile or system Settings."""
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == user_id).first()
        if profile and profile.leetcode_username:
            return profile.leetcode_username
        return self.settings.leetcode_username or ""

    async def check_user_leetcode_updates(self, db: Session, user_id: int) -> dict:
        """
        Poll LeetCode for profile stats and recent submissions for the target user.
        Detect newly accepted submissions, update local DB state, and trigger OpenClaw workflow if new ACs found.
        """
        username = self.get_configured_username(db, user_id)
        if not username:
            return {"status": "skipped", "reason": "No LeetCode username configured"}

        # 1. Fetch profile statistics & recent AC submissions from LeetCode GraphQL
        profile_stats = await self.query_client.fetch_user_profile(username)
        recent_submissions = await self.query_client.fetch_recent_ac_submissions(username, limit=15)

        # 2. Retrieve or initialize local LeetCode state
        state = db.query(LeetCodeState).filter(LeetCodeState.user_id == user_id).first()
        if not state:
            state = LeetCodeState(
                user_id=user_id,
                leetcode_username=username,
                total_solved=0,
                easy_solved=0,
                medium_solved=0,
                hard_solved=0,
                last_submission_id=None,
                last_polled_at=datetime.now(timezone.utc),
            )
            db.add(state)
            db.commit()
            db.refresh(state)

        # Update snapshot stats
        state.leetcode_username = username
        if profile_stats.get("found"):
            state.total_solved = profile_stats.get("total_solved", state.total_solved)
            state.easy_solved = profile_stats.get("easy", state.easy_solved)
            state.medium_solved = profile_stats.get("medium", state.medium_solved)
            state.hard_solved = profile_stats.get("hard", state.hard_solved)
            state.streak = profile_stats.get("streak", state.streak)
            state.active_days = profile_stats.get("active_days", state.active_days)
            if profile_stats.get("ranking") is not None:
                state.ranking = profile_stats.get("ranking")

        state.last_polled_at = datetime.now(timezone.utc)

        # 3. Perform change detection for accepted submissions
        newly_solved_items = []

        for sub in recent_submissions:
            sub_id = sub.get("submission_id")
            title = sub.get("title")
            title_slug = sub.get("title_slug")
            timestamp = sub.get("timestamp")

            if not sub_id or not title:
                continue

            # Check if this submission has already been recorded
            existing_by_sub_id = (
                db.query(DSAProblem)
                .filter(
                    DSAProblem.user_id == user_id,
                    DSAProblem.leetcode_submission_id == sub_id,
                )
                .first()
            )
            if existing_by_sub_id:
                continue

            # Check if problem title already solved today to prevent duplicate title entries
            solved_date = date.fromtimestamp(timestamp) if timestamp else date.today()
            existing_by_title = (
                db.query(DSAProblem)
                .filter(
                    DSAProblem.user_id == user_id,
                    DSAProblem.title == title,
                    DSAProblem.solved_on == solved_date,
                )
                .first()
            )
            if existing_by_title:
                existing_by_title.leetcode_submission_id = sub_id
                db.commit()
                continue

            # Fetch difficulty and main topic tag for new problem
            details = await self.query_client.fetch_problem_details(title_slug)
            difficulty = details.get("difficulty", "Medium")
            topic = details.get("topic", "General")

            # Insert new DSAProblem record into SQLite database
            new_problem = DSAProblem(
                user_id=user_id,
                title=title,
                topic=topic,
                difficulty=difficulty,
                attempts=1,
                solved_on=solved_date,
                needs_revision=False,
                leetcode_submission_id=sub_id,
            )
            db.add(new_problem)
            db.commit()

            newly_solved_items.append({
                "submission_id": sub_id,
                "title": title,
                "difficulty": difficulty,
                "topic": topic,
                "solved_on": solved_date.isoformat(),
            })

            # Track latest submission ID
            state.last_submission_id = sub_id

        db.commit()

        # 4. Sync DSA progress counts if new problems were recorded
        if newly_solved_items:
            DSAService.sync_progress(db, user_id)
            logger.info("Recorded %d new LeetCode accepted submission(s) for @%s", len(newly_solved_items), username)

            # 5. Trigger OpenClaw workflow to analyze goals & dispatch Telegram alert
            workflow_payload = {
                "username": username,
                "newly_solved": newly_solved_items,
                "total_solved": state.total_solved,
                "easy": state.easy_solved,
                "medium": state.medium_solved,
                "hard": state.hard_solved,
            }
            await self.dsa_workflow.run(user_id=user_id, db=db, payload=workflow_payload)

        return {
            "status": "success",
            "username": username,
            "total_solved": state.total_solved,
            "newly_solved_count": len(newly_solved_items),
            "newly_solved": newly_solved_items,
            "last_polled_at": state.last_polled_at.isoformat() if state.last_polled_at else None,
        }


leetcode_watcher_service = LeetCodeWatcherService()

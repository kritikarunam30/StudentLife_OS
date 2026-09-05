from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
Base = declarative_base()


def init_db() -> None:
	from app import models  # noqa: F401

	Base.metadata.create_all(bind=engine)
	if settings.database_url.startswith("sqlite"):
		_profile_columns = {
			"skills": "VARCHAR(1000)",
			"preferred_locations": "VARCHAR(500)",
			"available_study_hours": "FLOAT",
			"preferred_study_times": "VARCHAR(500)",
			"notification_preferences": "VARCHAR(1000)",
			"leetcode_username": "VARCHAR(255)",
		}
		with engine.begin() as connection:
			# Migrate users table
			user_columns = {column["name"] for column in inspect(connection).get_columns("users")}
			if "telegram_name" not in user_columns:
				connection.execute(text("ALTER TABLE users ADD COLUMN telegram_name VARCHAR(255)"))

			# Migrate student_profiles table
			existing = {column["name"] for column in inspect(connection).get_columns("student_profiles")}
			for column, column_type in _profile_columns.items():
				if column not in existing:
					connection.execute(text(f"ALTER TABLE student_profiles ADD COLUMN {column} {column_type}"))

			# Migrate dsa_problems table
			dsa_columns = {column["name"] for column in inspect(connection).get_columns("dsa_problems")}
			if "leetcode_submission_id" not in dsa_columns:
				connection.execute(text("ALTER TABLE dsa_problems ADD COLUMN leetcode_submission_id VARCHAR(100)"))

			event_columns = {column["name"] for column in inspect(connection).get_columns("calendar_events")}
			for column, column_type in {
				"task_id": "INTEGER",
				"google_event_id": "VARCHAR(255)",
				"creation_notified": "BOOLEAN DEFAULT 0",
				"reminded_day_before": "BOOLEAN DEFAULT 0",
			}.items():
				if column not in event_columns:
					connection.execute(text(f"ALTER TABLE calendar_events ADD COLUMN {column} {column_type}"))
			approval_columns = {column["name"] for column in inspect(connection).get_columns("approval_requests")}
			for column, column_type in {
				"metadata_json": "TEXT",
				"expires_at": "DATETIME",
				"result_json": "TEXT",
			}.items():
				if column not in approval_columns:
					connection.execute(text(f"ALTER TABLE approval_requests ADD COLUMN {column} {column_type}"))

			# Migrate leetcode_state table
			if inspect(connection).has_table("leetcode_state"):
				lc_columns = {column["name"] for column in inspect(connection).get_columns("leetcode_state")}
				for column, column_type in {
					"streak": "INTEGER DEFAULT 0",
					"active_days": "INTEGER DEFAULT 0",
					"ranking": "INTEGER",
				}.items():
					if column not in lc_columns:
						connection.execute(text(f"ALTER TABLE leetcode_state ADD COLUMN {column} {column_type}"))

			# Migrate email_messages table
			email_columns = {column["name"] for column in inspect(connection).get_columns("email_messages")}
			for column, column_type in {
				"processing_status": "VARCHAR(50) DEFAULT 'new'",
				"priority": "VARCHAR(50)",
				"requires_action": "BOOLEAN DEFAULT 0",
				"action_type": "VARCHAR(100)",
				"reasoning": "TEXT",
				"processed_at": "DATETIME",
				"error_message": "TEXT",
			}.items():
				if column not in email_columns:
					connection.execute(text(f"ALTER TABLE email_messages ADD COLUMN {column} {column_type}"))

			# Ensure active_job_pipeline table has all columns
			if inspect(connection).has_table("active_job_pipeline"):
				job_columns = {column["name"] for column in inspect(connection).get_columns("active_job_pipeline")}
				for column, column_type in {
					"required_skills": "TEXT",
					"match_score": "FLOAT",
					"readiness_score": "FLOAT",
					"role_match": "VARCHAR(50)",
					"matched_role": "VARCHAR(100)",
					"technical_strengths": "TEXT",
					"developing_topics": "TEXT",
					"sop_draft": "TEXT",
					"sop_status": "VARCHAR(50) DEFAULT 'not_generated'",
					"sop_generated_from": "TEXT",
					"student_preferences": "TEXT",
					"experience_level": "VARCHAR(100)",
					"responsibilities": "TEXT",
					"company_values": "TEXT",
					"deadline": "VARCHAR(100)",
				}.items():
					if column not in job_columns:
						connection.execute(text(f"ALTER TABLE active_job_pipeline ADD COLUMN {column} {column_type}"))

			# Migrate activity_logs table — add orchestration_id for cross-agent correlation
			activity_log_columns = {column["name"] for column in inspect(connection).get_columns("activity_logs")}
			if "orchestration_id" not in activity_log_columns:
				connection.execute(text("ALTER TABLE activity_logs ADD COLUMN orchestration_id VARCHAR(50)"))


def get_db() -> Generator:
	db = SessionLocal()
	try:
		yield db
	finally:
		db.close()

from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.student_profile import User
from app.models.calendar_event import CalendarEvent
from app.models.telegram_alert_delivery import TelegramAlertDelivery
from app.models.task import Task
from app.models.approval_request import ApprovalRequest
from app.services.telegram_bot_listener import TelegramBotListener, is_briefing_request
from app.integrations.google_calendar_adapter import GoogleCalendarAdapter
from app.integrations.gmail_adapter import GmailAdapter
from app.tools.tool_registry import tool_registry


class FakeCalendarRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeCalendarEvents:
    def __init__(self, event):
        self.event = event
        self.updated = None

    def get(self, **kwargs):
        assert kwargs["calendarId"] == "primary"
        assert kwargs["eventId"] == self.event["id"]
        return FakeCalendarRequest(self.event.copy())

    def update(self, **kwargs):
        self.updated = kwargs
        return FakeCalendarRequest(kwargs["body"])


class FakeCalendarService:
    def __init__(self, event):
        self.events_resource = FakeCalendarEvents(event)

    def events(self):
        return self.events_resource


@pytest.fixture
def mock_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(email="test@university.edu", full_name="Test Student")
    session.add(user)
    session.commit()
    session.refresh(user)

    event = CalendarEvent(
        user_id=user.id,
        title="Math Lecture",
        starts_at=datetime.now(timezone.utc),
        ends_at=datetime.now(timezone.utc),
    )
    session.add(event)

    task = Task(
        user_id=user.id,
        title="Study Chemistry",
        status="pending",
        priority="high",
    )
    session.add(task)
    session.commit()

    yield session, user
    session.close()


def test_google_tools_registered():
    schemas = tool_registry.get_schemas()
    tool_names = {s.name for s in schemas}
    assert "sync_google_calendar" in tool_names
    assert "create_google_calendar_event" in tool_names
    assert "list_gmail_messages" in tool_names
    assert "create_email_draft" in tool_names
    assert "send_email_draft" in tool_names


def test_send_email_draft_requires_approval():
    schemas = tool_registry.get_schemas()
    send_tool = next(s for s in schemas if s.name == "send_email_draft")
    assert send_tool.requires_approval is True
    assert send_tool.access_level.value == "external_or_consequential"


def test_google_adapters_graceful_fallback(monkeypatch):
    monkeypatch.setattr("app.integrations.google_calendar_adapter.get_calendar_service", lambda: None)
    monkeypatch.setattr("app.integrations.gmail_adapter.get_gmail_service", lambda: None)
    cal = GoogleCalendarAdapter()
    assert cal.is_connected() is False
    assert cal.list_events() == []

    gmail = GmailAdapter()
    assert gmail.is_connected() is False
    assert len(gmail.list_recent_messages()) >= 1
    draft_res = gmail.create_draft("prof@edu.com", "Test", "Hello")
    assert draft_res["status"] == "success"
    assert draft_res["mocked"] is True


def test_google_calendar_update_preserves_existing_event_details():
    original = {
        "id": "google-event-123",
        "summary": "Study block",
        "description": "Keep this description",
        "attendees": [{"email": "student@example.com"}],
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10}]},
        "start": {"dateTime": "2026-09-06T10:00:00+00:00"},
        "end": {"dateTime": "2026-09-06T11:00:00+00:00"},
    }
    service = FakeCalendarService(original)
    adapter = GoogleCalendarAdapter()
    adapter._service = service

    result = adapter.update_event(
        event_id="google-event-123",
        starts_at=datetime(2026, 9, 7, 10, tzinfo=timezone.utc),
        ends_at=datetime(2026, 9, 7, 11, tzinfo=timezone.utc),
    )

    assert result["status"] == "success"
    assert service.events_resource.updated["eventId"] == "google-event-123"
    updated = service.events_resource.updated["body"]
    assert updated["summary"] == original["summary"]
    assert updated["description"] == original["description"]
    assert updated["attendees"] == original["attendees"]
    assert updated["reminders"] == original["reminders"]
    assert updated["start"]["dateTime"] == "2026-09-07T10:00:00+00:00"
    assert updated["end"]["dateTime"] == "2026-09-07T11:00:00+00:00"


@pytest.mark.asyncio
async def test_telegram_bot_commands(mock_db):
    session, user = mock_db
    listener = TelegramBotListener()

    # Test /help
    help_resp = await listener.handle_command("/help", user_id=user.id, db=session)
    assert "StudentLife OS" in help_resp
    assert "/calendar" in help_resp

    # Test /tasks
    tasks_resp = await listener.handle_command("/tasks", user_id=user.id, db=session)
    assert "Study Chemistry" in tasks_resp

    # Test /drafts (empty)
    drafts_resp = await listener.handle_command("/drafts", user_id=user.id, db=session)
    assert "No pending approvals" in drafts_resp


def test_natural_language_briefing_request_detection():
    assert is_briefing_request("give me my morning brief") is True
    assert is_briefing_request("What's my daily briefing?") is True
    assert is_briefing_request("check my pending tasks") is False


@pytest.mark.asyncio
async def test_natural_language_briefing_request_uses_briefing_service(mock_db, monkeypatch):
    session, user = mock_db
    listener = TelegramBotListener()

    async def fake_generate_briefing(db, user_id, send_notification):
        assert db is session
        assert user_id == user.id
        assert send_notification is False
        return {"formatted_text": "Good morning, Test Student!"}

    monkeypatch.setattr(listener.briefing_service, "generate_briefing", fake_generate_briefing)

    response = await listener.handle_natural_language(
        "give me my morning brief", user_id=user.id, db=session
    )

    assert response == "Good morning, Test Student!"


@pytest.mark.asyncio
async def test_telegram_alert_is_persistent_and_content_sensitive(mock_db, monkeypatch):
    session, user = mock_db
    listener = TelegramBotListener()
    sent = []

    async def fake_send_message(chat_id, text):
        sent.append((chat_id, text))
        return True

    monkeypatch.setattr(listener, "send_message", fake_send_message)

    assert await listener.send_alert(session, "chat-1", "Event changed", "event:42") is True
    assert await listener.send_alert(session, "chat-1", "Event changed", "event:42") is False
    assert await listener.send_alert(session, "chat-1", "Event changed again", "event:42") is True

    assert len(sent) == 2
    assert session.query(TelegramAlertDelivery).count() == 2

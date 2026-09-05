import base64
import email
from email.message import EmailMessage
import logging
from typing import Any

from app.integrations.google_auth import get_gmail_service, is_google_authenticated

logger = logging.getLogger(__name__)


class GmailAdapter:
    """Adapter for interacting with Gmail API v1 (reading emails, creating drafts, sending approved emails)."""

    def __init__(self) -> None:
        self._service = None

    @property
    def service(self):
        if self._service is None:
            self._service = get_gmail_service()
        return self._service

    def is_connected(self) -> bool:
        """Return True if Gmail API service is authenticated and ready."""
        return self.service is not None

    def list_recent_messages(
        self,
        query: str = "is:unread",
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch recent email messages matching the query."""
        if not self.is_connected():
            logger.info("Gmail is not connected; no inbox records are available.")
            return []

        try:
            res = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            message_summaries = res.get("messages", [])
            messages = []

            for msg_item in message_summaries:
                msg = (
                    self.service.users()
                    .messages()
                    .get(userId="me", id=msg_item["id"], format="full")
                    .execute()
                )
                headers = {
                    h["name"].lower(): h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }

                # Extract plain text body
                body_text = self._extract_body(msg.get("payload", {})) or msg.get("snippet", "")

                messages.append({
                    "id": msg["id"],
                    "thread_id": msg.get("threadId"),
                    "from": headers.get("from", "Unknown"),
                    "subject": headers.get("subject", "No Subject"),
                    "date": headers.get("date", ""),
                    "snippet": msg.get("snippet", ""),
                    "body": body_text,
                })

            return messages
        except Exception as e:
            logger.error("Failed to list Gmail messages: %s", e)
            return []

    def create_draft(
        self,
        to: str,
        subject: str,
        body_text: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Create an email draft in Gmail WITHOUT sending it.
        Safe for Human-in-the-Loop workflows.
        """
        if not self.is_connected():
            return {
                "status": "success",
                "draft_id": f"mock-draft-{abs(hash(to + subject)) % 10000}",
                "to": to,
                "subject": subject,
                "preview": body_text[:200],
                "mocked": True,
            }

        try:
            msg = EmailMessage()
            msg.set_content(body_text)
            msg["To"] = to
            msg["Subject"] = subject

            raw_bytes = msg.as_bytes()
            encoded_message = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

            draft_body: dict[str, Any] = {
                "message": {
                    "raw": encoded_message,
                }
            }
            if thread_id:
                draft_body["message"]["threadId"] = thread_id

            draft = self.service.users().drafts().create(userId="me", body=draft_body).execute()
            draft_id = draft.get("id")
            logger.info("Successfully created Gmail draft %s to %s", draft_id, to)

            return {
                "status": "success",
                "draft_id": draft_id,
                "to": to,
                "subject": subject,
                "preview": body_text[:200],
            }
        except Exception as e:
            logger.error("Failed to create Gmail draft: %s", e)
            return {"status": "failed", "error": str(e)}

    def send_draft(self, draft_id: str) -> dict[str, Any]:
        """
        Send an existing draft after human approval has been confirmed.
        """
        if not self.is_connected():
            logger.info("Gmail is not connected; cannot send draft %s", draft_id)
            return {"status": "failed", "error": "Gmail is not connected"}

        try:
            sent = self.service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
            logger.info("Successfully sent Gmail draft %s (message ID: %s)", draft_id, sent.get("id"))
            return {
                "status": "success",
                "message_id": sent.get("id"),
                "thread_id": sent.get("threadId"),
            }
        except Exception as e:
            logger.error("Failed to send Gmail draft %s: %s", draft_id, e)
            return {"status": "failed", "error": str(e)}

    @staticmethod
    def _extract_body(payload: dict[str, Any]) -> str:
        """Helper to recursively decode text parts from a MIME payload."""
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")
                # Nested parts
                sub = GmailAdapter._extract_body(part)
                if sub:
                    return sub
        elif payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")
        return ""

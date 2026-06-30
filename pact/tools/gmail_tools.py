"""Gmail API tools for Pact.

Handles creating drafts, sending emails, and checking for replies.
Used by FirstDraftAgent (email domain) and EscalationAgent.
"""

import base64
import logging
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)


def create_draft(to: str, subject: str, body: str, task_id: str) -> str:
    """Create a Gmail draft message.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body text (plain text).
        task_id: Associated task ID for tracking.

    Returns:
        The draft ID string, or empty string on failure.
    """
    try:
        from ..utils.auth import get_gmail_service

        service = get_gmail_service()

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        message["X-Pact-Task-ID"] = task_id

        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft_body = {"message": {"raw": encoded}}

        draft = service.users().drafts().create(userId="me", body=draft_body).execute()
        draft_id = draft.get("id", "")
        logger.info(f"Created Gmail draft: {draft_id} for task {task_id}")
        return draft_id

    except Exception as e:
        logger.error(f"Error creating Gmail draft: {e}")
        return ""


def send_draft(draft_id: str) -> bool:
    """Send an existing Gmail draft.

    Args:
        draft_id: The draft ID to send.

    Returns:
        True if sent successfully, False otherwise.
    """
    try:
        from ..utils.auth import get_gmail_service

        service = get_gmail_service()
        service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
        logger.info(f"Sent Gmail draft: {draft_id}")
        return True

    except Exception as e:
        logger.error(f"Error sending Gmail draft: {e}")
        return False


def send_email(to: str, subject: str, body: str) -> bool:
    """Send an email directly (bypassing draft creation).

    Used for escalation alerts and accountability notifications.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body text.

    Returns:
        True if sent successfully, False otherwise.
    """
    try:
        from ..utils.auth import get_gmail_service

        service = get_gmail_service()

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject

        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_body = {"raw": encoded}

        result = (
            service.users()
            .messages()
            .send(userId="me", body=send_body)
            .execute()
        )
        logger.info(f"Sent email to {to}, message ID: {result.get('id')}")
        return True

    except Exception as e:
        logger.error(f"Error sending email: {e}")
        return False


def check_reply_received(thread_id: str) -> bool:
    """Check if a reply has been received in a Gmail thread.

    Used by EscalationAgent to check if user has approved sending a draft.

    Args:
        thread_id: The Gmail thread ID to check.

    Returns:
        True if a reply exists in the thread, False otherwise.
    """
    try:
        from ..utils.auth import get_gmail_service

        service = get_gmail_service()

        thread = (
            service.users()
            .threads()
            .get(userId="me", id=thread_id)
            .execute()
        )
        messages = thread.get("messages", [])

        # More than 1 message means there's a reply
        if len(messages) > 1:
            logger.info(f"Reply found in thread {thread_id}")
            return True

        logger.info(f"No reply yet in thread {thread_id}")
        return False

    except Exception as e:
        logger.error(f"Error checking for reply: {e}")
        return False

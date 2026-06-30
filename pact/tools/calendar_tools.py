"""Google Calendar API tools for Pact.

Handles finding available time slots, creating calendar blocks,
and monitoring event deletions for accountability.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def find_available_slot(
    peak_hours: list[int],
    duration_minutes: int,
    before_deadline: str,
) -> str:
    """Find the next available calendar slot within preferred peak hours before deadline.

    Scans Google Calendar for free windows during the user's peak productivity hours.

    Args:
        peak_hours: Preferred hours of day for focus work (e.g., [9, 10, 14, 15]).
        duration_minutes: Required slot duration in minutes.
        before_deadline: ISO datetime string — must find slot before this time.

    Returns:
        ISO datetime string of the start time for the available slot,
        or empty string if no slot found.
    """
    try:
        from ..utils.auth import get_calendar_service

        service = get_calendar_service()
        deadline = datetime.fromisoformat(before_deadline)
        now = datetime.now(deadline.tzinfo) if deadline.tzinfo else datetime.now()

        # Search day by day from now until deadline
        current_day = now.date()
        end_day = deadline.date()

        while current_day <= end_day:
            for hour in sorted(peak_hours):
                slot_start = datetime.combine(
                    current_day, datetime.min.time().replace(hour=hour)
                )
                slot_end = slot_start + timedelta(minutes=duration_minutes)

                # Skip slots in the past or after deadline
                if slot_start < now or slot_end > deadline:
                    continue

                # Check if this slot is free
                time_min = slot_start.isoformat() + "Z"
                time_max = slot_end.isoformat() + "Z"

                try:
                    events_result = (
                        service.events()
                        .list(
                            calendarId="primary",
                            timeMin=time_min,
                            timeMax=time_max,
                            singleEvents=True,
                        )
                        .execute()
                    )
                    events = events_result.get("items", [])

                    if not events:
                        logger.info(f"Found available slot: {slot_start.isoformat()}")
                        return slot_start.isoformat()
                except Exception as e:
                    logger.warning(f"Calendar API error checking slot: {e}")
                    continue

            current_day += timedelta(days=1)

        logger.warning("No available slots found before deadline")
        return ""

    except Exception as e:
        logger.error(f"Error finding available slot: {e}")
        # Fallback: suggest next peak hour
        now = datetime.now()
        for hour in sorted(peak_hours):
            candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if candidate > now:
                return candidate.isoformat()
        # Tomorrow first peak hour
        tomorrow = now + timedelta(days=1)
        fallback = tomorrow.replace(
            hour=peak_hours[0] if peak_hours else 9,
            minute=0,
            second=0,
            microsecond=0,
        )
        return fallback.isoformat()


def create_calendar_block(
    task_id: str,
    title: str,
    start_time: str,
    duration_minutes: int,
    color_id: str,
    description: str,
) -> str:
    """Create a calendar event block for a task.

    Args:
        task_id: The task ID to associate with this event.
        title: Event title (e.g., "PACT: Write proposal").
        start_time: ISO datetime string for event start.
        duration_minutes: Duration in minutes.
        color_id: Google Calendar color ID ("11" = red/aversive, "7" = blue/normal).
        description: Event description with task details.

    Returns:
        The created calendar event ID, or empty string on failure.
    """
    try:
        from ..utils.auth import get_calendar_service

        service = get_calendar_service()
        start = datetime.fromisoformat(start_time)
        end = start + timedelta(minutes=duration_minutes)

        event = {
            "summary": title,
            "description": f"{description}\n\n[PACT Task ID: {task_id}]",
            "start": {
                "dateTime": start.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": end.isoformat(),
                "timeZone": "UTC",
            },
            "colorId": color_id,
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 15},
                    {"method": "popup", "minutes": 5},
                ],
            },
        }

        created_event = service.events().insert(calendarId="primary", body=event).execute()
        event_id = created_event.get("id", "")
        logger.info(f"Created calendar block: {event_id} for task {task_id}")
        return event_id

    except Exception as e:
        logger.error(f"Error creating calendar block: {e}")
        return ""


def delete_calendar_block(event_id: str) -> bool:
    """Delete a calendar event by its ID.

    Args:
        event_id: The Google Calendar event ID to delete.

    Returns:
        True if successfully deleted, False otherwise.
    """
    try:
        from ..utils.auth import get_calendar_service

        service = get_calendar_service()
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        logger.info(f"Deleted calendar block: {event_id}")
        return True

    except Exception as e:
        logger.error(f"Error deleting calendar block: {e}")
        return False


def watch_event_deletion(event_id: str, webhook_url: str) -> str:
    """Set up a push notification watch on a calendar event for deletion detection.

    Note: Requires a publicly accessible webhook URL. In local development,
    this will log a warning and return empty string.

    Args:
        event_id: The calendar event ID to watch.
        webhook_url: The webhook URL to receive notifications.

    Returns:
        The watch channel ID, or empty string if setup fails.
    """
    try:
        from ..utils.auth import get_calendar_service
        import uuid

        service = get_calendar_service()
        channel_id = str(uuid.uuid4())

        watch_body = {
            "id": channel_id,
            "type": "web_hook",
            "address": webhook_url,
            "params": {"ttl": "86400"},  # 24 hours
        }

        service.events().watch(calendarId="primary", body=watch_body).execute()
        logger.info(f"Watch set up for event {event_id}, channel: {channel_id}")
        return channel_id

    except Exception as e:
        logger.warning(
            f"Could not set up event watch (requires public webhook URL): {e}"
        )
        return ""

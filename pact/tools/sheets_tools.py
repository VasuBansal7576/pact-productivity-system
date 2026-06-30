"""Google Sheets API tools for Pact.

State store for tasks and user patterns. Uses a single Sheets document
with tabs: 'tasks', 'patterns'. Auto-creates the sheet structure on first run.
"""

import os
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Sheet tab names
TASKS_TAB = "tasks"
PATTERNS_TAB = "patterns"


def _get_sheets_id() -> str:
    """Get the Sheets document ID from environment or create a new one."""
    sheets_id = os.environ.get("SHEETS_ID", "")
    if not sheets_id:
        sheets_id = _auto_create_sheet()
        if sheets_id:
            os.environ["SHEETS_ID"] = sheets_id
    return sheets_id


def _auto_create_sheet() -> str:
    """Auto-create a new Google Sheets document for Pact data storage.

    Returns:
        The new spreadsheet ID, or empty string on failure.
    """
    try:
        from ..utils.auth import get_sheets_service

        service = get_sheets_service()

        spreadsheet = {
            "properties": {"title": "PACT — Task Data Store"},
            "sheets": [
                {"properties": {"title": TASKS_TAB}},
                {"properties": {"title": PATTERNS_TAB}},
            ],
        }

        result = service.spreadsheets().create(body=spreadsheet).execute()
        sheet_id = result.get("spreadsheetId", "")

        if sheet_id:
            # Add headers to tasks tab
            from ..models.task import Task

            _update_range(
                service,
                sheet_id,
                f"{TASKS_TAB}!A1",
                [Task.sheets_headers()],
            )

            # Add headers to patterns tab
            from ..models.user_pattern import UserPattern

            _update_range(
                service,
                sheet_id,
                f"{PATTERNS_TAB}!A1",
                [UserPattern.sheets_headers()],
            )

            # Make accessible
            try:
                from googleapiclient.discovery import build
                from ..utils.auth import get_credentials

                drive = build("drive", "v3", credentials=get_credentials())
                drive.permissions().create(
                    fileId=sheet_id,
                    body={"type": "anyone", "role": "writer"},
                ).execute()
            except Exception as e:
                logger.warning(f"Could not share sheet: {e}")

            logger.info(
                f"Auto-created Pact data sheet: "
                f"https://docs.google.com/spreadsheets/d/{sheet_id}"
            )

        return sheet_id

    except Exception as e:
        logger.error(f"Error auto-creating sheet: {e}")
        return ""


def ensure_sheets_setup() -> str:
    """Ensure the Sheets document exists and is properly set up.

    Returns:
        The Sheets document ID.
    """
    return _get_sheets_id()


def _update_range(service, sheet_id: str, range_str: str, values: list) -> None:
    """Helper to update a range in a sheet."""
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=range_str,
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def write_task(task_json: str) -> str:
    """Write a new task to the tasks sheet tab.

    Args:
        task_json: JSON string of the Task object to write.

    Returns:
        'success' if written, error message otherwise.
    """
    try:
        import json
        from ..utils.auth import get_sheets_service
        from ..models.task import Task

        task_data = json.loads(task_json) if isinstance(task_json, str) else task_json
        task = Task(**task_data) if isinstance(task_data, dict) else task_data

        service = get_sheets_service()
        sheet_id = _get_sheets_id()

        if not sheet_id:
            return "Error: No Sheets ID configured and auto-creation failed"

        row = task.to_sheets_row()
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=f"{TASKS_TAB}!A:N",
            valueInputOption="RAW",
            body={"values": [row]},
        ).execute()

        logger.info(f"Wrote task {task.id} to sheets")
        return "success"

    except Exception as e:
        logger.error(f"Error writing task: {e}")
        return f"Error: {str(e)}"


def update_task_fields(task_id: str, fields_json: str) -> str:
    """Update specific fields of a task in the tasks sheet.

    Args:
        task_id: The task ID to find and update.
        fields_json: JSON string of field name-value pairs to update.
                     Example: '{"status": "drafted", "draft_url": "https://..."}'

    Returns:
        'success' if updated, error message otherwise.
    """
    try:
        import json
        from ..utils.auth import get_sheets_service
        from ..models.task import Task

        fields = json.loads(fields_json) if isinstance(fields_json, str) else fields_json
        service = get_sheets_service()
        sheet_id = _get_sheets_id()

        if not sheet_id:
            return "Error: No Sheets ID configured"

        # Read all tasks to find the row
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=f"{TASKS_TAB}!A:N")
            .execute()
        )
        rows = result.get("values", [])
        headers = Task.sheets_headers()

        # Find the row with matching task_id (column A = id)
        target_row = None
        for i, row in enumerate(rows):
            if i == 0:
                continue  # Skip header
            if len(row) > 0 and row[0] == task_id:
                target_row = i + 1  # 1-indexed for Sheets
                break

        if target_row is None:
            return f"Error: Task {task_id} not found in sheet"

        # Update each field
        for field_name, value in fields.items():
            if field_name in headers:
                col_index = headers.index(field_name)
                col_letter = chr(65 + col_index)  # A=0, B=1, etc.
                cell_range = f"{TASKS_TAB}!{col_letter}{target_row}"

                if isinstance(value, datetime):
                    value = value.isoformat()

                service.spreadsheets().values().update(
                    spreadsheetId=sheet_id,
                    range=cell_range,
                    valueInputOption="RAW",
                    body={"values": [[str(value)]]},
                ).execute()

        # Always update updated_at
        updated_at_col = headers.index("updated_at")
        col_letter = chr(65 + updated_at_col)
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"{TASKS_TAB}!{col_letter}{target_row}",
            valueInputOption="RAW",
            body={"values": [[datetime.now().isoformat()]]},
        ).execute()

        logger.info(f"Updated task {task_id} fields: {list(fields.keys())}")
        return "success"

    except Exception as e:
        logger.error(f"Error updating task fields: {e}")
        return f"Error: {str(e)}"


def read_user_pattern(user_id: str) -> str:
    """Read the user pattern from the patterns sheet tab.

    Args:
        user_id: The user ID to look up.

    Returns:
        JSON string of the UserPattern, or a default pattern if not found.
    """
    try:
        import json
        from ..utils.auth import get_sheets_service
        from ..models.user_pattern import UserPattern

        service = get_sheets_service()
        sheet_id = _get_sheets_id()

        if not sheet_id:
            default = UserPattern.default(user_id)
            return json.dumps(default.model_dump())

        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=f"{PATTERNS_TAB}!A:G")
            .execute()
        )
        rows = result.get("values", [])

        # Find row for this user
        for i, row in enumerate(rows):
            if i == 0:
                continue  # Skip header
            if len(row) > 0 and row[0] == user_id:
                pattern = UserPattern.from_sheets_row(row)
                return json.dumps(pattern.model_dump())

        # No pattern found — return default
        default = UserPattern.default(user_id)
        return json.dumps(default.model_dump())

    except Exception as e:
        logger.error(f"Error reading user pattern: {e}")
        import json
        from ..models.user_pattern import UserPattern

        default = UserPattern.default(user_id)
        return json.dumps(default.model_dump())


def update_user_pattern(user_id: str, pattern_json: str) -> str:
    """Update or create the user pattern in the patterns sheet tab.

    Args:
        user_id: The user ID to update.
        pattern_json: JSON string of the UserPattern to write.

    Returns:
        'success' if updated, error message otherwise.
    """
    try:
        import json
        from ..utils.auth import get_sheets_service
        from ..models.user_pattern import UserPattern

        pattern_data = json.loads(pattern_json) if isinstance(pattern_json, str) else pattern_json
        pattern = UserPattern(**pattern_data) if isinstance(pattern_data, dict) else pattern_data

        service = get_sheets_service()
        sheet_id = _get_sheets_id()

        if not sheet_id:
            return "Error: No Sheets ID configured"

        # Check if user already has a row
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=f"{PATTERNS_TAB}!A:G")
            .execute()
        )
        rows = result.get("values", [])

        target_row = None
        for i, row in enumerate(rows):
            if i == 0:
                continue
            if len(row) > 0 and row[0] == user_id:
                target_row = i + 1
                break

        row_data = pattern.to_sheets_row()

        if target_row:
            # Overwrite existing row
            _update_range(
                service,
                sheet_id,
                f"{PATTERNS_TAB}!A{target_row}:G{target_row}",
                [row_data],
            )
        else:
            # Append new row
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=f"{PATTERNS_TAB}!A:G",
                valueInputOption="RAW",
                body={"values": [row_data]},
            ).execute()

        logger.info(f"Updated user pattern for {user_id}")
        return "success"

    except Exception as e:
        logger.error(f"Error updating user pattern: {e}")
        return f"Error: {str(e)}"


def get_active_tasks(user_id: str) -> str:
    """Get all active tasks (scheduled or drafted, deadline > now).

    Args:
        user_id: The user ID (currently all tasks belong to same user).

    Returns:
        JSON string of list of active task dicts.
    """
    try:
        import json
        from ..utils.auth import get_sheets_service
        from ..models.task import Task

        service = get_sheets_service()
        sheet_id = _get_sheets_id()

        if not sheet_id:
            return json.dumps([])

        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=f"{TASKS_TAB}!A:N")
            .execute()
        )
        rows = result.get("values", [])
        now = datetime.now()

        active_tasks = []
        for i, row in enumerate(rows):
            if i == 0:
                continue  # Skip header
            try:
                task = Task.from_sheets_row(row)
                if task.status in ("captured", "scheduled", "drafted") and task.deadline > now:
                    active_tasks.append(task.model_dump(mode="json"))
            except Exception as e:
                logger.warning(f"Skipping malformed row {i}: {e}")

        return json.dumps(active_tasks)

    except Exception as e:
        logger.error(f"Error getting active tasks: {e}")
        import json
        return json.dumps([])


def get_task_history(user_id: str) -> str:
    """Get all completed and missed tasks for analytics.

    Args:
        user_id: The user ID.

    Returns:
        JSON string of list of completed/missed task dicts.
    """
    try:
        import json
        from ..utils.auth import get_sheets_service
        from ..models.task import Task

        service = get_sheets_service()
        sheet_id = _get_sheets_id()

        if not sheet_id:
            return json.dumps([])

        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=f"{TASKS_TAB}!A:N")
            .execute()
        )
        rows = result.get("values", [])

        history = []
        for i, row in enumerate(rows):
            if i == 0:
                continue
            try:
                task = Task.from_sheets_row(row)
                if task.status in ("done", "missed"):
                    history.append(task.model_dump(mode="json"))
            except Exception:
                pass

        return json.dumps(history)

    except Exception as e:
        logger.error(f"Error getting task history: {e}")
        import json
        return json.dumps([])

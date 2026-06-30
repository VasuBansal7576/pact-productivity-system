"""Task data model for Pact productivity system."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal, Optional
import uuid


class Task(BaseModel):
    """Represents a single task captured by the user."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    raw_input: str
    title: str
    deadline: datetime
    domain: Literal[
        "email", "document", "research", "booking", "payment", "form", "other"
    ]
    effort_estimate_minutes: int
    aversiveness_score: float = 0.0  # 0.0-1.0, set by AversivenessClassifier
    status: Literal["captured", "scheduled", "drafted", "done", "missed"] = "captured"
    calendar_event_id: Optional[str] = None
    draft_url: Optional[str] = None  # Gmail draft ID or Google Doc URL
    goal_id: Optional[str] = None  # Link to a goal if applicable
    escalation_tier: Optional[str] = None  # Current escalation level
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def to_sheets_row(self) -> list:
        """Convert to a flat list for Google Sheets storage."""
        return [
            self.id,
            self.raw_input,
            self.title,
            self.deadline.isoformat(),
            self.domain,
            self.effort_estimate_minutes,
            self.aversiveness_score,
            self.status,
            self.calendar_event_id or "",
            self.draft_url or "",
            self.goal_id or "",
            self.escalation_tier or "",
            self.created_at.isoformat(),
            self.updated_at.isoformat(),
        ]

    @classmethod
    def sheets_headers(cls) -> list[str]:
        """Column headers for the tasks sheet tab."""
        return [
            "id",
            "raw_input",
            "title",
            "deadline",
            "domain",
            "effort_estimate_minutes",
            "aversiveness_score",
            "status",
            "calendar_event_id",
            "draft_url",
            "goal_id",
            "escalation_tier",
            "created_at",
            "updated_at",
        ]

    @classmethod
    def from_sheets_row(cls, row: list) -> "Task":
        """Create a Task from a Google Sheets row."""
        headers = cls.sheets_headers()
        data = {}
        for i, header in enumerate(headers):
            if i < len(row):
                val = row[i]
                if header in ("deadline", "created_at", "updated_at") and val:
                    val = datetime.fromisoformat(val)
                elif header == "effort_estimate_minutes" and val:
                    val = int(val)
                elif header == "aversiveness_score" and val:
                    val = float(val)
                elif header in (
                    "calendar_event_id",
                    "draft_url",
                    "goal_id",
                    "escalation_tier",
                ) and val == "":
                    val = None
                data[header] = val
        return cls(**data)

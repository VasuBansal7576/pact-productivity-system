"""User pattern and goal data models for Pact productivity system."""

from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import json


class Goal(BaseModel):
    """A user-defined goal with streak tracking."""

    id: str
    title: str
    description: str = ""
    target_domain: str = "other"  # Links to task domains
    streak_current: int = 0
    streak_best: int = 0
    tasks_linked: int = 0
    tasks_completed: int = 0
    active: bool = True


class UserPattern(BaseModel):
    """Learned behavioral patterns for a user."""

    user_id: str
    avg_completion_minutes_by_domain: Dict[str, float] = Field(default_factory=dict)
    procrastination_domains: List[str] = Field(default_factory=list)
    peak_focus_hours: List[int] = Field(default_factory=lambda: [9, 10, 14, 15])
    tasks_completed_on_time: int = 0
    tasks_missed: int = 0
    goals: List[Goal] = Field(default_factory=list)

    def to_sheets_row(self) -> list:
        """Convert to a flat list for Google Sheets storage."""
        return [
            self.user_id,
            json.dumps(self.avg_completion_minutes_by_domain),
            json.dumps(self.procrastination_domains),
            json.dumps(self.peak_focus_hours),
            self.tasks_completed_on_time,
            self.tasks_missed,
            json.dumps([g.model_dump() for g in self.goals]),
        ]

    @classmethod
    def sheets_headers(cls) -> list[str]:
        """Column headers for the patterns sheet tab."""
        return [
            "user_id",
            "avg_completion_minutes_by_domain",
            "procrastination_domains",
            "peak_focus_hours",
            "tasks_completed_on_time",
            "tasks_missed",
            "goals",
        ]

    @classmethod
    def from_sheets_row(cls, row: list) -> "UserPattern":
        """Create a UserPattern from a Google Sheets row."""
        headers = cls.sheets_headers()
        data = {}
        for i, header in enumerate(headers):
            if i < len(row):
                val = row[i]
                if header in (
                    "avg_completion_minutes_by_domain",
                    "procrastination_domains",
                    "peak_focus_hours",
                ):
                    val = json.loads(val) if val else ([] if header != "avg_completion_minutes_by_domain" else {})
                elif header in ("tasks_completed_on_time", "tasks_missed"):
                    val = int(val) if val else 0
                elif header == "goals":
                    val = [Goal(**g) for g in json.loads(val)] if val else []
                data[header] = val
        return cls(**data)

    @classmethod
    def default(cls, user_id: str) -> "UserPattern":
        """Create a default pattern for a new user."""
        return cls(
            user_id=user_id,
            avg_completion_minutes_by_domain={},
            procrastination_domains=[],
            peak_focus_hours=[9, 10, 14, 15],
            tasks_completed_on_time=0,
            tasks_missed=0,
            goals=[],
        )

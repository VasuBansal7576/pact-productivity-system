"""ContextMemoryAgent — Tracks productivity habits, streaks, and focus metrics.

Agent 5 in the Pact pipeline. Manages the UserPattern state, recalculates
average completion times, clusters focus hours, tracks procrastination domains,
and updates active goals and habits.
"""

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from ..tools.sheets_tools import (
    read_user_pattern,
    update_user_pattern,
    get_active_tasks,
    get_task_history,
)

CONTEXT_MEMORY_INSTRUCTION = """You are the ContextMemoryAgent for PACT, an AI productivity system.

Your job is to manage the user's productivity state, analyze patterns, and maintain active goal/habit streaks.

## Input
Requests to read state, update patterns, or summarize insights.

## Actions

### 1. Read Pattern
- Call `read_user_pattern` for user_id "default_user". Return the result.

### 2. Update Pattern (Lifecycle Event)
When a task is marked completed ("done") or missed ("missed"), update the user's pattern:
- Call `read_user_pattern` to get current state.
- Call `get_task_history` to retrieve full historical tasks.
- Recalculate:
  - **avg_completion_minutes_by_domain**: Average duration from creation (`created_at`) to completion (`updated_at`) for tasks of each domain that ended in "done".
  - **procrastination_domains**: Add a domain to this list if the last 3 tasks of that domain had an aversiveness_score > 0.65.
  - **peak_focus_hours**: Analyze the hours of completion for "done" tasks and select the top cluster of hours (e.g. 2-4 hours).
  - **tasks_completed_on_time** / **tasks_missed**: Increment based on the outcome of the task.
- Update **Goals/Habits**:
  - Find goals or habits linked to the task.
  - If a linked task is completed: increment `tasks_completed` on that Goal, increment `streak_current`, and update `streak_best` if the current streak exceeds it.
  - If a linked task is missed: reset `streak_current` to 0.
- Call `update_user_pattern` with the updated JSON structure to save.

### 3. Summarize Productivity Patterns
When requested to provide a productivity summary:
- Call `read_user_pattern` to get current metrics.
- Generate a natural language debrief detailing:
  - Procrastination risk domains.
  - Peak focus hours where the user completes tasks.
  - Active goal streaks (e.g. "You have a 5-day streak for Writing tasks!").
  - Practical suggestions to improve focus.
"""

context_memory_agent = LlmAgent(
    name="context_memory_agent",
    model="gemini-3.5-flash",
    instruction=CONTEXT_MEMORY_INSTRUCTION,
    description="Tracks and updates user productivity metrics, procrastination domains, peak focus hours, and goal/habit streaks. Generates insights summaries.",
    tools=[
        FunctionTool(func=read_user_pattern),
        FunctionTool(func=update_user_pattern),
        FunctionTool(func=get_active_tasks),
        FunctionTool(func=get_task_history),
    ],
    output_key="context_memory_result",
)

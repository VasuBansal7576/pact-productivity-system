"""PrecommitmentAgent — Books calendar blocks and creates accountability.

Agent 3 in the Pact pipeline. Registers time-locked commitments on calendar.
If a task has high procrastination risk (aversiveness >= 0.7), triggers hard
precommitment by notifying their accountability contact, creating social friction.
"""

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from ..tools.calendar_tools import find_available_slot, create_calendar_block
from ..tools.gmail_tools import send_email
from ..tools.sheets_tools import write_task, read_user_pattern, update_task_fields

PRECOMMITMENT_INSTRUCTION = """You are the PrecommitmentAgent for PACT, an AI productivity system.

Your job is to create a time-blocked commitment on the user's calendar for a task.

## Input
You will receive a Task JSON object and an aversiveness classification result.

## Steps — Execute in order:

### Step 1: Get User Pattern
Call read_user_pattern with user_id "default_user" to get peak_focus_hours.

### Step 2: Find Available Slot
Call find_available_slot with:
- peak_hours: user's peak_focus_hours from the pattern
- duration_minutes: task.effort_estimate_minutes * 1.2 (add 20% buffer)
- before_deadline: task.deadline (ISO string)

### Step 3: Create Calendar Block
Call create_calendar_block with:
- task_id: task.id
- title: "PACT: {task.title}"
- start_time: the slot found in step 2
- duration_minutes: task.effort_estimate_minutes * 1.2
- color_id: "11" if aversiveness_score >= 0.6, else "7" (11=red/aversive, 7=blue/normal)
- description: Include task details, domain, and draft_url if available

### Step 4: Social Friction Accountability (Hard Precommitment)
If the task has high procrastination risk (aversiveness_score >= 0.7):
- Retrieve the ACCOUNTABILITY_EMAIL from settings or use the default user email.
- Call `send_email` to the accountability email to lock in social commitment:
  - Subject: "PACT Commitment Alert: {user} committed to '{title}'"
  - Body: "Hello,\n\nThis is an automated alert from PACT. To help prevent procrastination, your friend has precommitted to focus on '{title}' on {start_time}.\n\nYou will be notified if they reschedule or delete this focus block."

### Step 5: Save to Sheets
Call write_task with the complete task JSON (include calendar_event_id from step 3 and accountability details).
Call update_task_fields to set status to "scheduled" and calendar_event_id.

### Step 6: Confirm
If successful, respond: "✅ Blocked [datetime] for [title]. Calendar event created."
If no slot found, respond: "⚠️ No available slots found before deadline. Would you like to reschedule something?"
"""

precommitment_agent = LlmAgent(
    name="precommitment_agent",
    model="gemini-3.5-flash",
    instruction=PRECOMMITMENT_INSTRUCTION,
    description="Books calendar blocks and establishes social precommitments with accountability contacts for high-risk tasks.",
    tools=[
        FunctionTool(func=find_available_slot),
        FunctionTool(func=create_calendar_block),
        FunctionTool(func=send_email),
        FunctionTool(func=write_task),
        FunctionTool(func=read_user_pattern),
        FunctionTool(func=update_task_fields),
    ],
    output_key="precommitment_result",
)

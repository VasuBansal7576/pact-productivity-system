"""EscalationAgent — Background monitoring agent that enforces task action as deadlines near.

Agent 6 in the Pact pipeline. Periodically checks active tasks and applies
a dynamic temporal discounting escalation curve:
- Normal tasks: 24h / 6h / 1h thresholds.
- High-aversiveness tasks (score >= 0.6): Aggressive 36h / 12h / 3h thresholds to intercept procrastination windows early.
"""

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from ..tools.sheets_tools import get_active_tasks, update_task_fields
from ..tools.gmail_tools import create_draft, send_draft, send_email, check_reply_received
from ..tools.docs_tools import create_document

ESCALATION_INSTRUCTION = """You are the EscalationAgent for PACT, an AI productivity system.

Your job is to run periodically, evaluate all active tasks, and execute escalations.

## Input
A list of active tasks retrieved from `get_active_tasks` for "default_user".

## Dynamic Escalation Curve (Temporal Discounting)
For each active task, calculate time remaining until `deadline` relative to the current time, and apply the appropriate tier. The escalation threshold shifts dynamically based on `aversiveness_score`:

### Curve A: Standard Tasks (aversiveness_score < 0.6)
- **Tier 1 (>= 24 hours remaining)**:
  - If `draft_url` is None (or empty), create first draft and call `update_task_fields` to set status="drafted", escalation_tier="tier1_draft_created".
- **Tier 2 (6 - 24 hours remaining)**:
  - If draft exists and `escalation_tier` is not updated: send draft approval email request, set escalation_tier="tier2_approval_sent".
- **Tier 3 (1 - 6 hours remaining)**:
  - Call `check_reply_received`. If no reply: send urgent email reminder, set escalation_tier="tier3_urgent_reminder_sent".
- **Tier 4 (< 1 hour remaining)**:
  - If no approval and AUTO_SEND_ENABLED is "true": auto-send draft, set status="done", escalation_tier="tier4_auto_sent".
  - Else: send final alert to ACCOUNTABILITY_EMAIL, set status="missed", escalation_tier="tier4_alert_sent".

### Curve B: High-Aversiveness Tasks (aversiveness_score >= 0.6)
- **Tier 1 (>= 36 hours remaining)**:
  - Create first draft if missing, set status="drafted", escalation_tier="tier1_draft_created".
- **Tier 2 (12 - 36 hours remaining)**:
  - Send draft approval email request early, set escalation_tier="tier2_approval_sent".
- **Tier 3 (3 - 12 hours remaining)**:
  - Call `check_reply_received`. If no reply: send urgent email reminder, set escalation_tier="tier3_urgent_reminder_sent".
- **Tier 4 (< 3 hours remaining)**:
  - If no approval and AUTO_SEND_ENABLED is "true": auto-send draft, set status="done", escalation_tier="tier4_auto_sent".
  - Else: send final alert to ACCOUNTABILITY_EMAIL early, set status="missed", escalation_tier="tier4_alert_sent".

## Reporting
Output a short natural language log of all escalation actions performed during this run.
"""

escalation_agent = LlmAgent(
    name="escalation_agent",
    model="gemini-3.5-flash",
    instruction=ESCALATION_INSTRUCTION,
    description="Monitors active tasks and applies dynamic temporal discounting escalation curves based on procrastination risk.",
    tools=[
        FunctionTool(func=get_active_tasks),
        FunctionTool(func=update_task_fields),
        FunctionTool(func=create_draft),
        FunctionTool(func=send_draft),
        FunctionTool(func=send_email),
        FunctionTool(func=check_reply_received),
        FunctionTool(func=create_document),
    ],
    output_key="escalation_result",
)

# Pact — Design Spec

## Goal

Multi-agent productivity system built on Google ADK. When a user captures a task, Pact autonomously produces the first concrete artifact for it (Gmail draft, Google Doc outline, grounded research doc) before the user has to do anything. A background escalation agent monitors all active tasks and takes increasingly autonomous action as deadlines approach. Deploy to Google AI Studio.

---

## Stack

| Layer | Value |
|---|---|
| Agent framework | `google-adk` latest |
| Primary model | `gemini-3.5-flash` |
| Voice input model | `gemini-3.1-flash-live-preview` |
| TTS model | `gemini-3.1-flash-tts-preview` |
| API interface | Interactions API (`client.interactions.create`) — never `generateContent` |
| Background execution | `interactions.create(background=True)` |
| Search grounding | `google_search` built-in tool |
| State store | Google Sheets API v4 |
| Execution | Google Calendar API v3, Gmail API v1, Google Docs API v1 |
| Auth | Google OAuth 2.0 |
| Deployment | Google AI Studio |

---

## Data Models

```python
# models/task.py
from pydantic import BaseModel
from datetime import datetime
from typing import Literal, Optional

class Task(BaseModel):
    id: str
    raw_input: str
    title: str
    deadline: datetime
    domain: Literal["email", "document", "research", "booking", "payment", "form", "other"]
    effort_estimate_minutes: int
    aversiveness_score: float          # 0.0-1.0, set by AversivenessClassifier
    status: Literal["captured", "scheduled", "drafted", "done", "missed"]
    calendar_event_id: Optional[str] = None
    draft_url: Optional[str] = None    # Gmail draft ID or Google Doc URL
    created_at: datetime
    updated_at: datetime
```

```python
# models/user_pattern.py
from pydantic import BaseModel
from typing import Dict, List

class UserPattern(BaseModel):
    user_id: str
    avg_completion_minutes_by_domain: Dict[str, float]
    procrastination_domains: List[str]   # domains where avg aversiveness > 0.65
    peak_focus_hours: List[int]          # hours of day e.g. [9, 10, 14, 15]
    tasks_completed_on_time: int
    tasks_missed: int
```

---

## Google Sheets Schema

Single Sheets document. ID from env var SHEETS_ID.

Tab: tasks — one row per Task. Columns = all Task fields. Append on create. Update status, draft_url, calendar_event_id in place by id lookup.

Tab: patterns — single row per user_id. Overwrite in place on each update. Columns = all UserPattern fields.

---

## OAuth Scopes

```python
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]
```

---

## Tool Signatures

All tools are plain Python functions decorated with @tool from google.adk.tools. Full implementation required.

```python
# tools/calendar_tools.py
def find_available_slot(
    peak_hours: list[int],
    duration_minutes: int,
    before_deadline: datetime,
) -> datetime: ...
# scan Calendar API events.list for free slots within peak_hours before deadline

def create_calendar_block(
    task_id: str,
    title: str,
    start_time: datetime,
    duration_minutes: int,
    color_id: str,        # "11" = red (aversiveness >= 0.6), "7" = blue (normal)
    description: str,
) -> str: ...             # returns calendar event_id

def delete_calendar_block(event_id: str) -> bool: ...

def watch_event_deletion(event_id: str, webhook_url: str) -> None: ...
```

```python
# tools/gmail_tools.py
def create_draft(to: str, subject: str, body: str, task_id: str) -> str: ...  # returns draft_id
def send_draft(draft_id: str) -> bool: ...
def send_email(to: str, subject: str, body: str) -> bool: ...
def check_reply_received(thread_id: str) -> bool: ...
```

```python
# tools/docs_tools.py
def create_document(
    title: str,
    sections: list[dict],   # [{"heading": str, "body": str}]
    task_id: str,
) -> str: ...               # returns shareable doc URL

def append_to_document(doc_url: str, content: str) -> bool: ...
```

```python
# tools/sheets_tools.py
def read_user_pattern(user_id: str) -> dict: ...
def write_task(task: Task) -> bool: ...
def update_task_fields(task_id: str, fields: dict) -> bool: ...
def update_user_pattern(user_id: str, pattern: UserPattern) -> bool: ...
def get_active_tasks(user_id: str) -> list[dict]: ...
# returns tasks where status in ["scheduled","drafted"] and deadline > now
```

---

## Agents

All agents: LlmAgent from google.adk.agents, model="gemini-3.5-flash".

---

### Agent 0 — RootOrchestrator

File: app/agent.py
Sub-agents: all 7 agents below in sub_agents list

Instruction:
- Route to IntakeAgent when input is a new task description
- Route to ContextMemoryAgent when input is a status/summary request
- Route to PostMortemAgent when user marks a task done or missed
- After IntakeAgent returns a Task: call AversivenessClassifier, then PrecommitmentAgent, then FirstDraftAgent if triggers_immediate_draft is true
- Respond with what was created and the artifact link

---

### Agent 1 — IntakeAgent

File: agents/intake_agent.py
Tools: none

Instruction:
- Input: raw user string
- Output: valid JSON matching Task schema, no extra text
- Extract title, deadline (resolve relative refs: "tomorrow", "Friday", "in 2 hours" to absolute datetime), domain (classify into enum), effort_estimate_minutes (estimate from domain + complexity)
- If deadline ambiguous: ask exactly one question, wait for reply, then output JSON
- Set status = "captured", id = uuid4(), created_at/updated_at = now

---

### Agent 2 — AversivenessClassifier

File: agents/aversiveness_classifier.py
Tools: read_user_pattern

Instruction:
- Input: Task JSON + UserPattern
- Compute aversiveness_score 0.0-1.0:
  - task.domain in user.procrastination_domains: +0.4
  - no concrete first step detectable in description: +0.3
  - task.domain in ["document", "research"]: +0.2
  - deadline > 72h from now: +0.2
  - named external recipient or hard external deadline present: -0.2
  - cap at 1.0
- Output JSON: {"aversiveness_score": float, "triggers_immediate_draft": bool}
- triggers_immediate_draft = true if score >= 0.6

---

### Agent 3 — PrecommitmentAgent

File: agents/precommitment_agent.py
Tools: find_available_slot, create_calendar_block, watch_event_deletion, send_email, write_task, read_user_pattern

Instruction:
- Call find_available_slot using user.peak_focus_hours, task.effort_estimate_minutes * 1.2, task.deadline
- Call create_calendar_block — title: "PACT: {task.title}", color_id "11" if aversiveness >= 0.6 else "7", description includes task details + draft_url if available
- Call watch_event_deletion with event_id and webhook /webhooks/calendar
- Call write_task to persist calendar_event_id
- If no slot found: alert user, ask to reschedule something
- Confirm to user: "Blocked [datetime] for [title]. Starting your draft now."

---

### Agent 4 — FirstDraftAgent

File: agents/first_draft_agent.py
Tools: create_draft, create_document, send_email, update_task_fields
Built-in tool: google_search enabled

Instruction:
- Input: Task object
- Domain routing:
  - email: google_search recipient context if name/company present, create_draft with full subject + body, return draft_id
  - document: google_search 2-3 queries on topic, create_document with intro + 4-6 H2 sections each with opening para + bullet scaffold, return doc URL
  - research: google_search 4-5 queries, synthesise, create_document with findings + source list, return doc URL
  - booking: google_search service + location, return top 3 options with booking URLs
  - payment: google_search payment portal, return direct URL + amount if found
  - form: google_search form URL, return prefill link if possible
  - other: output concrete action checklist, first item = single smallest physical step to begin
- Always call update_task_fields with {"draft_url": result, "status": "drafted"} after artifact creation
- Output: one sentence + the link

---

### Agent 5 — ContextMemoryAgent

File: agents/context_memory_agent.py
Tools: read_user_pattern, update_user_pattern, get_active_tasks, write_task

Instruction:
- On read: return UserPattern for USER_ID from Sheets
- On update (after task lifecycle ends):
  - Recompute avg_completion_minutes_by_domain from full history
  - Add domain to procrastination_domains if last 3 tasks of that domain had aversiveness > 0.65
  - Update peak_focus_hours: cluster hours when tasks completed (status="done")
  - Increment tasks_completed_on_time or tasks_missed
  - Call update_user_pattern
- On summary request: return natural language productivity pattern summary

---

### Agent 6 — EscalationAgent

File: agents/escalation_agent.py
Tools: get_active_tasks, update_task_fields, send_email, send_draft, create_draft, create_document
Mode: Background Managed Agent. Launched at app startup via client.interactions.create(background=True). Poll loop every 30 minutes.

Instruction:
- Each poll: call get_active_tasks
- For each task compute time_until_deadline, apply thresholds:
  - >= 24h: draft_url is None -> run FirstDraftAgent domain logic to create draft
  - 6h-24h: draft exists -> send_email user with draft link + "Reply YES to send". No draft -> create now.
  - 1h-6h: check_reply_received. No reply -> resend approval email, urgent subject.
  - < 1h: no reply AND AUTO_SEND_ENABLED="true" -> send_draft with subject "[AUTO-SENT BY PACT]". Else -> send final alert.
- After each action: update_task_fields with escalation metadata

---

### Agent 7 — PostMortemAgent

File: agents/postmortem_agent.py
Tools: get_active_tasks, update_task_fields, update_user_pattern, read_user_pattern, send_email

Instruction:
- Triggered when deadline passes or user marks done
- Set task status "done" or "missed"
- Call ContextMemoryAgent update flow
- Send one-paragraph debrief email: what happened, pattern it reflects, one concrete change for next time
- Every Sunday: aggregate past week -> send weekly summary: on-time count, missed count, top procrastination domain, one insight

---

## Agent Wiring

```python
# app/agent.py
from google.adk.agents import LlmAgent
from google import genai
import os
from agents.intake_agent import intake_agent
from agents.aversiveness_classifier import aversiveness_classifier
from agents.precommitment_agent import precommitment_agent
from agents.first_draft_agent import first_draft_agent
from agents.context_memory_agent import context_memory_agent
from agents.escalation_agent import escalation_agent
from agents.postmortem_agent import postmortem_agent

root_agent = LlmAgent(
    name="pact_orchestrator",
    model="gemini-3.5-flash",
    instruction="[routing logic per Agent 0 spec above]",
    sub_agents=[
        intake_agent,
        aversiveness_classifier,
        precommitment_agent,
        first_draft_agent,
        context_memory_agent,
        escalation_agent,
        postmortem_agent,
    ],
)

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def start_escalation_loop():
    client.interactions.create(
        model="gemini-3.5-flash",
        input="Start escalation monitoring loop. Poll active tasks every 30 minutes.",
        background=True,
        store=True,
    )
```

---

## Voice — Live API

Wire to RootOrchestrator via ADK bidirectional streaming. On web client connection open Live API session (gemini-3.1-flash-live-preview). Stream mic audio -> transcript -> root_agent input. TTS via gemini-3.1-flash-tts-preview. Web UI: mic button -> WebSocket Live API session -> render transcript + agent response + artifact links.

---

## Webhook — Calendar Block Deletion

Endpoint: POST /webhooks/calendar
On receive: look up task by calendar_event_id. If task.status != "done" -> send_email to ACCOUNTABILITY_EMAIL: "You deleted your PACT block for [task.title] (deadline: [deadline]) without completing it."

---

## File Structure

```
pact/
├── app/
│   └── agent.py
├── agents/
│   ├── __init__.py
│   ├── intake_agent.py
│   ├── aversiveness_classifier.py
│   ├── precommitment_agent.py
│   ├── first_draft_agent.py
│   ├── context_memory_agent.py
│   ├── escalation_agent.py
│   └── postmortem_agent.py
├── tools/
│   ├── __init__.py
│   ├── calendar_tools.py
│   ├── gmail_tools.py
│   ├── docs_tools.py
│   └── sheets_tools.py
├── models/
│   ├── __init__.py
│   ├── task.py
│   └── user_pattern.py
├── utils/
│   ├── __init__.py
│   └── auth.py
├── static/
│   └── index.html
├── requirements.txt
├── .env.example
└── DESIGN_SPEC.md
```

---

## requirements.txt

```
google-adk>=1.0.0
google-genai>=1.0.0
google-auth>=2.0.0
google-auth-oauthlib>=1.0.0
google-auth-httplib2>=0.2.0
google-api-python-client>=2.0.0
pydantic>=2.0.0
python-dotenv>=1.0.0
fastapi>=0.100.0
uvicorn>=0.20.0
```

---

## .env.example

```
GEMINI_API_KEY=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/oauth/callback
SHEETS_ID=
USER_ID=default_user
ACCOUNTABILITY_EMAIL=
AUTO_SEND_ENABLED=false
```

---

## Done Criteria

- User speaks or types a task -> system creates Task, scores aversiveness, books calendar block, produces draft artifact, returns artifact link in one interaction
- EscalationAgent running in background, fires Gmail actions at all 4 thresholds
- UserPattern in Sheets updates after each task lifecycle
- App deployed and publicly accessible via Google AI Studio
- OAuth working end to end across all 4 Google APIs
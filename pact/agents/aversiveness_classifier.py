"""AversivenessClassifier — Scores task procrastination risk.

Agent 2 in the Pact pipeline. Takes a Task + UserPattern and computes
an aversiveness score (0.0-1.0) using an additive rubric based on
behavioral psychology research on procrastination triggers.
"""

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from ..tools.sheets_tools import read_user_pattern

AVERSIVENESS_INSTRUCTION = """You are the AversivenessClassifier for PACT, an AI productivity system.

Your job is to compute a procrastination risk score for a task.

## Input
You will receive:
1. A Task JSON object
2. A UserPattern JSON object (call read_user_pattern tool with the user_id to get this)

## Scoring Rubric
Start at 0.0 and add:
- Task domain is in user's procrastination_domains: **+0.4**
- No concrete first step detectable in the task description: **+0.3**
- Task domain is "document" or "research": **+0.2**
- Deadline is more than 72 hours from now: **+0.2**
- Named external recipient or hard external deadline present in description: **-0.2**
- Cap the final score at 1.0

## Output
You MUST output ONLY valid JSON — no extra text:
{
    "aversiveness_score": <float 0.0-1.0>,
    "triggers_immediate_draft": <true if score >= 0.6, false otherwise>,
    "scoring_breakdown": "<brief explanation of score components>"
}

## Important
- Use the read_user_pattern tool to get the user's pattern data
- The user_id is "default_user" unless otherwise specified
- Be accurate with the rubric — each factor is additive
- triggers_immediate_draft = true means the system should immediately create a first draft to reduce the activation energy barrier
"""

aversiveness_classifier = LlmAgent(
    name="aversiveness_classifier",
    model="gemini-3.5-flash",
    instruction=AVERSIVENESS_INSTRUCTION,
    description="Computes procrastination risk score (0.0-1.0) for a task based on user patterns and task characteristics. Returns aversiveness_score and triggers_immediate_draft flag.",
    tools=[FunctionTool(func=read_user_pattern)],
    output_key="aversiveness_result",
)

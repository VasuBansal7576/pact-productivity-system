"""RootOrchestrator and FastAPI application for Pact.

Wires together all 7 sub-agents, exposes API endpoints for the Web UI,
handles Google OAuth redirects, serves the static single-page app,
implements the calendar deletion webhook, and runs the background escalation loop.
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, WebSocket, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pact.app")

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

# Import agents
from ..agents.intake_agent import intake_agent
from ..agents.aversiveness_classifier import aversiveness_classifier
from ..agents.precommitment_agent import precommitment_agent
from ..agents.first_draft_agent import first_draft_agent
from ..agents.context_memory_agent import context_memory_agent
from ..agents.escalation_agent import escalation_agent
from ..agents.postmortem_agent import postmortem_agent

# Import tools
from ..tools.sheets_tools import (
    ensure_sheets_setup,
    get_active_tasks,
    get_task_history,
    read_user_pattern,
    update_user_pattern,
    update_task_fields,
)
from ..tools.gmail_tools import send_email

# Define Root Orchestrator Agent (as specified in ADK wireframe)
root_agent = LlmAgent(
    name="pact_orchestrator",
    model="gemini-3.5-flash",
    instruction="""You are the RootOrchestrator for PACT. Route queries to appropriate sub-agents:
    - IntakeAgent: For new tasks and scheduling.
    - ContextMemoryAgent: For status, productivity pattern summaries, or insights.
    - PostMortemAgent: For reflections when tasks are done or missed.
    """,
    sub_agents=[
        intake_agent,
        aversiveness_classifier,
        precommitment_agent,
        first_draft_agent,
        context_memory_agent,
        escalation_agent,
        postmortem_agent,
    ],
    description="Root agent of the Pact multi-agent system. Coordinates routing between all specialized agents.",
)

# Helper to run any ADK agent synchronously and get its text response
def run_agent_sync(agent, message_str: str, session_id: str = "default_session") -> str:
    import time
    max_retries = 3
    delay = 2
    
    for attempt in range(max_retries):
        try:
            runner = InMemoryRunner(agent=agent)
            runner.auto_create_session = True
            content = types.Content(parts=[types.Part.from_text(text=message_str)])
            events = runner.run(user_id="default_user", session_id=session_id, new_message=content)
            
            final_text = ""
            for event in events:
                if event.message:
                    if hasattr(event.message, "parts") and event.message.parts:
                        for part in event.message.parts:
                            if part.text:
                                final_text += part.text
                    elif isinstance(event.message, str):
                        final_text += event.message
            return final_text
            
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "503" in err_str or "unavailable" in err_str.lower() or "limit" in err_str.lower():
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Gemini API rate limit or demand spike detected on {agent.name} "
                        f"(Attempt {attempt+1}/{max_retries}). Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue
            logger.error(f"Error executing agent {agent.name}: {e}")
            raise e
    return ""

def clean_json_response(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

# Local session memory store path
SESSIONS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "sessions.json",
)

def load_session_history(session_id: str) -> list:
    """Load conversation history for the session."""
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r") as f:
                data = json.load(f)
                return data.get(session_id, [])
        except Exception as e:
            logger.warning(f"Could not load sessions file: {e}")
    return []

def save_session_history(session_id: str, history: list) -> None:
    """Save conversation history for the session."""
    data = {}
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            pass
    data[session_id] = history[-15:] # Keep last 15 exchanges
    try:
        with open(SESSIONS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save sessions file: {e}")

# Main multi-agent workflow orchestrator
def execute_pact_pipeline(user_input: str, session_id: str = "default_session") -> dict:
    """Executes the correct multi-agent routing or pipeline based on user input.

    Returns:
        dict: Response payload for UI containing log list and final response.
    """
    logs = []
    input_lower = user_input.lower()
    
    # Load short term memory context
    history = load_session_history(session_id)
    history_context = ""
    if history:
        history_context = "Prior Conversation History:\n"
        for exchange in history:
            history_context += f"User: {exchange.get('user')}\nAgent: {exchange.get('agent')}\n"
        history_context += "\nNew input: "

    # Route 1: Summary / Analytics Request
    if any(keyword in input_lower for keyword in ["summary", "pattern", "insights", "analytics", "how am i doing", "report"]):
        logs.append("Routing request to ContextMemoryAgent for pattern analysis...")
        summary = run_agent_sync(context_memory_agent, f"{history_context}Give me a productivity summary. Context: {user_input}")
        
        # Save to memory
        history.append({"user": user_input, "agent": summary})
        save_session_history(session_id, history)
        
        return {"response": summary, "logs": logs, "type": "summary"}

    # Route 2: Mark Task Done / Missed (Reflection)
    elif any(keyword in input_lower for keyword in ["completed", "done", "missed", "reflection", "finish"]):
        logs.append("Routing to PostMortemAgent for task lifecycle reflection...")
        reflection = run_agent_sync(postmortem_agent, f"{history_context}Process post-mortem reflection request: {user_input}")
        
        # Save to memory
        history.append({"user": user_input, "agent": reflection})
        save_session_history(session_id, history)
        
        return {"response": reflection, "logs": logs, "type": "reflection"}

    # Route 3: Standard Task Intake Pipeline
    else:
        logs.append("Initiating task capture pipeline...")

        # Step A: IntakeAgent parses raw text to Task JSON
        logs.append("IntakeAgent: Parsing relative times and domains...")
        intake_output = run_agent_sync(intake_agent, f"{history_context}{user_input}")
        cleaned_intake = clean_json_response(intake_output)

        try:
            task_dict = json.loads(cleaned_intake)
        except Exception as e:
            logger.error(f"Failed parsing IntakeAgent output: {e}. Output was: {intake_output}")
            return {
                "response": "I couldn't quite structure that task. Could you specify the deadline more clearly?",
                "logs": logs,
                "type": "error"
            }

        title = task_dict.get("title", "Task")
        sub_tasks = task_dict.get("sub_tasks", [])
        
        if sub_tasks:
            logs.append(f"Cognitive load trigger activated! Deconstructing '{title}' into {len(sub_tasks)} physical micro-steps.")
            
            # We process each sub-task as a task
            created_sub_tasks = []
            for i, sub in enumerate(sub_tasks):
                sub_title = sub.get("title")
                sub_est = sub.get("effort_estimate_minutes", 15)
                sub_dom = sub.get("domain", task_dict.get("domain"))
                
                logs.append(f"Scheduling micro-step {i+1}: '{sub_title}'...")
                
                # Formulate a unique sub-task dict
                sub_task_dict = {
                    "raw_input": f"Micro-step of {title}: {sub_title}",
                    "title": f"[PACT Part {i+1}] {sub_title}",
                    "deadline": task_dict.get("deadline"),
                    "domain": sub_dom,
                    "effort_estimate_minutes": sub_est,
                    "status": "captured"
                }
                
                # Classify aversiveness for each sub-task
                pattern_json = read_user_pattern("default_user")
                classification_input = json.dumps({"task": sub_task_dict, "pattern": json.loads(pattern_json)})
                classifier_output = run_agent_sync(aversiveness_classifier, classification_input)
                cleaned_classifier = clean_json_response(classifier_output)
                
                try:
                    class_dict = json.loads(cleaned_classifier)
                    aversiveness_score = class_dict.get("aversiveness_score", 0.0)
                except Exception:
                    aversiveness_score = 0.5
                
                sub_task_dict["aversiveness_score"] = aversiveness_score
                
                # Precommit/Schedule sub-task
                precommit_input = json.dumps({"task": sub_task_dict, "aversiveness_result": {"aversiveness_score": aversiveness_score, "triggers_immediate_draft": False}})
                precommit_output = run_agent_sync(precommitment_agent, precommit_input)
                
                # Refetch to confirm creation
                active_tasks = json.loads(get_active_tasks("default_user"))
                matching = [t for t in active_tasks if t["title"] == sub_task_dict["title"]]
                if matching:
                    created_sub_tasks.append(matching[0])
            
            summary_msg = f"Successfully deconstructed and scheduled '{title}' into {len(created_sub_tasks)} micro-steps. Check your calendar for focus blocks!"
            
            # Save to memory
            history.append({"user": user_input, "agent": summary_msg})
            save_session_history(session_id, history)
            
            return {
                "response": summary_msg,
                "logs": logs,
                "type": "deconstruction",
                "task": task_dict
            }
            
        else:
            logs.append(f"Task structured: '{title}' (Domain: {task_dict.get('domain')}, Est: {task_dict.get('effort_estimate_minutes')}m)")

            # Step B: Get UserPattern for Aversiveness classification
            pattern_json = read_user_pattern("default_user")

            # Step C: AversivenessClassifier computes score
            logs.append("AversivenessClassifier: Evaluating procrastination triggers...")
            classification_input = json.dumps({"task": task_dict, "pattern": json.loads(pattern_json)})
            classifier_output = run_agent_sync(aversiveness_classifier, classification_input)
            cleaned_classifier = clean_json_response(classifier_output)

            try:
                class_dict = json.loads(cleaned_classifier)
                aversiveness_score = class_dict.get("aversiveness_score", 0.0)
                triggers_draft = class_dict.get("triggers_immediate_draft", False)
            except Exception as e:
                logger.error(f"Failed parsing AversivenessClassifier output: {e}. Output was: {classifier_output}")
                aversiveness_score = 0.5
                triggers_draft = False

            logs.append(f"Aversiveness score: {aversiveness_score} (Immediate Draft Required: {triggers_draft})")
            task_dict["aversiveness_score"] = aversiveness_score

            # Step D: PrecommitmentAgent blocks Calendar slot
            logs.append("PrecommitmentAgent: Checking peak hours and blocking calendar...")
            precommit_input = json.dumps({"task": task_dict, "aversiveness_result": class_dict})
            precommit_output = run_agent_sync(precommitment_agent, precommit_input)
            logs.append(f"Calendar block response: {precommit_output}")

            # Fetch scheduled task details to get ID or updated calendar details
            active_tasks = json.loads(get_active_tasks("default_user"))
            matching_tasks = [t for t in active_tasks if t["title"] == task_dict["title"]]
            task_obj = matching_tasks[0] if matching_tasks else task_dict

            # Step E: FirstDraftAgent (if aversiveness triggers immediate draft)
            draft_url = None
            if triggers_draft:
                logs.append("FirstDraftAgent: Activation energy threshold exceeded! Generating first draft...")
                draft_output = run_agent_sync(first_draft_agent, json.dumps(task_obj))
                logs.append(f"Draft generated: {draft_output}")

                # Refetch task to display artifact URL
                active_tasks = json.loads(get_active_tasks("default_user"))
                matching_tasks = [t for t in active_tasks if t["title"] == task_dict["title"]]
                if matching_tasks:
                    draft_url = matching_tasks[0].get("draft_url")

            # Compile final response
            summary_msg = f"Successfully captured and scheduled '{title}'."
            if draft_url:
                summary_msg += f" Built your draft: {draft_url}"
            elif task_obj.get("calendar_event_id"):
                summary_msg += f" Time blocked on Calendar."

            # Save to memory
            history.append({"user": user_input, "agent": summary_msg})
            save_session_history(session_id, history)

            return {
                "response": summary_msg,
                "logs": logs,
                "type": "capture",
                "task": task_obj
            }

# FastAPI server initialization
app = FastAPI(title="Pact — Productivity Multi-Agent")

# Enable CORS for local UI testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serves static UI files
pact_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
static_dir = os.path.join(pact_dir, "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_home():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            return f.read()
    return "<h1>PACT Web UI files not found. Serve from /static/index.html</h1>"

@app.post("/chat")
async def chat_endpoint(payload: dict):
    message = payload.get("message", "")
    session_id = payload.get("session_id", "default_session")
    if not message:
        raise HTTPException(status_code=400, detail="Empty message")
    try:
        result = execute_pact_pipeline(message, session_id=session_id)
        return result
    except Exception as e:
        logger.exception("Pipeline execution failed")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks")
async def get_tasks_endpoint():
    active = json.loads(get_active_tasks("default_user"))
    history = json.loads(get_task_history("default_user"))
    return {"active": active, "history": history}

@app.get("/patterns")
async def get_patterns_endpoint():
    pattern_json = read_user_pattern("default_user")
    return json.loads(pattern_json)

# OAuth 2.0 Web Application Flow Endpoints
@app.get("/oauth/login")
async def oauth_login(request: Request):
    """Initiates Google OAuth Web Server flow."""
    redirect_uri = str(request.url_for("oauth_callback"))
    if "localhost" not in redirect_uri and redirect_uri.startswith("http:"):
        redirect_uri = redirect_uri.replace("http:", "https:")
    
    try:
        from ..utils.auth import get_authorization_url
        auth_url = get_authorization_url(redirect_uri)
        return RedirectResponse(auth_url)
    except Exception as e:
        logger.error(f"Failed to generate auth URL: {e}")
        raise HTTPException(status_code=500, detail=f"OAuth init failed: {e}")


@app.get("/oauth/callback")
async def oauth_callback(request: Request, code: str = None, error: str = None):
    """Receives callback, exchanges authorization code for user token."""
    if error:
        return HTMLResponse(f"<h3>OAuth Authentication Failed: {error}</h3>", status_code=400)
    
    if code:
        redirect_uri = str(request.url_for("oauth_callback"))
        if "localhost" not in redirect_uri and redirect_uri.startswith("http:"):
            redirect_uri = redirect_uri.replace("http:", "https:")
        
        try:
            from ..utils.auth import fetch_and_save_token
            fetch_and_save_token(code, redirect_uri)
            return HTMLResponse(
                "<h3>OAuth Success! PACT is now connected to your Google account. "
                "You may close this tab and return to the main dashboard.</h3>"
            )
        except Exception as e:
            logger.error(f"Error exchanging OAuth code: {e}")
            return HTMLResponse(f"<h3>OAuth Code Exchange Failed: {e}</h3>", status_code=500)
            
    return RedirectResponse(url="/")

# Google Calendar Event Deletion Webhook
@app.post("/webhooks/calendar")
async def calendar_webhook(request: Request):
    # Retrieve webhook body and triggers deletion check
    logger.info("Received Google Calendar watch callback notification")
    
    # Run the validation and accountability trigger in background
    from .agent import verify_and_alert_deleted_events
    try:
        verify_and_alert_deleted_events()
    except Exception as e:
        logger.warning(f"Error checking deleted events: {e}")
        
    return {"status": "processed"}

# Voice API audio file upload & transcription handler
@app.post("/chat/voice")
async def chat_voice_endpoint(file: UploadFile = File(...)):
    """Transcribes mic voice recording using Gemini API and runs PACT pipeline."""
    try:
        from google import genai
        # Initialize client
        genai_client = genai.Client()
        audio_bytes = await file.read()
        
        # Call Gemini multi-modal generation for speech to text transcription
        response = genai_client.models.generate_content(
            model="gemini-3.5-flash",
            contents=[
                types.Part.from_bytes(
                    data=audio_bytes,
                    mime_type=file.content_type or "audio/webm"
                ),
                "Transcribe the audio exactly. Output only the transcription text. Do not add explanations."
            ]
        )
        
        transcript = response.text or ""
        transcript = transcript.strip()
        logger.info(f"Voice Transcription: {transcript}")
        
        if not transcript:
            return {"response": "I couldn't hear any task details. Try again.", "logs": [], "type": "error"}
            
        result = execute_pact_pipeline(transcript)
        result["transcript"] = transcript
        return result
        
    except Exception as e:
        logger.exception("Voice transcription failed")
        raise HTTPException(status_code=500, detail=str(e))

def verify_and_alert_deleted_events():
    """Verify all calendar events for scheduled tasks. Alert accountability if deleted."""
    from ..utils.auth import get_calendar_service
    
    active_tasks = json.loads(get_active_tasks("default_user"))
    service = get_calendar_service()
    accountability_email = os.environ.get("ACCOUNTABILITY_EMAIL", "")
    
    for t_data in active_tasks:
        event_id = t_data.get("calendar_event_id")
        if event_id:
            try:
                service.events().get(calendarId="primary", eventId=event_id).execute()
            except Exception as e:
                if "410" in str(e) or "404" in str(e):
                    logger.warning(f"Detected deleted calendar event {event_id} for task {t_data.get('title')}")
                    
                    # Social friction trigger check (high procrastination risk tasks)
                    is_high_risk = t_data.get("aversiveness_score", 0.0) >= 0.7
                    
                    if accountability_email:
                        subject = f"PACT Alert: Focus block modified for {t_data.get('title')}"
                        risk_tag = " [HIGH RISK]" if is_high_risk else ""
                        body = (
                            f"Accountability Alert{risk_tag}:\n\n"
                            f"The user has deleted or modified their PACT focus block for '{t_data.get('title')}' "
                            f"(deadline: {t_data.get('deadline')}) without completing it.\n\n"
                            f"As their designated accountability partner, please remind them to stay committed!"
                        )
                        send_email(accountability_email, subject, body)
                    # Clear event id and reset status to captured
                    update_task_fields(t_data.get("id"), json.dumps({"calendar_event_id": "", "status": "captured"}))

# Background Escalation Poller Loop
async def run_escalation_poller():
    while True:
        try:
            logger.info("Running background task escalation checks...")
            active_tasks_json = get_active_tasks("default_user")
            
            # Execute EscalationAgent
            response = run_agent_sync(escalation_agent, active_tasks_json, session_id="escalation_session")
            logger.info(f"Escalation output: {response}")
            
            # Also run event watch checks
            verify_and_alert_deleted_events()
            
        except Exception as e:
            logger.error(f"Error in background escalation poller: {e}")
            
        await asyncio.sleep(1800)  # Wake up every 30 minutes

# Startup hook to setup Sheets and start background threads
@app.on_event("startup")
def startup_event():
    logger.info("Ensuring Google Sheets database structure is initialized...")
    try:
        ensure_sheets_setup()
    except Exception as e:
        logger.warning(f"Could not connect to Sheets on startup (requires credentials): {e}")
        
    logger.info("Starting background task escalation poller loop...")
    asyncio.create_task(run_escalation_poller())

# PACT — Multi-Agent Productivity Companion

Pact is an autonomous, agentic productivity system built on the Google Agent Development Kit (ADK) and Gemini models, designed to defeat procrastination. It captures tasks, schedules focus blocks, generates drafts, and runs a background escalation agent.

## Core Features

- **Intelligent Task Capture**: Voice or text input is parsed into structured tasks with deadline and domain classification.
- **Aversiveness Evaluation**: Tasks are scored (0.0 - 1.0) using an additive psychological rubric to measure procrastination risk.
- **Precommitment Blocking**: High-risk tasks trigger automated Google Calendar slots during preferred peak productivity hours.
- **Autonomous Draft Execution**: FirstDraftAgent generates initial concrete artifacts (Gmail drafts, Google Docs templates, or checklists) using Google Search grounding.
- **Active Escalation monitoring**: Background loop checks deadlines and escalates (Tier 1-4) with email reminders and auto-sending.
- **Habit and Streak Analytics**: ContextMemoryAgent monitors focus statistics and goal completion metrics.

---

## Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd Vibe2Ship/pact
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   Create a `.env` file from the example:
   ```bash
   cp .env.example .env
   ```
   Fill in the required keys:
   - `GEMINI_API_KEY`: Google AI Studio API Key.
   - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`: OAuth credentials from Google Cloud Console.
   - `ACCOUNTABILITY_EMAIL`: Email to receive alert escalations.

4. **Add Google Client Secret file**:
   Place your downloaded OAuth `client_secret.json` from the Google Cloud Console in the `pact/` directory.

---

## Running Locally

To start the FastAPI web server:
```bash
uvicorn pact.app.agent:app --reload --port 8000
```
Then visit [http://localhost:8000](http://localhost:8000) in your browser.

---

## Deployed on Google Cloud Run via Google AI Studio

This app is ready to deploy directly. Refer to [Google AI Studio Deployment Docs](https://ai.google.dev/gemini-api/docs/aistudio-deploying) to deploy your custom multi-agent application with environment variables configured.

# ContextFlow — AI-Powered Knowledge & Task Management

DigiPlus technical-assessment implementation. A small, persistent workplace continuity app that captures meeting notes and decisions, extracts actionable follow-ups with AI, tracks work to closure, links relevant team knowledge, and prepares handoff summaries.

## Quick start (Python)

Requires Python 3.10+ (3.12 recommended).

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Optional, enables AI: export AI_API_KEY='your_key_here'
# Optional: export AI_MODEL='gpt-4o-mini'
uvicorn app.main:app --reload
```

Open http://localhost:8000. Swagger API docs: http://localhost:8000/docs.

## Docker / deployment

```bash
cp .env.example .env
# Edit .env and supply an API key, or remove the AI_API_KEY line to use fallback mode.
docker compose up --build -d
```

Open http://localhost:8000. Deploy the same Docker container to a VM with a persistent `/app/data` volume; expose port 8000 through a reverse proxy with HTTPS. Add environment variables in the deployment service, not in source control. The `compose.yaml` persists SQLite data in a named volume, and binds `./logs` for inspection. **This archive has not been deployed automatically.**

## Demo workflow (5 minutes)

1. Create a meeting titled `Sprint planning` dated today, participants `Aisha, Rahul, Priya`.
2. Paste sample notes:
   ```
   Aisha, Rahul and Priya discussed release readiness.
   Decision: ship the dashboard in the November release.
   Rahul will fix the login bug by 2026-11-03.
   Priya will update onboarding docs by 2026-11-05.
   The team agreed to review outstanding items next week.
   ```
3. Click `AI recap`. With AI configured, a summary, decisions, owners and tasks are extracted and persisted.
4. Open **Action items**; reassign a task, mark a task blocked, then close another with a mandatory outcome. Click **History** to inspect updates.
5. Create next week's meeting, click **View details**, and **Carry forward** the previous meeting's unfinished tasks. Original task identity and event history are kept.
6. In **Knowledge base**, paste a team policy. Click **Related knowledge** on a meeting to ask AI for the most relevant records.
7. Open **Handoff center**, generate a catch-up brief of recent decisions and unfinished work.
8. Dashboard **Risk Radar** highlights blocked, unassigned or overdue work.
9. View structured JSON events in `logs/app.jsonl`.

## Architecture

Browser SPA (vanilla JS/CSS) -> FastAPI endpoints -> SQLAlchemy ORM -> SQLite. AI integration uses an OpenAI-compatible chat-completions API through HTTPX, with a low-temperature system prompt and validated JSON result. The AI model is configured via `AI_MODEL`, `AI_BASE_URL`, and `AI_API_KEY` (or `OPENAI_API_KEY`). No key is embedded in the frontend.

Database tables: `meetings` (agenda, notes, summary, decisions, participants), `tasks` (owner, due date, status, outcome, originating meeting), `task_events` (immutable chronological history including carry-forward references), `knowledge` (plain-text team references).

## AI prompts and data flow

- **Extraction:** send title + original notes to model along with instructions to only output JSON `{summary, decisions, action_items:[{title,owner,due_date}]}`; validate types and date shape. Persist the result only after validated success.
- **Knowledge linking:** provide the meeting text and excerpts from up to 40 stored knowledge documents, requesting existing relevant document IDs only. Filter returned IDs to the known database records.
- **Handoff:** provide recent meeting summaries/decisions and open task metadata to generate a concise Markdown transition brief.
- User-provided notes/documents are treated as untrusted source data in prompts. Keep API secrets server-side. Results are assistance and should be human-reviewed.

**AI failures:** network errors, missing key, malformed output, timeout, or provider outage produce an explicitly labeled fallback. Extraction does not invent tasks or overwrite the stored recap on failure; original notes remain. Handoff uses a transparent local template. Knowledge linking uses a limited word-overlap fallback. This is not silently presented as AI.

## Original feature: Continuity Risk Radar

The dashboard automatically flags open tasks that are overdue, blocked, or unassigned. Unlike a passive task list, it surfaces context-transfer failure risks early, helping teams know which owner or next step must be clarified before a meeting ends. Risk checks are deterministic and explainable; AI supplies the contextual summaries.

## Logging

JSON-lines log file: `logs/app.jsonl`. Per-request ID is accepted from a sanitized `X-Request-ID` header or newly generated UUID; it follows all events and model calls in a request using contextvars. Events include meeting creation, task creation/reassignment/closure, carry-forward, AI call success/failure and latency, extraction outcome, request status, and exception class. Do not log note content, prompts, credentials or raw exception messages. Log level INFO; ERROR for failed AI calls, WARNING for fallback paths. 

## Key API endpoints

| Route | Purpose |
|---|---|
| `POST/GET /api/meetings` | Create/list meetings |
| `PATCH /api/meetings/{id}` | Update meeting or close it |
| `POST /api/meetings/{id}/extract` | AI recap and task extraction |
| `POST /api/meetings/{id}/carry-forward?from_meeting_id=N` | Link outstanding work to next meeting |
| `GET /api/meetings/{id}/carried` | View carried items |
| `POST/GET /api/tasks` | Create/list action items |
| `PATCH /api/tasks/{id}` | Set owner, deadline, status and outcome |
| `POST/GET /api/knowledge` | Save/list knowledge records |
| `GET /api/meetings/{id}/knowledge` | AI knowledge-link suggestions |
| `POST /api/handoff` | AI handoff brief |
| `GET /api/radar` | Risk Radar |
| `GET /api/health` | Health and configured-AI flag |

## Assumptions and known limitations

- No user authentication, team permissions, actual invite/calendar/email sync, chat connectors, media transcription or file ingestion in this small MVP; text notes and pasted knowledge are the input source.
- Task event history is preserved; carried-forward tasks are linked by events rather than copied/moved. Historical links remain after task closure.
- Re-running AI extraction may add duplicate tasks. Review before repeated extraction; production would use idempotency keys or a review/approve extraction step.
- Output from an LLM can be inaccurate; owner/date/action extraction needs human confirmation. The date validator checks shape rather than date existence.
- Knowledge linking provides relevant ID suggestions, not semantic vector search or citations in generated handoff briefs.
- SQLite single-instance use; production multiuser deployment should use PostgreSQL plus auth, audit controls, background jobs and rate limits.
- The service should run behind HTTPS; no public deployment URL is included in this archive. Add a domain/reverse proxy and persistent storage on the target host.

## Tests

```bash
pytest -q
```

## Assessment criteria addressed

Functionality: CRUD workflows and task lifecycle. AI: model prompts, validated extraction and graceful fallback. Engineering: separated models/database/AI/routes. Data: SQLite persistence, task events. Logging: structured request correlation. Originality: Risk Radar. UX: responsive interactive dashboard.

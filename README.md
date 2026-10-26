# Agentic Interfaces Workshop

Workshop materials on agentic interfaces for AI-driven user experiences

## Workshop structure

Hosted through the ACM using the HACLab

### Nov 5th 5PM - 6:30PM on AG-UI

- 20 minutes basic info
- 20 minutes interactive questions
- 35 minutes hands on build
- 15 minutes for questions and mingle after

### Nov 19th 5PM - 6:30PM on A2UI

- 20 minutes basic info
- 20 minutes interactive questions
- 35 minutes hands on build
- 15 minutes for questions and mingle after

## Project

School task planner agent

- AG-UI version will only work with text
- A2UI version will build upon the previous example, incorporating A2UI to produce a final working app

### Project setup

Expectation that students will have their own laptop with Git, Node and VS Code installed. An Azure API Endpoint and Key will be available for use. We will need a way to distribute these to the participants.

An initial version of the app will be available for them to clone. The workshop will guide them on adding snippets to complete the development of the app.

- The initial version needs to find the balance between giving them enough so the focus is on what is being taught without giving them too much so that they do not understand how it is working.
- Perhaps the repo can tags set for different development stages of the app, so if someone falls behind they can be given a tag to pull a more complete version of the app.


## Workshop planning milestones


### Sept 22 - 28
- [x] Sept 28: Confirm dates and location

### Sept 29 - Oct 5
- Oct 5th: Outline for both presentations complete

### Oct 6 - Oct 12
- Oct 12: First presentation demo functionally complete 

### Oct 13 - Oct 19

### Oct 20 - Oct 26
- Oct 20: First wave of comms
- Oct 26: First presentation polished and ready

### Oct 27 - Nov 4
- Oct 29: First presentation dry run
- Nov 2: Second wave of comms

### Nov 6 - Nov 9
- Nov 10: Second presentation polished and ready

### Nov 10 - Nov 18
- Nov 12: Second presentation dry run
- Nov 16: Third wave of comms

# AG-UI + A2UI Study Planner Demo

A presentation-friendly student study planner that demonstrates:

- an **AG-UI 1.0** POST + Server-Sent Events endpoint using the official Python `ag-ui-protocol` package;
- a custom **A2UI catalog** supplied to the planning agent;
- A2UI operations streamed from the agent to the frontend inside AG-UI `CUSTOM` events;
- a React renderer for the schedule catalog;
- a live right-side event inspector that displays each AG-UI event as it arrives;
- a "Demonstrate classic 16" control for the requested older/core event catalogue.

> The current AG-UI protocol contains more event families than the classic 16. This project intentionally highlights the requested set for teaching/demo purposes.

## Architecture

```text
Student input
    |
    v
React/Vite frontend
    |  POST RunAgentInput
    v
FastAPI /agent
    |  AG-UI RUN_STARTED / STATE / STEP / TOOL events
    |  OpenAI or Azure OpenAI call from env config
    |  Agent sees custom A2UI catalog
    |  Agent returns A2UI operations
    |  AG-UI CUSTOM(name="a2ui") carries each operation
    v
SSE stream --------------------------------------+
    |                                             |
    +--> Event inspector (raw JSON, arrival order)|
    |                                             |
    +--> Chat renderer (TEXT_MESSAGE_*)            |
    |                                             |
    +--> A2UI renderer (CUSTOM a2ui payloads) <----+
```

## Requested classic 16 events

The UI tracks:

1. `RUN_STARTED`
2. `RUN_FINISHED`
3. `RUN_ERROR`
4. `STEP_STARTED`
5. `STEP_FINISHED`
6. `TEXT_MESSAGE_START`
7. `TEXT_MESSAGE_CONTENT`
8. `TEXT_MESSAGE_END`
9. `TOOL_CALL_START`
10. `TOOL_CALL_ARGS`
11. `TOOL_CALL_END`
12. `TOOL_CALL_RESULT`
13. `STATE_SNAPSHOT`
14. `STATE_DELTA`
15. `MESSAGES_SNAPSHOT`
16. `CUSTOM`

The “Demonstrate classic 16” button performs two deterministic demo runs: one ends with `RUN_FINISHED`, the other with `RUN_ERROR`. This shows both terminal event types without violating the one-terminal-per-run lifecycle.

## Run it

### 1. Backend

Python 3.11+ is recommended.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `backend/.env`:

```env
OPENAPI_KEY=your_real_key_here
OPENAI_MODEL=gpt-4o-mini
FRONTEND_ORIGIN=http://localhost:5173
```

Azure OpenAI is also supported. If you want to use the Azure endpoint you shared, set:

```env
AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com/
AZURE_OPENAI_API_KEY=your_azure_openai_key_here
OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
FRONTEND_ORIGIN=http://localhost:5173
```

Then start FastAPI:

```bash
uvicorn main:app --reload --port 8000
```

Health check: `http://localhost:8000/health`

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## How A2UI is used

`shared/study-planner-catalog.json` is the contract given to the agent. The model may use only these components:

- `WeekSchedule`
- `DayColumn`
- `StudyBlock`
- `DeadlineBadge`
- `ScheduleSummary`
- `WarningBanner`

The agent returns A2UI v0.9-style `createSurface` and `updateComponents` operations. Components use flat IDs and child references rather than an executable/nested UI tree. The frontend receives each A2UI operation over the AG-UI stream and routes it to the catalog renderer.

## Files to show during a presentation

- `backend/main.py` — AG-UI endpoint and event emission
- `shared/study-planner-catalog.json` — catalog supplied to the agent
- `frontend/src/agui.ts` — raw SSE event intake
- `frontend/src/a2ui.tsx` — declarative catalog renderer
- `frontend/src/App.tsx` — event panel and integration

## Notes

- The environment variable is intentionally named `OPENAPI_KEY` because that was the requested name, even though OpenAI examples commonly use `OPENAI_API_KEY`.
- The event inspector stores raw decoded event JSON in exactly the order received by the browser.
- The frontend parses SSE directly instead of hiding transport details behind a chat component. This is intentional: it makes the event flow visible for demonstration.

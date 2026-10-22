from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from openai import AzureOpenAI, OpenAI

from ag_ui.core import (
    CustomEvent,
    EventType,
    MessagesSnapshotEvent,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.encoder import EventEncoder

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "shared" / "study-planner-catalog.json"
CATALOG = json.loads(CATALOG_PATH.read_text())
CATALOG_ID = CATALOG["catalogId"]

app = FastAPI(title="AG-UI + A2UI Study Planner", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def using_azure_openai() -> bool:
    return (
        os.getenv("AZURE_OPENAI_ENDPOINT") is not None
        or os.getenv("AZURE_OPENAI_API_KEY") is not None
        or os.getenv("OPENAI_API_TYPE") == "azure"
    )


def get_client() -> OpenAI:
    if using_azure_openai():
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        if not endpoint:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT is not set.")

        key = os.getenv("AZURE_OPENAI_API_KEY")
        if not key:
            raise RuntimeError("AZURE_OPENAI_API_KEY is not set.")

        api_version = os.getenv("OPENAI_API_VERSION")
        if not api_version:
            raise RuntimeError("OPENAI_API_VERSION is not set for Azure OpenAI.")

        return AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=key,
            api_version=api_version,
        )

    key = os.getenv("OPENAPI_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENAPI_KEY (or OPENAI_API_KEY) is not set. Copy backend/.env.example to backend/.env and add your key."
        )
    return OpenAI(api_key=key)


def model_name() -> str:
    if using_azure_openai():
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        if deployment:
            return deployment

    return os.getenv("OPENAI_MODEL", "gpt-latest")


def camel_event_dict(event: Any) -> dict[str, Any]:
    """Useful only for local logging/tests; EventEncoder handles wire serialization."""
    return event.model_dump(by_alias=True, exclude_none=True)


def extract_user_text(input_data: RunAgentInput) -> str:
    parts: list[str] = []
    for message in input_data.messages:
        if getattr(message, "role", None) == "user":
            content = getattr(message, "content", "")
            if isinstance(content, str):
                parts.append(content)
    return "\n\n".join(parts).strip()


def tool_call_events(
    encoder: EventEncoder,
    tool_call_id: str,
    message_id: str,
    tool_name: str,
    arguments: str,
    result_message_id: str,
    result: str,
):
    yield encoder.encode(ToolCallStartEvent(
        type=EventType.TOOL_CALL_START,
        tool_call_id=tool_call_id,
        tool_call_name=tool_name,
        parent_message_id=message_id,
    ))
    yield encoder.encode(ToolCallArgsEvent(
        type=EventType.TOOL_CALL_ARGS,
        tool_call_id=tool_call_id,
        delta=arguments,
    ))
    yield encoder.encode(ToolCallEndEvent(
        type=EventType.TOOL_CALL_END,
        tool_call_id=tool_call_id,
    ))
    yield encoder.encode(ToolCallResultEvent(
        type=EventType.TOOL_CALL_RESULT,
        message_id=result_message_id,
        tool_call_id=tool_call_id,
        content=result,
        role="tool",
    ))


def planner_prompt(student_input: str) -> str:
    catalog_text = json.dumps(CATALOG, indent=2)
    return f"""
You are a university study-planning agent that emits A2UI v0.9-style declarative UI.

The user gives you:
- a rough week schedule / availability,
- assignments,
- due dates,
- estimated completion times.

Build a realistic seven-day plan. Split long assignments when useful. Never schedule work after its due date. Preserve fixed classes/work/sleep constraints. Leave reasonable transition/break time and do not invent impossible availability.

You MUST use only components in this A2UI catalog:
{catalog_text}

Return ONLY valid JSON with this exact top-level shape:
{{
  "assistantMessage": "brief explanation of the schedule strategy",
  "a2ui": [
    {{
      "version": "v0.9",
      "createSurface": {{
        "surfaceId": "week-schedule",
        "catalogId": "{CATALOG_ID}"
      }}
    }},
    {{
      "version": "v0.9",
      "updateComponents": {{
        "surfaceId": "week-schedule",
        "components": [
          {{"id":"root","component":"WeekSchedule","title":"...","subtitle":"...","children":["summary","monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]}}
        ]
      }}
    }}
  ]
}}

Rules for components:
- Include exactly one WeekSchedule root with id "root".
- Include exactly one ScheduleSummary with id "summary".
- Include one DayColumn for each Monday-Sunday, even if empty.
- DayColumn children reference StudyBlock and optional DeadlineBadge ids.
- Every referenced child id must exist in the same components array.
- StudyBlock start/end should be readable local times such as "3:00 PM".
- StudyBlock minutes must agree with start/end as closely as practical.
- Use WarningBanner only when the workload cannot fit or inputs are materially incomplete.
- Do not use HTML or executable code.

Student input:
{student_input}
""".strip()


def call_planner(student_input: str) -> dict[str, Any]:
    client = get_client()
    response = client.chat.completions.create(
        model=model_name(),
        messages=[
            {"role": "system", "content": "Return strict JSON only. You are generating a safe declarative A2UI surface from the supplied catalog."},
            {"role": "user", "content": planner_prompt(student_input)},
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    if not isinstance(data.get("a2ui"), list):
        raise ValueError("Model response did not contain an a2ui array")
    return data


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "catalogId": CATALOG_ID,
        "model": model_name(),
        "provider": "azure" if using_azure_openai() else "openai",
        "apiKeyConfigured": bool(
            os.getenv("OPENAPI_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("AZURE_OPENAI_API_KEY")
        ),
    }


@app.get("/catalog")
def catalog() -> JSONResponse:
    return JSONResponse(CATALOG)


@app.post("/agent")
async def agent_endpoint(input_data: RunAgentInput, request: Request) -> StreamingResponse:
    encoder = EventEncoder(accept=request.headers.get("accept"))
    student_input = extract_user_text(input_data)

    async def events() -> AsyncGenerator[str, None]:
        message_id = str(uuid.uuid4())
        tool_call_id = str(uuid.uuid4())
        try:
            yield encoder.encode(RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=input_data.thread_id,
                run_id=input_data.run_id,
            ))

            yield encoder.encode(MessagesSnapshotEvent(
                type=EventType.MESSAGES_SNAPSHOT,
                messages=input_data.messages,
            ))

            yield encoder.encode(StateSnapshotEvent(
                type=EventType.STATE_SNAPSHOT,
                snapshot={
                    "phase": "planning",
                    "catalogId": CATALOG_ID,
                    "scheduleReady": False,
                },
            ))

            yield encoder.encode(StepStartedEvent(
                type=EventType.STEP_STARTED,
                step_name="build-week-plan",
            ))

            tool_args = json.dumps({
                "studentInput": student_input,
                "catalogId": CATALOG_ID,
            })
            result = call_planner(student_input)
            for event in tool_call_events(
                encoder,
                tool_call_id,
                message_id,
                "generate_a2ui_week_schedule",
                tool_args,
                str(uuid.uuid4()),
                json.dumps({"status": "ok", "a2uiMessages": len(result["a2ui"])}),
            ):
                yield event

            # A2UI is transported inside AG-UI custom events. The frontend routes these
            # payloads into its declarative A2UI renderer and also displays the raw event.
            for operation in result["a2ui"]:
                yield encoder.encode(CustomEvent(
                    type=EventType.CUSTOM,
                    name="a2ui",
                    value=operation,
                ))

            yield encoder.encode(StateDeltaEvent(
                type=EventType.STATE_DELTA,
                delta=[
                    {"op": "replace", "path": "/phase", "value": "complete"},
                    {"op": "replace", "path": "/scheduleReady", "value": True},
                ],
            ))

            yield encoder.encode(StepFinishedEvent(
                type=EventType.STEP_FINISHED,
                step_name="build-week-plan",
            ))

            yield encoder.encode(TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=message_id,
                role="assistant",
            ))
            text = result.get("assistantMessage", "I built the week schedule from your availability and deadlines.")
            # Split text into a few chunks so the event panel visibly demonstrates streaming.
            words = text.split()
            for i in range(0, len(words), 7):
                delta = " ".join(words[i:i + 7]) + (" " if i + 7 < len(words) else "")
                if delta:
                    yield encoder.encode(TextMessageContentEvent(
                        type=EventType.TEXT_MESSAGE_CONTENT,
                        message_id=message_id,
                        delta=delta,
                    ))
            yield encoder.encode(TextMessageEndEvent(
                type=EventType.TEXT_MESSAGE_END,
                message_id=message_id,
            ))

            yield encoder.encode(RunFinishedEvent(
                type=EventType.RUN_FINISHED,
                thread_id=input_data.thread_id,
                run_id=input_data.run_id,
            ))

        except Exception as exc:
            yield encoder.encode(RunErrorEvent(
                type=EventType.RUN_ERROR,
                message=str(exc),
                code="STUDY_PLANNER_ERROR",
            ))

    return StreamingResponse(events(), media_type=encoder.get_content_type())


@app.post("/demo-events")
async def demo_events(input_data: RunAgentInput, request: Request, terminal: str = "finished") -> StreamingResponse:
    """Emit a deterministic event stream without calling OpenAI.

    The frontend calls this endpoint twice: one valid successful run and one valid failing
    run. Taken together they demonstrate all requested classic 16 types without putting
    RUN_FINISHED and RUN_ERROR in the same AG-UI run.
    """
    encoder = EventEncoder(accept=request.headers.get("accept"))

    async def events() -> AsyncGenerator[str, None]:
        msg_id = str(uuid.uuid4())
        tool_id = str(uuid.uuid4())
        yield encoder.encode(RunStartedEvent(type=EventType.RUN_STARTED, thread_id=input_data.thread_id, run_id=input_data.run_id))
        yield encoder.encode(MessagesSnapshotEvent(type=EventType.MESSAGES_SNAPSHOT, messages=input_data.messages))
        yield encoder.encode(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot={"demo": True, "count": 0}))
        yield encoder.encode(StepStartedEvent(type=EventType.STEP_STARTED, step_name="event-demo"))
        for event in tool_call_events(
            encoder,
            tool_id,
            msg_id,
            "demo_tool",
            '{"example":true}',
            str(uuid.uuid4()),
            '{"ok":true}',
        ):
            yield event
        yield encoder.encode(CustomEvent(type=EventType.CUSTOM, name="demo.custom", value={"purpose": "Shows CUSTOM payloads"}))
        yield encoder.encode(StateDeltaEvent(type=EventType.STATE_DELTA, delta=[{"op": "replace", "path": "/count", "value": 1}]))
        yield encoder.encode(StepFinishedEvent(type=EventType.STEP_FINISHED, step_name="event-demo"))
        yield encoder.encode(TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=msg_id, role="assistant"))
        yield encoder.encode(TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id=msg_id, delta="Classic AG-UI event demo."))
        yield encoder.encode(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=msg_id))
        if terminal == "error":
            yield encoder.encode(RunErrorEvent(type=EventType.RUN_ERROR, message="Intentional demo error event", code="DEMO_ONLY"))
        else:
            yield encoder.encode(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=input_data.thread_id, run_id=input_data.run_id))

    return StreamingResponse(events(), media_type=encoder.get_content_type())

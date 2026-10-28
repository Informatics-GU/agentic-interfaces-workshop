from __future__ import annotations

import json
import os
import uuid
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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

app = FastAPI(title="AG-UI Study Planner", version="1.0.0")
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
    return f"""
You are a university study-planning agent.

The user gives you a rough week schedule / availability, classes, assignments,
due dates, and estimated completion times.

Return the complete plan as plain text with short section headings, blank lines,
and simple bullets. Do not return JSON, HTML, UI components, or code fences.

Include these sections:
Classes and fixed commitments:
- List every supplied class and other fixed commitment with its days and times.
  Preserve unnamed classes as unnamed; do not invent course names.
Assignments:
- List every supplied homework assignment with its course (if supplied), deadline,
  and estimated completion time. Explicitly flag missing details.
Weekly plan:
- Include Monday through Sunday, even when no study is scheduled.
- Show readable local start/end times, assignment names, and duration for each
  homework block, fitting homework around the existing schedule.
Plan summary:
- Briefly explain prioritization and give the total scheduled study time.
- Identify any unfinished work, insufficient availability, missing information,
  or assumptions. Ask specific questions when needed.

Build a realistic seven-day plan. Split long assignments when useful. Never
schedule work after its due date or overlap fixed classes/work/sleep constraints.
Respect study preferences and leave reasonable transition/break time. Do not
invent availability or silently drop assignments. When work cannot fit before a
deadline, state how much remains unscheduled instead of forcing it into the plan.
If dates or availability are ambiguous, state assumptions or ask for clarification.

Student input:
{student_input}
""".strip()


def call_planner(student_input: str) -> str:
    client = get_client()
    response = client.chat.completions.create(
        model=model_name(),
        messages=[
            {"role": "system", "content": "You are a study-planning agent. Return a complete, readable text plan using headings and simple bullets."},
            {"role": "user", "content": planner_prompt(student_input)},
        ],
    )
    content = response.choices[0].message.content
    if not content or not content.strip():
        raise ValueError("Model response did not contain a text plan")
    return content


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "model": model_name(),
        "provider": "azure" if using_azure_openai() else "openai",
        "apiKeyConfigured": bool(
            os.getenv("OPENAPI_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("AZURE_OPENAI_API_KEY")
        ),
    }


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
                    "scheduleReady": False,
                },
            ))

            yield encoder.encode(StepStartedEvent(
                type=EventType.STEP_STARTED,
                step_name="build-week-plan",
            ))

            tool_args = json.dumps({
                "studentInput": student_input,
            })
            result = call_planner(student_input)
            for event in tool_call_events(
                encoder,
                tool_call_id,
                message_id,
                "generate_week_schedule",
                tool_args,
                str(uuid.uuid4()),
                json.dumps({"status": "ok"}),
            ):
                yield event

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

            for i in range(0, len(result), 160):
                yield encoder.encode(TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT,
                    message_id=message_id,
                    delta=result[i:i + 160],
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

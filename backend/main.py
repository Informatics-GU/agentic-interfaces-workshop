from __future__ import annotations

import asyncio
import json
import os
import re
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

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
SURFACES = ("intake", "preferences", "week-schedule")

# The planner LLM only sees the schedule components; form components are built by the backend.
SCHEDULE_COMPONENTS = {
    "WeekSchedule", "DayColumn", "StudyBlock", "DeadlineBadge", "ScheduleSummary", "WarningBanner",
}
SCHEDULE_CATALOG = {
    "catalogId": CATALOG_ID,
    "components": {k: v for k, v in CATALOG["components"].items() if k in SCHEDULE_COMPONENTS},
}

LENGTH_OPTIONS = [
    ("short", "Short sprints", "25 to 30 minute blocks with quick breaks"),
    ("medium", "Steady blocks", "45 to 60 minute blocks"),
    ("long", "Deep work", "90 minute blocks, fewer of them"),
]
PACING_OPTIONS = [
    ("early", "Finish early", "Front-load work so deadlines never feel tight"),
    ("even", "Spread evenly", "Roughly the same amount each day"),
    ("late", "Closer to the deadline", "Leave more of the work for the final days"),
]

SAMPLE_SCHEDULE = {
    "availability": {
        "monday": "Class 9:00-10:15 and 1:00-2:15; free after 3:00 PM",
        "tuesday": "Class 10:30-11:45; work 4:00-8:00 PM",
        "wednesday": "Class 9:00-10:15 and 1:00-2:15; free after 3:00 PM",
        "thursday": "Class 10:30-11:45; work 4:00-8:00 PM",
        "friday": "Class 9:00-10:15; free after 11:00 AM",
        "saturday": "Mostly free after noon",
        "sunday": "Free 1:00-6:00 PM",
    },
    "assignments": [
        {"name": "Physics reading", "course": "Physics", "dueDay": "Tuesday", "dueTime": "09:00", "hours": 0.5},
        {"name": "Physics homework", "course": "Physics", "dueDay": "Thursday", "dueTime": "23:59", "hours": 2},
        {"name": "New Testament reading", "course": "Religion", "dueDay": "Friday", "dueTime": "09:00", "hours": 0.5},
        {"name": "Algorithms problem set", "course": "CS", "dueDay": "Sunday", "dueTime": "23:59", "hours": 3},
        {"name": "Mobile app feature", "course": "CS", "dueDay": "Monday", "dueTime": "08:00", "hours": 4},
    ],
    "limits": "I prefer not to study after 10 PM.",
}

app = FastAPI(title="AG-UI + A2UI Study Planner", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------

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

        return AzureOpenAI(azure_endpoint=endpoint, api_key=key, api_version=api_version)

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


def llm_json(system: str, user: str) -> dict[str, Any]:
    response = get_client().chat.completions.create(
        model=model_name(),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )
    data = json.loads(response.choices[0].message.content or "{}")
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# A2UI message builders
# ---------------------------------------------------------------------------

def a2ui(operation: dict[str, Any]) -> dict[str, Any]:
    return {"version": "v0.9", **operation}


def create_surface(surface_id: str) -> dict[str, Any]:
    return a2ui({"createSurface": {"surfaceId": surface_id, "catalogId": CATALOG_ID}})


def update_components(surface_id: str, components: list[dict[str, Any]]) -> dict[str, Any]:
    return a2ui({"updateComponents": {"surfaceId": surface_id, "components": components}})


def update_data_model(surface_id: str, value: Any, path: str = "/") -> dict[str, Any]:
    return a2ui({"updateDataModel": {"surfaceId": surface_id, "path": path, "value": value}})


def delete_surface(surface_id: str) -> dict[str, Any]:
    return a2ui({"deleteSurface": {"surfaceId": surface_id}})


def show_surface(surface_id: str, components: list[dict[str, Any]], data: Any = None) -> list[dict[str, Any]]:
    """Replace whatever surface is on screen with this one."""
    ops = [delete_surface(s) for s in SURFACES if s != surface_id]
    ops.append(create_surface(surface_id))
    ops.append(update_components(surface_id, components))
    if data is not None:
        ops.append(update_data_model(surface_id, data))
    return ops


def button(component_id: str, label: str, event: str, variant: str = "primary", requires: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": component_id,
        "component": "Button",
        "label": label,
        "variant": variant,
        "requires": requires or [],
        "action": {"event": {"name": event}},
    }


def text_field(component_id: str, label: str, path: str, placeholder: str = "", multiline: bool = False) -> dict[str, Any]:
    return {
        "id": component_id,
        "component": "TextField",
        "label": label,
        "placeholder": placeholder,
        "multiline": multiline,
        "value": {"path": path},
    }


# ---------------------------------------------------------------------------
# Step 1: intake form
# ---------------------------------------------------------------------------

def blank_assignment() -> dict[str, Any]:
    return {"name": "", "course": "", "dueDay": "Friday", "dueTime": "23:59", "hours": 1}


def build_intake(schedule: dict[str, Any] | None) -> list[dict[str, Any]]:
    schedule = schedule or {}
    saved = schedule.get("availability") or {}
    data = {
        "availability": {d: saved.get(d, "") for d in DAYS},
        "assignments": schedule.get("assignments") or [blank_assignment()],
        "limits": schedule.get("limits", ""),
    }
    components: list[dict[str, Any]] = [
        {
            "id": "root",
            "component": "Form",
            "title": "Tell me about your week",
            "subtitle": "Share what is already fixed and what you need to get done. Next, I'll suggest when you could study.",
            "children": ["sec-week", "sec-assignments", "sec-limits", "submit"],
        },
        {
            "id": "sec-week",
            "component": "Section",
            "title": "Your typical week",
            "description": "Classes, work and other fixed commitments, plus any time you know is free. Leave a day blank if nothing is fixed.",
            "columns": 2,
            "children": [f"day-{d}" for d in DAYS],
        },
    ]
    for d in DAYS:
        placeholder = "Class 9:00 to 10:15, work 4 to 8 PM, free after 3" if d == "monday" else "Commitments and free time"
        components.append(text_field(f"day-{d}", d.capitalize(), f"/availability/{d}", placeholder))
    components += [
        {
            "id": "sec-assignments",
            "component": "Section",
            "title": "Assignments",
            "description": "One row per assignment, with the due date and how long you think it will take.",
            "children": ["assignments"],
        },
        {"id": "assignments", "component": "AssignmentList", "value": {"path": "/assignments"}},
        {
            "id": "sec-limits",
            "component": "Section",
            "title": "Hard limits",
            "children": ["limits"],
        },
        text_field("limits", "Anything I should always protect?", "/limits", "Sleep 11 PM to 7 AM, no studying after 10 PM, church Sunday morning", multiline=True),
        button("submit", "Choose study times", "submit_schedule", requires=["/assignments"]),
    ]
    return show_surface("intake", components, data)


# ---------------------------------------------------------------------------
# Step 2: study-time preferences (windows are tailored by the LLM)
# ---------------------------------------------------------------------------

def build_preferences(options: list[dict[str, Any]], prefs: dict[str, Any] | None) -> list[dict[str, Any]]:
    prefs = prefs or {}
    data = {
        "prefs": {
            "windows": prefs.get("windows") or [o["id"] for o in options if o.get("recommended")],
            "sessionLength": prefs.get("sessionLength", "medium"),
            "pacing": prefs.get("pacing", "even"),
            "notes": prefs.get("notes", ""),
        }
    }

    components: list[dict[str, Any]] = [
        {
            "id": "root",
            "component": "Form",
            "title": "When do you want to study?",
            "subtitle": "These windows fit around what you told me. Pick any that sound right.",
            "children": ["sec-windows", "sec-length", "sec-pacing", "sec-notes", "actions"],
        },
        {"id": "sec-windows", "component": "Section", "title": "Study windows", "children": ["windows"]},
        {
            "id": "windows",
            "component": "ChoiceGroup",
            "mode": "multi",
            "label": "Choose one or more",
            "value": {"path": "/prefs/windows"},
            "children": [f"win-{i}" for i in range(len(options))],
        },
    ]
    for i, o in enumerate(options):
        components.append({
            "id": f"win-{i}",
            "component": "OptionCard",
            "optionId": o["id"],
            "label": o["label"],
            "description": o["description"],
            "meta": o["when"],
            "badge": "Suggested" if o.get("recommended") else "",
        })

    components += [
        {"id": "sec-length", "component": "Section", "title": "Session length", "children": ["length"]},
        {
            "id": "length",
            "component": "ChoiceGroup",
            "mode": "single",
            "value": {"path": "/prefs/sessionLength"},
            "children": [f"len-{k}" for k, _, _ in LENGTH_OPTIONS],
        },
        {"id": "sec-pacing", "component": "Section", "title": "Pacing", "children": ["pacing"]},
        {
            "id": "pacing",
            "component": "ChoiceGroup",
            "mode": "single",
            "value": {"path": "/prefs/pacing"},
            "children": [f"pace-{k}" for k, _, _ in PACING_OPTIONS],
        },
        {"id": "sec-notes", "component": "Section", "title": "Anything else?", "children": ["notes"]},
        text_field("notes", "Notes for the planner", "/prefs/notes", "I focus best before noon, keep Friday nights free", multiline=True),
        {"id": "actions", "component": "ActionBar", "children": ["btn-back", "btn-build"]},
        button("btn-back", "Edit my schedule", "back_to_schedule", variant="secondary"),
        button("btn-build", "Build my week", "submit_preferences", requires=["/prefs/windows"]),
    ]
    for k, label, desc in LENGTH_OPTIONS:
        components.append({"id": f"len-{k}", "component": "OptionCard", "optionId": k, "label": label, "description": desc})
    for k, label, desc in PACING_OPTIONS:
        components.append({"id": f"pace-{k}", "component": "OptionCard", "optionId": k, "label": label, "description": desc})

    return show_surface("preferences", components, data)


def options_prompt(schedule: dict[str, Any]) -> str:
    return f"""
You help a university student decide WHEN to study. Read their weekly commitments and propose 3 to 5 concrete study windows
that are actually free for them. Respect their hard limits. Prefer windows that give each assignment enough room before its due date.

Return ONLY valid JSON with this exact shape:
{{
  "assistantMessage": "one or two sentences on what you noticed about their week",
  "options": [
    {{
      "id": "kebab-case-id",
      "label": "short title",
      "description": "one sentence on why this window works for this student",
      "when": "Mon to Thu, 3:00 to 6:00 PM",
      "recommended": true
    }}
  ]
}}

Rules:
- Unique kebab-case ids.
- Never propose a window that overlaps a class, work shift or hard limit.
- Mark 1 to 3 options as recommended.
- Plain text only, no HTML.

Student input:
{format_schedule(schedule)}
""".strip()


def clean_options(raw: dict[str, Any]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw.get("options") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        if not label:
            continue
        option_id = re.sub(r"[^a-z0-9-]+", "-", str(item.get("id") or label).lower()).strip("-") or f"option-{len(options) + 1}"
        if option_id in seen:
            option_id = f"{option_id}-{len(options) + 1}"
        seen.add(option_id)
        options.append({
            "id": option_id,
            "label": label[:60],
            "description": str(item.get("description", "")).strip()[:200],
            "when": str(item.get("when", "")).strip()[:80],
            "recommended": bool(item.get("recommended")),
        })
    return options[:5]


def call_options(schedule: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    raw = llm_json(
        "Return strict JSON only. You suggest realistic study windows for a student.",
        options_prompt(schedule),
    )
    options = clean_options(raw)
    if not options:
        return "Here are some common study windows. Pick the ones that suit you.", DEFAULT_OPTIONS
    message = str(raw.get("assistantMessage") or "Here are some study windows that fit around your week.")
    return message, options


# ---------------------------------------------------------------------------
# Step 3: weekly plan
# ---------------------------------------------------------------------------

def fmt_time(value: str) -> str:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not match:
        return value
    hour, minute = int(match[1]), match[2]
    return f"{(hour % 12) or 12}:{minute} {'AM' if hour < 12 else 'PM'}"


def clean_schedule(data: Any) -> dict[str, Any]:
    data = data if isinstance(data, dict) else {}
    raw_availability = data.get("availability") if isinstance(data.get("availability"), dict) else {}
    availability = {d: str(raw_availability.get(d, "")).strip()[:400] for d in DAYS}

    assignments: list[dict[str, Any]] = []
    for row in data.get("assignments") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        try:
            hours = float(row.get("hours") or 1)
        except (TypeError, ValueError):
            hours = 1.0
        due_day = str(row.get("dueDay", "Friday")).strip().capitalize()
        if due_day.lower() not in DAYS:
            due_day = "Friday"
        assignments.append({
            "name": name[:120],
            "course": str(row.get("course", "")).strip()[:80],
            "dueDay": due_day,
            "dueTime": str(row.get("dueTime", "23:59")).strip()[:5],
            "hours": max(0.25, min(hours, 40.0)),
        })

    return {
        "availability": availability,
        "assignments": assignments[:20],
        "limits": str(data.get("limits", "")).strip()[:600],
    }


def clean_prefs(data: Any, options: list[dict[str, Any]]) -> dict[str, Any]:
    data = data if isinstance(data, dict) else {}
    raw = data.get("prefs") if isinstance(data.get("prefs"), dict) else {}
    valid_windows = {o["id"] for o in options}
    windows = [str(w) for w in (raw.get("windows") or []) if str(w) in valid_windows]
    length = raw.get("sessionLength") if raw.get("sessionLength") in {k for k, _, _ in LENGTH_OPTIONS} else "medium"
    pacing = raw.get("pacing") if raw.get("pacing") in {k for k, _, _ in PACING_OPTIONS} else "even"
    return {
        "windows": windows,
        "sessionLength": length,
        "pacing": pacing,
        "notes": str(raw.get("notes", "")).strip()[:500],
    }


def format_schedule(schedule: dict[str, Any]) -> str:
    lines = ["Rough week schedule:"]
    for d in DAYS:
        lines.append(f"{d.capitalize()}: {schedule['availability'].get(d) or 'nothing specified'}")
    if schedule.get("limits"):
        lines += ["", f"Hard limits and fixed commitments: {schedule['limits']}"]
    lines += ["", "Assignments:"]
    for a in schedule["assignments"]:
        course = f" ({a['course']})" if a["course"] else ""
        lines.append(f"{a['name']}{course} — due {a['dueDay']} {fmt_time(a['dueTime'])} — {a['hours']:g} hours")
    return "\n".join(lines)


def format_preferences(prefs: dict[str, Any], options: list[dict[str, Any]]) -> str:
    by_id = {o["id"]: o for o in options}
    windows = [f"- {by_id[w]['label']}: {by_id[w]['when']}" for w in prefs["windows"] if w in by_id]
    length = next(f"{label} ({desc})" for k, label, desc in LENGTH_OPTIONS if k == prefs["sessionLength"])
    pacing = next(f"{label} ({desc})" for k, label, desc in PACING_OPTIONS if k == prefs["pacing"])
    lines = ["Preferred study windows (schedule inside these):", *windows, f"Session length: {length}", f"Pacing: {pacing}"]
    if prefs["notes"]:
        lines.append(f"Extra notes: {prefs['notes']}")
    return "\n".join(lines)


def planner_prompt(student_input: str) -> str:
    catalog_text = json.dumps(SCHEDULE_CATALOG, indent=2)
    return f"""
You are a university study-planning agent that emits A2UI v0.9-style declarative UI.

The user gives you:
- a rough week schedule / availability,
- assignments, due dates and estimated completion times,
- their preferred study windows, session length and pacing.

Build a realistic seven-day plan. Split long assignments when useful. Never schedule work after its due date.
Preserve fixed classes/work/sleep constraints. Put study blocks inside the preferred windows. Only go outside them when a deadline
makes that impossible, and say so in a WarningBanner. Respect the preferred session length and pacing. Leave reasonable breaks.

You MUST use only components in this A2UI catalog:
{catalog_text}

Return ONLY valid JSON with this exact top-level shape:
{{
  "assistantMessage": "brief explanation of the schedule strategy",
  "a2ui": [
    {{
      "version": "v0.9",
      "createSurface": {{ "surfaceId": "week-schedule", "catalogId": "{CATALOG_ID}" }}
    }},
    {{
      "version": "v0.9",
      "updateComponents": {{
        "surfaceId": "week-schedule",
        "components": [
          {{"id":"root","component":"WeekSchedule","title":"...","subtitle":"...","children":["summary","monday","tuesday","wednesday","thursday","friday","saturday","sunday"]}}
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


def extract_week_components(data: dict[str, Any]) -> list[dict[str, Any]]:
    for op in data.get("a2ui") or []:
        components = (op or {}).get("updateComponents", {}).get("components")
        if isinstance(components, list):
            return [c for c in components if isinstance(c, dict)]
    raise ValueError("The planner did not return any A2UI components.")


def validate_week_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = {c.get("id") for c in components}
    if "root" not in ids:
        raise ValueError("The planner response has no root component.")
    for c in components:
        if c.get("component") not in SCHEDULE_COMPONENTS:
            raise ValueError(f"Planner used a component outside the catalog: {c.get('component')}")
        if "children" in c:
            c["children"] = [child for child in c["children"] if child in ids]
    return components


def footer_components() -> list[dict[str, Any]]:
    return [
        {"id": "footer", "component": "ActionBar", "children": ["btn-prefs", "btn-schedule", "btn-restart"]},
        button("btn-prefs", "Change study times", "back_to_preferences", variant="secondary"),
        button("btn-schedule", "Edit my schedule", "back_to_schedule", variant="secondary"),
        button("btn-restart", "Start over", "restart", variant="secondary"),
    ]


def call_planner(schedule: dict[str, Any], prefs: dict[str, Any], options: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    student_input = f"{format_schedule(schedule)}\n\n{format_preferences(prefs, options)}"
    data = llm_json(
        "Return strict JSON only. You are generating a safe declarative A2UI surface from the supplied catalog.",
        planner_prompt(student_input),
    )
    components = validate_week_components(extract_week_components(data))
    message = str(data.get("assistantMessage") or "I built your week from your schedule and study preferences.")
    return message, components


# ---------------------------------------------------------------------------
# Agent logic: one function per A2UI action
# ---------------------------------------------------------------------------

async def plan_step(name: str, data: Any, state: dict[str, Any]) -> dict[str, Any]:
    if name in ("start", "restart"):
        return {
            "step": "show-intake-form",
            "message": "Tell me about your week and your assignments. Then I'll suggest when you could study.",
            "state": {"phase": "intake"},
            "ops": build_intake(SAMPLE_SCHEDULE),   # was build_intake(None),
        }

    if name == "back_to_schedule":
        return {
            "step": "show-intake-form",
            "message": "Update anything you like, then continue.",
            "state": {**state, "phase": "intake"},
            "ops": build_intake(state.get("schedule")),
        }

    if name == "submit_schedule":
        schedule = clean_schedule(data)
        if not schedule["assignments"]:
            raise ValueError("Add at least one assignment with a name before continuing.")
        message, options = await asyncio.to_thread(call_options, schedule)
        return {
            "step": "suggest-study-windows",
            "tool": {
                "name": "suggest_study_windows",
                "args": {"schedule": schedule},
                "result": {"status": "ok", "options": len(options)},
            },
            "message": message,
            "state": {"phase": "preferences", "schedule": schedule, "options": options},
            "ops": build_preferences(options, None),
        }

    if name == "back_to_preferences":
        options = state.get("options") or DEFAULT_OPTIONS
        return {
            "step": "show-preferences",
            "message": "Adjust your study preferences and I'll rebuild the week.",
            "state": {**state, "phase": "preferences"},
            "ops": build_preferences(options, state.get("prefs")),
        }

    if name == "submit_preferences":
        schedule = state.get("schedule")
        if not schedule:
            raise ValueError("I lost your schedule. Please start over.")
        options = state.get("options") or DEFAULT_OPTIONS
        prefs = clean_prefs(data, options)
        if not prefs["windows"]:
            raise ValueError("Pick at least one study window.")
        message, components = await asyncio.to_thread(call_planner, schedule, prefs, options)
        return {
            "step": "build-week-plan",
            "tool": {
                "name": "generate_a2ui_week_schedule",
                "args": {"schedule": schedule, "preferences": prefs},
                "result": {"status": "ok", "components": len(components)},
            },
            "message": message,
            "state": {**state, "phase": "complete", "prefs": prefs},
            "ops": show_surface("week-schedule", components + footer_components()),
        }

    raise ValueError(f"Unknown action: {name}")


# ---------------------------------------------------------------------------
# AG-UI plumbing
# ---------------------------------------------------------------------------

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
    """One endpoint, three phases. The client sends the A2UI action that was clicked in
    `forwardedProps.a2uiAction` ({name, data}) and echoes the last STATE_SNAPSHOT in `state`."""
    encoder = EventEncoder(accept=request.headers.get("accept"))

    forwarded = input_data.forwarded_props if isinstance(input_data.forwarded_props, dict) else {}
    action = forwarded.get("a2uiAction") if isinstance(forwarded.get("a2uiAction"), dict) else {}
    action_name = str(action.get("name") or "start")
    action_data = action.get("data") or {}
    state = input_data.state if isinstance(input_data.state, dict) else {}

    async def events() -> AsyncGenerator[str, None]:
        message_id = str(uuid.uuid4())
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
                snapshot={**state, "phase": "working", "action": action_name},
            ))

            result = await plan_step(action_name, action_data, state)

            yield encoder.encode(StepStartedEvent(type=EventType.STEP_STARTED, step_name=result["step"]))

            tool = result.get("tool")
            if tool:
                for event in tool_call_events(
                    encoder,
                    str(uuid.uuid4()),
                    message_id,
                    tool["name"],
                    json.dumps(tool["args"]),
                    str(uuid.uuid4()),
                    json.dumps(tool["result"]),
                ):
                    yield event

            # A2UI rides inside AG-UI CUSTOM events; the frontend feeds them to its renderer.
            for operation in result["ops"]:
                yield encoder.encode(CustomEvent(type=EventType.CUSTOM, name="a2ui", value=operation))

            yield encoder.encode(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=result["state"]))
            yield encoder.encode(StepFinishedEvent(type=EventType.STEP_FINISHED, step_name=result["step"]))

            yield encoder.encode(TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=message_id,
                role="assistant",
            ))
            words = result["message"].split()
            for i in range(0, len(words), 7):
                delta = " ".join(words[i:i + 7]) + (" " if i + 7 < len(words) else "")
                if delta:
                    yield encoder.encode(TextMessageContentEvent(
                        type=EventType.TEXT_MESSAGE_CONTENT,
                        message_id=message_id,
                        delta=delta,
                    ))
            yield encoder.encode(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id))

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
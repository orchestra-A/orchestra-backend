"""
main.py — Week 5, Member 4 (builds on Week 3)
Added in Week 5:
  - /standup/trigger       — manually run the standup job (for testing)
  - /standup/preview       — preview what the standup digest will look like
  - /standup/developer/{actor} — single-developer digest
  - /discord/button        — receives button interaction from Member 3's bot
  - All Week 3 endpoints remain unchanged
"""

import hmac
import hashlib
import os
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import socketio

from dotenv import load_dotenv

from normalizer import normalize_event
from models import NormalizedEvent
from state_machine import (
    load_tasks, save_tasks, create_task, get_task, upsert_task,
    process_normalized_event, Task, TaskState,
)
from broadcaster import sio, broadcast_task_update, broadcast_new_event
from scheduler import start_scheduler, stop_scheduler
from summarizer import build_team_digest, build_single_developer_digest
from discord_sender import (
    send_developer_digest_webhook,
    send_team_digest_webhook,
    send_standup_with_buttons,
    parse_button_interaction,
)

load_dotenv()

SECRET     = os.getenv("GITHUB_WEBHOOK_SECRET", "testsecret123")
EVENTS_FILE = "events.json"


# ─────────────────────────────────────────────
# App lifecycle
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


fastapi_app = FastAPI(
    title="Orchestra — Member 4 Pipeline",
    version="0.5.0",
    lifespan=lifespan,
)
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

socket_app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)


# ─────────────────────────────────────────────
# Helpers (unchanged from Week 3)
# ─────────────────────────────────────────────

def verify_signature(payload: bytes, sig_header: str) -> bool:
    if not sig_header:
        return False
    mac = hmac.new(SECRET.encode(), payload, hashlib.sha256)
    return hmac.compare_digest("sha256=" + mac.hexdigest(), sig_header)


def save_event(event: NormalizedEvent) -> None:
    with open(EVENTS_FILE, "a") as f:
        f.write(event.model_dump_json() + "\n")


def load_events() -> list[NormalizedEvent]:
    try:
        with open(EVENTS_FILE) as f:
            return [NormalizedEvent.model_validate_json(l) for l in f if l.strip()]
    except FileNotFoundError:
        return []


# ─────────────────────────────────────────────
# GitHub webhook (unchanged from Week 3)
# ─────────────────────────────────────────────

@fastapi_app.post("/webhook")
async def receive_github_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(payload, sig):
        raise HTTPException(status_code=403, detail="Bad HMAC signature")

    event_type = request.headers.get("X-GitHub-Event", "unknown")
    try:
        body = json.loads(payload)
        normalized = normalize_event(event_type, body)
        save_event(normalized)
        await broadcast_new_event(normalized.model_dump())
        state_change = process_normalized_event(normalized.model_dump())
        if state_change:
            await broadcast_task_update(state_change)
        print(f"✅ [{event_type.upper()}] {normalized.action_summary}")
        return {"status": "ok", "event": normalized.model_dump(), "state_change": state_change}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# Discord endpoint (unchanged from Week 3)
# ─────────────────────────────────────────────

@fastapi_app.post("/discord")
async def receive_discord_message(request: Request):
    try:
        body = await request.json()
        normalized = normalize_event("discord_message", body)
        save_event(normalized)
        await broadcast_new_event(normalized.model_dump())
        return {"status": "ok", "event": normalized.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# ⭐ NEW Week 5: Discord button interactions
# Member 3's bot forwards button clicks here
# ─────────────────────────────────────────────

@fastapi_app.post("/discord/button")
async def handle_discord_button(request: Request):
    """
    Receives a button click from Member 3's Discord bot.
    Payload: { "custom_id": "standup_done_arnav", "actor": "arnav" }

    When a developer clicks "✅ All done" in Discord,
    Member 3's bot POSTs to this endpoint.
    We update the task state and broadcast via WebSocket.

    TODO: Confirm payload format with Member 3.
    """
    body = await request.json()
    custom_id = body.get("custom_id", "")

    parsed = parse_button_interaction(custom_id)
    if not parsed:
        raise HTTPException(status_code=400, detail="Could not parse custom_id")

    actor     = parsed["actor"]
    new_state = parsed["new_state"]

    # Find all tasks currently assigned to this developer
    tasks = load_tasks()
    updated = []

    for task_id, task in tasks.items():
        if task.assigned_to != actor:
            continue
        if task.state in ("PENDING", "IN_PROGRESS", "BLOCKED"):
            changed = task.transition(
                TaskState(new_state),
                actor=actor,
                reason=f"Discord button: {parsed['action']}",
            )
            if changed:
                upsert_task(task)
                await broadcast_task_update(task.to_dict())
                updated.append(task_id)

    print(f"[BUTTON] {actor} clicked '{parsed['action']}' → updated {len(updated)} task(s)")
    return {"status": "ok", "actor": actor, "new_state": new_state, "updated_tasks": updated}


# ─────────────────────────────────────────────
# ⭐ NEW Week 5: Standup endpoints
# ─────────────────────────────────────────────

@fastapi_app.post("/standup/trigger")
async def trigger_standup():
    """
    Manually triggers the morning standup job.
    Use this to test without waiting for 9 AM.
    """
    from scheduler import morning_standup_job
    await morning_standup_job()
    return {"status": "standup triggered"}


@fastapi_app.post("/standup/evening")
async def trigger_evening_summary():
    """Manually triggers the evening summary job."""
    from scheduler import evening_summary_job
    await evening_summary_job()
    return {"status": "evening summary triggered"}


@fastapi_app.get("/standup/preview")
def preview_standup():
    """
    Preview what today's standup digest will look like — WITHOUT sending to Discord.
    Useful for debugging and checking the data looks right.
    """
    hours = 24
    team = build_team_digest(hours=hours)
    return {
        "preview": True,
        "will_send_to_discord": bool(
            os.getenv("DISCORD_WEBHOOK_URL") or os.getenv("DISCORD_BOT_TOKEN")
        ),
        "digest": team.to_dict(),
    }


@fastapi_app.get("/standup/developer/{actor}")
def get_developer_digest(actor: str, hours: int = 24):
    """
    Get the activity digest for a single developer.
    Query param: hours=24  (default: last 24 hours)
    """
    digest = build_single_developer_digest(actor, hours=hours)
    return digest.to_dict()


@fastapi_app.get("/standup/team")
def get_team_digest(hours: int = 24):
    """Get the full team digest. Query param: hours=24"""
    team = build_team_digest(hours=hours)
    return team.to_dict()


# ─────────────────────────────────────────────
# Events + Tasks (unchanged from Week 3)
# ─────────────────────────────────────────────

@fastapi_app.get("/events")
def get_all_events():
    return [e.model_dump() for e in load_events()]


@fastapi_app.get("/events/{platform}")
def get_events_by_platform(platform: str):
    return [e.model_dump() for e in load_events() if e.platform == platform]


@fastapi_app.delete("/events/reset")
def reset_events():
    try:
        os.remove(EVENTS_FILE)
        return {"status": "cleared"}
    except FileNotFoundError:
        return {"status": "nothing to clear"}


@fastapi_app.get("/tasks")
def get_all_tasks():
    return {k: v.to_dict() for k, v in load_tasks().items()}


@fastapi_app.get("/tasks/{task_id}")
def get_single_task(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return task.to_dict()


@fastapi_app.post("/tasks")
async def create_new_task(request: Request):
    body = await request.json()
    task_id = body.get("id")
    if not task_id:
        raise HTTPException(status_code=400, detail="'id' field required")
    task = create_task(task_id, body.get("title", "Untitled"))
    await broadcast_task_update(task.to_dict())
    return task.to_dict()


@fastapi_app.patch("/tasks/{task_id}/state")
async def manually_update_task_state(task_id: str, request: Request):
    body = await request.json()
    new_state_str = body.get("state")
    actor = body.get("actor", "manual")
    reason = body.get("reason", "Manual override")
    try:
        new_state = TaskState(new_state_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid state: {new_state_str}")
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    changed = task.transition(new_state, actor=actor, reason=reason)
    if not changed:
        raise HTTPException(status_code=409, detail=f"Transition not allowed")
    upsert_task(task)
    await broadcast_task_update(task.to_dict())
    return task.to_dict()


@fastapi_app.delete("/tasks/reset")
def reset_tasks():
    try:
        os.remove("tasks.json")
        return {"status": "cleared"}
    except FileNotFoundError:
        return {"status": "nothing to clear"}


# ─────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────

@fastapi_app.get("/health")
def health():
    tasks = load_tasks()
    events = load_events()
    state_counts = {}
    for t in tasks.values():
        state_counts[t.state] = state_counts.get(t.state, 0) + 1

    return {
        "status": "alive",
        "week": 5,
        "total_events": len(events),
        "total_tasks": len(tasks),
        "task_states": state_counts,
        "discord_webhook_set": bool(os.getenv("DISCORD_WEBHOOK_URL")),
        "discord_bot_set":     bool(os.getenv("DISCORD_BOT_TOKEN")),
        "scheduler_running":   True,
    }


# ─────────────────────────────────────────────
# Run with:
#   uvicorn main:socket_app --reload --port 8000
# ─────────────────────────────────────────────

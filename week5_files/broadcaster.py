"""
broadcaster.py — Week 3, Member 4
WebSocket Engine — broadcasts real-time state changes to all active sessions.

Uses python-socketio (Socket.IO protocol) which Member 3 hooks the frontend to.
Every time the state machine transitions a task, this broadcasts it.

Events emitted:
  "task_update"    → when a task state changes
  "new_event"      → when a new normalized event arrives
  "heartbeat"      → every 30s to keep connections alive
"""

import socketio

# ─────────────────────────────────────────────
# Socket.IO server instance
# Async mode so it plays nicely with FastAPI/uvicorn
# ─────────────────────────────────────────────

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",   # TODO: Lock this down in production
    logger=False,
    engineio_logger=False,
)


# ─────────────────────────────────────────────
# Connection lifecycle
# ─────────────────────────────────────────────

@sio.event
async def connect(sid, environ):
    print(f"[WEBSOCKET] ✅ Client connected: {sid}")
    # Send current task state to newly connected client
    from state_machine import load_tasks
    tasks = load_tasks()
    await sio.emit(
        "init",
        {"tasks": {k: v.to_dict() for k, v in tasks.items()}},
        to=sid,
    )


@sio.event
async def disconnect(sid):
    print(f"[WEBSOCKET] ❌ Client disconnected: {sid}")


@sio.event
async def ping(sid, data):
    """Client can ping to confirm connection is alive."""
    await sio.emit("pong", {"sid": sid}, to=sid)


# ─────────────────────────────────────────────
# Broadcast helpers (called from main.py)
# ─────────────────────────────────────────────

async def broadcast_task_update(task_dict: dict) -> None:
    """
    Broadcast a task state change to ALL connected clients.
    Called whenever the state machine transitions a task.

    Payload:
    {
        "id": "task-12",
        "state": "COMPLETED",
        "assigned_to": "arnav",
        "action_summary": "arnav merged PR #42",
        "updated_at": "2026-05-20T12:30:45Z"
    }
    """
    print(f"[WEBSOCKET] 📡 Broadcasting task_update: {task_dict['id']} → {task_dict['state']}")
    await sio.emit("task_update", task_dict)


async def broadcast_new_event(event_dict: dict) -> None:
    """
    Broadcast a new normalized event to ALL connected clients.
    Called whenever a new GitHub/Discord event arrives.

    Payload: NormalizedEvent dict
    """
    print(f"[WEBSOCKET] 📡 Broadcasting new_event: {event_dict.get('action_summary', '')}")
    await sio.emit("new_event", event_dict)


async def broadcast_heartbeat() -> None:
    """
    Keep-alive ping to all connected clients.
    Called by the cron scheduler every 30 seconds.
    """
    from datetime import datetime, timezone
    await sio.emit("heartbeat", {"timestamp": datetime.now(timezone.utc).isoformat()})

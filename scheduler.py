"""
scheduler.py — Week 3, Member 4
Background Cron Schedulers — runs periodically to summarize activity.

Jobs:
  1. Daily summary — every day at 9 AM, posts what everyone did
  2. Heartbeat — every 30 seconds, keeps WebSocket clients alive
  3. Stale task check — every hour, flags tasks stuck IN_PROGRESS > 24h
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timezone, timedelta
import json

scheduler = AsyncIOScheduler(timezone="UTC")

# ─────────────────────────────────────────────
# Job 1: Daily summary at 9:00 AM UTC
# ─────────────────────────────────────────────


async def daily_summary_job():
    """
    Reads all events from last 24 hours.
    Groups by developer.
    Broadcasts a summary digest to all connected clients.
    """
    from app.utils.websocket_manager import manager

    try:
        with open("events.json") as f:
            events = json.load(f)
    except FileNotFoundError:
        print("[SCHEDULER] No events.json found, skipping daily summary")
        return
    except json.JSONDecodeError:
        print("[SCHEDULER] Failed to decode events.json")
        return

    # Filter last 24 hours
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent = [e for e in events if e.get("timestamp", "") >= cutoff]

    if not recent:
        print("[SCHEDULER] No events in last 24h, skipping summary")
        return

    # Group by developer
    by_actor: dict[str, list] = {}
    for event in recent:
        actor = event.get("actor", "unknown")
        by_actor.setdefault(actor, []).append(event)

    # Build summary lines
    lines = []
    for actor, actor_events in by_actor.items():
        pushes = [e for e in actor_events if e.get("event_type") == "push"]
        prs = [e for e in actor_events if e.get("event_type") == "pull_request"]
        msgs = [e for e in actor_events if e.get("event_type") == "message"]

        parts = []
        if pushes:
            parts.append(f"{len(pushes)} push(es)")
        if prs:
            parts.append(f"{len(prs)} PR action(s)")
        if msgs:
            parts.append(f"{len(msgs)} Discord message(s)")

        if parts:
            lines.append(f"• {actor}: {', '.join(parts)}")

    summary = {
        "id": f"summary-{datetime.now(timezone.utc).date()}",
        "platform": "system",
        "event_type": "daily_summary",
        "actor": "scheduler",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action_summary": f"Daily digest — {len(recent)} events, {len(by_actor)} developer(s) active",
        "raw_metadata": {
            "date": str(datetime.now(timezone.utc).date()),
            "total_events": len(recent),
            "by_actor": {actor: len(evts) for actor, evts in by_actor.items()},
            "breakdown": lines,
        },
        "type": "new_event",
    }

    await manager.broadcast(summary)
    print(
        f"[SCHEDULER] Daily summary sent — {len(recent)} events, {len(by_actor)} developers"
    )


# ─────────────────────────────────────────────
# Job 2: Heartbeat every 30 seconds
# ─────────────────────────────────────────────


async def heartbeat_job():
    from app.utils.websocket_manager import manager
    from datetime import datetime, timezone

    await manager.broadcast(
        {"type": "heartbeat", "timestamp": datetime.now(timezone.utc).isoformat()}
    )


# ─────────────────────────────────────────────
# Job 3: Stale task check every 60 minutes
# ─────────────────────────────────────────────


async def stale_task_check_job():
    """
    Finds tasks stuck IN_PROGRESS for more than 24 hours.
    Broadcasts a warning to all connected clients.
    """
    from state_machine import load_tasks, TaskState
    from app.utils.websocket_manager import manager

    tasks = load_tasks()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    stale = []
    for t in tasks.values():
        if t.state == TaskState.IN_PROGRESS:
            last_updated = t.history[-1]["timestamp"] if t.history else t.created_at
            if last_updated < cutoff:
                # Attach the stuck time temporarily for the broadcast
                t._stuck_since = last_updated
                stale.append(t)

    if not stale:
        return

    for task in stale:
        warning = {
            "id": f"stale-warning-{task.id}",
            "platform": "system",
            "event_type": "stale_task_warning",
            "actor": "scheduler",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action_summary": f"Task '{task.id}' has been IN_PROGRESS for over 24h",
            "raw_metadata": {
                "task_id": task.id,
                "task_title": task.title,
                "assigned_to": task.assigned_to,
                "stuck_since": getattr(task, "_stuck_since", task.created_at),
            },
            "type": "new_event",
        }
        await manager.broadcast(warning)
        print(
            f"[SCHEDULER] Stale task alert: {task.id} (assigned to {task.assigned_to})"
        )


# ─────────────────────────────────────────────
# Start / Stop
# ─────────────────────────────────────────────


def start_scheduler():
    scheduler.add_job(
        daily_summary_job,
        CronTrigger(hour=9, minute=0),
        id="daily_summary",
        replace_existing=True,
    )
    scheduler.add_job(
        heartbeat_job,
        IntervalTrigger(seconds=30),
        id="heartbeat",
        replace_existing=True,
    )
    scheduler.add_job(
        stale_task_check_job,
        IntervalTrigger(minutes=60),
        id="stale_task_check",
        replace_existing=True,
    )
    scheduler.start()
    print("[SCHEDULER] Started — daily_summary, heartbeat, stale_task_check")


def stop_scheduler():
    scheduler.shutdown()
    print("[SCHEDULER] Stopped")

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
    Reads all events from last 24 hours from PostgreSQL.
    Groups by developer.
    Broadcasts a summary digest to all connected clients.
    """
    from app.utils.websocket_manager import manager
    from database import SessionLocal
    from models_sql import EventTable

    db = SessionLocal()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        recent = db.query(EventTable).filter(EventTable.timestamp >= cutoff).all()
        
        if not recent:
            print("[SCHEDULER] No events in last 24h, skipping summary")
            return

        # Group by developer
        by_actor: dict[str, list] = {}
        for event in recent:
            actor = event.actor or "unknown"
            by_actor.setdefault(actor, []).append(event)

        # Build summary lines
        lines = []
        for actor, actor_events in by_actor.items():
            pushes = [e for e in actor_events if e.event_type == "push"]
            prs = [e for e in actor_events if e.event_type == "pull_request"]
            msgs = [e for e in actor_events if e.event_type == "message"]

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
    except Exception as e:
        print(f"[SCHEDULER] Error generating daily summary: {e}")
    finally:
        db.close()


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
            if last_updated is None:
                continue
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
# Job 4: Deadline check every 15 minutes
# ─────────────────────────────────────────────


async def deadline_check_job():
    """
    Finds tasks where the deadline has passed and marks them as halted.
    """
    from database import SessionLocal
    from models_sql import TaskTable
    from state_machine import get_task, upsert_task, TaskState
    from app.utils.websocket_manager import manager
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc).isoformat()
        db_tasks = db.query(TaskTable.id, TaskTable.title, TaskTable.deadline).filter(
            TaskTable.status.notin_(["completed", "halted", "blocked"]),
            TaskTable.deadline.isnot(None),
        ).all()
        
        stale_task_records = [t for t in db_tasks if t.deadline < now]
    except Exception as e:
        print(f"[SCHEDULER] Error checking deadlines: {e}")
        stale_task_records = []
    finally:
        db.close()
        
    if not stale_task_records:
        return
        
    halted_tasks = []
    for t_db in stale_task_records:
        task_obj = get_task(t_db.id)
        if task_obj:
            changed = task_obj.transition(
                TaskState.HALTED, actor="scheduler", reason="Deadline passed"
            )
            if changed:
                upsert_task(task_obj)
                halted_tasks.append(t_db)

    for task in halted_tasks:
        event = {
            "id": f"deadline-passed-{task.id}",
            "platform": "system",
            "event_type": "deadline_passed",
            "actor": "scheduler",
            "timestamp": now,
            "action_summary": f"Task '{task.title}' deadline passed, marked as halted",
            "raw_metadata": {
                "task_id": task.id,
                "task_title": task.title,
                "deadline": task.deadline
            },
            "type": "new_event",
        }
        await manager.broadcast(event)
        print(f"[SCHEDULER] Task {task.id} deadline passed, marked as halted.")


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
    scheduler.add_job(
        deadline_check_job,
        IntervalTrigger(minutes=15),
        id="deadline_check",
        replace_existing=True,
    )
    scheduler.start()
    print("[SCHEDULER] Started — daily_summary, heartbeat, stale_task_check, deadline_check")


def stop_scheduler():
    scheduler.shutdown()
    print("[SCHEDULER] Stopped")

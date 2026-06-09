"""
scheduler.py — Week 5, Member 4 (enhanced from Week 3)
Background cron schedulers for developer standup digests.

Jobs:
  1. morning_standup  — 9:00 AM UTC: sends per-developer digest to Discord
  2. evening_summary  — 6:00 PM UTC: sends team-wide recap
  3. heartbeat        — every 30s: keeps WebSocket connections alive
  4. stale_task_check — every 60 min: flags IN_PROGRESS tasks stuck >24h
  5. weekly_report    — Monday 8:00 AM: weekly team summary
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timezone
import os

scheduler = AsyncIOScheduler(timezone="UTC")


# ─────────────────────────────────────────────
# Job 1: Morning standup — 9:00 AM UTC
# Sends individual digests to each developer via Discord
# ─────────────────────────────────────────────

async def morning_standup_job():
    """
    Builds a digest for every active developer.
    Sends each one a personalised Discord message.
    If bot token available: sends with interactive buttons.
    Otherwise: sends via webhook (plain embed).
    """
    from summarizer import build_team_digest
    from discord_sender import (
        send_developer_digest_webhook,
        send_standup_with_buttons,
    )
    from broadcaster import broadcast_new_event

    print("[SCHEDULER] 🌅 Running morning standup job...")
    team = build_team_digest(hours=24)
    active = team.active_developers()

    if not active:
        print("[SCHEDULER] No active developers — standup skipped")
        return

    bot_token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = os.getenv("DISCORD_CHANNEL_ID", "")

    for dev_digest in active:
        if bot_token and channel_id:
            # Interactive buttons via bot
            send_standup_with_buttons(dev_digest, channel_id)
        else:
            # Plain embed via webhook (no bot needed)
            send_developer_digest_webhook(dev_digest)

        # Also broadcast via WebSocket so frontend can update
        await broadcast_new_event({
            "id": f"standup-{dev_digest.actor}-{team.date}",
            "platform": "system",
            "event_type": "standup_digest",
            "actor": dev_digest.actor,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action_summary": f"📊 Standup digest for {dev_digest.actor}: {dev_digest.headline()}",
            "raw_metadata": dev_digest.to_dict(),
        })

    print(f"[SCHEDULER] ✅ Morning standup sent for {len(active)} developer(s)")


# ─────────────────────────────────────────────
# Job 2: Evening summary — 6:00 PM UTC
# Sends one team-wide summary embed
# ─────────────────────────────────────────────

async def evening_summary_job():
    """
    Sends a single team-wide recap to the general Discord channel.
    Good for managers and cross-team visibility.
    """
    from summarizer import build_team_digest
    from discord_sender import send_team_digest_webhook
    from broadcaster import broadcast_new_event

    print("[SCHEDULER] 🌆 Running evening summary job...")
    team = build_team_digest(hours=24)

    sent = send_team_digest_webhook(team)

    await broadcast_new_event({
        "id": f"evening-summary-{team.date}",
        "platform": "system",
        "event_type": "evening_summary",
        "actor": "scheduler",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action_summary": (
            f"Evening summary: {len(team.active_developers())} active, "
            f"{team.total_commits()} commits, "
            f"{team.total_completed()} tasks completed"
        ),
        "raw_metadata": team.to_dict(),
    })

    print(f"[SCHEDULER] {'✅' if sent else '⚠️'} Evening summary complete")


# ─────────────────────────────────────────────
# Job 3: Heartbeat — every 30 seconds
# ─────────────────────────────────────────────

async def heartbeat_job():
    from broadcaster import broadcast_heartbeat
    await broadcast_heartbeat()


# ─────────────────────────────────────────────
# Job 4: Stale task check — every 60 minutes
# ─────────────────────────────────────────────

async def stale_task_check_job():
    """
    Finds tasks stuck IN_PROGRESS for >24h.
    Broadcasts a warning via WebSocket and Discord.
    """
    from state_machine import load_tasks, TaskState
    from broadcaster import broadcast_new_event
    from discord_sender import _post_to_webhook
    from datetime import timedelta

    tasks = load_tasks()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    stale = [
        t for t in tasks.values()
        if t.state == TaskState.IN_PROGRESS and t.updated_at < cutoff
    ]

    if not stale:
        return

    print(f"[SCHEDULER] ⚠️ Found {len(stale)} stale task(s)")

    for task in stale:
        warning_event = {
            "id": f"stale-{task.id}",
            "platform": "system",
            "event_type": "stale_task_warning",
            "actor": "scheduler",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action_summary": f"⚠️ Task '{task.id}' has been IN_PROGRESS for over 24h",
            "raw_metadata": {
                "task_id": task.id,
                "task_title": task.title,
                "assigned_to": task.assigned_to,
                "stuck_since": task.updated_at,
            },
        }
        await broadcast_new_event(warning_event)

    # Send one grouped Discord warning
    if stale and os.getenv("DISCORD_WEBHOOK_URL"):
        rows = [
            f"• `{t.id}` ({t.assigned_to or 'unassigned'}) — stuck since {t.updated_at[:10]}"
            for t in stale
        ]
        _post_to_webhook({
            "embeds": [{
                "title": f"⚠️ Stale Tasks Alert — {len(stale)} task(s)",
                "description": "\n".join(rows),
                "color": 0xFEE75C,
                "footer": {"text": "Orchestra · Auto-detected stale tasks"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        })


# ─────────────────────────────────────────────
# Job 5: Weekly report — Monday 8:00 AM UTC
# ─────────────────────────────────────────────

async def weekly_report_job():
    """
    Builds and sends a 7-day summary of team activity.
    Great for sprint reviews and async team updates.
    """
    from summarizer import build_team_digest
    from discord_sender import send_team_digest_webhook, _post_to_webhook
    from broadcaster import broadcast_new_event

    print("[SCHEDULER] 📅 Running weekly report job...")
    team = build_team_digest(hours=168)   # 7 days

    # Enhanced weekly payload
    active = team.active_developers()
    top_contributors = sorted(active, key=lambda d: d.total_commits(), reverse=True)

    rows = []
    for dev in top_contributors[:5]:   # Top 5
        rows.append(
            f"• **{dev.actor}** — {dev.total_commits()} commits, "
            f"{len(dev.tasks_completed)} completed"
        )

    if os.getenv("DISCORD_WEBHOOK_URL"):
        _post_to_webhook({
            "embeds": [{
                "title": f"📅 Weekly Report — {team.date}",
                "description": "Here's what the team accomplished this week:",
                "color": 0x5865F2,
                "fields": [
                    {
                        "name": "🏆 Top Contributors",
                        "value": "\n".join(rows) or "No activity",
                        "inline": False,
                    },
                    {
                        "name": "📈 Team Stats",
                        "value": (
                            f"Total commits: {team.total_commits()}\n"
                            f"Tasks completed: {team.total_completed()}\n"
                            f"Active developers: {len(active)}"
                        ),
                        "inline": False,
                    },
                ],
                "footer": {"text": "Orchestra · Weekly Digest"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        })

    print(f"[SCHEDULER] ✅ Weekly report complete ({len(active)} developers)")


# ─────────────────────────────────────────────
# Start / Stop
# ─────────────────────────────────────────────

def start_scheduler():
    scheduler.add_job(
        morning_standup_job,
        CronTrigger(hour=9, minute=0),
        id="morning_standup",
        replace_existing=True,
    )
    scheduler.add_job(
        evening_summary_job,
        CronTrigger(hour=18, minute=0),
        id="evening_summary",
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
        weekly_report_job,
        CronTrigger(day_of_week="mon", hour=8, minute=0),
        id="weekly_report",
        replace_existing=True,
    )
    scheduler.start()
    print(
        "[SCHEDULER] ✅ Started — "
        "morning_standup (9AM), evening_summary (6PM), "
        "heartbeat (30s), stale_task_check (60m), weekly_report (Mon 8AM)"
    )


def stop_scheduler():
    scheduler.shutdown()
    print("[SCHEDULER] Stopped")

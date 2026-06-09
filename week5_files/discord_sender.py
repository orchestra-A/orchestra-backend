"""
discord_sender.py — Week 5, Member 4
Sends activity digests to Discord.

Two modes:
  1. Webhook URL (Member 4 can use independently — just needs a webhook URL)
  2. Bot token (requires Member 3's bot — unlocks interactive buttons)

Week 5 plan:
  - Day 1-3: Use webhook URL only (no dependency on Member 3)
  - Day 4-5: Coordinate with Member 3 for bot token + button interactions
"""

import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from summarizer import DeveloperDigest, TeamDigest

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_BOT_TOKEN   = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID  = os.getenv("DISCORD_CHANNEL_ID", "")


# ─────────────────────────────────────────────
# Mode 1: Discord Webhook (no bot needed)
# Member 4 can use this independently.
# Get a webhook URL: Discord server → channel → Edit → Integrations → Webhooks
# ─────────────────────────────────────────────

def _post_to_webhook(payload: dict) -> bool:
    """POST a message payload to a Discord webhook URL. Returns True on success."""
    if not DISCORD_WEBHOOK_URL:
        print("[DISCORD] No DISCORD_WEBHOOK_URL set — skipping send")
        return False

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            print(f"[DISCORD] ✅ Webhook sent — status {r.status}")
            return True
    except urllib.error.HTTPError as e:
        print(f"[DISCORD] ❌ Webhook failed — {e.code}: {e.read().decode()}")
        return False


def send_developer_digest_webhook(digest: DeveloperDigest) -> bool:
    """
    Sends one developer's digest as a Discord embed via webhook.
    No bot token needed — just DISCORD_WEBHOOK_URL in .env.
    """
    color = _state_color(digest)

    fields = []

    if digest.tasks_completed:
        fields.append({
            "name": "✅ Completed",
            "value": "\n".join(f"`{t['id']}` {t.get('title', '')}" for t in digest.tasks_completed),
            "inline": False,
        })

    if digest.tasks_in_progress:
        fields.append({
            "name": "🔄 In Progress",
            "value": "\n".join(f"`{t['id']}` {t.get('title', '')}" for t in digest.tasks_in_progress),
            "inline": False,
        })

    if digest.tasks_blocked:
        fields.append({
            "name": "🔴 Blocked",
            "value": "\n".join(f"`{t['id']}` {t.get('title', '')}" for t in digest.tasks_blocked),
            "inline": False,
        })

    if digest.total_commits() > 0 or digest.prs_merged:
        gh_parts = []
        if digest.total_commits() > 0:
            gh_parts.append(f"{digest.total_commits()} commit(s) pushed")
        if digest.prs_merged:
            gh_parts.append(f"{len(digest.prs_merged)} PR(s) merged")
        if digest.prs_opened:
            gh_parts.append(f"{len(digest.prs_opened)} PR(s) opened")
        fields.append({
            "name": "💻 GitHub",
            "value": " · ".join(gh_parts),
            "inline": True,
        })

    if digest.discord_messages > 0:
        fields.append({
            "name": "💬 Discord",
            "value": f"{digest.discord_messages} message(s)",
            "inline": True,
        })

    if not fields:
        fields.append({
            "name": "Activity",
            "value": "No activity recorded today",
            "inline": False,
        })

    payload = {
        "embeds": [{
            "title": f"📊 Daily Update — {digest.actor}",
            "description": digest.headline(),
            "color": color,
            "fields": fields,
            "footer": {"text": f"Period: {digest.period_start[:10]} · Orchestra Bot"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }

    return _post_to_webhook(payload)


def send_team_digest_webhook(team_digest: TeamDigest) -> bool:
    """
    Sends a team-wide summary embed via webhook.
    Shows all active developers and their status at a glance.
    """
    active = team_digest.active_developers()
    if not active:
        return _post_to_webhook({
            "content": "📊 **Daily Standup** — No activity recorded in the last 24h."
        })

    rows = []
    for dev in active:
        icon = "✅" if dev.tasks_completed else ("🔴" if dev.tasks_blocked else "🔄")
        rows.append(f"{icon} **{dev.actor}** — {dev.headline()}")

    payload = {
        "embeds": [{
            "title": f"📊 Team Standup — {team_digest.date}",
            "description": "\n".join(rows),
            "color": 0x5865F2,
            "fields": [
                {"name": "👥 Active Devs", "value": str(len(active)), "inline": True},
                {"name": "📝 Total Commits", "value": str(team_digest.total_commits()), "inline": True},
                {"name": "✅ Tasks Done", "value": str(team_digest.total_completed()), "inline": True},
            ],
            "footer": {"text": "Orchestra · Automated Standup"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }

    return _post_to_webhook(payload)


# ─────────────────────────────────────────────
# Mode 2: Discord Bot (requires Member 3's bot token)
# Unlocks: interactive buttons, DMs, slash commands
# ─────────────────────────────────────────────

def _post_to_channel(channel_id: str, payload: dict) -> bool:
    """
    Send a message to a specific channel via Bot token.
    Requires DISCORD_BOT_TOKEN in .env (provided by Member 3).
    """
    if not DISCORD_BOT_TOKEN:
        print("[DISCORD BOT] No DISCORD_BOT_TOKEN set — skipping (use webhook instead)")
        return False

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            print(f"[DISCORD BOT] ✅ Message sent to channel {channel_id}")
            return True
    except urllib.error.HTTPError as e:
        print(f"[DISCORD BOT] ❌ Failed to send — {e.code}: {e.read().decode()}")
        return False


def send_standup_with_buttons(digest: DeveloperDigest, channel_id: str) -> bool:
    """
    Sends a developer's digest WITH interactive confirmation buttons.
    Buttons: [✅ Confirm Done] [🔄 Still In Progress] [🔴 I'm Blocked]

    Requires Member 3's bot token. Bot must handle the button interactions
    and POST back to your /discord/button endpoint.

    TODO: Coordinate with Member 3 about:
      - Their bot token (they add to your .env)
      - Which channel to send to (DISCORD_CHANNEL_ID in .env)
      - Their bot must handle interaction callbacks and POST to /discord/button
    """
    task_lines = []
    for task in digest.tasks_in_progress:
        task_lines.append(f"• `{task['id']}` {task.get('title', '')}")
    for task in digest.tasks_blocked:
        task_lines.append(f"• 🔴 `{task['id']}` {task.get('title', '')} (BLOCKED)")

    description = digest.headline()
    if task_lines:
        description += "\n\n**Open tasks:**\n" + "\n".join(task_lines)

    payload = {
        "embeds": [{
            "title": f"👋 Standup check-in — {digest.actor}",
            "description": description,
            "color": _state_color(digest),
            "footer": {"text": "Click a button to update your status"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
        # Discord Components v1 — button row
        # Member 3's bot handles the interaction_id callbacks
        "components": [{
            "type": 1,  # Action Row
            "components": [
                {
                    "type": 2,          # Button
                    "style": 3,         # Green (SUCCESS)
                    "label": "✅ All done",
                    "custom_id": f"standup_done_{digest.actor}",
                },
                {
                    "type": 2,
                    "style": 1,         # Blue (PRIMARY)
                    "label": "🔄 Still in progress",
                    "custom_id": f"standup_inprogress_{digest.actor}",
                },
                {
                    "type": 2,
                    "style": 4,         # Red (DANGER)
                    "label": "🔴 I'm blocked",
                    "custom_id": f"standup_blocked_{digest.actor}",
                },
            ],
        }],
    }

    return _post_to_channel(channel_id, payload)


# ─────────────────────────────────────────────
# Button interaction handler
# Called from main.py when Member 3's bot forwards a button click
# ─────────────────────────────────────────────

def parse_button_interaction(custom_id: str) -> dict:
    """
    Parse a Discord button custom_id into actor + intended state.
    custom_id format: "standup_{action}_{actor}"

    Returns: {"actor": str, "action": str, "new_state": str}
    """
    parts = custom_id.split("_", 2)
    if len(parts) < 3 or parts[0] != "standup":
        return {}

    _, action, actor = parts
    state_map = {
        "done": "COMPLETED",
        "inprogress": "IN_PROGRESS",
        "blocked": "BLOCKED",
    }
    return {
        "actor": actor,
        "action": action,
        "new_state": state_map.get(action, "PENDING"),
    }


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _state_color(digest: DeveloperDigest) -> int:
    """Discord embed color based on developer's overall status."""
    if digest.tasks_blocked:
        return 0xED4245   # Red  — blocked
    if digest.tasks_completed and not digest.tasks_in_progress:
        return 0x57F287   # Green — all done
    if digest.tasks_in_progress:
        return 0xFEE75C   # Yellow — in progress
    return 0x5865F2       # Blurple — neutral

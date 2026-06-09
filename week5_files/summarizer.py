"""
summarizer.py — Week 5, Member 4
Reads events.json + tasks.json and builds per-developer activity digests.

A "digest" answers: "What did developer X do in the last 24 hours"
  - How many commits
  - Which tasks moved forward
  - Any PRs opened or merged
  - Any tasks blocked
  - Discord activity

The digest is then formatted and sent to Discord by discord_sender.py.
"""

import json
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

EVENTS_FILE = "events.json"
TASKS_FILE  = "tasks.json"


# ─────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────

@dataclass
class DeveloperDigest:
    """Complete activity summary for one developer over a time window."""
    actor: str
    period_start: str
    period_end: str

    # GitHub activity
    pushes: list             = field(default_factory=list)   # raw push events
    prs_opened: list         = field(default_factory=list)   # PR open events
    prs_merged: list         = field(default_factory=list)   # PR merge events
    prs_closed: list         = field(default_factory=list)   # PR closed (no merge)

    # Task states
    tasks_completed: list    = field(default_factory=list)   # tasks moved to COMPLETED
    tasks_in_progress: list  = field(default_factory=list)   # tasks currently IN_PROGRESS
    tasks_blocked: list      = field(default_factory=list)   # tasks currently BLOCKED

    # Discord activity
    discord_messages: int    = 0

    def is_empty(self) -> bool:
        """Returns True if the developer had zero activity."""
        return (
            not self.pushes
            and not self.prs_opened
            and not self.prs_merged
            and not self.prs_closed
            and not self.tasks_completed
            and not self.tasks_in_progress
            and not self.tasks_blocked
            and self.discord_messages == 0
        )

    def total_commits(self) -> int:
        return sum(p.get("raw_metadata", {}).get("commit_count", 0) for p in self.pushes)

    def headline(self) -> str:
        """One-line summary of the developer's day."""
        parts = []
        if self.tasks_completed:
            parts.append(f"✅ {len(self.tasks_completed)} task(s) completed")
        if self.tasks_in_progress:
            parts.append(f"🔄 {len(self.tasks_in_progress)} task(s) in progress")
        if self.tasks_blocked:
            parts.append(f"🔴 {len(self.tasks_blocked)} task(s) blocked")
        if self.prs_merged:
            parts.append(f"🔀 {len(self.prs_merged)} PR(s) merged")
        if self.total_commits():
            parts.append(f"📝 {self.total_commits()} commit(s)")
        if not parts:
            return "No activity recorded"
        return " · ".join(parts)

    def to_dict(self) -> dict:
        return {
            "actor": self.actor,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "headline": self.headline(),
            "pushes": len(self.pushes),
            "total_commits": self.total_commits(),
            "prs_opened": len(self.prs_opened),
            "prs_merged": len(self.prs_merged),
            "prs_closed": len(self.prs_closed),
            "tasks_completed": [t["id"] for t in self.tasks_completed],
            "tasks_in_progress": [t["id"] for t in self.tasks_in_progress],
            "tasks_blocked": [t["id"] for t in self.tasks_blocked],
            "discord_messages": self.discord_messages,
        }


@dataclass
class TeamDigest:
    """Full team summary — one DeveloperDigest per active member."""
    date: str
    period_start: str
    period_end: str
    developers: list[DeveloperDigest] = field(default_factory=list)

    def active_developers(self) -> list[DeveloperDigest]:
        return [d for d in self.developers if not d.is_empty()]

    def total_commits(self) -> int:
        return sum(d.total_commits() for d in self.developers)

    def total_completed(self) -> int:
        return sum(len(d.tasks_completed) for d in self.developers)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "total_active_developers": len(self.active_developers()),
            "total_commits": self.total_commits(),
            "total_tasks_completed": self.total_completed(),
            "developers": [d.to_dict() for d in self.active_developers()],
        }


# ─────────────────────────────────────────────
# Loaders
# ─────────────────────────────────────────────

def _load_events(since: Optional[str] = None) -> list[dict]:
    """Load all events from events.json, optionally filtered by timestamp."""
    try:
        with open(EVENTS_FILE) as f:
            events = [json.loads(line) for line in f if line.strip()]
        if since:
            events = [e for e in events if e.get("timestamp", "") >= since]
        return events
    except FileNotFoundError:
        return []


def _load_tasks() -> dict[str, dict]:
    """Load all tasks from tasks.json as a flat dict."""
    try:
        with open(TASKS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# ─────────────────────────────────────────────
# Core builder
# ─────────────────────────────────────────────

def build_developer_digest(
    actor: str,
    events: list[dict],
    tasks: dict[str, dict],
    period_start: str,
    period_end: str,
) -> DeveloperDigest:
    """Build a complete digest for one developer."""
    digest = DeveloperDigest(
        actor=actor,
        period_start=period_start,
        period_end=period_end,
    )

    # ── GitHub activity ──────────────────────
    actor_events = [e for e in events if e.get("actor") == actor]

    for event in actor_events:
        etype = event.get("event_type")
        metadata = event.get("raw_metadata", {})

        if etype == "push":
            digest.pushes.append(event)

        elif etype == "pull_request":
            action = metadata.get("action", "")
            merged = metadata.get("merged", False)
            if action == "opened":
                digest.prs_opened.append(event)
            elif action == "closed" and merged:
                digest.prs_merged.append(event)
            elif action == "closed" and not merged:
                digest.prs_closed.append(event)

        elif etype == "message":
            digest.discord_messages += 1

    # ── Task states (owned by this developer) ─
    for task_id, task in tasks.items():
        if task.get("assigned_to") != actor:
            continue
        state = task.get("state", "")
        if state == "COMPLETED":
            # Only include if it was completed within this period
            updated = task.get("updated_at", "")
            if period_start <= updated <= period_end:
                digest.tasks_completed.append(task)
        elif state == "IN_PROGRESS":
            digest.tasks_in_progress.append(task)
        elif state == "BLOCKED":
            digest.tasks_blocked.append(task)

    return digest


def build_team_digest(hours: int = 24) -> TeamDigest:
    """
    Build a digest for the whole team over the last `hours` hours.
    Default: last 24 hours.
    """
    now = datetime.now(timezone.utc)
    period_end = now.isoformat()
    period_start = (now - timedelta(hours=hours)).isoformat()

    events = _load_events(since=period_start)
    tasks = _load_tasks()

    # Collect all unique actors from events
    actors = sorted({e.get("actor", "unknown") for e in events if e.get("actor")})

    digests = [
        build_developer_digest(actor, events, tasks, period_start, period_end)
        for actor in actors
    ]

    return TeamDigest(
        date=str(now.date()),
        period_start=period_start,
        period_end=period_end,
        developers=digests,
    )


def build_single_developer_digest(actor: str, hours: int = 24) -> DeveloperDigest:
    """Build a digest for just one developer."""
    now = datetime.now(timezone.utc)
    period_end = now.isoformat()
    period_start = (now - timedelta(hours=hours)).isoformat()

    events = _load_events(since=period_start)
    tasks = _load_tasks()

    return build_developer_digest(actor, events, tasks, period_start, period_end)

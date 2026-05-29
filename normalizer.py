"""
normalizer.py — Week 2, Member 4
The "Semantic Data Normalizer" — core of your Week 2 deliverable.

Takes messy raw payloads from GitHub / Discord / Figma and
outputs clean, uniform NormalizedEvent objects every time.

Week 2 scope: GitHub push + PR events, Discord message stub.
Figma + others will be added in Week 3.
"""

import uuid
from datetime import datetime, timezone
from models import NormalizedEvent


# ─────────────────────────────────────────────
# GitHub normalizers
# ─────────────────────────────────────────────

def _normalize_github_push(body: dict) -> NormalizedEvent:
    commits = body.get("commits", [])
    branch = body.get("ref", "").replace("refs/heads/", "")
    pusher = body.get("pusher", {}).get("name", "unknown")

    return NormalizedEvent(
        id=str(uuid.uuid4()),
        platform="github",
        event_type="push",
        actor=pusher,
        timestamp=datetime.now(timezone.utc).isoformat(),
        repo=body.get("repository", {}).get("full_name"),
        action_summary=(
            f"{pusher} pushed {len(commits)} commit(s) to {branch}"
        ),
        raw_metadata={
            "branch": branch,
            "commit_count": len(commits),
            "commits": [
                {"id": c.get("id", "")[:7], "message": c.get("message", "")}
                for c in commits
            ],
            "compare_url": body.get("compare"),
        },
    )


def _normalize_github_pr(body: dict) -> NormalizedEvent:
    pr = body.get("pull_request", {})
    action = body.get("action", "unknown")
    actor = pr.get("user", {}).get("login", "unknown")
    pr_num = pr.get("number")
    pr_title = pr.get("title", "")

    return NormalizedEvent(
        id=str(uuid.uuid4()),
        platform="github",
        event_type="pull_request",
        actor=actor,
        timestamp=datetime.now(timezone.utc).isoformat(),
        repo=body.get("repository", {}).get("full_name"),
        action_summary=f"{actor} {action} PR #{pr_num}: {pr_title}",
        raw_metadata={
            "action": action,
            "pr_number": pr_num,
            "pr_title": pr_title,
            "base_branch": pr.get("base", {}).get("ref"),
            "head_branch": pr.get("head", {}).get("ref"),
            "merged": pr.get("merged", False),
            "pr_url": pr.get("html_url"),
        },
    )


def _normalize_github_issue(body: dict) -> NormalizedEvent:
    issue = body.get("issue", {})
    action = body.get("action", "unknown")
    actor = body.get("sender", {}).get("login", "unknown")

    return NormalizedEvent(
        id=str(uuid.uuid4()),
        platform="github",
        event_type="issue",
        actor=actor,
        timestamp=datetime.now(timezone.utc).isoformat(),
        repo=body.get("repository", {}).get("full_name"),
        action_summary=f"{actor} {action} issue #{issue.get('number')}: {issue.get('title', '')}",
        raw_metadata={
            "action": action,
            "issue_number": issue.get("number"),
            "issue_title": issue.get("title"),
            "issue_state": issue.get("state"),
            "issue_url": issue.get("html_url"),
        },
    )


def _normalize_github_release(body: dict) -> NormalizedEvent:
    release = body.get("release", {})
    action = body.get("action", "unknown")
    actor = body.get("sender", {}).get("login", "unknown")
    
    tag_name = release.get("tag_name", "unknown")
    release_name = release.get("name", "unknown")

    return NormalizedEvent(
        id=str(uuid.uuid4()),
        platform="github",
        event_type="release",
        actor=actor,
        timestamp=datetime.now(timezone.utc).isoformat(),
        repo=body.get("repository", {}).get("full_name"),
        action_summary=f"{actor} {action} release {tag_name}: {release_name}",
        raw_metadata={
            "action": action,
            "tag_name": tag_name,
            "release_name": release_name,
            "release_url": release.get("html_url"),
        },
    )


# ─────────────────────────────────────────────
# Discord normalizer (stub — Member 3 provides real payload shape)
# ─────────────────────────────────────────────

def _normalize_discord_message(body: dict) -> NormalizedEvent:
    """
    TODO: Member 3 sets up the Discord bot and will clarify the exact
    payload format they forward to /discord endpoint.
    This normalizer handles both raw Discord API shape and any
    wrapper format M3 might add.
    """
    # Handle both raw Discord API shape and simple wrapper
    author = (
        body.get("author", {}).get("username")
        or body.get("username")
        or "unknown"
    )
    content = body.get("content", "")
    channel_id = str(body.get("channel_id", body.get("channel", "unknown")))
    timestamp = body.get("timestamp") or datetime.now(timezone.utc).isoformat()

    return NormalizedEvent(
        id=str(uuid.uuid4()),
        platform="discord",
        event_type="message",
        actor=author,
        timestamp=timestamp,
        channel=channel_id,
        action_summary=(
            f"{author} posted in #{channel_id}: "
            + (content[:60] + "..." if len(content) > 60 else content)
        ),
        raw_metadata={
            "content": content,
            "channel_id": channel_id,
            "message_id": body.get("id"),
            "guild_id": body.get("guild_id"),
            # Preserve mentions for future RAG use
            "mentions": body.get("mentions", []),
        },
    )


# ─────────────────────────────────────────────
# Figma normalizer
# ─────────────────────────────────────────────

def _normalize_figma_event(body: dict) -> NormalizedEvent:
    """
    Normalizes a Figma webhook payload.
    """
    event_type = body.get("event_type", "design_update")
    actor = body.get("triggered_by", {}).get("handle", "unknown")
    file_name = body.get("file_name", "unknown_file")
    timestamp = body.get("timestamp") or datetime.now(timezone.utc).isoformat()

    return NormalizedEvent(
        id=str(uuid.uuid4()),
        platform="figma",
        event_type=event_type,
        actor=actor,
        timestamp=timestamp,
        action_summary=f"{actor} triggered {event_type} on Figma file: {file_name}",
        raw_metadata=body,
    )


# ─────────────────────────────────────────────
# Fallback for unknown platforms
# ─────────────────────────────────────────────

def _normalize_unknown(event_type: str, body: dict) -> NormalizedEvent:
    return NormalizedEvent(
        id=str(uuid.uuid4()),
        platform="unknown",
        event_type=event_type,
        actor="unknown",
        timestamp=datetime.now(timezone.utc).isoformat(),
        action_summary=f"Received unrecognized event type: {event_type}",
        raw_metadata=body,
    )


# ─────────────────────────────────────────────
# Main entry point — call this from main.py
# ─────────────────────────────────────────────

ROUTER: dict = {
    "push": _normalize_github_push,
    "pull_request": _normalize_github_pr,
    "issues": _normalize_github_issue,
    "release": _normalize_github_release,
    "discord_message": _normalize_discord_message,
    "figma": _normalize_figma_event,
}


def normalize_event(event_type: str, body: dict) -> NormalizedEvent:
    """
    Routes any incoming raw event to the correct normalizer.
    Returns a clean NormalizedEvent every time — no crashes on bad input.
    """
    handler = ROUTER.get(event_type)
    if handler:
        return handler(body)
    return _normalize_unknown(event_type, body)

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


def _extract_timestamp(body: dict) -> str:
    ts = body.get("timestamp")
    if isinstance(ts, str) and ts:
        return ts
    elif ts is not None and not isinstance(ts, dict):
        return str(ts)
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────
# GitHub normalizers
# ─────────────────────────────────────────────


def _normalize_github_push(body: dict) -> NormalizedEvent:
    commits = body.get("commits", [])
    branch = body.get("ref", "").replace("refs/heads/", "")
    
    pusher = body.get("pusher", {}).get("name") if isinstance(body.get("pusher"), dict) else None
    if not pusher or pusher == "unknown":
        pusher = body.get("sender", {}).get("login") if isinstance(body.get("sender"), dict) else None
    if not pusher or pusher == "unknown":
        if commits and isinstance(commits, list) and isinstance(commits[0], dict):
            author = commits[0].get("author", {})
            if isinstance(author, dict):
                pusher = author.get("username") or author.get("name")
    if not pusher or pusher == "unknown":
        pusher = "unknown"

    timestamp = _extract_timestamp(body)

    return NormalizedEvent(
        id=str(uuid.uuid4()),
        platform="github",
        event_type="push",
        actor=pusher,
        timestamp=timestamp,
        repo=body.get("repository", {}).get("full_name"),
        action_summary=(f"{pusher} pushed {len(commits)} commit(s) to {branch}"),
        raw_metadata={
            "branch": branch,
            "commit_count": len(commits),
            "commits": [
                {
                    "id": c.get("id", "")[:7],
                    "message": c.get("message", ""),
                    "added": c.get("added", []),
                    "modified": c.get("modified", []),
                    "removed": c.get("removed", []),
                }
                for c in commits
            ],
            "compare_url": body.get("compare"),
        },
    )


def _normalize_github_pr(body: dict) -> NormalizedEvent:
    pr = body.get("pull_request", {})
    action = body.get("action", "unknown")
    
    actor = None
    if isinstance(pr, dict):
        actor = pr.get("user", {}).get("login") if isinstance(pr.get("user"), dict) else None
    if not actor or actor == "unknown":
        actor = body.get("sender", {}).get("login") if isinstance(body.get("sender"), dict) else None
    if not actor or actor == "unknown":
        actor = "unknown"

    pr_num = pr.get("number") if isinstance(pr, dict) else None
    pr_title = pr.get("title", "") if isinstance(pr, dict) else ""
    timestamp = _extract_timestamp(body)

    return NormalizedEvent(
        id=str(uuid.uuid4()),
        platform="github",
        event_type="pull_request",
        actor=actor,
        timestamp=timestamp,
        repo=body.get("repository", {}).get("full_name"),
        action_summary=f"{actor} {action} PR #{pr_num}: {pr_title}",
        raw_metadata={
            "action": action,
            "pr_number": pr_num,
            "pr_title": pr_title,
            "base_branch": pr.get("base", {}).get("ref") if isinstance(pr, dict) else None,
            "head_branch": pr.get("head", {}).get("ref") if isinstance(pr, dict) else None,
            "merged": pr.get("merged", False) if isinstance(pr, dict) else False,
            "pr_url": pr.get("html_url") if isinstance(pr, dict) else None,
        },
    )


def _normalize_github_issue(body: dict) -> NormalizedEvent:
    issue = body.get("issue", {})
    action = body.get("action", "unknown")
    
    actor = body.get("sender", {}).get("login") if isinstance(body.get("sender"), dict) else None
    if not actor or actor == "unknown":
        if isinstance(issue, dict):
            actor = issue.get("user", {}).get("login") if isinstance(issue.get("user"), dict) else None
    if not actor or actor == "unknown":
        actor = "unknown"

    issue_num = issue.get("number") if isinstance(issue, dict) else None
    issue_title = issue.get("title", "") if isinstance(issue, dict) else ""
    timestamp = _extract_timestamp(body)

    return NormalizedEvent(
        id=str(uuid.uuid4()),
        platform="github",
        event_type="issue",
        actor=actor,
        timestamp=timestamp,
        repo=body.get("repository", {}).get("full_name"),
        action_summary=f"{actor} {action} issue #{issue_num}: {issue_title}",
        raw_metadata={
            "action": action,
            "issue_number": issue_num,
            "issue_title": issue_title,
            "issue_state": issue.get("state") if isinstance(issue, dict) else None,
            "issue_url": issue.get("html_url") if isinstance(issue, dict) else None,
        },
    )


def _normalize_github_release(body: dict) -> NormalizedEvent:
    release = body.get("release", {})
    action = body.get("action", "unknown")
    
    actor = body.get("sender", {}).get("login") if isinstance(body.get("sender"), dict) else None
    if not actor or actor == "unknown":
        if isinstance(release, dict):
            actor = release.get("author", {}).get("login") if isinstance(release.get("author"), dict) else None
    if not actor or actor == "unknown":
        actor = "unknown"

    tag_name = release.get("tag_name", "unknown") if isinstance(release, dict) else "unknown"
    release_name = release.get("name", "unknown") if isinstance(release, dict) else "unknown"
    timestamp = _extract_timestamp(body)

    return NormalizedEvent(
        id=str(uuid.uuid4()),
        platform="github",
        event_type="release",
        actor=actor,
        timestamp=timestamp,
        repo=body.get("repository", {}).get("full_name"),
        action_summary=f"{actor} {action} release {tag_name}: {release_name}",
        raw_metadata={
            "action": action,
            "tag_name": tag_name,
            "release_name": release_name,
            "release_url": release.get("html_url") if isinstance(release, dict) else None,
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
    # Handle both cases:
    # Case 1 — author is a dict: {"username": "mohit"} (raw Discord API format)
    # Case 2 — author is a plain string: "Mohit"
    author_field = body.get("author")
    author = None
    if isinstance(author_field, dict):
        author = author_field.get("username") or author_field.get("global_name")
    elif isinstance(author_field, str):
        author = author_field

    if not author or author == "unknown":
        author = body.get("username")
    if not author or author == "unknown":
        author = body.get("author_id")
    if not author or author == "unknown":
        author = "unknown"

    content = body.get("content", "")
    channel_id = str(body.get("channel_id", body.get("channel", "unknown")))
    timestamp = _extract_timestamp(body)

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
    
    triggered_by = body.get("triggered_by")
    actor = None
    if isinstance(triggered_by, dict):
        actor = triggered_by.get("handle") or triggered_by.get("email") or triggered_by.get("id")

    if not actor or actor == "unknown":
        act = body.get("actor")
        if isinstance(act, dict):
            actor = act.get("handle") or act.get("email")
        elif isinstance(act, str):
            actor = act

    if not actor or actor == "unknown":
        usr = body.get("user")
        if isinstance(usr, dict):
            actor = usr.get("handle") or usr.get("email")
        elif isinstance(usr, str):
            actor = usr

    if not actor or actor == "unknown":
        actor = "unknown"

    file_name = body.get("file_name", "unknown_file")
    timestamp = _extract_timestamp(body)

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

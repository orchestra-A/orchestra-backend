"""
models.py — Week 2, Member 4
Defines the exact shape of a "Normalized Event".
Every platform (GitHub, Discord, Figma) gets flattened into this same format.
This is what gets stored in events.json and shared with the rest of the team.
"""

from pydantic import BaseModel
from typing import Optional


class NormalizedEvent(BaseModel):
    id: str  # UUID — unique per event
    platform: str  # "github" | "discord" | "figma" | "unknown"
    event_type: str  # "push" | "pull_request" | "message" | "design_update"
    actor: str  # username who triggered this event
    timestamp: str  # ISO 8601 — always UTC
    repo: Optional[str] = None  # for GitHub events: "owner/repo"
    channel: Optional[str] = None  # for Discord events: channel_id
    action_summary: str  # human-readable one-liner for the UI
    raw_metadata: dict  # original fields preserved for M1/M2 to use
    project_id: Optional[str] = None

"""
main.py — Week 2, Member 4 (merged with Member 3's infrastructure)
Added in Week 2:
  - Integrates the Semantic Data Normalizer (normalizer.py)
  - Stores normalized events to events.json (one JSON object per line)
  - Member 3's dedicated webhook endpoints (/webhook/github, /webhook/discord, /webhook/figma)
  - Handles Discord verification handshake
  - Serves static task list for frontend team
"""

import hmac
import hashlib
import os
import json
import sys
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv
from normalizer import normalize_event
from models import NormalizedEvent
from typing import List

load_dotenv()

# =====================================================================
# FastAPI Application Metadata
# =====================================================================
app = FastAPI(
    title="Timeline Orchestra Backend",
    description="Infrastructure layer for Timeline Orchestra",
    version="0.2.0"
)
SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "testsecret123")
EVENTS_FILE = "events.json"

# =====================================================================
# Shared Infrastructure Helpers
# =====================================================================
def log_webhook_payload(platform: str, payload: dict) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    separator = "=" * 60
    print(separator)
    print(f"Incoming webhook received!")
    print(f"Platform  : {platform}")
    print(f"Timestamp : {timestamp}")
    print("Payload:")
    print(json.dumps(payload, indent=2))
    print(separator)
    sys.stdout.flush()

def verify_signature(payload: bytes, sig_header: str) -> bool:
    if not sig_header:
        return False
    mac = hmac.new(SECRET.encode(), payload, hashlib.sha256)
    expected = "sha256=" + mac.hexdigest()
    return hmac.compare_digest(expected, sig_header)

def save_event(event: NormalizedEvent) -> None:
    """Append one normalized event as a JSON line. Thread-safe enough for Week 2."""
    with open(EVENTS_FILE, "a") as f:
        f.write(event.model_dump_json() + "\n")

def load_events() -> List[NormalizedEvent]:
    """Load all stored events from disk."""
    try:
        with open(EVENTS_FILE) as f:
            return [
                NormalizedEvent.model_validate_json(line)
                for line in f
                if line.strip()
            ]
    except FileNotFoundError:
        return []

# =====================================================================
# Route 1 — Health Check
# =====================================================================
@app.get("/")
async def health_check():
    return "Orchestra Backend Set by Sarvyagya"

@app.get("/health")
def health():
    events = load_events()
    return {
        "status": "alive",
        "week": 2,
        "total_events_stored": len(events),
        "platforms_seen": list({e.platform for e in events}),
    }

# =====================================================================
# Route 2 & 3 — Generic Webhook Receivers (kept from Week 1)
# =====================================================================
@app.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()
    log_webhook_payload("GENERIC", payload)
    return {
        "received": True,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/test/simulate-webhook")
async def simulate_webhook(request: Request):
    payload = await request.json()
    log_webhook_payload("SIMULATED", payload)
    return {
        "simulated": True,
        "payload_received": payload,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# =====================================================================
# Route 4 — GitHub Webhook Receiver
# =====================================================================
@app.post("/webhook/github")
async def receive_github(request: Request):
    payload_bytes = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")

    if not verify_signature(payload_bytes, sig):
        raise HTTPException(status_code=403, detail="Bad HMAC signature")

    event_type = request.headers.get("X-GitHub-Event", "unknown")

    try:
        payload = json.loads(payload_bytes)
        log_webhook_payload("GITHUB", payload)
        
        normalized = normalize_event(event_type, payload)
        save_event(normalized)
        print(f"[{event_type.upper()}] {normalized.action_summary}")
        
        return {
            "received": True,
            "platform": "github",
            "event": normalized.model_dump(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except json.JSONDecodeError:
        print(f"[ERROR] [{event_type}] Invalid JSON in payload")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        print(f"[ERROR] [{event_type}] Normalization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# Route 5 — Discord Webhook Receiver
# =====================================================================
@app.post("/webhook/discord")
async def receive_discord(request: Request):
    try:
        payload = await request.json()
        log_webhook_payload("DISCORD", payload)

        if payload.get("type") == 1:
            print("Discord verification ping received — responding with handshake.")
            sys.stdout.flush()
            return {"type": 1}

        normalized = normalize_event("discord_message", payload)
        save_event(normalized)
        print(f"[DISCORD] {normalized.action_summary}")

        return {
            "received": True,
            "platform": "discord",
            "event": normalized.model_dump(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"[ERROR] [DISCORD] Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# Route 6 — Figma Webhook Receiver
# =====================================================================
@app.post("/webhook/figma")
async def receive_figma(request: Request):
    try:
        payload = await request.json()
        log_webhook_payload("FIGMA", payload)
        
        normalized = normalize_event("figma", payload)
        save_event(normalized)
        print(f"[FIGMA] {normalized.action_summary}")

        return {
            "received": True,
            "platform": "figma",
            "event": normalized.model_dump(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"[ERROR] [FIGMA] Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# Read endpoints (for team to inspect stored events)
# =====================================================================
@app.get("/events", response_model=List[NormalizedEvent])
def get_all_events():
    return load_events()

@app.get("/events/{platform}", response_model=List[NormalizedEvent])
def get_events_by_platform(platform: str):
    return [e for e in load_events() if e.platform == platform]

@app.delete("/events/reset")
def reset_events():
    try:
        os.remove(EVENTS_FILE)
        return {"status": "cleared"}
    except FileNotFoundError:
        return {"status": "nothing to clear"}


# =====================================================================
# Route 7 — Mock Tasks Endpoint (for Prince, Frontend Developer)
# =====================================================================
@app.get("/tasks")
async def get_tasks():
    tasks = [
        {
            "id": "task_001",
            "title": "Set up Neo4j database schema",
            "description": "Define node types and relationship models for the knowledge graph.",
            "status": "completed",
            "assigned_to": "Member 2 — Knowledge Graph Engineer",
            "platform": "github",
            "priority": "high",
            "created_at": "2025-05-28T09:00:00Z",
            "updated_at": "2025-05-30T14:30:00Z"
        },
        {
            "id": "task_002",
            "title": "Build semantic data normalizer",
            "description": "Scrub incoming platform events into clean uniform data blocks.",
            "status": "in_progress",
            "assigned_to": "Member 4 — Data Pipeline Engineer",
            "platform": "github",
            "priority": "high",
            "created_at": "2025-05-28T09:00:00Z",
            "updated_at": "2025-06-01T10:00:00Z"
        },
        {
            "id": "task_003",
            "title": "Connect reactflow canvas to backend",
            "description": "Replace static mock files with live database endpoints.",
            "status": "in_progress",
            "assigned_to": "Member 5 — Interactive Canvas Specialist",
            "platform": "figma",
            "priority": "medium",
            "created_at": "2025-05-29T11:00:00Z",
            "updated_at": "2025-05-31T16:00:00Z"
        },
        {
            "id": "task_004",
            "title": "Implement Connect Workspaces UI",
            "description": "Build authentication screens for team tool integrations.",
            "status": "in_progress",
            "assigned_to": "Member 6 — Interface Developer",
            "platform": "figma",
            "priority": "medium",
            "created_at": "2025-05-29T11:00:00Z",
            "updated_at": "2025-06-01T09:00:00Z"
        },
        {
            "id": "task_005",
            "title": "Configure Discord webhook listener",
            "description": "Expand FastAPI server to natively catch Discord events.",
            "status": "completed",
            "assigned_to": "Member 3 — Infrastructure Engineer",
            "platform": "discord",
            "priority": "high",
            "created_at": "2025-06-01T08:00:00Z",
            "updated_at": "2025-06-01T12:00:00Z"
        },
        {
            "id": "task_006",
            "title": "Configure Figma webhook listener",
            "description": "Expand FastAPI server to natively catch Figma design events.",
            "status": "completed",
            "assigned_to": "Member 3 — Infrastructure Engineer",
            "platform": "figma",
            "priority": "high",
            "created_at": "2025-06-01T08:00:00Z",
            "updated_at": "2025-06-01T12:00:00Z"
        },
        {
            "id": "task_007",
            "title": "LLM JSON extraction prompting",
            "description": "Force LLM to respond only in structured valid JSON with no conversational output.",
            "status": "completed",
            "assigned_to": "Member 1 — Agent Architect",
            "platform": "github",
            "priority": "high",
            "created_at": "2025-05-28T09:00:00Z",
            "updated_at": "2025-05-30T11:00:00Z"
        },
        {
            "id": "task_008",
            "title": "GitHub State Machine setup",
            "description": "Auto-update task status when matching pull requests are submitted.",
            "status": "todo",
            "assigned_to": "Member 3 — Infrastructure Engineer",
            "platform": "github",
            "priority": "high",
            "created_at": "2025-06-01T08:00:00Z",
            "updated_at": "2025-06-01T08:00:00Z"
        }
    ]
    return {
        "total": len(tasks),
        "tasks": tasks
    }

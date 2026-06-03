from datetime import datetime, timezone
import json
import sys
import os
from fastapi import FastAPI, Request, Response

# Import Member 4's normalizer and models
from normalizer import normalize_event
from models import NormalizedEvent

# =====================================================================
# FastAPI Application Metadata
# =====================================================================
app = FastAPI(
    title="Timeline Orchestra Backend",
    description="Infrastructure layer for Timeline Orchestra",
    version="0.3.0"
)

# =====================================================================
# Shared Infrastructure Helpers
# =====================================================================

def log_webhook_payload(platform: str, payload: dict) -> None:
    """
    Logs raw incoming webhook payload to terminal.
    """
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


def save_normalized_event(event: NormalizedEvent) -> None:
    """
    Saves a normalized event to events.json file.
    This is temporary storage until Neo4j database is connected.
    Member 2 will replace this with a real database call later.

    Every event gets appended to the list in events.json.
    If the file doesn't exist yet, it creates it automatically.
    """
    filepath = "events.json"

    # Load existing events if file exists
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            events = json.load(f)
    else:
        events = []

    # Append new event
    events.append(event.model_dump())

    # Save back to file
    with open(filepath, "w") as f:
        json.dump(events, f, indent=2)

    print(f"[SAVED] Normalized event saved to {filepath} (total: {len(events)})")
    sys.stdout.flush()


def process_and_save(platform: str, event_type: str, payload: dict) -> NormalizedEvent:
    """
    Central processing pipeline.
    Every webhook route calls this after logging the raw payload.

    1. Passes raw payload to Member 4's normalizer
    2. Prints the clean normalized result
    3. Saves it to events.json
    4. Returns the normalized event
    """
    normalized = normalize_event(event_type, payload)

    print(f"[NORMALIZED] {normalized.action_summary}")
    sys.stdout.flush()

    save_normalized_event(normalized)

    return normalized


# =====================================================================
# Route 1 — Health Check
# =====================================================================
@app.get("/")
async def health_check():
    return "Orchestra Backend Set by Sarvyagya"


# =====================================================================
# Route 2 — Generic Webhook Receiver (kept from Week 1)
# =====================================================================
@app.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()
    log_webhook_payload("GENERIC", payload)
    return {
        "received": True,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# =====================================================================
# Route 3 — Webhook Simulator (for internal testing)
# =====================================================================
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
# Detects event type from the X-GitHub-Event header GitHub sends.
# Routes it to the correct normalizer automatically.
#
# GitHub event types we handle:
# "push"         — someone pushed code to a branch
# "pull_request" — PR opened, closed, merged
# "issues"       — issue opened, closed, commented
# "release"      — a new release was published
# "ping"         — GitHub's verification ping when webhook is registered
# =====================================================================
@app.post("/webhook/github")
async def receive_github(request: Request):
    payload = await request.json()

    # GitHub tells us the event type in a header called X-GitHub-Event
    # e.g. "push", "pull_request", "issues", "ping"
    github_event = request.headers.get("X-GitHub-Event", "unknown")

    log_webhook_payload("GITHUB", payload)

    # GitHub sends a "ping" the first time a webhook is registered
    # Just acknowledge it — no normalization needed
    if github_event == "ping":
        print("[GITHUB] Ping received — webhook registered successfully!")
        sys.stdout.flush()
        return {"received": True, "message": "Ping acknowledged"}

    # For all real events, normalize and save
    normalized = process_and_save("github", github_event, payload)

    return {
        "received": True,
        "platform": "github",
        "event_type": github_event,
        "normalized_summary": normalized.action_summary,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# =====================================================================
# Route 5 — Discord Webhook Receiver
# =====================================================================
# Handles Discord verification ping on first registration.
# All real Discord messages get normalized and saved.
# =====================================================================
@app.post("/webhook/discord")
async def receive_discord(request: Request):
    payload = await request.json()
    log_webhook_payload("DISCORD", payload)

    # Discord verification handshake
    if payload.get("type") == 1:
        print("[DISCORD] Verification ping received — responding with handshake.")
        sys.stdout.flush()
        return {"type": 1}

    # Normalize and save real Discord messages
    normalized = process_and_save("discord", "discord_message", payload)

    return {
        "received": True,
        "platform": "discord",
        "normalized_summary": normalized.action_summary,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# =====================================================================
# Route 6 — Figma Webhook Receiver
# =====================================================================
# All Figma events get normalized and saved.
# =====================================================================
@app.post("/webhook/figma")
async def receive_figma(request: Request):
    payload = await request.json()
    log_webhook_payload("FIGMA", payload)

    # Normalize and save Figma events
    normalized = process_and_save("figma", "figma", payload)

    return {
        "received": True,
        "platform": "figma",
        "normalized_summary": normalized.action_summary,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# =====================================================================
# Route 7 — Mock Tasks Endpoint (for Prince, Frontend Developer)
# =====================================================================
@app.get("/tasks")
async def get_tasks():
    import urllib.request
    import json
    from fastapi import Response
    url = "https://orchestra-ai-production.up.railway.app/tasks"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
        result = {
            "total": len(data),
            "tasks": data
        }
    except Exception as e:
        print(f"[ERROR] Failed to fetch tasks from Graph DB: {e}")
        result = {
            "total": 0,
            "tasks": [],
            "error": str(e)
        }
    
    formatted_json = json.dumps(result, indent=4)
    return Response(content=formatted_json, media_type="application/json")


# =====================================================================
# Route 8 — View Saved Normalized Events
# =====================================================================
# GET /events
# Returns everything saved in events.json so far.
# Useful for Member 2 (Graph Engineer) to see what normalized
# events look like before connecting the real database.
# Also useful for debugging — see exactly what got normalized.
# =====================================================================
@app.get("/events")
async def get_events():
    filepath = "events.json"
    if not os.path.exists(filepath):
        events_data = {"total": 0, "events": []}
    else:
        with open(filepath, "r") as f:
            events_data = {"total": len(json.load(f)), "events": json.load(open(filepath))}

    formatted_json = json.dumps(events_data, indent=4)
    return Response(content=formatted_json, media_type="application/json")
from datetime import datetime, timezone
import json
import sys
from fastapi import FastAPI, Request

# =====================================================================
# FastAPI Application Metadata
# =====================================================================
app = FastAPI(
    title="Timeline Orchestra Backend",
    description="Infrastructure layer for Timeline Orchestra",
    version="0.2.0"
)

# =====================================================================
# Shared Infrastructure Helpers
# =====================================================================
def log_webhook_payload(platform: str, payload: dict) -> None:
    """
    Helper function to print incoming webhook payloads to the terminal.
    Now accepts a "platform" argument so we know which service sent the event.
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


# =====================================================================
# Route 1 — Health Check
# =====================================================================
# - WHAT IT DOES:
#   Quick sanity check to verify the backend is up and accessible.
# - WHY IT RETURNS 200:
#   Standard practice for health checks so monitors know the service is alive.
# - WHAT "async" MEANS:
#   Allows the server to handle other requests while this one is being processed.
# =====================================================================
@app.get("/")
async def health_check():
    return "Orchestra Backend Set by Sarvyagya"


# =====================================================================
# Route 2 — Generic Webhook Receiver (kept from Week 1)
# =====================================================================
# - WHAT IT DOES:
#   Original catch-all webhook route from Stage 1. Kept for backward
#   compatibility so nothing breaks if someone is still pointing at /webhook.
# - WHY IT RETURNS 200:
#   External platforms need a 200 OK immediately or they retry indefinitely.
# - WHAT THE "Request" OBJECT IS:
#   FastAPI utility representing the raw HTTP request — headers, body, IP, etc.
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
# Route 3 — Webhook Simulator (for internal testing, kept from Week 1)
# =====================================================================
# - WHAT IT DOES:
#   Lets developers simulate any incoming webhook payload internally.
#   Runs through the same logging logic as the real receivers.
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
# - WHAT IT DOES:
#   Dedicated endpoint for GitHub events. GitHub sends a POST request
#   here whenever a developer pushes code, opens a pull request, or
#   closes an issue. Each event also carries a header "X-GitHub-Event"
#   telling you the event type (push, pull_request, issues, etc).
#   We log it for now. Member 4 will plug in processing logic later.
# - WHY SEPARATE FROM /webhook:
#   Keeping platforms separated makes Member 4's normalizer job easier —
#   they always know exactly which platform's data they are cleaning.
# =====================================================================
@app.post("/webhook/github")
async def receive_github(request: Request):
    payload = await request.json()
    log_webhook_payload("GITHUB", payload)
    return {
        "received": True,
        "platform": "github",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# =====================================================================
# Route 5 — Discord Webhook Receiver
# =====================================================================
# - WHAT IT DOES:
#   Dedicated endpoint for Discord events such as messages being posted,
#   bot commands being triggered, or users joining/leaving a server.
#
# - DISCORD VERIFICATION HANDSHAKE:
#   The first time you register this URL in the Discord Developer Portal,
#   Discord sends a "ping" to verify the URL is real and responding.
#   That ping looks like: { "type": 1 }
#   Discord expects back: { "type": 1 }
#   If we don't handle this, Discord rejects the URL and webhooks never work.
#   We check for it here and respond correctly so registration succeeds.
# =====================================================================
@app.post("/webhook/discord")
async def receive_discord(request: Request):
    payload = await request.json()
    log_webhook_payload("DISCORD", payload)

    # Discord verification ping — must respond with { "type": 1 }
    # or Discord will reject this URL during registration
    if payload.get("type") == 1:
        print("Discord verification ping received — responding with handshake.")
        sys.stdout.flush()
        return {"type": 1}

    return {
        "received": True,
        "platform": "discord",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# =====================================================================
# Route 6 — Figma Webhook Receiver
# =====================================================================
# - WHAT IT DOES:
#   Dedicated endpoint for Figma events. Figma sends a POST request here
#   when a designer updates a file, publishes a library, or adds a comment.
#
# - COMMON FIGMA EVENT TYPES (in payload's "event_type" field):
#   FILE_UPDATE      — a file was edited
#   FILE_COMMENT     — a comment was added to a design
#   LIBRARY_PUBLISH  — a shared design library was updated
#
# - WHY THIS MATTERS FOR THE PROJECT:
#   When a designer updates the UI in Figma, this endpoint will catch it.
#   That event can later be linked to the corresponding frontend task node
#   in the knowledge graph, keeping design and dev work in sync.
# =====================================================================
@app.post("/webhook/figma")
async def receive_figma(request: Request):
    payload = await request.json()
    log_webhook_payload("FIGMA", payload)
    return {
        "received": True,
        "platform": "figma",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# =====================================================================
# Route 7 — Mock Tasks Endpoint (for Prince, Frontend Developer)
# =====================================================================
# - WHAT IT DOES:
#   Returns hardcoded sample task data so Prince can build and test the
#   UI without waiting for the real database to be ready.
#
# - WHY HARDCODED FOR NOW:
#   The Neo4j database and AI pipeline aren't connected yet. This gives
#   Prince a real, correctly shaped JSON response to build against.
#   When the real database is ready, we replace the hardcoded list with
#   an actual DB query. Prince's frontend code won't need to change at all
#   because the shape (fields and structure) stays exactly the same.
#
# - FIELD REFERENCE FOR PRINCE:
#   id          — unique task identifier
#   title       — short task name
#   description — full task details
#   status      — one of: "todo", "in_progress", "completed"
#   assigned_to — team member responsible
#   platform    — where the task activity comes from: github/figma/discord
#   priority    — "high", "medium", or "low"
#   created_at  — ISO 8601 UTC timestamp
#   updated_at  — ISO 8601 UTC timestamp
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
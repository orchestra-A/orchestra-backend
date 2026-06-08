from datetime import datetime, timezone
import json
import sys
import os
from fastapi import FastAPI, Request
from fastapi.websockets import WebSocket, WebSocketDisconnect
from typing import List
import asyncio
import re
import discord
from discord.ext import tasks
import hmac
import hashlib

# Import Member 4's normalizer and models
from normalizer import normalize_event
from state_machine import process_normalized_event
from models import NormalizedEvent

# =====================================================================
# FastAPI Application Metadata
# =====================================================================
app = FastAPI(
    title="Timeline Orchestra Backend",
    description="Infrastructure layer for Timeline Orchestra",
    version="0.7.0"
)

@app.on_event("startup")
async def startup_event():
    """
    Runs when FastAPI server starts.
    Starts the Discord bot as a background task.
    Bot runs alongside your server forever.
    """
    print("[STARTUP] Server starting...")
    sys.stdout.flush()
    asyncio.create_task(start_discord_bot())
    print("[STARTUP] Discord bot task created")
    sys.stdout.flush()

# =====================================================================
# Environment Variables
# GitHub & Discord OAuth credentials — stored in .env file, never hardcoded
# =====================================================================
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_WEBHOOK_SECRET_KEY = os.getenv("GITHUB_WEBHOOK_SECRET_KEY", "default_secret")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# =====================================================================
# WEBSOCKET CONNECTION MANAGER
# =====================================================================
# This is the broadcast system.
#
# Imagine a WhatsApp group called "Task Updates".
# Every browser tab that opens Timeline Orchestra joins this group.
# When a task changes status, your server sends a message to the group.
# Every browser in the group receives it instantly.
#
# active_connections = the list of all browsers currently open
# connect()         = adds a browser to the group when it opens
# disconnect()      = removes a browser when it closes the tab
# broadcast()       = sends a message to every browser in the group
# =====================================================================
class ConnectionManager:
    def __init__(self):
        # List of all currently connected browsers
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        # Accept the connection request from browser
        # Add it to our active list
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WEBSOCKET] ✅ New browser connected. Total connected: {len(self.active_connections)}")
        sys.stdout.flush()

    def disconnect(self, websocket: WebSocket):
        # Browser closed the tab — remove from list
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"[WEBSOCKET] ❌ Browser disconnected. Total connected: {len(self.active_connections)}")
        sys.stdout.flush()

    async def broadcast(self, message: dict):
        # Send message to every connected browser simultaneously
        # If any connection is broken, remove it silently
        disconnected = []

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                # Connection broke — mark for removal
                disconnected.append(connection)

        # Clean up broken connections
        for connection in disconnected:
            self.active_connections.remove(connection)

        print(f"[WEBSOCKET] 📡 Broadcast sent to {len(self.active_connections)} browser(s)")
        print(f"[WEBSOCKET] Message: {message}")
        sys.stdout.flush()


# Create one single manager that lives as long as the server runs
# Every route uses this same manager
manager = ConnectionManager()

# =====================================================================
# STARTUP — Initialize tasks.json
# =====================================================================
# When server starts, if tasks.json doesn't exist yet,
# create it from our hardcoded task list.
# This gives the State Machine something to read and update.
# =====================================================================
# =====================================================================
# GITHUB WEBHOOK AUTO-REGISTRATION HELPERS
# =====================================================================

def generate_user_webhook_secret(github_username: str) -> str:
    """
    Generates a unique webhook secret for each user.

    Why unique per user?
    When 100 different teams connect their GitHub repos,
    each team's events need to be verified separately.
    If everyone shared one secret and it leaked, all teams
    would be compromised. Unique secrets isolate the damage.

    How it works:
    Combines your master secret key with the username
    and creates a unique hash. Same username always
    produces the same secret — so you can verify later.
    """
    combined = f"{GITHUB_WEBHOOK_SECRET_KEY}:{github_username}"
    return hmac.new(
        GITHUB_WEBHOOK_SECRET_KEY.encode(),
        combined.encode(),
        hashlib.sha256
    ).hexdigest()[:32]


async def register_github_webhook(
    access_token: str,
    github_username: str,
    repo_full_name: str
) -> dict:
    """
    Automatically registers a webhook on the user's GitHub repo.

    This is called after OAuth login completes.
    The user never has to manually go to GitHub settings.
    Orchestra does it for them automatically.

    access_token   = the token GitHub gave us after OAuth
    github_username = their GitHub username
    repo_full_name  = "username/repo-name" format
    """
    import httpx

    # Generate a unique secret for this user
    webhook_secret = generate_user_webhook_secret(github_username)

    # This is the URL GitHub will send events to
    # Every user's events come to the same endpoint
    # We identify whose event it is from the payload
    webhook_url = "https://orchestra-backend-2v5a.onrender.com/webhook/github"

    # The webhook configuration we send to GitHub
    webhook_config = {
        "name": "web",
        "active": True,
        "events": [
            "push",           # Someone pushed code
            "pull_request",   # PR opened, closed, merged
            "issues"          # Issue created, closed, commented
        ],
        "config": {
            "url": webhook_url,
            "content_type": "json",
            "secret": webhook_secret,
            "insecure_ssl": "0"
        }
    }

    # Call GitHub API to create the webhook
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.github.com/repos/{repo_full_name}/hooks",
            json=webhook_config,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"
            }
        )

    if response.status_code == 201:
        print(f"[GITHUB] ✅ Webhook registered for {repo_full_name}")
        sys.stdout.flush()
        return {
            "success": True,
            "repo": repo_full_name,
            "webhook_id": response.json().get("id"),
            "events": ["push", "pull_request", "issues"]
        }
    elif response.status_code == 422:
        # 422 means webhook already exists on this repo
        print(f"[GITHUB] ℹ️ Webhook already exists for {repo_full_name}")
        sys.stdout.flush()
        return {
            "success": True,
            "repo": repo_full_name,
            "note": "Webhook already registered"
        }
    else:
        print(f"[GITHUB] ❌ Failed to register webhook: {response.status_code}")
        print(f"[GITHUB] Response: {response.text}")
        sys.stdout.flush()
        return {
            "success": False,
            "repo": repo_full_name,
            "error": response.text,
            "status_code": response.status_code
        }


def save_connected_user(
    github_username: str,
    access_token: str,
    repo_full_name: str,
    webhook_result: dict
) -> None:
    """
    Saves the connected user's information to connected_users.json.

    This is your record of which users have connected their GitHub.
    Later this will be stored in a proper database.
    For now a JSON file works fine for development.
    """
    filepath = "connected_users.json"

    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            users = json.load(f)
    else:
        users = {}

    users[github_username] = {
        "github_username": github_username,
        "repo": repo_full_name,
        "connected_at": datetime.now(timezone.utc).isoformat(),
        "webhook_registered": webhook_result.get("success", False),
        "webhook_id": webhook_result.get("webhook_id"),
        "access_token": access_token  # In production this would be encrypted
    }

    with open(filepath, "w") as f:
        json.dump(users, f, indent=2)

    print(f"[USER] ✅ Saved connected user: {github_username}")
    sys.stdout.flush()

def save_discord_user(
    discord_id: str,
    discord_username: str,
    access_token: str,
    email: str = None
) -> None:
    """
    Saves a Discord connected user to discord_users.json
    
    When a user logs in with Discord, we save:
    - Their Discord ID (unique identifier)
    - Their username
    - Their access token (for sending them DMs later via bot)
    - Their email if they provided it
    
    This file is what the bot uses in Step 4 (daily standup)
    to know who to send messages to.
    """
    filepath = "discord_users.json"

    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            users = json.load(f)
    else:
        users = {}

    users[discord_id] = {
        "discord_id": discord_id,
        "discord_username": discord_username,
        "access_token": access_token,
        "email": email,
        "connected_at": datetime.now(timezone.utc).isoformat()
    }

    with open(filepath, "w") as f:
        json.dump(users, f, indent=2)

    print(f"[DISCORD AUTH] ✅ Saved Discord user: {discord_username}")
    sys.stdout.flush()

def update_member_activity(actor: str, content: str, timestamp: str) -> None:
    """
    Updates what each team member is working on.
    Called every time a Discord message arrives.

    Builds a picture like:
    "Arjun is working on: Just finished the login page"

    This is what gets shown on the Orchestra dashboard as:
    Member X is doing: ----
    Member Y is doing: ----
    """
    filepath = "discord_activity.json"

    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            activity = json.load(f)
    else:
        activity = {}

    activity[actor] = {
        "actor": actor,
        "latest_message": content,
        "last_seen": timestamp,
        "message_count": activity.get(actor, {}).get("message_count", 0) + 1
    }

    with open(filepath, "w") as f:
        json.dump(activity, f, indent=2)

    print(f"[ACTIVITY] Updated activity for {actor}: {content[:40]}")
    sys.stdout.flush()

def initialize_tasks_file():
    if not os.path.exists("tasks.json"):
        tasks_data = {
            "total": 12,
            "tasks": [
                {
                    "id": "task_001",
                    "order": 1,
                    "project_id": "proj_orchestra",
                    "title": "Set up Neo4j database schema",
                    "description": "Define node types and relationship models.",
                    "status": "completed",
                    "assigned_to": "Member 2 — Knowledge Graph Engineer",
                    "platform": "github",
                    "priority": "high",
                    "created_at": "2025-05-28T09:00:00Z",
                    "updated_at": "2025-05-30T14:30:00Z"
                },
                {
                    "id": "task_002",
                    "order": 2,
                    "project_id": "proj_orchestra",
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
                    "order": 3,
                    "project_id": "proj_orchestra",
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
                    "order": 4,
                    "project_id": "proj_orchestra",
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
                    "order": 5,
                    "project_id": "proj_orchestra",
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
                    "order": 6,
                    "project_id": "proj_orchestra",
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
                    "order": 7,
                    "project_id": "proj_orchestra",
                    "title": "LLM JSON extraction prompting",
                    "description": "Force LLM to respond only in structured valid JSON.",
                    "status": "completed",
                    "assigned_to": "Member 1 — Agent Architect",
                    "platform": "github",
                    "priority": "high",
                    "created_at": "2025-05-28T09:00:00Z",
                    "updated_at": "2025-05-30T11:00:00Z"
                },
                {
                    "id": "task_008",
                    "order": 8,
                    "project_id": "proj_orchestra",
                    "title": "GitHub State Machine setup",
                    "description": "Auto-update task status when matching pull requests are submitted.",
                    "status": "todo",
                    "assigned_to": "Member 3 — Infrastructure Engineer",
                    "platform": "github",
                    "priority": "high",
                    "created_at": "2025-06-01T08:00:00Z",
                    "updated_at": "2025-06-01T08:00:00Z"
                },
                {
                    "id": "task_009",
                    "order": 1,
                    "project_id": "proj_marketing",
                    "title": "Design new landing page",
                    "description": "Create wireframes and mockups for the marketing site.",
                    "status": "completed",
                    "assigned_to": "Member 6 — Interface Developer",
                    "platform": "figma",
                    "priority": "high",
                    "created_at": "2025-06-02T08:00:00Z",
                    "updated_at": "2025-06-02T12:00:00Z"
                },
                {
                    "id": "task_010",
                    "order": 2,
                    "project_id": "proj_marketing",
                    "title": "Write copy for landing page",
                    "description": "Draft marketing copy and value propositions.",
                    "status": "todo",
                    "assigned_to": "Member 1 — Agent Architect",
                    "platform": "discord",
                    "priority": "medium",
                    "created_at": "2025-06-02T09:00:00Z",
                    "updated_at": "2025-06-02T09:00:00Z"
                },
                {
                    "id": "task_011",
                    "order": 1,
                    "project_id": "proj_mobile_app",
                    "title": "Setup React Native CLI",
                    "description": "Initialize the bare React Native project.",
                    "status": "todo",
                    "assigned_to": "Member 5 — Interactive Canvas Specialist",
                    "platform": "github",
                    "priority": "high",
                    "created_at": "2025-06-03T10:00:00Z",
                    "updated_at": "2025-06-03T10:00:00Z"
                },
                {
                    "id": "task_012",
                    "order": 1,
                    "project_id": "proj_analytics",
                    "title": "Define tracking plan",
                    "description": "Map out all funnel events for mixpanel.",
                    "status": "in_progress",
                    "assigned_to": "Member 4 — Data Pipeline Engineer",
                    "platform": "figma",
                    "priority": "medium",
                    "created_at": "2025-06-04T11:00:00Z",
                    "updated_at": "2025-06-04T11:00:00Z"
                }
            ]
        }
        with open("tasks.json", "w") as f:
            json.dump(tasks_data, f, indent=2)
        print("[STARTUP] tasks.json initialized successfully")
        sys.stdout.flush()
    else:
        print("[STARTUP] tasks.json already exists, skipping initialization")
        sys.stdout.flush()

# Run on startup
initialize_tasks_file()

# =====================================================================
# DISCORD BOT
# =====================================================================
# This bot runs as a background task inside your FastAPI server.
# When your server starts, the bot logs in to Discord automatically.
#
# What the bot does:
# 1. Sits in your team's Discord server
# 2. Reads every message sent in the channels it can see
# 3. Forwards messages to your /webhook/discord logic directly
# 4. Sends daily standup summaries (Step 4 — built next)
#
# Think of it as a team member who never sleeps and reads
# every message in the Discord server and reports it to Orchestra.
# =====================================================================

# Set up Discord bot with all necessary permissions
# intents = what the bot is allowed to do
intents = discord.Intents.default()
intents.message_content = True    # Can read message text
intents.members = True            # Can see server members
intents.guilds = True             # Can see servers it's in
intents.messages = True           # Can receive message events

bot = discord.Client(intents=intents)


@bot.event
async def on_ready():
    """
    Fires when bot successfully logs in to Discord.
    Think of it like the bot saying "I'm here, ready to work."
    """
    print(f"[DISCORD BOT] ✅ Bot logged in as: {bot.user.name}")
    print(f"[DISCORD BOT] Connected to {len(bot.guilds)} server(s)")
    for guild in bot.guilds:
        print(f"[DISCORD BOT] - {guild.name} (id: {guild.id})")
    sys.stdout.flush()


@bot.event
async def on_message(message):
    """
    Fires every time someone sends a message in any channel
    the bot can see.

    What we do:
    1. Ignore messages from the bot itself (prevents infinite loops)
    2. Ignore empty messages
    3. Build a payload in the same format as our /webhook/discord expects
    4. Call our existing processing logic directly
    5. Update member activity tracker

    This replaces Make.com completely.
    Real message text is now captured properly.
    """
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return

    # Ignore empty messages (images, stickers with no text)
    if not message.content:
        return

    print(f"[DISCORD BOT] 📨 Message from {message.author.name}: {message.content[:50]}")
    sys.stdout.flush()

    # Build payload in same format as /webhook/discord expects
    # This way our existing normalizer handles it exactly the same
    payload = {
        "type": 0,
        "channel_id": str(message.channel.id),
        "channel_name": str(message.channel.name),
        "content": message.content,
        "author": message.author.name,
        "author_id": str(message.author.id),
        "guild_id": str(message.guild.id) if message.guild else None,
        "message_id": str(message.id),
        "timestamp": message.created_at.isoformat()
    }

    # Update member activity tracker
    # This builds "Member X is working on: ..."
    update_member_activity(
        actor=message.author.name,
        content=message.content,
        timestamp=message.created_at.isoformat()
    )

    # Save as normalized event using existing pipeline
    # Same as if it came through /webhook/discord
    try:
        from normalizer import normalize_event
        normalized = normalize_event("discord_message", payload)
        save_normalized_event(normalized)
        print(f"[DISCORD BOT] ✅ Message normalized and saved")
        sys.stdout.flush()
    except Exception as e:
        print(f"[DISCORD BOT] ⚠️ Normalization error: {e}")
        sys.stdout.flush()


async def start_discord_bot():
    """
    Starts the Discord bot.
    Called when FastAPI server starts up.
    Runs forever in the background alongside your server.
    """
    if not DISCORD_BOT_TOKEN:
        print("[DISCORD BOT] ⚠️ No bot token found. Bot not starting.")
        print("[DISCORD BOT] Add DISCORD_BOT_TOKEN to your .env file")
        sys.stdout.flush()
        return

    try:
        print("[DISCORD BOT] Starting...")
        sys.stdout.flush()
        await bot.start(DISCORD_BOT_TOKEN)
    except Exception as e:
        print(f"[DISCORD BOT] ❌ Failed to start: {e}")
        sys.stdout.flush()

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


def save_normalized_event(event: NormalizedEvent) -> None:
    filepath = "events.json"
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            events = json.load(f)
    else:
        events = []
    events.append(event.model_dump())
    with open(filepath, "w") as f:
        json.dump(events, f, indent=2)
    print(f"[SAVED] Normalized event saved (total: {len(events)})")
    sys.stdout.flush()


def process_and_save(platform: str, event_type: str, payload: dict) -> NormalizedEvent:
    normalized = normalize_event(event_type, payload)
    print(f"[NORMALIZED] {normalized.action_summary}")
    sys.stdout.flush()
    save_normalized_event(normalized)
    return normalized


# =====================================================================
# STATE MACHINE HELPERS
# =====================================================================

def extract_task_references(commit_message: str) -> list:
    """
    Scans a commit message for task references.

    Recognized patterns:
    - "Fixes Task #8"       → task_008
    - "Closes #3"           → task_003
    - "Resolves task_005"   → task_005
    - "fixes task 12"       → task_012

    Returns a list of task IDs found in the message.
    """
    patterns = [
        r'(?:fixes|closes|resolves)\s+task[_\s#]+(\d+)',
        r'(?:fixes|closes|resolves)\s+#(\d+)',
        r'task[_\s#]+(\d+)',
    ]
    found = []
    message_lower = commit_message.lower()
    for pattern in patterns:
        matches = re.findall(pattern, message_lower)
        found.extend(matches)
    return list(set(found))


def update_task_status(task_ref: str, new_status: str) -> bool:
    """
    Finds a task by its reference number and updates its status.

    task_ref is just the number — "8" finds "task_008"
    new_status is "completed", "in_progress", or "todo"

    Returns True if task was found and updated.
    Returns False if task was not found.
    """
    filepath = "tasks.json"

    if not os.path.exists(filepath):
        print(f"[STATE MACHINE] tasks.json not found — cannot update task")
        sys.stdout.flush()
        return False

    with open(filepath, "r") as f:
        data = json.load(f)

    # Build the full task ID from the number
    # "8" becomes "task_008"
    full_task_id = f"task_{task_ref.zfill(3)}"

    for task in data.get("tasks", []):
        if task["id"] == full_task_id:
            old_status = task["status"]
            task["status"] = new_status
            task["updated_at"] = datetime.now(timezone.utc).isoformat()

            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)

            print(f"[STATE MACHINE] ✅ {full_task_id}: {old_status} → {new_status}")
            sys.stdout.flush()

            # ── WEBSOCKET BROADCAST ────────────────────────────────
            # The moment a task status changes, tell every connected
            # browser about it immediately.
            # Member 5's frontend listens for this and changes the
            # task node color on screen without any page refresh.
            # ──────────────────────────────────────────────────────
            try:
                asyncio.create_task(manager.broadcast({
                    "type": "task_updated",
                    "task_id": full_task_id,
                    "old_status": old_status,
                    "new_status": new_status,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }))
                print(f"[WEBSOCKET] 📡 Broadcast triggered for {full_task_id}")
                sys.stdout.flush()
            except Exception as e:
                print(f"[WEBSOCKET] ⚠️ Broadcast failed: {e}")
                sys.stdout.flush()

            return True

    print(f"[STATE MACHINE] ❌ Task {full_task_id} not found in tasks.json")
    sys.stdout.flush()
    return False


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
# Route 3 — Webhook Simulator
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
# Route 4 — GitHub Webhook Receiver + State Machine
# =====================================================================
# When GitHub sends a push event, this route:
# 1. Logs the raw payload
# 2. Reads every commit message
# 3. Looks for task references like "Fixes Task #8"
# 4. Automatically updates matching tasks to "completed"
# 5. Normalizes and saves the event
# =====================================================================
@app.post("/webhook/github")
async def receive_github(request: Request):

    # ── SIGNATURE VERIFICATION ─────────────────────────────────
    # Read raw bytes first — needed for signature check
    # We must read raw_body BEFORE parsing as JSON
    raw_body = await request.body()

    # Get the signature GitHub sent in the header
    github_signature = request.headers.get("X-Hub-Signature-256", "")

    # Parse payload
    try:
        payload = json.loads(raw_body)
    except Exception:
        return {"error": "Invalid JSON payload"}

    # Find out who sent this event
    sender = (
        payload.get("sender", {}).get("login")
        or payload.get("pusher", {}).get("name")
        or "unknown"
    )

    # Look up this user's unique webhook secret
    connected_users_file = "connected_users.json"
    user_secret = None

    if os.path.exists(connected_users_file):
        with open(connected_users_file, "r") as f:
            users = json.load(f)
        if sender in users:
            user_secret = generate_user_webhook_secret(sender)

    # Verify signature if we have a secret for this user
    if github_signature and user_secret:
        expected_signature = "sha256=" + hmac.new(
            user_secret.encode(),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(github_signature, expected_signature):
            print(f"[GITHUB] ❌ Signature verification FAILED for {sender}")
            sys.stdout.flush()
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid signature"}
            )
        print(f"[GITHUB] ✅ Signature verified for {sender}")
        sys.stdout.flush()
    # ── END SIGNATURE VERIFICATION ──────────────────────────────

    github_event = request.headers.get("X-GitHub-Event", "unknown")
    log_webhook_payload("GITHUB", payload)

    # GitHub ping when webhook is first registered
    if github_event == "ping":
        print(f"[GITHUB] ✅ Ping from {sender} — webhook registered!")
        sys.stdout.flush()
        return {"received": True, "message": "Ping acknowledged"}

    # ── NORMALIZE EVENT FIRST ──────────────────────────────────
    normalized = process_and_save("github", github_event, payload)

    # ── WEBSOCKET BROADCAST: New Event ─────────────────────────
    # Broadcast every new event to the frontend feed
    asyncio.create_task(manager.broadcast({
        "type": "new_event",
        **normalized.model_dump()
    }))

    # ── SMART STATE MACHINE ────────────────────────────────────
    updated_tasks = []
    
    # Pass the normalized dict straight to the engine (now async)
    state_change = await process_normalized_event(normalized.model_dump())
    
    if state_change:
        # A state transition successfully happened!
        updated_tasks.append(state_change["id"])
        
        # Get the old and new status from the history trail
        last_transition = state_change["history"][-1] if state_change["history"] else {}
        old_status = last_transition.get("from", "PENDING").lower() if last_transition.get("from") != "PENDING" else "todo"
        new_status = state_change["status"]
        
        # ── WEBSOCKET BROADCAST ────────────────────────────────
        try:
            asyncio.create_task(manager.broadcast({
                "type": "task_updated",
                "task_id": state_change["id"],
                "old_status": old_status,
                "new_status": new_status,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }))
            print(f"[WEBSOCKET] 📡 Broadcast triggered for {state_change['id']}")
            sys.stdout.flush()
        except Exception as e:
            print(f"[WEBSOCKET] ⚠️ Broadcast failed: {e}")
            sys.stdout.flush()

    return {
        "received": True,
        "platform": "github",
        "event_type": github_event,
        "sender": sender,
        "normalized_summary": normalized.action_summary,
        "tasks_auto_updated": updated_tasks,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# =====================================================================
# Route 5 — Discord Webhook Receiver
# =====================================================================
@app.post("/webhook/discord")
async def receive_discord(request: Request):
    payload = await request.json()
    log_webhook_payload("DISCORD", payload)
    if payload.get("type") == 1:
        print("[DISCORD] Verification ping — responding with handshake.")
        sys.stdout.flush()
        return {"type": 1}
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
@app.post("/webhook/figma")
async def receive_figma(request: Request):
    payload = await request.json()
    log_webhook_payload("FIGMA", payload)
    normalized = process_and_save("figma", "figma", payload)
    return {
        "received": True,
        "platform": "figma",
        "normalized_summary": normalized.action_summary,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# =====================================================================
# Route 7 — Local Tasks Endpoint
# =====================================================================
# Returns tasks from local tasks.json.
# This ensures Member 3's UI sees the latest State Machine updates.
# =====================================================================
@app.get("/tasks")
async def get_tasks():
    from fastapi import Response
    filepath = "tasks.json"
    if not os.path.exists(filepath):
        initialize_tasks_file()
    with open(filepath, "r") as f:
        data = json.load(f)
    
    formatted_json = json.dumps(data, indent=4)
    return Response(content=formatted_json, media_type="application/json")

# =====================================================================
# Route 7.1 — Live Tasks Endpoint (Member 2's API)
# =====================================================================
@app.get("/tasks/live")
async def get_tasks_live():
    import urllib.request
    from fastapi import Response
    url = "https://orchestra-backend-2v5a.onrender.com/tasks"
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
# Route 7.2 — Task CRUD Endpoints (Week 3 Day 2)
# =====================================================================
@app.get("/tasks/{task_id}")
async def get_single_task(task_id: str):
    filepath = "tasks.json"
    if not os.path.exists(filepath):
        return {"error": "tasks.json not found"}
    with open(filepath, "r") as f:
        data = json.load(f)
    for task in data.get("tasks", []):
        if task["id"] == task_id:
            return task
    return {"error": "Task not found"}

@app.post("/tasks")
async def create_new_task(request: Request):
    body = await request.json()
    task_id = body.get("id")
    title = body.get("title", "Untitled")
    if not task_id:
        return {"error": "'id' field required"}
        
    filepath = "tasks.json"
    if not os.path.exists(filepath):
        initialize_tasks_file()
    with open(filepath, "r") as f:
        data = json.load(f)
        
    new_task = {
        "id": task_id,
        "title": title,
        "status": "todo",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    data["tasks"].append(new_task)
    data["total"] = len(data["tasks"])
    
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
        
    # Broadcast new task creation
    try:
        asyncio.create_task(manager.broadcast({
            "type": "task_created",
            "task": new_task,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }))
    except Exception:
        pass
        
    return new_task

@app.patch("/tasks/{task_id}/state")
async def manually_update_task_state(task_id: str, request: Request):
    body = await request.json()
    new_state = body.get("state")
    if not new_state:
        return {"error": "'state' field required"}
        
    # Extract just the number for the update function (e.g. "task_001" -> "1")
    task_ref = task_id.replace("task_", "").lstrip("0")
    if not task_ref:
        task_ref = "0"
        
    success = update_task_status(task_ref, new_state)
    if success:
        return {"status": "success", "message": f"Updated {task_id} to {new_state}"}
    return {"error": "Task not found"}



# =====================================================================
# Route 8 — View Saved Normalized Events
# =====================================================================
@app.get("/events")
async def get_events():
    from fastapi.responses import Response
    filepath = "events.json"
    if not os.path.exists(filepath):
        return {"total": 0, "events": []}

    with open(filepath, "r") as f:
        events = json.load(f)

    result = {
        "total": len(events),
        "events": events
    }

    formatted = json.dumps(result, indent=4)
    return Response(content=formatted, media_type="application/json")
# =====================================================================
# Route 9 — WebSocket Live Connection
# =====================================================================
# This is the permanent open phone line browsers connect to.
#
# HOW IT WORKS:
# 1. Member 5's frontend connects to this URL once when page loads
# 2. Connection stays open as long as the browser tab is open
# 3. When any task updates, manager.broadcast() fires automatically
# 4. This route pushes the update to Member 5's browser instantly
# 5. Member 5's code uses task_id to find the node and change color
#
# WHAT MEMBER 5 RECEIVES (automatically, no request needed):
# {
#   "type": "task_updated",
#   "task_id": "task_008",
#   "old_status": "in_progress",
#   "new_status": "completed",
#   "timestamp": "2025-06-03T10:00:00Z"
# }
#
# URL TO GIVE MEMBER 5:
# wss://orchestra-backend-2v5a.onrender.com/ws
#
# NOTE: wss:// is the secure version of ws:// — same as https vs http
# =====================================================================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Add this browser to the connected list
    await manager.connect(websocket)

    # Send a welcome message so Member 5 knows connection succeeded
    await websocket.send_json({
        "type": "connection_established",
        "message": "Connected to Timeline Orchestra live updates",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    try:
        # Keep the connection alive forever
        # Wait for any message from the browser
        # Browser can send "ping" to check if connection is still alive
        while True:
            data = await websocket.receive_text()

            if data == "ping":
                # Browser is checking if we're still here — respond
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                print(f"[WEBSOCKET] Ping received — pong sent")
                sys.stdout.flush()

    except WebSocketDisconnect:
        # Browser closed the tab — remove from list
        manager.disconnect(websocket)
# =====================================================================
# Route — GitHub OAuth Login
# =====================================================================
# User clicks "Connect GitHub" on the frontend.
# This redirects them to GitHub's authorization page.
# After approval, GitHub redirects back to /auth/github/callback
# =====================================================================
@app.get("/auth/github")
async def github_login(repo: str = None):
    from fastapi.responses import RedirectResponse
    import urllib.parse

    # We pass the repo name through GitHub's "state" parameter
    # GitHub preserves "state" through the OAuth flow and sends it back
    # This is the standard way to pass data through OAuth redirects
    state = urllib.parse.quote(repo) if repo else ""

    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&scope=read:user,repo,admin:repo_hook"
        f"&state={state}"
    )
    return RedirectResponse(github_auth_url)


# =====================================================================
# Route — GitHub OAuth Callback
# =====================================================================
# GitHub redirects here after user approves access.
# We exchange the code for a token, get their profile,
# then automatically register a webhook on their repo.
#
# User passes their repo like this:
# /auth/github/callback?code=XXX&repo=username/reponame
# =====================================================================
@app.get("/auth/github/callback")
async def github_callback(code: str, state: str = None):
    import httpx

    async with httpx.AsyncClient() as client:

        # Step 1 — Exchange code for access token
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code
            },
            headers={"Accept": "application/json"}
        )
        token_data = token_response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            return {
                "error": "Failed to get access token",
                "details": token_data
            }

        # Step 2 — Get user's GitHub profile
        user_response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }
        )
        user_data = user_response.json()
        github_username = user_data.get("login")

    # Step 3 — Auto register webhook on their repo
    # Decode the repo name from the state parameter
    import urllib.parse
    repo = urllib.parse.unquote(state) if state else None
    webhook_result = {"success": False, "note": "No repo provided"}

    if repo:
        print(f"[GITHUB] Registering webhook for {github_username} on {repo}")
        sys.stdout.flush()
        webhook_result = await register_github_webhook(
            access_token=access_token,
            github_username=github_username,
            repo_full_name=repo
        )
        save_connected_user(
            github_username=github_username,
            access_token=access_token,
            repo_full_name=repo,
            webhook_result=webhook_result
        )

    return {
        "message": "GitHub connected successfully",
        "user": {
            "github_username": github_username,
            "name": user_data.get("name"),
            "avatar": user_data.get("avatar_url"),
            "github_url": user_data.get("html_url")
        },
        "webhook_registration": webhook_result
    }


# =====================================================================
# Route — View Connected Users
# =====================================================================
# GET /connected-users
# Shows all users who connected their GitHub to Orchestra.
# =====================================================================
@app.get("/connected-users")
async def get_connected_users():
    from fastapi.responses import Response

    filepath = "connected_users.json"
    if not os.path.exists(filepath):
        return {"total": 0, "users": []}

    with open(filepath, "r") as f:
        users = json.load(f)

    safe_users = []
    for username, data in users.items():
        safe_users.append({
            "github_username": data.get("github_username"),
            "repo": data.get("repo"),
            "connected_at": data.get("connected_at"),
            "webhook_registered": data.get("webhook_registered"),
            "webhook_id": data.get("webhook_id")
        })

    result = {
        "total": len(safe_users),
        "connected_users": safe_users
    }

    formatted = json.dumps(result, indent=4)
    return Response(content=formatted, media_type="application/json")

# =====================================================================
# Route — Discord OAuth Login
# =====================================================================
# User clicks "Login with Discord" on the frontend.
# This redirects them to Discord's authorization page.
#
# Scopes we request:
# identify  = get their username and Discord ID
# email     = get their email address
# guilds    = see which Discord servers they are in
#             (needed later for bot to join their server)
# =====================================================================
@app.get("/auth/discord")
async def discord_login():
    from fastapi.responses import RedirectResponse

    discord_auth_url = (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri=https://orchestra-backend-2v5a.onrender.com/auth/discord/callback"
        f"&response_type=code"
        f"&scope=identify%20email%20guilds"
    )
    return RedirectResponse(discord_auth_url)


# =====================================================================
# Route — Discord OAuth Callback
# =====================================================================
# Discord redirects here after user approves access.
# We exchange the code for a token and get their profile.
#
# What "identify" scope gives us:
# - id          = their unique Discord ID (like "799906716887679028")
# - username    = their Discord username (like "moonknight6006")
# - avatar      = their profile picture
# - email       = their email (if they approved email scope)
#
# We save all this to discord_users.json for the bot to use later.
# =====================================================================
@app.get("/auth/discord/callback")
async def discord_callback(code: str):
    import httpx

    async with httpx.AsyncClient() as client:

        # Step 1 — Exchange code for access token
        token_response = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://orchestra-backend-2v5a.onrender.com/auth/discord/callback"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        token_data = token_response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            return {
                "error": "Failed to get access token from Discord",
                "details": token_data
            }

        # Step 2 — Use token to get user's Discord profile
        user_response = await client.get(
            "https://discord.com/api/users/@me",
            headers={
                "Authorization": f"Bearer {access_token}"
            }
        )
        user_data = user_response.json()

        discord_id = user_data.get("id")
        discord_username = user_data.get("username")
        email = user_data.get("email")
        avatar_hash = user_data.get("avatar")

        # Build avatar URL if they have one
        avatar_url = None
        if avatar_hash:
            avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.png"

    # Step 3 — Save this user to our records
    save_discord_user(
        discord_id=discord_id,
        discord_username=discord_username,
        access_token=access_token,
        email=email
    )

    return {
        "message": "Discord login successful",
        "user": {
            "discord_id": discord_id,
            "discord_username": discord_username,
            "email": email,
            "avatar": avatar_url
        }
    }


# =====================================================================
# Route — View Discord Connected Users
# =====================================================================
# GET /discord-users
# Shows all users who logged in with Discord.
# The bot will use this list for daily standup messages.
# Access tokens are hidden from the response for security.
# =====================================================================
@app.get("/discord-users")
async def get_discord_users():
    from fastapi.responses import Response

    filepath = "discord_users.json"

    if not os.path.exists(filepath):
        return {"total": 0, "users": []}

    with open(filepath, "r") as f:
        users = json.load(f)

    # Never expose access tokens in API responses
    safe_users = []
    for discord_id, data in users.items():
        safe_users.append({
            "discord_id": data.get("discord_id"),
            "discord_username": data.get("discord_username"),
            "email": data.get("email"),
            "connected_at": data.get("connected_at")
        })

    result = {
        "total": len(safe_users),
        "discord_users": safe_users
    }

    formatted = json.dumps(result, indent=4)
    return Response(content=formatted, media_type="application/json")

# =====================================================================
# Route — Discord Activity Summary
# =====================================================================
# GET /discord/activity
#
# Shows what each team member is currently working on
# based on their Discord messages.
#
# This is displayed on Orchestra dashboard as:
# "Member X is doing: GUI and Visualizer work"
# "Member Y is doing: utility integration"
# =====================================================================
@app.get("/discord/activity")
async def get_discord_activity():
    from fastapi.responses import Response

    filepath = "discord_activity.json"

    if not os.path.exists(filepath):
        return {"total_members": 0, "activity": []}

    with open(filepath, "r") as f:
        activity = json.load(f)

    summary = []
    for actor, data in activity.items():
        summary.append({
            "member": actor,
            "currently_working_on": data.get("latest_message", "No recent updates"),
            "last_seen": data.get("last_seen", "unknown"),
            "total_messages": data.get("message_count", 0)
        })

    result = {
        "total_members_active": len(summary),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "team_activity": summary
    }

    formatted = json.dumps(result, indent=4)
    return Response(content=formatted, media_type="application/json")
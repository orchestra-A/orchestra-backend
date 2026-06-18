from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json
import sys
import os
from fastapi import FastAPI, Request
from fastapi.websockets import WebSocket, WebSocketDisconnect
from typing import List, Optional
import asyncio
import re
import requests
import discord
from discord.ext import tasks
import hmac
import hashlib
import requests

# Import Member 4's normalizer and models
from normalizer import normalize_event
from state_machine import process_normalized_event
from models import NormalizedEvent

# =====================================================================
# FastAPI Application Metadata
# =====================================================================
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Timeline Orchestra Backend",
    description="Infrastructure layer for Timeline Orchestra",
    version="0.7.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

    # Create tables in the database if they don't exist
    from database import engine, Base
    import models_sql  # registers ConnectedUserTable, DiscordUserTable, UserProfileTable, etc.
    Base.metadata.create_all(bind=engine)
    print("[STARTUP] Database tables verified/created.")
    sys.stdout.flush()

    # Seed TaskTable from tasks.json if TaskTable is empty
    from database import SessionLocal
    from models_sql import TaskTable
    db = SessionLocal()
    try:
        if db.query(TaskTable).count() == 0:
            print("[STARTUP] TaskTable is empty. Seeding from tasks.json...")
            sys.stdout.flush()
            # If tasks.json doesn't exist, initialize it first
            initialize_tasks_file()
            with open("tasks.json", "r") as f:
                tdata = json.load(f)
            for t in tdata.get("tasks", []):
                new_db_task = TaskTable(
                    id=t["id"],
                    title=t.get("title", "Untitled"),
                    state=t.get("status", "pending").upper(),
                    assigned_to=t.get("assigned_to"),
                    project_id=t.get("project_id"),
                    order=t.get("order"),
                    created_at=t.get("created_at"),
                    depends_on=t.get("depends_on", []),
                    history=t.get("history", [])
                )
                db.add(new_db_task)
            db.commit()
            print("[STARTUP] TaskTable seeded successfully.")
        else:
            print("[STARTUP] TaskTable already contains data, skipping seeding.")
    except Exception as e:
        print(f"[STARTUP] Error seeding TaskTable: {e}")
        db.rollback()
    finally:
        db.close()
        sys.stdout.flush()

    asyncio.create_task(start_discord_bot())
    print("[STARTUP] Discord bot task created")
    sys.stdout.flush()

    from scheduler import start_scheduler

    start_scheduler()
    print("[STARTUP] WebSocket Cron Scheduler started")
    sys.stdout.flush()


@app.on_event("shutdown")
async def shutdown_event():
    from scheduler import stop_scheduler

    stop_scheduler()
    print("[SHUTDOWN] WebSocket Cron Scheduler stopped")
    sys.stdout.flush()


# =====================================================================
# Environment Variables
# GitHub & Discord OAuth credentials — stored in .env file
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
        print(
            f"[WEBSOCKET] ✅ New browser connected. Total connected: {len(self.active_connections)}"
        )
        sys.stdout.flush()

    def disconnect(self, websocket: WebSocket):
        # Browser closed the tab — remove from list
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(
            f"[WEBSOCKET] ❌ Browser disconnected. Total connected: {len(self.active_connections)}"
        )
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

        print(
            f"[WEBSOCKET] 📡 Broadcast sent to {len(self.active_connections)} browser(s)"
        )
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

    Why unique per user
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
        GITHUB_WEBHOOK_SECRET_KEY.encode(), combined.encode(), hashlib.sha256
    ).hexdigest()[:32]


async def register_github_webhook(
    access_token: str, github_username: str, repo_full_name: str
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
            "push",  # Someone pushed code
            "pull_request",  # PR opened, closed, merged
            "issues",  # Issue created, closed, commented
        ],
        "config": {
            "url": webhook_url,
            "content_type": "json",
            "secret": webhook_secret,
            "insecure_ssl": "0",
        },
    }

    # Call GitHub API to create the webhook
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.github.com/repos/{repo_full_name}/hooks",
            json=webhook_config,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    if response.status_code == 201:
        print(f"[GITHUB] ✅ Webhook registered for {repo_full_name}")
        sys.stdout.flush()
        return {
            "success": True,
            "repo": repo_full_name,
            "webhook_id": response.json().get("id"),
            "events": ["push", "pull_request", "issues"],
        }
    elif response.status_code == 422:
        # 422 means webhook already exists on this repo
        print(f"[GITHUB] ℹ️ Webhook already exists for {repo_full_name}")
        sys.stdout.flush()
        return {
            "success": True,
            "repo": repo_full_name,
            "note": "Webhook already registered",
        }
    else:
        print(f"[GITHUB] ❌ Failed to register webhook: {response.status_code}")
        print(f"[GITHUB] Response: {response.text}")
        sys.stdout.flush()
        return {
            "success": False,
            "repo": repo_full_name,
            "error": response.text,
            "status_code": response.status_code,
        }


def save_connected_user(
    github_username: str, access_token: str, repo_full_name: str, webhook_result: dict
) -> None:
    """
    Saves the connected user's information to the database.
    """
    save_unified_user_profile(
        github_username=github_username,
        github_access_token=access_token,
        github_repo=repo_full_name
    )


def save_discord_user(
    discord_id: str, discord_username: str, access_token: str, email: Optional[str] = None
) -> None:
    """
    Saves a Discord connected user to the database.
    """
    save_unified_user_profile(
        discord_id=discord_id,
        discord_username=discord_username,
        discord_access_token=access_token,
        email=email
    )


def save_unified_user_profile(
    github_username: Optional[str] = None,
    github_access_token: Optional[str] = None,
    discord_id: Optional[str] = None,
    discord_username: Optional[str] = None,
    discord_access_token: Optional[str] = None,
    email: Optional[str] = None,
    github_repo: Optional[str] = None,
) -> dict:
    """
    Creates or updates a unified user profile in the database using the dynamic PlatformIntegration table.
    """
    from database import SessionLocal
    from models_sql import UserTable, PlatformIntegrationTable
    import uuid

    db = SessionLocal()
    try:
        # 1. Find or create UserTable
        user = None
        if email:
            user = db.query(UserTable).filter_by(email=email).first()
        if not user and github_username:
            user = db.query(UserTable).filter_by(username=github_username).first()
        if not user and discord_username:
            user = db.query(UserTable).filter_by(username=discord_username).first()

        if not user:
            user_id = f"usr_{str(uuid.uuid4())[:8]}"
            primary_username = github_username or discord_username or email.split("@")[0]
            user = UserTable(
                id=user_id,
                username=primary_username,
                email=email,
                created_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat()
            )
            db.add(user)
            db.flush() # get user.id so we can use it for foreign keys

        # 2. Upsert GitHub PlatformIntegration
        if github_username:
            pi_gh = db.query(PlatformIntegrationTable).filter_by(platform_name="github", user_id=user.id).first()
            if not pi_gh:
                pi_gh = PlatformIntegrationTable(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    platform_name="github",
                    connected_at=datetime.now(timezone.utc).isoformat()
                )
                db.add(pi_gh)
            pi_gh.access_token = github_access_token
            pi_gh.platform_metadata = {"username": github_username, "repo": github_repo}

        # 3. Upsert Discord PlatformIntegration
        if discord_id:
            pi_dc = db.query(PlatformIntegrationTable).filter_by(platform_name="discord", user_id=user.id).first()
            if not pi_dc:
                pi_dc = PlatformIntegrationTable(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    platform_name="discord",
                    connected_at=datetime.now(timezone.utc).isoformat()
                )
                db.add(pi_dc)
            pi_dc.access_token = discord_access_token
            pi_dc.platform_metadata = {"discord_id": discord_id, "username": discord_username}

        db.commit()
        return {
            "user_id": user.id,
            "username": user.username,
            "email": user.email
        }
    except Exception as e:
        print(f"[USER PROFILE] ❌ Failed to save user profile: {e}")
        db.rollback()
        raise e
    finally:
        db.close()
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
        "message_count": activity.get(actor, {}).get("message_count", 0) + 1,
    }

    with open(filepath, "w") as f:
        json.dump(activity, f, indent=2)

    print(f"[ACTIVITY] Updated activity for {actor}: {content[:40]}")
    sys.stdout.flush()


GRAPH_API_URL = os.getenv("GRAPH_API_URL", "https://orchestra-ai-36zm.onrender.com")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


def sync_task_status_to_neo4j(task_id: str, status: str) -> bool:
    """
    Pushes a task status update to the Neo4j-backed AI service.

    WHY THIS EXISTS:
    Postgres is the source of truth for task data. Neo4j is a
    separate database that Clover (the AI chatbot) reads from to
    answer questions about project status. Without this function,
    Neo4j never finds out when a task changes — so Clover gives
    stale answers.

    WHY IT'S SYNCHRONOUS (uses requests, not httpx):
    The 'requests' library blocks the entire thread while waiting
    for a response. Since state_machine.py calls this from inside
    a synchronous function (save_tasks), we keep this function
    synchronous too. The async wrapping happens at the call site
    using asyncio.to_thread(), which runs this blocking function
    in a separate thread so it doesn't freeze the main server.

    Returns True if Neo4j was updated successfully, False otherwise.
    Never raises — a sync failure should never crash the State Machine.
    """
    if not GRAPH_API_URL or not INTERNAL_API_KEY:
        print("[GRAPH SYNC] ⚠️ Missing GRAPH_API_URL or INTERNAL_API_KEY — skipping sync")
        sys.stdout.flush()
        return False

    url = f"{GRAPH_API_URL}/tasks/{task_id}/status"

    try:
        response = requests.patch(
            url,
            json={"status": status},
            headers={"x-api-key": INTERNAL_API_KEY},
            timeout=10
        )

        if response.status_code == 200:
            print(f"[GRAPH SYNC] ✅ Neo4j updated: {task_id} → {status}")
            sys.stdout.flush()
            return True
        else:
            print(f"[GRAPH SYNC] ❌ Neo4j sync failed for {task_id}: "
                  f"HTTP {response.status_code} — {response.text}")
            sys.stdout.flush()
            return False

    except requests.exceptions.RequestException as e:
        print(f"[GRAPH SYNC] ❌ Network error syncing {task_id} to Neo4j: {e}")
        sys.stdout.flush()
        return False


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
                    "assigned_to": "Member 2",
                    "platform": "github",
                    "priority": "high",
                    "created_at": "2025-05-28T09:00:00Z",
                    "updated_at": "2025-05-30T14:30:00Z",
                },
                {
                    "id": "task_002",
                    "order": 2,
                    "project_id": "proj_orchestra",
                    "title": "Build semantic data normalizer",
                    "description": "Scrub incoming platform events into clean uniform data blocks.",
                    "status": "in_progress",
                    "assigned_to": "Member 4",
                    "platform": "github",
                    "priority": "high",
                    "created_at": "2025-05-28T09:00:00Z",
                    "updated_at": "2025-06-01T10:00:00Z",
                },
                {
                    "id": "task_003",
                    "order": 3,
                    "project_id": "proj_orchestra",
                    "title": "Connect reactflow canvas to backend",
                    "description": "Replace static mock files with live database endpoints.",
                    "status": "in_progress",
                    "assigned_to": "Member 5",
                    "platform": "figma",
                    "priority": "medium",
                    "created_at": "2025-05-29T11:00:00Z",
                    "updated_at": "2025-05-31T16:00:00Z",
                },
                {
                    "id": "task_004",
                    "order": 4,
                    "project_id": "proj_orchestra",
                    "title": "Implement Connect Workspaces UI",
                    "description": "Build authentication screens for team tool integrations.",
                    "status": "in_progress",
                    "assigned_to": "Member 6",
                    "platform": "figma",
                    "priority": "medium",
                    "created_at": "2025-05-29T11:00:00Z",
                    "updated_at": "2025-06-01T09:00:00Z",
                },
                {
                    "id": "task_005",
                    "order": 5,
                    "project_id": "proj_orchestra",
                    "title": "Configure Discord webhook listener",
                    "description": "Expand FastAPI server to natively catch Discord events.",
                    "status": "completed",
                    "assigned_to": "Member 3",
                    "platform": "discord",
                    "priority": "high",
                    "created_at": "2025-06-01T08:00:00Z",
                    "updated_at": "2025-06-01T12:00:00Z",
                },
                {
                    "id": "task_006",
                    "order": 6,
                    "project_id": "proj_orchestra",
                    "title": "Configure Figma webhook listener",
                    "description": "Expand FastAPI server to natively catch Figma design events.",
                    "status": "completed",
                    "assigned_to": "Member 3",
                    "platform": "figma",
                    "priority": "high",
                    "created_at": "2025-06-01T08:00:00Z",
                    "updated_at": "2025-06-01T12:00:00Z",
                },
                {
                    "id": "task_007",
                    "order": 7,
                    "project_id": "proj_orchestra",
                    "title": "LLM JSON extraction prompting",
                    "description": "Force LLM to respond only in structured valid JSON.",
                    "status": "completed",
                    "assigned_to": "Member 1",
                    "platform": "github",
                    "priority": "high",
                    "created_at": "2025-05-28T09:00:00Z",
                    "updated_at": "2025-05-30T11:00:00Z",
                },
                {
                    "id": "task_008",
                    "order": 8,
                    "project_id": "proj_orchestra",
                    "title": "GitHub State Machine setup",
                    "description": "Auto-update task status when matching pull requests are submitted.",
                    "status": "todo",
                    "assigned_to": "Member 3",
                    "platform": "github",
                    "priority": "high",
                    "created_at": "2025-06-01T08:00:00Z",
                    "updated_at": "2025-06-01T08:00:00Z",
                },
                {
                    "id": "task_009",
                    "order": 1,
                    "project_id": "proj_marketing",
                    "title": "Design new landing page",
                    "description": "Create wireframes and mockups for the marketing site.",
                    "status": "completed",
                    "assigned_to": "Member 6",
                    "platform": "figma",
                    "priority": "high",
                    "created_at": "2025-06-02T11:00:00Z",
                },
                {
                    "id": "task_010",
                    "order": 2,
                    "project_id": "proj_marketing",
                    "title": "Write copy for landing page",
                    "description": "Draft marketing copy and value propositions.",
                    "status": "todo",
                    "assigned_to": "Member 1",
                    "platform": "discord",
                    "priority": "medium",
                    "created_at": "2025-06-02T08:00:00Z",
                },
                {
                    "id": "task_011",
                    "order": 1,
                    "project_id": "proj_mobile_app",
                    "title": "Setup React Native CLI",
                    "description": "Initialize the bare React Native project.",
                    "status": "todo",
                    "assigned_to": "Member 5",
                    "platform": "github",
                    "priority": "high",
                    "created_at": "2025-06-03T09:00:00Z",
                },
                {
                    "id": "task_012",
                    "order": 1,
                    "project_id": "proj_analytics",
                    "title": "Define tracking plan",
                    "description": "Map out all funnel events for mixpanel.",
                    "status": "in_progress",
                    "assigned_to": "Member 4",
                    "platform": "figma",
                    "priority": "medium",
                    "created_at": "2025-06-04T10:00:00Z",
                },
            ],
        }

        # --- NEW DEPENDENCY LOGIC ---
        from collections import defaultdict

        project_order_tasks = defaultdict(lambda: defaultdict(list))

        for task in tasks_data["tasks"]:
            pid = task.get("project_id")
            order = task.get("order")
            if pid and order:
                project_order_tasks[pid][order].append(task["id"])

        for task in tasks_data["tasks"]:
            pid = task.get("project_id")
            order = task.get("order")
            task["depends_on"] = []  # type: ignore
            if pid and order and int(order) > 1:
                task["depends_on"] = project_order_tasks[pid][int(order) - 1]  # type: ignore
        # ----------------------------

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
intents.message_content = True  # Can read message text
intents.members = True  # Can see server members
intents.guilds = True  # Can see servers it's in
intents.messages = True  # Can receive message events

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

    # Start the standup scheduler loop if not already running
    if not standup_scheduler.is_running():
        standup_scheduler.start()
        print("[DISCORD BOT] ⏰ Daily Standup Scheduler started (9:00 AM)")
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

    print(
        f"[DISCORD BOT] 📨 Message from {message.author.name}: {message.content[:50]}"
    )
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
        "timestamp": message.created_at.isoformat(),
    }

    # Update member activity tracker
    # This builds "Member X is working on: ..."
    update_member_activity(
        actor=message.author.name,
        content=message.content,
        timestamp=message.created_at.isoformat(),
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
# DAILY STANDUP BOT
# =====================================================================
# State of the last standup run date (to avoid running multiple times in 9:00 AM minute)
last_standup_run_date = ""


class StandupButtonsView(discord.ui.View):
    def __init__(self, task_ids: list, member_name: str):
        super().__init__(timeout=None)  # Persistent view
        self.task_ids = task_ids
        self.member_name = member_name

    @discord.ui.button(
        label="Confirm ⬜",
        style=discord.ButtonStyle.secondary,
        custom_id="standup_confirm",
    )
    async def confirm_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        button.label = "Confirm ✅"
        button.style = discord.ButtonStyle.success
        button.disabled = True

        for child in self.children:
            if child.custom_id != "standup_confirm":
                child.disabled = True
                if child.custom_id == "standup_edit":
                    child.label = "Edit ➡️⬜"
                elif child.custom_id == "standup_skip":
                    child.label = "Skip ⬜⬜"

        await interaction.response.edit_message(view=self)
        await confirm_standup_tasks(self.task_ids, self.member_name)
        await interaction.followup.send(
            "Daily standup confirmed! Tasks updated and broadcasted.", ephemeral=True
        )

    @discord.ui.button(
        label="Edit ➡️⬜", style=discord.ButtonStyle.secondary, custom_id="standup_edit"
    )
    async def edit_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        button.label = "Edit ➡️ Selected"
        button.disabled = True
        for child in self.children:
            if child.custom_id != "standup_edit":
                child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            "Standup edit selected. Please update your tasks on the Orchestra dashboard.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Skip ⬜⬜", style=discord.ButtonStyle.secondary, custom_id="standup_skip"
    )
    async def skip_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        button.label = "Skipped ❌"
        button.style = discord.ButtonStyle.danger
        button.disabled = True
        for child in self.children:
            if child.custom_id != "standup_skip":
                child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("Daily standup skipped.", ephemeral=True)


def users_match(actor1: str, actor2: str) -> bool:
    if not actor1 or not actor2:
        return False
    a1 = actor1.lower().strip()
    a2 = actor2.lower().strip()
    if " — " in a1:
        a1 = a1.split(" — ")[0].strip()
    if " — " in a2:
        a2 = a2.split(" — ")[0].strip()
    return a1 == a2 or a1 in a2 or a2 in a1


def get_user_standup_data(member_username: str):
    completed_yesterday = []
    in_progress = []
    task_ids = []

    from database import SessionLocal
    from models_sql import EventTable, TaskTable

    db = SessionLocal()
    recent_task_ids = set()
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    try:
        events = db.query(EventTable).all()
        for event in events:
            event_time_str = event.timestamp
            if event_time_str:
                try:
                    event_time = datetime.fromisoformat(
                        event_time_str.replace("Z", "+00:00")
                    )
                    if event_time >= yesterday:
                        if users_match(event.actor, member_username):
                            summary = event.action_summary or ""
                            refs = extract_task_references(summary)
                            for ref in refs:
                                recent_task_ids.add(f"task_{ref.zfill(3)}")

                            raw_meta = event.raw_metadata or {}
                            if isinstance(raw_meta, str):
                                try:
                                    raw_meta = json.loads(raw_meta)
                                except Exception:
                                    raw_meta = {}
                            commits = raw_meta.get("commits", [])
                            for commit in commits:
                                commit_msg = commit.get("message", "")
                                refs = extract_task_references(commit_msg)
                                for ref in refs:
                                    recent_task_ids.add(f"task_{ref.zfill(3)}")
                except Exception:
                    pass
    except Exception as e:
        print(f"[STANDUP BOT] Error reading EventTable: {e}")
        sys.stdout.flush()

    try:
        db_tasks = db.query(TaskTable).all()
        for task in db_tasks:
            task_id = task.id
            assigned = task.assigned_to

            is_assigned = users_match(assigned, member_username)
            is_recent_activity = task_id in recent_task_ids

            if is_assigned or is_recent_activity:
                status = (task.state or "").lower()

                task_dict = {
                    "id": task.id,
                    "title": task.title,
                    "status": status,
                    "assigned_to": task.assigned_to,
                    "project_id": task.project_id,
                    "order": task.order,
                    "depends_on": task.depends_on,
                    "created_at": task.created_at,
                    "history": task.history,
                }

                if status == "completed":
                    history = task.history or []
                    updated_at_str = None
                    if history:
                        status_changes = [h for h in history if h.get("type") == "STATUS_CHANGE" and h.get("to") == "completed"]
                        if status_changes:
                            updated_at_str = status_changes[-1].get("timestamp")
                    if not updated_at_str:
                        updated_at_str = task.created_at

                    is_completed_yesterday = False
                    if updated_at_str:
                        try:
                            updated_at = datetime.fromisoformat(
                                updated_at_str.replace("Z", "+00:00")
                            )
                            if updated_at >= yesterday:
                                is_completed_yesterday = True
                        except Exception:
                            pass
                    if is_completed_yesterday or is_recent_activity:
                        completed_yesterday.append(task_dict)
                        task_ids.append(task_id)
                elif status == "in_progress":
                    in_progress.append(task_dict)
                    task_ids.append(task_id)
    except Exception as e:
        print(f"[STANDUP BOT] Error reading TaskTable: {e}")
        sys.stdout.flush()
    finally:
        db.close()

    return completed_yesterday, in_progress, task_ids


async def confirm_standup_tasks(task_ids: list, member_name: str):
    from database import SessionLocal
    from models_sql import TaskTable
    from sqlalchemy.orm.attributes import flag_modified

    db = SessionLocal()
    updated_tasks = []
    try:
        for t_id in task_ids:
            task = db.query(TaskTable).filter(TaskTable.id == t_id).first()
            if task:
                if not task.history:
                    task.history = []
                task.history.append({
                    "type": "STANDUP_CONFIRMED",
                    "actor": member_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": "Standup task confirmation"
                })
                flag_modified(task, "history")
                updated_tasks.append(t_id)
        if updated_tasks:
            db.commit()
            print(f"[STANDUP BOT] ✅ Confirmed tasks in DB for {member_name}: {updated_tasks}")
            sys.stdout.flush()
    except Exception as e:
        print(f"[STANDUP BOT] Error confirming tasks in DB: {e}")
        db.rollback()
    finally:
        db.close()

    filepath = "tasks.json"
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            json_updated = False
            for task in data.get("tasks", []):
                if task["id"] in task_ids:
                    task["confirmed"] = True
                    task["updated_at"] = datetime.now(timezone.utc).isoformat()
                    json_updated = True
            if json_updated:
                with open(filepath, "w") as f:
                    json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[STANDUP BOT] Error writing to tasks.json in confirm_standup_tasks: {e}")
            sys.stdout.flush()

    if updated_tasks:
        try:
            await manager.broadcast(
                {
                    "type": "tasks_confirmed",
                    "task_ids": updated_tasks,
                    "confirmed_by": member_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            print(f"[WEBSOCKET] 📡 Broadcast standup confirmation for {updated_tasks}")
            sys.stdout.flush()
        except Exception as e:
            print(f"[WEBSOCKET] ⚠️ Standup confirmation broadcast failed: {e}")
            sys.stdout.flush()


async def run_daily_standup():
    print("[STANDUP BOT] Running daily standup summary check...")
    sys.stdout.flush()

    from database import SessionLocal
    from models_sql import DiscordUserTable

    db = SessionLocal()
    try:
        db_users = db.query(DiscordUserTable).all()
        users_list = [
            {
                "discord_id": u.discord_id,
                "discord_username": u.discord_username,
                "access_token": u.access_token,
                "email": u.email,
                "connected_at": u.connected_at
            }
            for u in db_users
        ]
    finally:
        db.close()

    if not users_list:
        print("[STANDUP BOT] No discord users found. Skipping.")
        sys.stdout.flush()
        return

    for user_data in users_list:
        discord_id = user_data.get("discord_id")
        discord_username = user_data.get("discord_username")
        print(f"[STANDUP BOT] Processing user {discord_username} ({discord_id})...")
        sys.stdout.flush()

        completed, in_progress, task_ids = get_user_standup_data(discord_username)

        # Build message
        msg = f"Hey {discord_username}! Here is your daily update:\n\n"

        msg += "Completed yesterday:\n"
        if completed:
            for task in completed:
                msg += f" - {task['id']}: {task['title']}\n"
        else:
            msg += " - None\n"

        msg += "\nIn Progress:\n"
        if in_progress:
            for task in in_progress:
                msg += f" - {task['id']}: {task['title']}\n"
        else:
            msg += " - None\n"

        try:
            user = await bot.fetch_user(int(discord_id))
            if user:
                view = StandupButtonsView(task_ids, discord_username)
                await user.send(msg, view=view)
                print(f"[STANDUP BOT] ✅ Sent standup DM to {discord_username}")
                sys.stdout.flush()
            else:
                print(f"[STANDUP BOT] ❌ Could not fetch discord user {discord_id}")
                sys.stdout.flush()
        except Exception as e:
            print(f"[STANDUP BOT] ❌ Error sending DM to {discord_username}: {e}")
            sys.stdout.flush()


@tasks.loop(seconds=60)
async def standup_scheduler():
    now = datetime.now()
    if now.hour == 9 and now.minute == 0:
        global last_standup_run_date
        today_str = now.date().isoformat()
        if last_standup_run_date != today_str:
            last_standup_run_date = today_str
            await run_daily_standup()


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
    from database import SessionLocal
    from models_sql import EventTable

    db = SessionLocal()
    try:
        new_event = EventTable(
            id=event.id,
            platform=event.platform,
            event_type=event.event_type,
            actor=event.actor,
            timestamp=event.timestamp,
            repo=event.repo,
            channel=event.channel,
            action_summary=event.action_summary,
            raw_metadata=event.raw_metadata,
        )
        db.add(new_event)
        db.commit()
        print(f"[SAVED] Normalized event saved to database")
    except Exception as e:
        print(f"[SAVED] Error saving event to database: {e}")
        db.rollback()
    finally:
        db.close()
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
        r"(?::fixes|closes|resolves)\s+task[_\s#]+(\d+)",
        r"(?::fixes|closes|resolves)\s+#(\d+)",
        r"task[_\s#]+(\d+)",
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
    from database import SessionLocal
    from models_sql import TaskTable
    from sqlalchemy.orm.attributes import flag_modified

    # Build the full task ID from the number
    # "8" becomes "task_008"
    full_task_id = f"task_{task_ref.zfill(3)}"

    db = SessionLocal()
    try:
        task = db.query(TaskTable).filter(TaskTable.id == full_task_id).first()
        if not task:
            print(f"[STATE MACHINE] ❌ Task {full_task_id} not found in database")
            sys.stdout.flush()
            return False

        old_status = task.state
        task.state = new_status

        if not task.history:
            task.history = []

        task.history.append(
            {
                "type": "STATUS_CHANGE",
                "from": old_status,
                "to": new_status,
                "actor": "manual_update",
                "message": f"Status manually updated to {new_status}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        flag_modified(task, "history")

        db.commit()

        print(f"[STATE MACHINE] ✅ {full_task_id}: {old_status} → {new_status}")
        sys.stdout.flush()

        # Sync to Neo4j Graph DB
        sync_task_status_to_neo4j(full_task_id, new_status)

        # ── WEBSOCKET BROADCAST ────────────────────────────────
        # The moment a task status changes, tell every connected
        # browser about it immediately.
        # Member 5's frontend listens for this and changes the
        # task node color on screen without any page refresh.
        # ──────────────────────────────────────────────────────
        try:
            asyncio.create_task(
                manager.broadcast(
                    {
                        "type": "task_updated",
                        "task_id": full_task_id,
                        "old_status": old_status,
                        "new_status": new_status,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )
            print(f"[WEBSOCKET] 📡 Broadcast triggered for {full_task_id}")
            sys.stdout.flush()
        except Exception as e:
            print(f"[WEBSOCKET] ⚠️ Broadcast failed: {e}")
            sys.stdout.flush()

        return True
    except Exception as e:
        print(f"[STATE MACHINE] Error updating task {full_task_id}: {e}")
        db.rollback()
        return False
    finally:
        db.close()


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
    return {"received": True, "timestamp": datetime.now(timezone.utc).isoformat()}


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
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
    user_secret = None
    from database import SessionLocal
    from models_sql import PlatformIntegrationTable

    db = SessionLocal()
    try:
        integrations = db.query(PlatformIntegrationTable).filter_by(platform_name="github").all()
        for pi in integrations:
            meta = pi.platform_metadata or {}
            if meta.get("username") == sender:
                user_secret = generate_user_webhook_secret(sender)
                break
    finally:
        db.close()

    # Enforce signature verification if GITHUB_WEBHOOK_SECRET_KEY is configured
    if GITHUB_WEBHOOK_SECRET_KEY and GITHUB_WEBHOOK_SECRET_KEY != "default_secret":
        if not user_secret:
            from fastapi.responses import JSONResponse
            print(f"[GITHUB] ❌ Unauthorized sender: {sender} is not registered")
            sys.stdout.flush()
            return JSONResponse(status_code=401, content={"error": "Unauthorized sender"})

        if not github_signature:
            from fastapi.responses import JSONResponse
            print(f"[GITHUB] ❌ Missing signature header for {sender}")
            sys.stdout.flush()
            return JSONResponse(status_code=401, content={"error": "Missing signature"})

        expected_signature = (
            "sha256="
            + hmac.new(user_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        )

        if not hmac.compare_digest(github_signature, expected_signature):
            print(f"[GITHUB] ❌ Signature verification FAILED for {sender}")
            sys.stdout.flush()
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=401, content={"error": "Invalid signature"})
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
    asyncio.create_task(
        manager.broadcast({"type": "new_event", **normalized.model_dump()})
    )

    # ── SMART STATE MACHINE ────────────────────────────────────
    updated_tasks = []

    # Pass the normalized dict straight to the engine (now async)
    state_change = await process_normalized_event(normalized.model_dump())

    if state_change:
        # A state transition successfully happened!
        updated_tasks.append(state_change["id"])

        # Get the old and new status from the history trail
        last_transition = state_change["history"][-1] if state_change["history"] else {}
        old_status = (
            last_transition.get("from", "PENDING").lower()
            if last_transition.get("from") != "PENDING"
            else "todo"
        )
        new_status = state_change["status"]

        # ── WEBSOCKET BROADCAST ────────────────────────────────
        try:
            asyncio.create_task(
                manager.broadcast(
                    {
                        "type": "task_updated",
                        "task_id": state_change["id"],
                        "old_status": old_status,
                        "new_status": new_status,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# =====================================================================
# Route 7 — Local Tasks Endpoint
# =====================================================================
# Returns tasks from local tasks.json.
# This ensures Member 3's UI sees the latest State Machine updates.
# =====================================================================
@app.get("/tasks")
async def get_tasks(project_id: Optional[str] = None):
    from fastapi import Response
    from database import SessionLocal
    from models_sql import TaskTable

    db = SessionLocal()
    try:
        if project_id:
            db_tasks = db.query(TaskTable).filter_by(project_id=project_id).all()
        else:
            db_tasks = db.query(TaskTable).all()
        tasks = []
        for t in db_tasks:
            tasks.append(
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.state.lower() if t.state else "todo",
                    "assigned_to": t.assigned_to,
                    "project_id": t.project_id,
                    "order": t.order,
                    "depends_on": t.depends_on,
                    "created_at": t.created_at,
                    "pr_number": t.pr_number,
                    "branch": t.branch,
                    "history": t.history,
                }
            )
        result = {"total": len(tasks), "tasks": tasks}
        formatted_json = json.dumps(result, indent=4)
        return Response(content=formatted_json, media_type="application/json")
    finally:
        db.close()


# TODO: Member 2 (Neo4j Team) - Hook this /graph endpoint up to the Neo4j database!
@app.get("/graph")
async def get_graph():
    try:
        response = requests.get(
            "https://orchestra-ai-36zm.onrender.com/graph", timeout=30
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"error": str(exc), "nodes": [], "edges": []}


# =====================================================================
# Route 7.2 — Task CRUD Endpoints (Week 3 Day 2)
# =====================================================================
@app.get("/tasks/{task_id}")
async def get_single_task(task_id: str):
    from database import SessionLocal
    from models_sql import TaskTable

    db = SessionLocal()
    try:
        t = db.query(TaskTable).filter(TaskTable.id == task_id).first()
        if t:
            return {
                "id": t.id,
                "title": t.title,
                "status": t.state.lower() if t.state else "todo",
                "assigned_to": t.assigned_to,
                "project_id": t.project_id,
                "order": t.order,
                "depends_on": t.depends_on,
                "created_at": t.created_at,
                "pr_number": t.pr_number,
                "branch": t.branch,
                "history": t.history,
            }
        return {"error": "Task not found"}
    finally:
        db.close()


@app.post("/tasks")
async def create_new_task(request: Request):
    body = await request.json()
    task_id = body.get("id")
    title = body.get("title", "Untitled")
    if not task_id:
        return {"error": "'id' field required"}

    from database import SessionLocal
    from models_sql import TaskTable

    created_at = datetime.now(timezone.utc).isoformat()

    # Save to SQL database
    db = SessionLocal()
    try:
        exists = db.query(TaskTable).filter(TaskTable.id == task_id).first()
        if not exists:
            new_db_task = TaskTable(
                id=task_id,
                title=title,
                state="TODO",
                created_at=created_at,
                depends_on=[],
                history=[]
            )
            db.add(new_db_task)
            db.commit()
    except Exception as e:
        print(f"[API] Error saving new task to database: {e}")
        db.rollback()
    finally:
        db.close()

    # Save to legacy tasks.json for compatibility
    filepath = "tasks.json"
    if not os.path.exists(filepath):
        initialize_tasks_file()
    try:
        with open(filepath, "r") as f:
            data = json.load(f)

        if not any(t["id"] == task_id for t in data.get("tasks", [])):
            new_task = {
                "id": task_id,
                "title": title,
                "status": "todo",
                "created_at": created_at,
            }
            data["tasks"].append(new_task)
            data["total"] = len(data["tasks"])

            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
        else:
            new_task = next(t for t in data["tasks"] if t["id"] == task_id)
    except Exception as e:
        print(f"[API] Error writing to tasks.json: {e}")
        new_task = {
            "id": task_id,
            "title": title,
            "status": "todo",
            "created_at": created_at,
        }

    # Broadcast new task creation
    try:
        asyncio.create_task(
            manager.broadcast(
                {
                    "type": "task_created",
                    "task": new_task,
                    "timestamp": created_at,
                }
            )
        )
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


@app.post("/tasks/{task_id}/history")
async def add_task_history_update(task_id: str, request: Request):
    body = await request.json()
    message = body.get("message")
    actor = body.get("actor", "unknown")

    if not message:
        return {"error": "'message' field required"}

    from database import SessionLocal
    from models_sql import TaskTable
    from sqlalchemy.orm.attributes import flag_modified

    db = SessionLocal()
    try:
        task = db.query(TaskTable).filter(TaskTable.id == task_id).first()
        if not task:
            return {"error": "Task not found"}

        if not task.history:
            task.history = []

        update_entry = {
            "type": "UPDATE",
            "message": message,
            "actor": actor,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        task.history.append(update_entry)
        flag_modified(task, "history")

        db.commit()

        try:
            asyncio.create_task(
                manager.broadcast(
                    {
                        "type": "task_history_updated",
                        "task_id": task_id,
                        "update": update_entry,
                    }
                )
            )
        except Exception:
            pass

        return {"status": "success", "history_entry": update_entry}
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


# =====================================================================
# Route 8 — View Saved Normalized Events
# =====================================================================
@app.get("/events")
async def get_events():
    from fastapi.responses import Response
    from database import SessionLocal
    from models_sql import EventTable

    db = SessionLocal()
    try:
        db_events = db.query(EventTable).all()
        events = []
        for e in db_events:
            events.append(
                {
                    "id": e.id,
                    "platform": e.platform,
                    "event_type": e.event_type,
                    "actor": e.actor,
                    "timestamp": e.timestamp,
                    "repo": e.repo,
                    "channel": e.channel,
                    "action_summary": e.action_summary,
                    "raw_metadata": e.raw_metadata,
                }
            )
        result = {"total": len(events), "events": events}
        formatted = json.dumps(result, indent=4)
        return Response(content=formatted, media_type="application/json")
    finally:
        db.close()


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
    await websocket.send_json(
        {
            "type": "connection_established",
            "message": "Connected to Timeline Orchestra live updates",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    try:
        # Keep the connection alive forever
        # Wait for any message from the browser
        # Browser can send "ping" to check if connection is still alive
        while True:
            data = await websocket.receive_text()

            if data == "ping":
                # Browser is checking if we're still here — respond
                await websocket.send_json(
                    {
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
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
async def github_login(repo: Optional[str] = None):
    from fastapi.responses import RedirectResponse
    import urllib.parse

    # We pass the repo name through GitHub's "state" parameter
    # GitHub preserves "state" through the OAuth flow and sends it back
    # This is the standard way to pass data through OAuth redirects
    state = urllib.parse.quote(repo) if repo else ""

    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"client_id={GITHUB_CLIENT_ID}"
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
# /auth/github/callbackcode=XXX&repo=username/reponame
# =====================================================================
@app.get("/auth/github/callback")
async def github_callback(code: str, state: Optional[str] = None):
    import httpx

    async with httpx.AsyncClient() as client:
        # Step 1 — Exchange code for access token
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        token_data = token_response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            return {"error": "Failed to get access token", "details": token_data}

        # Step 2 — Get user's GitHub profile
        user_response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
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
            repo_full_name=repo,
        )
        save_connected_user(
            github_username=github_username,
            access_token=access_token,
            repo_full_name=repo,
            webhook_result=webhook_result,
        )
        save_unified_user_profile(
            github_username=github_username, github_access_token=access_token
        )

    return {
        "message": "GitHub connected successfully",
        "user": {
            "github_username": github_username,
            "name": user_data.get("name"),
            "avatar": user_data.get("avatar_url"),
            "github_url": user_data.get("html_url"),
        },
        "webhook_registration": webhook_result,
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
    from database import SessionLocal
    from models_sql import PlatformIntegrationTable

    db = SessionLocal()
    try:
        db_users = db.query(PlatformIntegrationTable).filter_by(platform_name="github").all()
        safe_users = []
        for u in db_users:
            meta = u.platform_metadata or {}
            safe_users.append(
                {
                    "github_username": meta.get("username"),
                    "repo": meta.get("repo"),
                    "connected_at": u.connected_at,
                    "webhook_registered": True, # Hardcoded assuming registered if present
                    "webhook_id": meta.get("webhook_id"),
                }
            )
        result = {"total": len(safe_users), "connected_users": safe_users}
        formatted = json.dumps(result, indent=4)
        return Response(content=formatted, media_type="application/json")
    finally:
        db.close()


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
        f"client_id={DISCORD_CLIENT_ID}"
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
                "redirect_uri": "https://orchestra-backend-2v5a.onrender.com/auth/discord/callback",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token_data = token_response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            return {
                "error": "Failed to get access token from Discord",
                "details": token_data,
            }

        # Step 2 — Use token to get user's Discord profile
        user_response = await client.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_data = user_response.json()

        discord_id = user_data.get("id")
        discord_username = user_data.get("username")
        email = user_data.get("email")
        avatar_hash = user_data.get("avatar")

        # Build avatar URL if they have one
        avatar_url = None
        if avatar_hash:
            avatar_url = (
                f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.png"
            )

    # Step 3 — Save this user to our records
    save_discord_user(
        discord_id=discord_id,
        discord_username=discord_username,
        access_token=access_token,
        email=email,
    )
    save_unified_user_profile(
        discord_id=discord_id,
        discord_username=discord_username,
        discord_access_token=access_token,
        email=email,
    )

    return {
        "message": "Discord login successful",
        "user": {
            "discord_id": discord_id,
            "discord_username": discord_username,
            "email": email,
            "avatar": avatar_url,
        },
        "next_step": {
            "action": "Add Orchestra Bot to your Discord server",
            "bot_invite_url": f"https://discord.com/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&permissions=84992&scope=bot",
            "instructions": "Open the bot_invite_url and select your team's Discord server to add Orchestra Bot",
        },
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
    from database import SessionLocal
    from models_sql import PlatformIntegrationTable, UserTable

    db = SessionLocal()
    try:
        db_users = db.query(PlatformIntegrationTable, UserTable)\
                     .join(UserTable, PlatformIntegrationTable.user_id == UserTable.id)\
                     .filter(PlatformIntegrationTable.platform_name == "discord").all()
        
        safe_users = []
        for pi, user in db_users:
            meta = pi.platform_metadata or {}
            safe_users.append(
                {
                    "discord_id": meta.get("discord_id"),
                    "discord_username": meta.get("username"),
                    "email": user.email,
                    "connected_at": pi.connected_at,
                }
            )
        result = {"total": len(safe_users), "discord_users": safe_users}
        formatted = json.dumps(result, indent=4)
        return Response(content=formatted, media_type="application/json")
    finally:
        db.close()


# =====================================================================
# Route — View Unified User Profiles
# =====================================================================
# GET /users
# Shows all users with their connected platforms.
# This is the master identity record.
# Member 6 uses this to show which platforms each user has connected.
# =====================================================================
@app.get("/users")
async def get_users():
    from fastapi.responses import Response
    from database import SessionLocal
    from models_sql import UserTable, PlatformIntegrationTable

    db = SessionLocal()
    try:
        db_users = db.query(UserTable).all()
        safe_profiles = []
        for u in db_users:
            # Get integrations for this user
            integrations = db.query(PlatformIntegrationTable).filter_by(user_id=u.id).all()
            platforms_connected = [pi.platform_name for pi in integrations]
            
            # Find specific usernames for backwards compatibility
            gh = next((pi for pi in integrations if pi.platform_name == "github"), None)
            dc = next((pi for pi in integrations if pi.platform_name == "discord"), None)
            
            safe_profiles.append(
                {
                    "user_id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "github_username": gh.platform_metadata.get("username") if gh and gh.platform_metadata else None,
                    "discord_username": dc.platform_metadata.get("username") if dc and dc.platform_metadata else None,
                    "discord_id": dc.platform_metadata.get("discord_id") if dc and dc.platform_metadata else None,
                    "platforms_connected": platforms_connected,
                    "created_at": u.created_at,
                    "updated_at": u.updated_at,
                }
            )
        result = {"total": len(safe_profiles), "users": safe_profiles}
        formatted = json.dumps(result, indent=4)
        return Response(content=formatted, media_type="application/json")
    finally:
        db.close()


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
        summary.append(
            {
                "member": actor,
                "currently_working_on": data.get("latest_message", "No recent updates"),
                "last_seen": data.get("last_seen", "unknown"),
                "total_messages": data.get("message_count", 0),
            }
        )

    result = {
        "total_members_active": len(summary),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "team_activity": summary,
    }

    formatted = json.dumps(result, indent=4)
    return Response(content=formatted, media_type="application/json")


# =====================================================================
# Route 10 — Discord & GitHub Commit Intel (GET /commit-intel)
# =====================================================================
# Correlates Discord active members' latest messages with actual GitHub
# commit/PR activity, so the team can see what is being discussed in
# Discord vs what commits are actually happening in one place.
# =====================================================================
@app.get("/commit-intel")
async def get_commit_intel():
    from fastapi.responses import Response
    from database import SessionLocal
    from models_sql import EventTable
    import re

    filepath = "discord_activity.json"
    intel_list = []

    db = SessionLocal()
    try:
        # Fetch GitHub events to correlate activity
        db_events = db.query(EventTable).filter(EventTable.platform == "github").all()
        # Sort events by timestamp descending
        sorted_events = sorted(db_events, key=lambda x: x.timestamp or "", reverse=True)

        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                activity = json.load(f)
        else:
            activity = {}

        for actor, data in activity.items():
            discord_last_message = data.get("latest_message") or ""
            discord_last_seen = data.get("last_seen") or ""

            # Check if this actor appears in any github event
            matching_summaries = []
            github_actor_match = False

            for e in sorted_events:
                if e.actor == actor:
                    github_actor_match = True
                    if len(matching_summaries) < 3:
                        matching_summaries.append(e.action_summary)

            # Extract task mentions (task-\d+ or T\d{3})
            task_mentions = re.findall(r"(task-\d+|T\d{3})", discord_last_message, re.IGNORECASE)

            intel_list.append(
                {
                    "member": actor,
                    "discord_last_message": discord_last_message,
                    "discord_last_seen": discord_last_seen,
                    "github_actor_match": github_actor_match,
                    "recent_github_activity": matching_summaries,
                    "task_mentions_in_discord": task_mentions,
                }
            )

        result = {
            "total_members": len(intel_list),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "intel": intel_list,
        }

        formatted = json.dumps(result, indent=4)
        return Response(content=formatted, media_type="application/json")
    finally:
        db.close()


@app.get("/test/standup")
async def test_standup():
    print("[TEST] Manually triggering standup...")
    sys.stdout.flush()
    await run_daily_standup()
    return {
        "message": "Standup triggered manually",
        "check": "Your Discord DMs for the standup message",
    }


# =====================================================================
# Route — Trigger Daily Standup Manually
# =====================================================================
# GET /test-daily-standup
#
# Triggers the daily standup logic instantly for testing.
# Normally runs automatically at 9:00 AM.
# =====================================================================
@app.get("/test-daily-standup")
async def test_daily_standup():
    """
    Manually triggers the daily standup routine in the background.
    """
    asyncio.create_task(run_daily_standup())
    return {"status": "success", "message": "Daily standup triggered in background."}

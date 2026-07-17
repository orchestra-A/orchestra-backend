from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json
import sys
import os
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.websockets import WebSocket, WebSocketDisconnect
from typing import List, Optional, Dict, Any
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
    allow_origins=[
        "https://orchestra-frontend-roan.vercel.app",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    # Runs when FastAPI server starts. Starts the Discord bot as a background task.
    print("[STARTUP] Server starting...")
    sys.stdout.flush()

    # Create tables in the database if they don't exist
    from database import engine, Base
    import models_sql  # registers UserTable, PlatformIntegrationTable, etc.
    Base.metadata.create_all(bind=engine)
    print("[STARTUP] Database tables verified/created.")
    sys.stdout.flush()

    # (Legacy task.json seeding removed)

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
# Environment Variables — stored in .env file
# =====================================================================
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_WEBHOOK_SECRET_KEY = os.getenv("GITHUB_WEBHOOK_SECRET_KEY", "default_secret")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://orchestra-frontend-roan.vercel.app")

# =====================================================================
# WEBSOCKET CONNECTION MANAGER
# =====================================================================
# Broadcast system: all connected browsers receive task updates instantly.
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
# GITHUB WEBHOOK AUTO-REGISTRATION HELPERS
# =====================================================================


def generate_user_webhook_secret(github_username: str) -> str:
    # Generates a unique webhook secret per user using HMAC-SHA256.
    combined = f"{GITHUB_WEBHOOK_SECRET_KEY}:{github_username}"
    return hmac.new(
        GITHUB_WEBHOOK_SECRET_KEY.encode(), combined.encode(), hashlib.sha256
    ).hexdigest()[:32]


async def register_github_webhook(
    access_token: str, github_username: str, repo_full_name: str
) -> dict:
    # Auto-registers a webhook on the user's GitHub repo after OAuth login.
    import httpx

    # Generate a unique secret for this user
    webhook_secret = generate_user_webhook_secret(github_username)

    # This is the URL GitHub will send events to
    # Every user's events come to the same endpoint
    # We identify whose event it is from the payload
    webhook_url = f"{BACKEND_URL}/webhook/github"

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
    # Saves the connected user's information to the database.
    save_unified_user_profile(
        github_username=github_username,
        github_access_token=access_token,
        github_repo=repo_full_name
    )


def save_discord_user(
    discord_id: str, discord_username: str, access_token: str, email: Optional[str] = None
) -> None:
    # Saves a Discord connected user to the database.
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
    existing_user_id: Optional[str] = None,
    google_id: Optional[str] = None,
    google_name: Optional[str] = None,
    google_picture: Optional[str] = None,
    google_access_token: Optional[str] = None,
) -> dict:
    # Creates or updates a unified user profile in the database using the dynamic PlatformIntegration table.
    from database import SessionLocal
    from models_sql import UserTable, PlatformIntegrationTable
    from sqlalchemy.orm.attributes import flag_modified
    from sqlalchemy.exc import OperationalError
    import uuid
    import time

    retries = 3
    for attempt in range(retries):
        db = SessionLocal()
        try:
            # 1. Find or create UserTable
            user = None
            if existing_user_id:
                user = db.query(UserTable).filter_by(id=existing_user_id).first()
            if not user and email:
                user = db.query(UserTable).filter_by(email=email).first()
            if not user and github_username:
                user = db.query(UserTable).filter_by(username=github_username).first()
            if not user and discord_username:
                user = db.query(UserTable).filter_by(username=discord_username).first()
    
            if not user:
                user_id = f"usr_{str(uuid.uuid4())[:8]}"
                primary_username = github_username or discord_username or (email.split("@")[0] if email else f"user_{str(uuid.uuid4())[:4]}")
                user = UserTable(
                    id=user_id,
                    username=primary_username,
                    email=email,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    skills=[]
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
                meta = dict(pi_gh.platform_metadata) if pi_gh.platform_metadata else {}
                meta["username"] = github_username
                if github_repo:
                    meta["repo"] = github_repo
                pi_gh.platform_metadata = meta
                flag_modified(pi_gh, "platform_metadata")
    
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
                meta = dict(pi_dc.platform_metadata) if pi_dc.platform_metadata else {}
                meta["discord_id"] = discord_id
                meta["username"] = discord_username
                pi_dc.platform_metadata = meta
                flag_modified(pi_dc, "platform_metadata")
     
            # 4. Upsert Google PlatformIntegration
            if google_id:
                pi_go = db.query(PlatformIntegrationTable).filter_by(
                    platform_name="google", user_id=user.id
                ).first()
                if not pi_go:
                    pi_go = PlatformIntegrationTable(
                        id=str(uuid.uuid4()),
                        user_id=user.id,
                        platform_name="google",
                        connected_at=datetime.now(timezone.utc).isoformat()
                    )
                    db.add(pi_go)
                pi_go.access_token = google_access_token
                meta = dict(pi_go.platform_metadata) if pi_go.platform_metadata else {}
                meta["google_id"] = google_id
                meta["name"] = google_name
                meta["picture"] = google_picture
                pi_go.platform_metadata = meta
                flag_modified(pi_go, "platform_metadata")
    
            db.commit()
    
            # Check if fully onboarded
            integrations = db.query(PlatformIntegrationTable).filter_by(user_id=user.id).all()
            platforms_connected = [pi.platform_name for pi in integrations]
            is_fully_onboarded = (
                "github" in platforms_connected or
                "discord" in platforms_connected or
                "google" in platforms_connected 
            )
            return {
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
                "is_new_user": not is_fully_onboarded
            }
        except OperationalError as e:
            db.rollback()
            if "neon:retryable" in str(e) and attempt < retries - 1:
                time.sleep(1)
                continue
            print(f"[USER PROFILE] ❌ OperationalError: {e}")
            raise e
        except Exception as e:
            print(f"[USER PROFILE] ❌ Failed to save user profile: {e}")
            db.rollback()
            raise e
        finally:
            db.close()
            sys.stdout.flush()


def update_member_activity(actor: str, content: str, timestamp: str) -> None:
    # Updates each team member's activity in discord_activity.json when a Discord message arrives.
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
    # Syncs task status to Neo4j for Clover AI; uses synchronous requests to match state_machine.py's sync call path.
    if not GRAPH_API_URL or not INTERNAL_API_KEY:
        print("[GRAPH SYNC] ⚠️ Missing GRAPH_API_URL or INTERNAL_API_KEY — skipping sync")
        sys.stdout.flush()
        return False

    import time
    url = f"{GRAPH_API_URL}/tasks/{task_id}/status"

    max_retries = 3
    base_delay = 1.0  # seconds

    for attempt in range(max_retries + 1):
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
            elif response.status_code >= 500:
                # Server error, worth retrying
                print(f"[GRAPH SYNC] ⚠️ Neo4j sync failed (HTTP {response.status_code}). "
                      f"Attempt {attempt + 1}/{max_retries + 1}")
            else:
                # Client error (4xx) or unexpected status, don't retry
                print(f"[GRAPH SYNC] ❌ Neo4j sync failed for {task_id}: "
                      f"HTTP {response.status_code} — {response.text}")
                sys.stdout.flush()
                return False

        except requests.exceptions.RequestException as e:
            print(f"[GRAPH SYNC] ⚠️ Network error (Attempt {attempt + 1}/{max_retries + 1}): {e}")

        if attempt < max_retries:
            delay = base_delay * (2 ** attempt)
            print(f"[GRAPH SYNC] ⏳ Retrying in {delay}s...")
            sys.stdout.flush()
            time.sleep(delay)

    print(f"[GRAPH SYNC] ❌ Neo4j sync completely failed after {max_retries + 1} attempts for {task_id}.")
    sys.stdout.flush()
    return False


# (Legacy initialize_tasks_file removed)
# =====================================================================
# DISCORD BOT
# =====================================================================
# Discord bot runs as a background task inside FastAPI, reading messages and forwarding them.
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
    # Fires when bot successfully logs in to Discord.
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


# The one Discord channel Orchestra listens to.
# Only messages from this channel are processed.
# All other channels are ignored completely.
DISCORD_ALLOWED_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "1509182463493013526"))

@bot.event
async def on_message(message):
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return

    # Only process messages from the designated channel
    if message.channel.id != DISCORD_ALLOWED_CHANNEL_ID:
        return

    # Ignore empty messages
    if not message.content:
        return

    print(f"[DISCORD BOT] 📨 Message from {message.author.name} "
          f"in #{message.channel.name}: {message.content[:50]}")
    sys.stdout.flush()

    # Build payload
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

    # Update activity tracker
    update_member_activity(
        actor=message.author.name,
        content=message.content,
        timestamp=message.created_at.isoformat()
    )

    # Normalize and save
    try:
        from normalizer import normalize_event
        normalized = normalize_event("discord_message", payload)
        save_normalized_event(normalized)
        print(f"[DISCORD BOT] ✅ Message normalized and saved")
        sys.stdout.flush()
    except Exception as e:
        print(f"[DISCORD BOT] ⚠️ Error: {e}")
        sys.stdout.flush()


async def start_discord_bot():
    # Starts the Discord bot when FastAPI server starts up.
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
                status = (task.status or "").lower()

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
    # Scans a commit message for task references like "Fixes Task #8", returns found task IDs.
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


def update_task_status(task_id: str, new_status: str) -> bool:
    # Finds a task by its exact ID or legacy reference number and updates its status.
    from database import SessionLocal
    from models_sql import TaskTable
    from sqlalchemy.orm.attributes import flag_modified

    db = SessionLocal()
    try:
        task = db.query(TaskTable).filter(TaskTable.id == task_id).first()
        if not task:
            task_ref = task_id.replace("task_", "").lstrip("0")
            if not task_ref:
                task_ref = "0"
            full_task_id = f"task_{task_ref.zfill(3)}"
            task = db.query(TaskTable).filter(TaskTable.id == full_task_id).first()
            if task:
                task_id = full_task_id

        if not task:
            print(f"[STATE MACHINE] ❌ Task {task_id} not found in database")
            sys.stdout.flush()
            return False

        old_status = task.status
        task.status = new_status

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

        print(f"[STATE MACHINE] ✅ {task_id}: {old_status} → {new_status}")
        sys.stdout.flush()

        # Sync to Neo4j Graph DB
        sync_task_status_to_neo4j(task_id, new_status)

        # Broadcasts task status change to all connected browsers for live UI updates.
        try:
            asyncio.create_task(
                manager.broadcast(
                    {
                        "type": "task_updated",
                        "task_id": task_id,
                        "old_status": old_status,
                        "new_status": new_status,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )
            print(f"[WEBSOCKET] 📡 Broadcast triggered for {task_id}")
            sys.stdout.flush()
        except Exception as e:
            print(f"[WEBSOCKET] ⚠️ Broadcast failed: {e}")
            sys.stdout.flush()

        return True
    except Exception as e:
        print(f"[STATE MACHINE] Error updating task {task_id}: {e}")
        db.rollback()
        return False
    finally:
        db.close()


# =====================================================================
# Route 1 — Health Check
# =====================================================================
@app.get("/")
async def health_check():
    return "Orchestra Backend Set by Sarvyagya & Arnav"


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
# Handles GitHub push events: logs, extracts task refs, auto-updates matching tasks, and saves.
# =====================================================================
@app.post("/webhook/github")
async def receive_github(request: Request):
    github_event = request.headers.get("X-GitHub-Event", "unknown")

    # ── HANDLE PING FIRST — before any verification ──
    # Ping is just GitHub checking the URL works.
    # No signature needed, just return 200 immediately.
    if github_event == "ping":
        print("[GITHUB] ✅ Ping received — webhook registered successfully!")
        sys.stdout.flush()
        return {"received": True, "message": "Ping acknowledged"}

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

    # Enforce signature verification only if:
    # 1. A webhook secret is configured
    # 2. AND we have a registered user secret to verify against
    # If no user is registered yet (e.g. org-level webhooks),
    # we skip verification and trust the payload.
    if GITHUB_WEBHOOK_SECRET_KEY and GITHUB_WEBHOOK_SECRET_KEY != "default_secret" and user_secret:
        if github_signature:
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
        else:
            print(f"[GITHUB] ⚠️ No signature header — skipping verification for {sender}")
            sys.stdout.flush()
    else:
        print(f"[GITHUB] ℹ️ No user secret found for {sender} — accepting without verification")
        sys.stdout.flush()
    # ── END SIGNATURE VERIFICATION ──────────────────────────────

    log_webhook_payload("GITHUB", payload)

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
            else "pending"
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
# Returns tasks from the database for the frontend UI.
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
                    "status": t.status.lower() if t.status else "pending",
                    "track": t.track,
                    "description": t.description,
                    "priority": t.priority,
                    "updated_at": t.updated_at,
                    "platform": t.platform,
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
        ai_url = os.getenv("GRAPH_API_URL", "https://orchestra-ai-36zm.onrender.com")
        api_key = os.getenv("INTERNAL_API_KEY", "")
        response = requests.get(
            f"{ai_url}/graph", 
            headers={"x-api-key": api_key},
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"error": str(exc), "nodes": [], "edges": []}


# =====================================================================
# Route: GET /team
# =====================================================================
# Proxies frontend requests to the AI service for team/skills data, keeping INTERNAL_API_KEY server-side.
@app.get("/team")
async def get_team():
    import httpx
    from fastapi.responses import JSONResponse
    
    ai_service_url = os.getenv("AI_SERVICE_URL", "https://orchestra-ai-36zm.onrender.com")
    internal_api_key = os.getenv("INTERNAL_API_KEY", "")
    
    if not internal_api_key:
        print("[TEAM] ❌ Missing INTERNAL_API_KEY")
        sys.stdout.flush()
        return JSONResponse(status_code=500, content={"error": "AI service not configured"})
        
    print("[TEAM] 🔄 Forwarding team request to AI service")
    sys.stdout.flush()
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{ai_service_url}/team",
                headers={"x-api-key": internal_api_key},
                timeout=30.0
            )
            
        if response.status_code != 200:
            print(f"[TEAM] ❌ AI service returned non-200: {response.status_code}")
            sys.stdout.flush()
            return JSONResponse(status_code=502, content={"error": "AI service error", "detail": response.text})
            
        print("[TEAM] ✅ Team data received, returning to frontend")
        sys.stdout.flush()
        return JSONResponse(status_code=200, content=response.json())
        
    except httpx.RequestError as e:
        print(f"[TEAM] ❌ Network error or timeout: {str(e)}")
        sys.stdout.flush()
        return JSONResponse(status_code=504, content={"error": "AI service timeout or unreachable"})


from pydantic import BaseModel

class BlueprintRequest(BaseModel):
    name: str
    description: str
    tech_stack: List[str]
    members: List[str] = []

# =====================================================================
# Route: POST /blueprint
# =====================================================================
# Proxies frontend roadmap requests to the AI service, keeping INTERNAL_API_KEY server-side.
# =====================================================================
@app.post("/blueprint")
async def proxy_blueprint(request: Request):
    import httpx
    from fastapi.responses import JSONResponse
    
    ai_service_url = os.getenv("AI_SERVICE_URL", os.getenv("GRAPH_API_URL", "https://orchestra-ai-36zm.onrender.com"))
    internal_api_key = os.getenv("INTERNAL_API_KEY", "")
    
    if not internal_api_key:
        print("[BLUEPRINT] ❌ Missing INTERNAL_API_KEY")
        sys.stdout.flush()
        return JSONResponse(status_code=500, content={"error": "AI service not configured"})
        
    try:
        body = await request.json()
    except Exception:
        body = {}
        
    print("[BLUEPRINT] 🔄 Forwarding blueprint request to AI service")
    sys.stdout.flush()
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{ai_service_url}/blueprint",
                json=body,
                headers={"x-api-key": internal_api_key},
                timeout=120.0
            )
            
        if response.status_code != 200:
            print(f"[BLUEPRINT] ❌ AI service returned non-200: {response.status_code}")
            sys.stdout.flush()
            return JSONResponse(status_code=response.status_code, content={"error": "AI service error", "detail": response.text})
            
        print("[BLUEPRINT] ✅ Blueprint data received, returning to frontend")
        sys.stdout.flush()
        return JSONResponse(status_code=200, content=response.json())
        
    except httpx.RequestError as e:
        print(f"[BLUEPRINT] ❌ Network error or timeout: {str(e)}")
        sys.stdout.flush()
        return JSONResponse(status_code=504, content={"error": "AI service timeout or unreachable"})


class CloverRequest(BaseModel):
    question: str
    conversation_history: List[Dict[str, Any]] = []

# =====================================================================
# Route: POST /clover
# =====================================================================
# Proxies frontend chat requests to the Clover AI assistant, keeping INTERNAL_API_KEY server-side.
# =====================================================================
@app.post("/clover")
async def proxy_clover(request: Request):
    import httpx
    from fastapi.responses import JSONResponse
    
    ai_service_url = os.getenv("AI_SERVICE_URL", os.getenv("GRAPH_API_URL", "https://orchestra-ai-36zm.onrender.com"))
    internal_api_key = os.getenv("INTERNAL_API_KEY", "")
    
    if not internal_api_key:
        print("[CLOVER] ❌ Missing INTERNAL_API_KEY")
        sys.stdout.flush()
        return JSONResponse(status_code=500, content={"error": "AI service not configured"})
        
    try:
        body = await request.json()
    except Exception:
        body = {}
        
    print("[CLOVER] 🔄 Forwarding clover request to AI service")
    sys.stdout.flush()
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{ai_service_url}/clover",
                json=body,
                headers={"x-api-key": internal_api_key},
                timeout=120.0
            )
            
        if response.status_code != 200:
            print(f"[CLOVER] ❌ AI service returned non-200: {response.status_code}")
            sys.stdout.flush()
            return JSONResponse(status_code=response.status_code, content={"error": "AI service error", "detail": response.text})
            
        print("[CLOVER] ✅ Clover response received, returning to frontend")
        sys.stdout.flush()
        return JSONResponse(status_code=200, content=response.json())
        
    except httpx.RequestError as e:
        print(f"[CLOVER] ❌ Network error or timeout: {str(e)}")
        sys.stdout.flush()
        return JSONResponse(status_code=504, content={"error": "AI service timeout or unreachable"})


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
                "status": t.status.lower() if t.status else "pending",
                "track": t.track,
                "description": t.description,
                "priority": t.priority,
                "updated_at": t.updated_at,
                "platform": t.platform,
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

    track = body.get("track")
    description = body.get("description")
    priority = body.get("priority")
    updated_at = body.get("updated_at")
    platform = body.get("platform")
    assigned_to = body.get("assigned_to")
    project_id = body.get("project_id")
    depends_on = body.get("depends_on") or body.get("dependencies", [])
    
    from database import SessionLocal
    from models_sql import TaskTable

    created_at = datetime.now(timezone.utc).isoformat()
    if not updated_at:
        updated_at = created_at

    new_task = {
        "id": task_id,
        "title": title,
        "status": "pending",
        "track": track,
        "description": description,
        "priority": priority,
        "updated_at": updated_at,
        "platform": platform,
        "assigned_to": assigned_to,
        "project_id": project_id,
        "depends_on": depends_on,
        "created_at": created_at,
    }

    # Save to SQL database
    db = SessionLocal()
    try:
        exists = db.query(TaskTable).filter(TaskTable.id == task_id).first()
        if not exists:
            new_db_task = TaskTable(
                id=task_id,
                title=title,
                status="PENDING",
                track=track,
                description=description,
                priority=priority,
                updated_at=updated_at,
                platform=platform,
                assigned_to=assigned_to,
                project_id=project_id,
                created_at=created_at,
                depends_on=depends_on,
                history=[]
            )
            db.add(new_db_task)
            db.commit()
    except Exception as e:
        print(f"[API] Error saving new task to database: {e}")
        db.rollback()
    finally:
        db.close()

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


from pydantic import BaseModel

class TaskStatusUpdate(BaseModel):
    status: str

@app.patch("/tasks/{task_id}/status")
async def manually_update_task_status(task_id: str, request: TaskStatusUpdate):
    new_status = request.status
    if not new_status:
        return {"error": "'status' field required"}

    success = update_task_status(task_id, new_status)
    if success:
        return {"status": "success", "message": f"Updated {task_id} to {new_status}"}
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
# Projects routes
# =====================================================================

@app.post("/projects")
async def create_project(request: Request, user_id: Optional[str] = None):
    from fastapi.responses import Response
    from database import SessionLocal
    from models_sql import ProjectTable
    import uuid

    print(f"[PROJECT] Received request to create a project, user_id={user_id}")
    try:
        body = await request.json()
    except Exception:
        body = {}

    name = body.get("name")
    if not name:
        print("[PROJECT] Error: 'name' field is missing")
        return Response(content='{"error": "name is required"}', media_type="application/json", status_code=400)

    description = body.get("description")
    tech_stack = body.get("tech_stack", [])
    members = body.get("members", [])

    created_at = datetime.now(timezone.utc).isoformat()
    updated_at = created_at
    project_id = f"proj_{uuid.uuid4().hex[:8]}"

    db = SessionLocal()
    try:
        new_project = ProjectTable(
            id=project_id,
            name=name,
            description=description,
            created_by=user_id,
            tech_stack=tech_stack,
            members=members,
            created_at=created_at,
            updated_at=updated_at,
        )
        db.add(new_project)
        db.commit()
        print(f"[PROJECT] Successfully created project {project_id}")
        
        project_dict = {
            "id": project_id,
            "name": name,
            "description": description,
            "created_by": user_id,
            "tech_stack": tech_stack,
            "members": members,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        return Response(content=json.dumps(project_dict, indent=4), media_type="application/json")
    except Exception as e:
        print(f"[PROJECT] Error saving new project to database: {e}")
        db.rollback()
        return Response(content=json.dumps({"error": str(e)}), media_type="application/json", status_code=500)
    finally:
        db.close()


# =====================================================================
# Route — Get Projects
# =====================================================================
# Retrieves a list of projects, optionally filtered by the creator.
# =====================================================================
@app.get("/projects")
async def get_projects(user_id: Optional[str] = None):
    from fastapi.responses import Response
    from database import SessionLocal
    from models_sql import ProjectTable

    print(f"[PROJECT] Received request to list projects, user_id={user_id}")
    db = SessionLocal()
    try:
        query = db.query(ProjectTable)
        if user_id:
            query = query.filter(ProjectTable.created_by == user_id)
        db_projects = query.all()
        
        projects_list = []
        for p in db_projects:
            projects_list.append({
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "created_by": p.created_by,
                "tech_stack": p.tech_stack,
                "members": p.members,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            })
        
        result = {
            "total": len(projects_list),
            "projects": projects_list
        }
        return Response(content=json.dumps(result, indent=4), media_type="application/json")
    except Exception as e:
        print(f"[PROJECT] Error querying projects: {e}")
        return Response(content=json.dumps({"error": str(e)}), media_type="application/json", status_code=500)
    finally:
        db.close()


# =====================================================================
# Route — Get Project by ID
# =====================================================================
# Retrieves details of a single project by its ID.
# =====================================================================
@app.get("/projects/{project_id}")
async def get_project_by_id(project_id: str):
    from fastapi.responses import Response
    from database import SessionLocal
    from models_sql import ProjectTable

    print(f"[PROJECT] Received request to get project {project_id}")
    db = SessionLocal()
    try:
        p = db.query(ProjectTable).filter(ProjectTable.id == project_id).first()
        if not p:
            print(f"[PROJECT] Project {project_id} not found")
            return Response(content='{"error": "Project not found"}', media_type="application/json", status_code=404)
        
        project_dict = {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "created_by": p.created_by,
            "tech_stack": p.tech_stack,
            "members": p.members,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }
        return Response(content=json.dumps(project_dict, indent=4), media_type="application/json")
    except Exception as e:
        print(f"[PROJECT] Error querying project {project_id}: {e}")
        return Response(content=json.dumps({"error": str(e)}), media_type="application/json", status_code=500)
    finally:
        db.close()


# =====================================================================
# Route — Update Project (PATCH)
# =====================================================================
# Updates fields of a project by its ID.
# =====================================================================
@app.patch("/projects/{project_id}")
async def update_project(project_id: str, request: Request):
    from fastapi.responses import Response
    from database import SessionLocal
    from models_sql import ProjectTable

    print(f"[PROJECT] Received request to update project {project_id}")
    try:
        body = await request.json()
    except Exception:
        body = {}

    db = SessionLocal()
    try:
        p = db.query(ProjectTable).filter(ProjectTable.id == project_id).first()
        if not p:
            print(f"[PROJECT] Project {project_id} not found for update")
            return Response(content='{"error": "Project not found"}', media_type="application/json", status_code=404)
        
        if "name" in body:
            p.name = body["name"]
        if "description" in body:
            p.description = body["description"]
        if "tech_stack" in body:
            p.tech_stack = body["tech_stack"]
        if "members" in body:
            p.members = body["members"]
            
        p.updated_at = datetime.now(timezone.utc).isoformat()
        db.commit()
        
        print(f"[PROJECT] Successfully updated project {project_id}")
        project_dict = {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "created_by": p.created_by,
            "tech_stack": p.tech_stack,
            "members": p.members,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }
        return Response(content=json.dumps(project_dict, indent=4), media_type="application/json")
    except Exception as e:
        print(f"[PROJECT] Error updating project {project_id}: {e}")
        db.rollback()
        return Response(content=json.dumps({"error": str(e)}), media_type="application/json", status_code=500)
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
# WebSocket endpoint — persistent connection for live task update broadcasts to the frontend.
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
# Redirects user to GitHub's OAuth authorization page.
# =====================================================================
def get_frontend_url(request: Request, return_url: Optional[str] = None) -> str:
    allowed_origins = [
        "https://orchestra-frontend-roan.vercel.app",
        "http://localhost:3000",
        "http://localhost:5173",
        FRONTEND_URL,
    ]

    from urllib.parse import urlparse
    if return_url:
        parsed = urlparse(return_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in allowed_origins:
            return return_url

    referer = request.headers.get("referer")
    if referer:
        parsed = urlparse(referer)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in allowed_origins:
            return origin
            
    return FRONTEND_URL

@app.get("/auth/github")
async def github_login(request: Request, repo: Optional[str] = None, user_id: Optional[str] = None, return_url: Optional[str] = None):
    from fastapi.responses import RedirectResponse
    import urllib.parse
    import json

    actual_return = get_frontend_url(request, return_url)

    # We pass the repo name and user_id through GitHub's "state" parameter
    # GitHub preserves "state" through the OAuth flow and sends it back
    state_dict = {}
    if repo:
        state_dict["repo"] = repo
    if user_id:
        state_dict["user_id"] = user_id
    if actual_return != FRONTEND_URL:
        state_dict["return_url"] = actual_return
        
    state = urllib.parse.quote(json.dumps(state_dict)) if state_dict else ""

    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&scope=read:user,repo,admin:repo_hook"
        f"&state={state}"
        f"&redirect_uri={os.getenv('BACKEND_URL', 'http://localhost:8000')}/auth/github/callback"
    )
    return RedirectResponse(github_auth_url)


# =====================================================================
# Route — GitHub OAuth Callback
# =====================================================================
# GitHub OAuth callback: exchanges code for token, gets profile, registers webhook on their repo.
# =====================================================================
@app.get("/auth/github/callback")
async def github_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None, error_description: Optional[str] = None):
    frontend_url = FRONTEND_URL
    import urllib.parse
    import json
    
    repo = None
    existing_user_id = None
    if state:
        try:
            state_dict = json.loads(urllib.parse.unquote(state))
            if isinstance(state_dict, dict):
                repo = state_dict.get("repo")
                existing_user_id = state_dict.get("user_id")
                if state_dict.get("return_url"):
                    frontend_url = state_dict.get("return_url")
            else:
                repo = urllib.parse.unquote(state)
        except Exception:
            # Fallback for old simple string state
            repo = urllib.parse.unquote(state)

    if error or not code:
        err_msg = error_description or error or "missing_code"
        return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=github&error={err_msg}")

    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        print("[GITHUB AUTH] ❌ Missing GitHub client credentials.")
        return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=github&error=server_error")

    import httpx

    async with httpx.AsyncClient() as client:
        # Step 1 — Exchange code for access token
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{os.getenv('BACKEND_URL', 'http://localhost:8000')}/auth/github/callback",
            },
            headers={"Accept": "application/json"},
        )
        try:
            token_data = token_response.json()
        except ValueError:
            return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=github&error=provider_error")

        access_token = token_data.get("access_token")

        if not access_token:
            return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=github&error=failed_to_get_token")

        # Step 2 — Get user's GitHub profile
        user_response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        try:
            user_data = user_response.json()
        except ValueError:
            return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=github&error=provider_error")

        github_username = user_data.get("login")

    # Step 3 — Auto register webhook on their repo
    # State parameter was decoded at the top of the function

    webhook_result = {"success": False, "note": "No repo provided"}

    user_profile = save_unified_user_profile(
        github_username=github_username, 
        github_access_token=access_token,
        github_repo=repo,
        existing_user_id=existing_user_id
    )
    user_id = user_profile.get("user_id") if user_profile else ""
    is_new_user = user_profile.get("is_new_user", True) if user_profile else True

    if repo:
        print(f"[GITHUB] Registering webhook for {github_username} on {repo}")
        sys.stdout.flush()
        webhook_result = await register_github_webhook(
            access_token=access_token,
            github_username=github_username,
            repo_full_name=repo,
        )

    redirect_url = f"{frontend_url}/oauth/callback?platform=github&username={github_username}&user_id={user_id}"
    if is_new_user:
        redirect_url += "&isNewUser=true"
    return RedirectResponse(url=redirect_url)


# =====================================================================
# Route — View Connected Users
# =====================================================================
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
# Redirects user to Discord's OAuth authorization page with identify/email/guilds scopes.
# =====================================================================
@app.get("/auth/discord")
async def discord_login(request: Request, user_id: Optional[str] = None, return_url: Optional[str] = None):
    from fastapi.responses import RedirectResponse
    import urllib.parse
    import json

    actual_return = get_frontend_url(request, return_url)

    state_dict = {}
    if user_id:
        state_dict["user_id"] = user_id
    if actual_return != FRONTEND_URL:
        state_dict["return_url"] = actual_return

    state = urllib.parse.quote(json.dumps(state_dict)) if state_dict else ""

    discord_auth_url = (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={os.getenv('BACKEND_URL', 'http://localhost:8000')}/auth/discord/callback"
        f"&response_type=code"
        f"&scope=identify%20email%20guilds"
        f"&state={state}"
    )
    return RedirectResponse(discord_auth_url)


# =====================================================================
# Route — Discord OAuth Callback
# =====================================================================
# Discord OAuth callback: exchanges code for token, gets profile, saves to database.
# =====================================================================
@app.get("/auth/discord/callback")
async def discord_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None, error_description: Optional[str] = None):
    frontend_url = FRONTEND_URL
    import urllib.parse
    import json
    
    existing_user_id = None
    if state:
        try:
            state_dict = json.loads(urllib.parse.unquote(state))
            if isinstance(state_dict, dict):
                existing_user_id = state_dict.get("user_id")
                if state_dict.get("return_url"):
                    frontend_url = state_dict.get("return_url")
            else:
                existing_user_id = urllib.parse.unquote(state)
        except Exception:
            existing_user_id = urllib.parse.unquote(state)

    if error or not code:
        err_msg = error_description or error or "missing_code"
        return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=discord&error={err_msg}")

    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        print("[DISCORD AUTH] ❌ Missing Discord client credentials.")
        return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=discord&error=server_error")

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
                "redirect_uri": f"{os.getenv('BACKEND_URL', 'http://localhost:8000')}/auth/discord/callback",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            token_data = token_response.json()
        except ValueError:
            return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=discord&error=provider_error")

        access_token = token_data.get("access_token")

        if not access_token:
            return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=discord&error=failed_to_get_token")

        # Step 2 — Use token to get user's Discord profile
        user_response = await client.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        try:
            user_data = user_response.json()
        except ValueError:
            return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=discord&error=provider_error")

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
    # existing_user_id was decoded at the top of the function

    user_profile = save_unified_user_profile(
        discord_id=discord_id,
        discord_username=discord_username,
        discord_access_token=access_token,
        email=email,
        existing_user_id=existing_user_id
    )
    user_id = user_profile.get("user_id") if user_profile else ""
    is_new_user = user_profile.get("is_new_user", True) if user_profile else True

    redirect_url = f"{frontend_url}/oauth/callback?platform=discord&username={discord_username}&user_id={user_id}"
    if is_new_user:
        redirect_url += "&isNewUser=true"
    return RedirectResponse(url=redirect_url)

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
# Route — Google OAuth Login
# =====================================================================
# Redirects user to Google's OAuth authorization page with openid/email/profile scopes.
# =====================================================================
@app.get("/auth/google")
async def google_login(request: Request, user_id: Optional[str] = None, return_url: Optional[str] = None):
    from fastapi.responses import RedirectResponse
    import urllib.parse
    import json

    actual_return = get_frontend_url(request, return_url)

    state_dict = {}
    if user_id:
        state_dict["user_id"] = user_id
    if actual_return != FRONTEND_URL:
        state_dict["return_url"] = actual_return

    # Pass state so we can link to existing profile and redirect correctly
    state = urllib.parse.quote(json.dumps(state_dict)) if state_dict else ""

    google_auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={os.getenv('BACKEND_URL', 'http://localhost:8000')}/auth/google/callback"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
        f"&state={state}"
    )
    return RedirectResponse(google_auth_url)

# =====================================================================
# Route — Google OAuth Callback
# =====================================================================
# Google OAuth callback: exchanges code for tokens, gets profile, saves to unified user profile.
# =====================================================================
@app.get("/auth/google/callback")
async def google_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None, error_description: Optional[str] = None):
    from fastapi.responses import RedirectResponse
    import httpx
    import urllib.parse
    import json

    frontend_url = FRONTEND_URL
    existing_user_id = None
    
    if state:
        try:
            state_dict = json.loads(urllib.parse.unquote(state))
            if isinstance(state_dict, dict):
                existing_user_id = state_dict.get("user_id")
                if state_dict.get("return_url"):
                    frontend_url = state_dict.get("return_url")
            else:
                existing_user_id = urllib.parse.unquote(state)
        except Exception:
            existing_user_id = urllib.parse.unquote(state)

    if error or not code:
        err_msg = error_description or error or "missing_code"
        return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=google&error={err_msg}")

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        print("[GOOGLE AUTH] ❌ Missing Google client credentials.")
        return RedirectResponse(url=f"{frontend_url}/oauth/callback?platform=google&error=server_error")

    async with httpx.AsyncClient() as client:

        # Step 1 — Exchange code for access token
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": f"{os.getenv('BACKEND_URL', 'http://localhost:8000')}/auth/google/callback"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        try:
            token_data = token_response.json()
        except ValueError:
            return RedirectResponse(
                url=f"{frontend_url}/oauth/callback?platform=google&error=provider_error"
            )

        access_token = token_data.get("access_token")

        if not access_token:
            print(f"[GOOGLE AUTH] ❌ Failed to get token: {token_data}")
            sys.stdout.flush()
            return RedirectResponse(
                url=f"{frontend_url}/oauth/callback?platform=google&error=failed_to_get_token"
            )

        # Step 2 — Use token to get user's Google profile
        user_response = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        try:
            user_data = user_response.json()
        except ValueError:
            return RedirectResponse(
                url=f"{frontend_url}/oauth/callback?platform=google&error=provider_error"
            )

    google_id = user_data.get("id")
    email = user_data.get("email")
    name = user_data.get("name")
    picture = user_data.get("picture")

    print(f"[GOOGLE AUTH] ✅ User logged in: {email} ({name})")
    sys.stdout.flush()

    # Step 3 — Get existing user_id from state if linking accounts
    # existing_user_id was decoded at the top of the function

    # Step 4 — Save to unified user profile (links to any existing GitHub/Discord profile)
    user_profile = save_unified_user_profile(
        email=email,
        existing_user_id=existing_user_id,
        google_id=google_id,
        google_name=name,
        google_picture=picture,
        google_access_token=access_token
    )

    user_id = user_profile.get("user_id") if user_profile else ""
    is_new_user = user_profile.get("is_new_user", True) if user_profile else True

    # Step 5 — Redirect back to frontend with user info
    redirect_url = (
        f"{frontend_url}/oauth/callback"
        f"?platform=google"
        f"&email={urllib.parse.quote(email or '')}"
        f"&name={urllib.parse.quote(name or '')}"
        f"&user_id={user_id}"
        f"&picture={urllib.parse.quote(picture or '')}"
    )
    if is_new_user:
        redirect_url += "&isNewUser=true"

    return RedirectResponse(url=redirect_url)

# =====================================================================
# Route — View Google Connected Users
# =====================================================================
# Shows all users who signed in with Google (access tokens never exposed).
# =====================================================================
@app.get("/google-users")
async def get_google_users():
    from fastapi.responses import Response
    from database import SessionLocal
    from models_sql import PlatformIntegrationTable, UserTable
    import json

    db = SessionLocal()
    try:
        db_users = db.query(PlatformIntegrationTable, UserTable)\
                     .join(UserTable, PlatformIntegrationTable.user_id == UserTable.id)\
                     .filter(PlatformIntegrationTable.platform_name == "google").all()

        safe_users = []
        for pi, user in db_users:
            meta = pi.platform_metadata or {}
            
            # Check for other integrations
            other_pis = db.query(PlatformIntegrationTable).filter(PlatformIntegrationTable.user_id == user.id).all()
            github_username = None
            discord_username = None
            for opi in other_pis:
                if opi.platform_name == "github":
                    github_username = (opi.platform_metadata or {}).get("username")
                elif opi.platform_name == "discord":
                    discord_username = (opi.platform_metadata or {}).get("username")

            safe_users.append({
                "user_id": user.id,
                "email": user.email,
                "google_name": meta.get("name"),
                "google_picture": meta.get("picture"),
                "github_username": github_username,
                "discord_username": discord_username,
                "connected_at": pi.connected_at
            })

        result = {
            "total": len(safe_users),
            "google_users": safe_users
        }
        formatted = json.dumps(result, indent=4)
        return Response(content=formatted, media_type="application/json")
    finally:
        db.close()

# =====================================================================
# Route — View Unified User Profiles
# =====================================================================
# Shows all users with their connected platforms (master identity record).
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
                    "skills": u.skills if u.skills is not None else [],
                }
            )
        result = {"total": len(safe_profiles), "users": safe_profiles}
        formatted = json.dumps(result, indent=4)
        return Response(content=formatted, media_type="application/json")
    finally:
        db.close()


# =====================================================================
# Route — Update User Profile
# =====================================================================
# Updates user profile information.
# =====================================================================
@app.put("/users/{user_id}")
async def update_user_put(user_id: str, payload: dict):
    from fastapi.responses import Response
    from database import SessionLocal
    from models_sql import UserTable

    db = SessionLocal()
    try:
        user = db.query(UserTable).filter_by(id=user_id).first()
        if not user:
            return Response(content='{"error": "User not found"}', media_type="application/json", status_code=404)
        
        data = payload
        if "username" in data:
            user.username = data["username"]
        if "name" in data:
            user.name = data["name"]
        if "email" in data:
            user.email = data["email"]
        if "skills" in data:
            user.skills = data["skills"]
        
        user.updated_at = datetime.now(timezone.utc).isoformat()
        db.commit()
        return Response(content='{"message": "User updated successfully"}', media_type="application/json")
    finally:
        db.close()

@app.patch("/users/{user_id}")
async def update_user_patch(user_id: str, payload: dict):
    from fastapi.responses import Response
    from database import SessionLocal
    from models_sql import UserTable

    db = SessionLocal()
    try:
        user = db.query(UserTable).filter_by(id=user_id).first()
        if not user:
            return Response(content='{"error": "User not found"}', media_type="application/json", status_code=404)
        
        data = payload
        if "username" in data:
            user.username = data["username"]
        if "name" in data:
            user.name = data["name"]
        if "email" in data:
            user.email = data["email"]
        if "skills" in data:
            user.skills = data["skills"]
        
        user.updated_at = datetime.now(timezone.utc).isoformat()
        db.commit()
        return Response(content='{"message": "User patched successfully"}', media_type="application/json")
    finally:
        db.close()


# =====================================================================
# Route — Discord Activity Summary
# =====================================================================
# Shows what each team member is currently working on based on Discord messages.
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
# Correlates Discord messages with GitHub commit/PR activity for unified team intel.
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
# Triggers the daily standup logic instantly for testing (normally runs at 9:00 AM).
# =====================================================================
@app.get("/test-daily-standup")
async def test_daily_standup():
    # Manually triggers the daily standup routine in the background.
    asyncio.create_task(run_daily_standup())
    return {"status": "success", "message": "Daily standup triggered in background."}

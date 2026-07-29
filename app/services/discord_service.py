import os
import sys
import json
import discord
from app.core.config import DISCORD_BOT_TOKEN, DISCORD_ALLOWED_CHANNEL_ID
from app.services.event_service import save_normalized_event

# Set up Discord bot with all necessary permissions
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

    from app.services.standup_service import standup_scheduler

    # Start the standup scheduler loop if not already running
    if not standup_scheduler.is_running():
        standup_scheduler.start()
        print("[DISCORD BOT] ⏰ Daily Standup Scheduler started (9:00 AM)")
        sys.stdout.flush()


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

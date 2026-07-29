import os
import sys
import json
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import tasks
from app.utils.websocket_manager import manager
from app.services.discord_service import bot

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
    from app.services.task_service import extract_task_references

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

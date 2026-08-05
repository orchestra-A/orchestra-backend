"""
state_machine.py — Week 3, Member 4
Automated Status State Machine.

Listens to GitHub PR/push events and automatically transitions task states.
States: PENDING → IN_PROGRESS → COMPLETED → BLOCKED

Examples:
  - Developer pushes to "feature/task-12" → Task 12 moves IN_PROGRESS
  - PR #42 merged → Task moves COMPLETED
  - Branch deleted without merge → Task moves BLOCKED
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

TASKS_FILE = "tasks.json"


class TaskState(str, Enum):
    UPCOMING = "upcoming"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class Task:
    id: str
    title: str
    state: TaskState = TaskState.UPCOMING
    assigned_to: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    pr_number: Optional[int] = None
    branch: Optional[str] = None
    project_id: Optional[str] = None
    order: Optional[int] = None
    depends_on: list = field(default_factory=list)
    history: list = field(default_factory=list)
    confirmed: bool = False

    def transition(self, new_state: TaskState, actor: str, reason: str = "") -> bool:
        """
        Attempt a state transition.
        Returns True if valid, False if the transition is not allowed.
        """
        allowed = TRANSITIONS.get(self.state, [])
        if new_state not in allowed:
            print(
                f"[STATE MACHINE] ❌ {self.id}: {self.state} → {new_state} NOT allowed"
            )
            return False

        old_state = self.state
        self.state = new_state
        self.assigned_to = actor
        timestamp = datetime.now(timezone.utc).isoformat()
        self.history.append(
            {
                "type": "STATUS_CHANGE",
                "from": old_state.value,
                "to": new_state.value,
                "actor": actor,
                "message": reason,
                "timestamp": timestamp,
            }
        )
        print(f"[STATE MACHINE] ✅ {self.id}: {old_state.value} → {new_state.value} (by {actor})")
        return True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.state.value,
            "assigned_to": self.assigned_to,
            "project_id": self.project_id,
            "order": self.order,
            "depends_on": self.depends_on,
            "created_at": self.created_at,
            "pr_number": self.pr_number,
            "branch": self.branch,
            "history": self.history,
            "confirmed": self.confirmed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        # Map raw status strings to TaskState Enum
        raw_status = d.get("status", "upcoming").lower()
        if raw_status in ("todo", "pending", "upcoming"):
            state = TaskState.UPCOMING
        elif raw_status in ("in_progress", "in progress"):
            state = TaskState.IN_PROGRESS
        elif raw_status in ("completed", "done"):
            state = TaskState.COMPLETED
        elif raw_status in ("blocked", "stopped"):
            state = TaskState.BLOCKED
        else:
            state = TaskState(raw_status)

        t = cls(
            id=d["id"],
            title=d["title"],
            state=state,
            assigned_to=d.get("assigned_to"),
            project_id=d.get("project_id"),
            order=d.get("order"),
            depends_on=d.get("depends_on", []),
            created_at=d.get("created_at", ""),
            pr_number=d.get("pr_number"),
            branch=d.get("branch"),
            history=d.get("history", []),
            confirmed=d.get("confirmed", False),
        )
        return t


# ─────────────────────────────────────────────
# Valid state transitions
# ─────────────────────────────────────────────

TRANSITIONS: dict[TaskState, list[TaskState]] = {
    TaskState.UPCOMING: [TaskState.IN_PROGRESS, TaskState.BLOCKED],
    TaskState.IN_PROGRESS: [TaskState.COMPLETED, TaskState.BLOCKED, TaskState.UPCOMING],
    TaskState.BLOCKED: [TaskState.UPCOMING, TaskState.IN_PROGRESS],
    TaskState.COMPLETED: [],  # Terminal state — no going back
}


# ─────────────────────────────────────────────
# Task store (file-backed for Week 3)
# ─────────────────────────────────────────────

from database import SessionLocal
from models_sql import TaskTable


def load_tasks() -> dict[str, Task]:
    db = SessionLocal()
    try:
        db_tasks = db.query(TaskTable).all()
        tasks_dict = {}
        for dt in db_tasks:
            # Map SQL attributes to dict so from_dict still works
            d = {
                "id": dt.id,
                "title": dt.title,
                "status": dt.status.lower() if dt.status else "upcoming",
                "assigned_to": dt.assigned_to,
                "project_id": dt.project_id,
                "order": dt.order,
                "depends_on": dt.depends_on,
                "created_at": dt.created_at,
                "pr_number": dt.pr_number,
                "branch": dt.branch,
                "history": dt.history,
            }
            tasks_dict[dt.id] = Task.from_dict(d)
        return tasks_dict
    finally:
        db.close()


def save_tasks(tasks: dict[str, Task]) -> None:
    db = SessionLocal()
    try:
        for t_id, task_obj in tasks.items():
            dt = db.query(TaskTable).filter(TaskTable.id == t_id).first()
            if not dt:
                dt = TaskTable(id=t_id)
                db.add(dt)
                old_state = None
            else:
                old_state = dt.status

            d = task_obj.to_dict()
            new_state = d.get("status", "upcoming").lower()

            dt.title = d.get("title")
            dt.status = new_state
            dt.assigned_to = d.get("assigned_to")
            dt.project_id = d.get("project_id")
            dt.order = d.get("order")
            dt.depends_on = d.get("depends_on", [])
            dt.created_at = d.get("created_at")
            dt.pr_number = d.get("pr_number")
            dt.branch = d.get("branch")
            dt.history = d.get("history", [])

            # If task status has changed, sync to Neo4j Graph DB
            if old_state != new_state:
                try:
                    from app.services.graph_service import sync_task_status_to_neo4j
                    import threading
                    threading.Thread(
                        target=sync_task_status_to_neo4j,
                        args=(t_id, new_state),
                        daemon=True
                    ).start()
                except Exception as e:
                    print(f"[STATE MACHINE] Error importing/calling sync_task_status_to_neo4j: {e}")
        db.commit()
    finally:
        db.close()


def get_task(task_id: str) -> Optional[Task]:
    return load_tasks().get(task_id)


def upsert_task(task: Task) -> None:
    tasks = load_tasks()
    tasks[task.id] = task
    save_tasks(tasks)


def create_task(task_id: str, title: str) -> Task:
    task = Task(id=task_id, title=title)
    upsert_task(task)
    return task


# ─────────────────────────────────────────────
# GitHub event → state machine triggers
# ─────────────────────────────────────────────


def extract_task_id_from_branch(branch: str) -> Optional[str]:
    """
    Extracts task ID from branch name.
    Normalizes it to "task_00X" format to match DB if old format.
    Examples:
      "feature/P001-T042" → "P001-T042"
      "feature/task-12"   → "task_012"
      "fix/task-7-login"  → "task_007"
      "main"              → None
    """
    import re

    match_new = re.search(r"(P\w+-T\d+)", branch, re.IGNORECASE)
    if match_new:
        return match_new.group(1).upper()

    match_old = re.search(r"task[-_](\d+)", branch, re.IGNORECASE)
    if match_old:
        return f"task_{match_old.group(1).zfill(3)}"
    return None


def extract_task_id_from_pr_title(title: str) -> Optional[str]:
    """
    Extracts task ID from PR title.
    Normalizes it to "task_00X" format to match DB if old format.
    Examples:
      "Fixes task-12: Add normalizer"   → "task_012"
      "Closes task-7"                   → "task_007"
      "Random PR title"                 → None
    """
    import re

    match_new = re.search(r"(P\w+-T\d+)", title, re.IGNORECASE)
    if match_new:
        return match_new.group(1).upper()

    match_old = re.search(r"task[-_](\d+)", title, re.IGNORECASE)
    if match_old:
        return f"task_{match_old.group(1).zfill(3)}"
    return None


async def handle_push_event(event: dict) -> Optional[dict]:
    """
    GitHub push → check if branch name contains a task ID
    If yes, move that task to IN_PROGRESS.
    Returns the state change dict if a transition happened.
    """
    branch = event.get("raw_metadata", {}).get("branch", "")
    actor = event.get("actor", "unknown")
    task_id = extract_task_id_from_branch(branch)

    if not task_id:
        print(f"[STATE MACHINE] Push to '{branch}' — no task ID found, skipping")
        return None

    tasks = load_tasks()
    task = tasks.get(task_id)

    if not task:
        # Auto-create task if it doesn't exist
        task = Task(id=task_id, title=f"Auto-created from branch: {branch}")
        print(f"[STATE MACHINE] Auto-created task '{task_id}' from branch '{branch}'")

    task.branch = branch
    changed = task.transition(
        TaskState.IN_PROGRESS,
        actor=actor,
        reason=f"Developer pushed to {branch}",
    )

    if changed:
        upsert_task(task)
        task_dict = task.to_dict()

        # Broadcast the update dynamically to avoid circular import
        from app.utils.websocket_manager import manager

        await manager.broadcast({"type": "task_update", **task_dict})

        return task_dict
    return None


async def handle_pr_event(event: dict) -> Optional[dict]:
    """
    GitHub PR event → check if PR title or branch contains a task ID
    - PR opened → IN_PROGRESS
    - PR merged → COMPLETED
    - PR closed (not merged) → BLOCKED
    Returns the state change dict if a transition happened.
    """
    metadata = event.get("raw_metadata", {})
    action = metadata.get("action", "")
    actor = event.get("actor", "unknown")
    pr_number = metadata.get("pr_number")
    pr_title = metadata.get("pr_title", "")
    merged = metadata.get("merged", False)

    # Try to extract task ID from PR title or branch
    task_id = extract_task_id_from_pr_title(pr_title) or extract_task_id_from_branch(
        metadata.get("head_branch", "")
    )

    if not task_id:
        print(f"[STATE MACHINE] PR '{pr_title}' — no task ID found, skipping")
        return None

    tasks = load_tasks()
    task = tasks.get(task_id)

    if not task:
        task = Task(id=task_id, title=pr_title)
        print(f"[STATE MACHINE] Auto-created task '{task_id}' from PR '{pr_title}'")

    task.pr_number = pr_number
    target_state = None
    reason = ""

    if action == "opened" or action == "synchronize":
        target_state = TaskState.IN_PROGRESS
        reason = f"PR #{pr_number} opened: {pr_title}"
    elif action == "closed" and merged:
        target_state = TaskState.COMPLETED
        reason = f"PR #{pr_number} merged: {pr_title}"
    elif action == "closed" and not merged:
        target_state = TaskState.BLOCKED
        reason = f"PR #{pr_number} closed without merging"

    if target_state:
        changed = task.transition(target_state, actor=actor, reason=reason)
        if changed:
            upsert_task(task)
            task_dict = task.to_dict()

            # Broadcast the update dynamically to avoid circular import
            from app.utils.websocket_manager import manager

            await manager.broadcast({"type": "task_update", **task_dict})

            return task_dict

    return None


async def process_normalized_event(event: dict) -> Optional[dict]:
    """
    Main entry point — routes normalized events to the right handler.
    Call this from main.py when a new event arrives.
    """
    event_type = event.get("event_type", "")
    platform = event.get("platform", "")

    if platform != "github":
        return None  # State machine only cares about GitHub for now

    if event_type == "push":
        return await handle_push_event(event)
    elif event_type == "pull_request":
        return await handle_pr_event(event)

    return None

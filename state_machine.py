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
import json
import os

TASKS_FILE = "tasks.json"


class TaskState(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


@dataclass
class Task:
    id: str
    title: str
    state: TaskState = TaskState.PENDING
    assigned_to: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pr_number: Optional[int] = None
    branch: Optional[str] = None
    history: list = field(default_factory=list)

    def transition(self, new_state: TaskState, actor: str, reason: str = "") -> bool:
        """
        Attempt a state transition.
        Returns True if valid, False if the transition is not allowed.
        """
        allowed = TRANSITIONS.get(self.state, [])
        if new_state not in allowed:
            print(f"[STATE MACHINE] ❌ {self.id}: {self.state} → {new_state} NOT allowed")
            return False

        old_state = self.state
        self.state = new_state
        self.assigned_to = actor
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.history.append({
            "from": old_state,
            "to": new_state,
            "actor": actor,
            "reason": reason,
            "timestamp": self.updated_at,
        })
        print(f"[STATE MACHINE] ✅ {self.id}: {old_state} → {new_state} (by {actor})")
        return True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.state.value.lower() if self.state != TaskState.PENDING else "todo",
            "assigned_to": self.assigned_to,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pr_number": self.pr_number,
            "branch": self.branch,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        # Map Member 3's 'status' field back to TaskState Enum
        raw_status = d.get("status", "todo")
        if raw_status == "todo":
            state = TaskState.PENDING
        else:
            state = TaskState(raw_status.upper())

        t = cls(
            id=d["id"],
            title=d["title"],
            state=state,
            assigned_to=d.get("assigned_to"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            pr_number=d.get("pr_number"),
            branch=d.get("branch"),
            history=d.get("history", []),
        )
        return t


# ─────────────────────────────────────────────
# Valid state transitions
# ─────────────────────────────────────────────

TRANSITIONS: dict[TaskState, list[TaskState]] = {
    TaskState.PENDING:      [TaskState.IN_PROGRESS, TaskState.BLOCKED],
    TaskState.IN_PROGRESS:  [TaskState.COMPLETED, TaskState.BLOCKED, TaskState.PENDING],
    TaskState.BLOCKED:      [TaskState.PENDING, TaskState.IN_PROGRESS],
    TaskState.COMPLETED:    [],  # Terminal state — no going back
}


# ─────────────────────────────────────────────
# Task store (file-backed for Week 3)
# ─────────────────────────────────────────────

def load_tasks() -> dict[str, Task]:
    try:
        with open(TASKS_FILE) as f:
            raw = json.load(f)
        tasks_list = raw.get("tasks", [])
        return {t["id"]: Task.from_dict(t) for t in tasks_list}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_tasks(tasks: dict[str, Task]) -> None:
    tasks_list = [v.to_dict() for v in tasks.values()]
    output = {
        "total": len(tasks_list),
        "tasks": tasks_list
    }
    with open(TASKS_FILE, "w") as f:
        json.dump(output, f, indent=2)


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
    Examples:
      "feature/task-12"  → "task-12"
      "fix/task-7-login" → "task-7"
      "main"             → None
    """
    import re
    match = re.search(r"task-(\d+)", branch, re.IGNORECASE)
    if match:
        return f"task-{match.group(1)}"
    return None


def extract_task_id_from_pr_title(title: str) -> Optional[str]:
    """
    Extracts task ID from PR title.
    Examples:
      "Fixes task-12: Add normalizer"   → "task-12"
      "Closes task-7"                   → "task-7"
      "Random PR title"                 → None
    """
    import re
    match = re.search(r"task-(\d+)", title, re.IGNORECASE)
    if match:
        return f"task-{match.group(1)}"
    return None


def handle_push_event(event: dict) -> Optional[dict]:
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
        return task.to_dict()
    return None


def handle_pr_event(event: dict) -> Optional[dict]:
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
    task_id = (
        extract_task_id_from_pr_title(pr_title)
        or extract_task_id_from_branch(metadata.get("head_branch", ""))
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
            return task.to_dict()

    return None


def process_normalized_event(event: dict) -> Optional[dict]:
    """
    Main entry point — routes normalized events to the right handler.
    Call this from main.py when a new event arrives.
    """
    event_type = event.get("event_type", "")
    platform = event.get("platform", "")

    if platform != "github":
        return None  # State machine only cares about GitHub for now

    if event_type == "push":
        return handle_push_event(event)
    elif event_type == "pull_request":
        return handle_pr_event(event)

    return None

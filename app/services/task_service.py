import re
import sys
import asyncio
from datetime import datetime, timezone
from app.utils.websocket_manager import manager
from app.services.graph_service import sync_task_status_to_neo4j

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

    # Normalize incoming status to align with AI team canonical words
    canonical_status = new_status.lower()
    if canonical_status in ("pending", "todo", "upcoming"):
        canonical_status = "upcoming"
    elif canonical_status in ("stopped", "blocked"):
        canonical_status = "blocked"
    elif canonical_status in ("in progress", "in_progress"):
        canonical_status = "in_progress"
    elif canonical_status in ("completed", "done"):
        canonical_status = "completed"
    new_status = canonical_status

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

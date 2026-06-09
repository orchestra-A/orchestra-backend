import json
import os
from database import engine, SessionLocal, Base
from models_sql import TaskTable, EventTable

print("Creating database tables if they don't exist...")
Base.metadata.create_all(bind=engine)

def migrate():
    db = SessionLocal()
    
    # 1. Migrate Events
    events_path = "c:/Projects/coding/Orchestra/events.json"
    if os.path.exists(events_path):
        with open(events_path, "r") as f:
            events_data = json.load(f)
            for evt in events_data:
                # Check if exists
                if not db.query(EventTable).filter(EventTable.id == evt.get("id", evt.get("event_id"))).first():
                    # Handle varying id keys in older JSON
                    evt_id = evt.get("id", evt.get("event_id"))
                    if not evt_id:
                        continue
                    new_evt = EventTable(
                        id=evt_id,
                        platform=evt.get("platform", "unknown"),
                        event_type=evt.get("event_type", "unknown"),
                        actor=evt.get("actor", "unknown"),
                        timestamp=evt.get("timestamp", ""),
                        repo=evt.get("repo"),
                        channel=evt.get("channel"),
                        action_summary=evt.get("action_summary", ""),
                        raw_metadata=evt.get("raw_metadata", {})
                    )
                    db.add(new_evt)
        print("Migrated events.json")
    
    # 2. Migrate Tasks
    tasks_path = "c:/Projects/coding/Orchestra/tasks.json"
    if os.path.exists(tasks_path):
        with open(tasks_path, "r") as f:
            tasks_data = json.load(f)
            for task in tasks_data.get("tasks", []):
                if not db.query(TaskTable).filter(TaskTable.id == task["id"]).first():
                    new_task = TaskTable(
                        id=task["id"],
                        title=task.get("title", ""),
                        state=task.get("status", "PENDING").upper(),
                        assigned_to=task.get("assigned_to"),
                        project_id=task.get("project_id"),
                        order=task.get("order"),
                        created_at=task.get("created_at", ""),
                        updated_at=task.get("updated_at", ""),
                        pr_number=task.get("pr_number"),
                        branch=task.get("branch"),
                        depends_on=task.get("depends_on", []),
                        history=task.get("history", [])
                    )
                    db.add(new_task)
        print("Migrated tasks.json")
        
    db.commit()
    db.close()
    print("Migration complete!")

if __name__ == "__main__":
    migrate()

import json
import asyncio
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, Response
from database import SessionLocal
from models_sql import TaskTable
from sqlalchemy.orm.attributes import flag_modified

from app.utils.websocket_manager import manager
from app.schemas.task import TaskStatusUpdate
from app.services.task_service import update_task_status

router = APIRouter()


@router.get("/tasks")
async def get_tasks(project_id: Optional[str] = None):
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


@router.get("/tasks/{task_id}")
async def get_single_task(task_id: str):
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


@router.post("/tasks")
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
        import sys
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


@router.patch("/tasks/{task_id}/status")
async def manually_update_task_status(task_id: str, request: TaskStatusUpdate):
    new_status = request.status
    if not new_status:
        return {"error": "'status' field required"}

    success = update_task_status(task_id, new_status)
    if success:
        return {"status": "success", "message": f"Updated {task_id} to {new_status}"}
    return {"error": "Task not found"}


@router.post("/tasks/{task_id}/history")
async def add_task_history_update(task_id: str, request: Request):
    body = await request.json()
    message = body.get("message")
    actor = body.get("actor", "unknown")

    if not message:
        return {"error": "'message' field required"}

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

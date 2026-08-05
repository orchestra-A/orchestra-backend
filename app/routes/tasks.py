import json
import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
import httpx
from database import SessionLocal
from models_sql import TaskTable, UserTable
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
                    "status": t.status.lower() if t.status else "upcoming",
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
                    "deadline": t.deadline,
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
                "status": t.status.lower() if t.status else "upcoming",
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
                "deadline": t.deadline,
                "history": t.history,
            }
        return JSONResponse(status_code=404, content={"error": "Task not found"})
    finally:
        db.close()


@router.post("/tasks")
async def create_new_task(request: Request):
    body = await request.json()
    title = body.get("title", "Untitled")
    project_id = body.get("project_id")

    # Generate custom task ID format: P{project_id}-T{num}
    db = SessionLocal()
    try:
        if project_id:
            num = db.query(TaskTable).filter(TaskTable.project_id == project_id).count() + 1
            clean_proj = project_id.replace("proj_", "").upper()[:3]
            generated_id = f"P{clean_proj}-T{num:03d}"
        else:
            num = db.query(TaskTable).filter((TaskTable.project_id == None) | (TaskTable.project_id == "")).count() + 1
            generated_id = f"P000-T{num:03d}"
    except Exception as e:
        print(f"[API] Error counting tasks for ID generation: {e}")
        sys.stdout.flush()
        generated_id = f"P000-T001"
    finally:
        db.close()

    task_id = body.get("id") or generated_id

    track = body.get("track")
    description = body.get("description")
    priority = body.get("priority")
    updated_at = body.get("updated_at")
    platform = body.get("platform")
    assigned_to = body.get("assigned_to")
    deadline = body.get("deadline")
    depends_on = body.get("depends_on") or body.get("dependencies", [])
    
    created_at = datetime.now(timezone.utc).isoformat()
    if not updated_at:
        updated_at = created_at

    new_task = {
        "id": task_id,
        "title": title,
        "status": "upcoming",
        "track": track,
        "description": description,
        "priority": priority,
        "updated_at": updated_at,
        "platform": platform,
        "assigned_to": assigned_to,
        "project_id": project_id,
        "deadline": deadline,
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
                status="upcoming",
                track=track,
                description=description,
                priority=priority,
                updated_at=updated_at,
                platform=platform,
                assigned_to=assigned_to,
                project_id=project_id,
                deadline=deadline,
                created_at=created_at,
                depends_on=depends_on,
                history=[]
            )
            db.add(new_db_task)
            db.commit()
    except Exception as e:
        print(f"[API] Error saving new task to database: {e}")
        sys.stdout.flush()
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


def normalize_status_for_neo4j(status: str) -> str:
    mapping = {
        "pending": "upcoming",
        "todo": "upcoming", 
        "PENDING": "upcoming",
        "TODO": "upcoming",
        "stopped": "blocked",
        "STOPPED": "blocked",
        "in progress": "in_progress",
        "done": "completed",
        "DONE": "completed",
        "COMPLETED": "completed",
        "IN_PROGRESS": "in_progress",
        "BLOCKED": "blocked",
        "UPCOMING": "upcoming",
    }
    return mapping.get(status, status.lower())


@router.patch("/tasks/{task_id}/status")
async def manually_update_task_status(task_id: str, request: TaskStatusUpdate):
    new_status = request.status
    if not new_status:
        return {"error": "'status' field required"}

    normalized_status = normalize_status_for_neo4j(new_status)
    success = update_task_status(task_id, normalized_status)
    if success:
        return {"status": "success", "message": f"Updated {task_id} to {normalized_status}"}
    return JSONResponse(status_code=404, content={"error": "Task not found"})


@router.patch("/tasks/{task_id}/assign")
async def manually_reassign_task(task_id: str, request: Request):
    body = await request.json()
    new_assignee = body.get("assigned_to")
    if new_assignee is None:
        return JSONResponse(status_code=400, content={"error": "'assigned_to' is required"})

    db = SessionLocal()
    try:
        task = db.query(TaskTable).filter(TaskTable.id == task_id).first()
        if not task:
            return JSONResponse(status_code=404, content={"error": "Task not found"})

        now_iso = datetime.now(timezone.utc).isoformat()
        task.assigned_to = new_assignee
        task.updated_at = now_iso

        if not task.history:
            task.history = []
        task.history.append({
            "type": "REASSIGNMENT",
            "to": new_assignee,
            "actor": "manual",
            "timestamp": now_iso
        })
        flag_modified(task, "history")
        db.commit()

        print(f"[REASSIGN] Task {task_id} manually reassigned to {new_assignee}")
        sys.stdout.flush()

        task_dict = {
            "id": task.id,
            "title": task.title,
            "status": task.status.lower() if task.status else "upcoming",
            "track": task.track,
            "description": task.description,
            "priority": task.priority,
            "updated_at": task.updated_at,
            "platform": task.platform,
            "assigned_to": task.assigned_to,
            "project_id": task.project_id,
            "order": task.order,
            "depends_on": task.depends_on,
            "created_at": task.created_at,
            "pr_number": task.pr_number,
            "branch": task.branch,
            "deadline": task.deadline,
            "history": task.history,
        }

        # Broadcast update
        try:
            asyncio.create_task(
                manager.broadcast({
                    "type": "task_updated",
                    "task_id": task_id,
                    "task": task_dict,
                    "timestamp": now_iso
                })
            )
        except Exception:
            pass

        return task_dict
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        db.close()


@router.post("/tasks/{task_id}/ai-assign")
async def ai_reassign_task(task_id: str, request: Request):
    body = await request.json() or {}
    reason = body.get("reason", "")

    db = SessionLocal()
    try:
        task = db.query(TaskTable).filter(TaskTable.id == task_id).first()
        if not task:
            return JSONResponse(status_code=404, content={"error": "Task not found"})

        users = db.query(UserTable).all()
        team_members = [{"id": u.id, "skills": u.skills or []} for u in users]

        task_dict = {
            "id": task.id,
            "title": task.title,
            "status": task.status.lower() if task.status else "upcoming",
            "track": task.track,
            "description": task.description,
            "priority": task.priority,
            "updated_at": task.updated_at,
            "platform": task.platform,
            "assigned_to": task.assigned_to,
            "project_id": task.project_id,
            "order": task.order,
            "depends_on": task.depends_on,
            "created_at": task.created_at,
            "pr_number": task.pr_number,
            "branch": task.branch,
            "deadline": task.deadline,
            "history": task.history,
        }
    finally:
        db.close()

    ai_service_url = os.getenv("AI_SERVICE_URL", "https://orchestra-ai-36zm.onrender.com")
    internal_api_key = os.getenv("INTERNAL_API_KEY", "")

    url = f"{ai_service_url}/tasks/{task_id}/ai-assign"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"x-api-key": internal_api_key},
                json={
                    "task": task_dict,
                    "team_members": team_members,
                    "reason": reason
                },
                timeout=30.0
            )

        if response.status_code != 200:
            return JSONResponse(status_code=503, content={"error": "AI service unavailable"})

        res_data = response.json()
        ai_suggested = res_data.get("suggested_assignee") or res_data.get("assigned_to") or res_data.get("new_assignee")

        if not ai_suggested:
            return JSONResponse(status_code=500, content={"error": "AI service did not return suggested assignee"})

        db = SessionLocal()
        try:
            task = db.query(TaskTable).filter(TaskTable.id == task_id).first()
            old_assignee = task.assigned_to
            now_iso = datetime.now(timezone.utc).isoformat()
            task.assigned_to = ai_suggested
            task.updated_at = now_iso

            if not task.history:
                task.history = []
            task.history.append({
                "type": "REASSIGNMENT",
                "to": ai_suggested,
                "actor": "ai",
                "timestamp": now_iso
            })
            flag_modified(task, "history")
            db.commit()

            print(f"[AI REASSIGN] Task {task_id} AI suggested {ai_suggested}")
            sys.stdout.flush()

            # Broadcast update
            try:
                asyncio.create_task(
                    manager.broadcast({
                        "type": "task_updated",
                        "task_id": task_id,
                        "task": {
                            "id": task.id,
                            "assigned_to": task.assigned_to,
                            "updated_at": task.updated_at,
                            "history": task.history
                        },
                        "timestamp": now_iso
                    })
                )
            except Exception:
                pass

            return {
                "task_id": task_id,
                "previous_assignee": old_assignee,
                "new_assignee": ai_suggested,
                "reason": reason,
                "ai_response": res_data
            }
        finally:
            db.close()

    except Exception as e:
        print(f"[AI REASSIGN] Error: {e}")
        sys.stdout.flush()
        return JSONResponse(status_code=503, content={"error": "AI service unavailable"})


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

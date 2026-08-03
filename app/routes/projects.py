import json
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, Response
from database import SessionLocal
from models_sql import ProjectTable, TaskTable
from app.services.ai_service import delete_ai_project
from app.services.github_service import sync_project_webhooks

router = APIRouter()


@router.post("/projects")
async def create_project(request: Request, user_id: Optional[str] = None):
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
    blueprint_summary = body.get("blueprint_summary")
    created_by_body = body.get("created_by")
    tracked_repos = body.get("tracked_repos", [])
    tracked_channels = body.get("tracked_channels", [])
    is_archived = body.get("is_archived", False)
    github_repo_url = body.get("github_repo_url")

    created_at = datetime.now(timezone.utc).isoformat()
    updated_at = created_at
    project_id = body.get("id") or f"proj_{uuid.uuid4().hex[:8]}"
    
    final_created_by = created_by_body or user_id

    db = SessionLocal()
    try:
        new_project = ProjectTable(
            id=project_id,
            name=name,
            description=description,
            created_by=final_created_by,
            tech_stack=tech_stack,
            members=members,
            created_at=created_at,
            updated_at=updated_at,
            blueprint_summary=blueprint_summary,
            tracked_repos=tracked_repos,
            tracked_channels=tracked_channels,
            is_archived=is_archived,
            github_repo_url=github_repo_url,
        )
        db.add(new_project)
        db.commit()
        db.refresh(new_project)
        print(f"[PROJECT] Successfully created project {new_project.id}")
        
        project_dict = {
            "id": new_project.id,
            "name": name,
            "description": description,
            "created_by": final_created_by,
            "tech_stack": tech_stack,
            "members": members,
            "created_at": created_at,
            "updated_at": updated_at,
            "blueprint_summary": blueprint_summary,
            "tracked_repos": tracked_repos,
            "tracked_channels": tracked_channels,
            "is_archived": is_archived,
            "github_repo_url": github_repo_url,
        }
        return Response(content=json.dumps(project_dict, indent=4), media_type="application/json")
    except Exception as e:
        print(f"[PROJECT] Error saving new project to database: {e}")
        db.rollback()
        return Response(content=json.dumps({"error": str(e)}), media_type="application/json", status_code=500)
    finally:
        db.close()


@router.get("/projects")
async def get_projects(user_id: Optional[str] = None):
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
                "blueprint_summary": p.blueprint_summary,
                "tracked_repos": p.tracked_repos,
                "tracked_channels": p.tracked_channels,
                "is_archived": p.is_archived,
                "github_repo_url": p.github_repo_url,
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


@router.get("/projects/{project_id}")
async def get_project_by_id(project_id: str):
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
            "blueprint_summary": p.blueprint_summary,
            "tracked_repos": p.tracked_repos,
            "tracked_channels": p.tracked_channels,
            "is_archived": p.is_archived,
            "github_repo_url": p.github_repo_url,
        }
        return Response(content=json.dumps(project_dict, indent=4), media_type="application/json")
    except Exception as e:
        print(f"[PROJECT] Error querying project {project_id}: {e}")
        return Response(content=json.dumps({"error": str(e)}), media_type="application/json", status_code=500)
    finally:
        db.close()


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, request: Request):
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
        
        if p.is_archived and body.get("is_archived") is not False:
            print(f"[PROJECT] Project {project_id} is archived, updates are blocked")
            return Response(content='{"error": "Project is archived and cannot be edited"}', media_type="application/json", status_code=400)
            
        if "name" in body:
            p.name = body["name"]
        if "description" in body:
            p.description = body["description"]
        if "tech_stack" in body:
            p.tech_stack = body["tech_stack"]
        if "members" in body:
            p.members = body["members"]
        if "blueprint_summary" in body:
            p.blueprint_summary = body["blueprint_summary"]
        if "tracked_repos" in body:
            p.tracked_repos = body["tracked_repos"]
            import asyncio
            asyncio.create_task(sync_project_webhooks(project_id, body["tracked_repos"], p.created_by))
            
        if "tracked_channels" in body:
            p.tracked_channels = body["tracked_channels"]
        if "is_archived" in body:
            p.is_archived = body["is_archived"]
        if "github_repo_url" in body:
            p.github_repo_url = body["github_repo_url"]
            
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
            "blueprint_summary": p.blueprint_summary,
            "tracked_repos": p.tracked_repos,
            "tracked_channels": p.tracked_channels,
            "is_archived": p.is_archived,
            "github_repo_url": p.github_repo_url,
        }
        return Response(content=json.dumps(project_dict, indent=4), media_type="application/json")
    except Exception as e:
        print(f"[PROJECT] Error updating project {project_id}: {e}")
        db.rollback()
        return Response(content=json.dumps({"error": str(e)}), media_type="application/json", status_code=500)
    finally:
        db.close()


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    print(f"[PROJECT] Received request to delete project {project_id}")
    db = SessionLocal()
    try:
        p = db.query(ProjectTable).filter(ProjectTable.id == project_id).first()
        if not p:
            print(f"[PROJECT] Project {project_id} not found for deletion")
            return Response(content='{"error": "Project not found"}', media_type="application/json", status_code=404)
            
        # Cascading delete of tasks
        db.query(TaskTable).filter(TaskTable.project_id == project_id).delete()
        print(f"[PROJECT] Deleted associated tasks for project {project_id}")
        
        # Delete project
        db.delete(p)
        db.commit()
        print(f"[PROJECT] Successfully deleted project {project_id}")
        
        # Clean up AI server asynchronously
        import asyncio
        asyncio.create_task(delete_ai_project(project_id))
        
        return Response(content='{"success": true}', media_type="application/json")
    except Exception as e:
        print(f"[PROJECT] Error deleting project {project_id}: {e}")
        db.rollback()
        return Response(content=json.dumps({"error": str(e)}), media_type="application/json", status_code=500)
    finally:
        db.close()

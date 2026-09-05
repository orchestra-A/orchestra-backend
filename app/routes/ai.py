import sys
import os
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
import httpx

from app.schemas.ai import BlueprintRequest, CloverRequest
from app.services.ai_service import get_team_data, post_blueprint_data_stream, post_clover_data_stream
from database import SessionLocal
from models_sql import ProjectTable

router = APIRouter()


@router.get("/team")
async def get_team():
    internal_api_key = os.getenv("INTERNAL_API_KEY", "")
    if not internal_api_key:
        print("[TEAM] ❌ Missing INTERNAL_API_KEY")
        sys.stdout.flush()
        return JSONResponse(status_code=500, content={"error": "AI service not configured"})
        
    print("[TEAM] 🔄 Forwarding team request to AI service")
    sys.stdout.flush()
    
    try:
        response = await get_team_data()
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


@router.post("/blueprint")
async def proxy_blueprint(payload: BlueprintRequest, request: Request):
    internal_api_key = os.getenv("INTERNAL_API_KEY", "")
    if not internal_api_key:
        print("[BLUEPRINT] ❌ Missing INTERNAL_API_KEY")
        sys.stdout.flush()
        return JSONResponse(status_code=500, content={"error": "AI service not configured"})
        
    # Extract tracking fields
    tracked_repos = payload.tracked_repos
    tracked_channels = payload.tracked_channels
    
    body = payload.model_dump()
    print("[BLUEPRINT] 🔄 Forwarding blueprint request to AI service as a stream")
    sys.stdout.flush()
    
    async def event_generator():
        try:
            async for line in post_blueprint_data_stream(body):
                if not line.strip():
                    yield f"{line}\n"
                    continue

                if line.startswith("data: "):
                    content = line[6:].strip()
                    if content:
                        import json
                        try:
                            data = json.loads(content)
                            if data.get("done") and "project" in data:
                                project_id = data["project"].get("id")
                                if project_id and (tracked_repos or tracked_channels):
                                    db = SessionLocal()
                                    try:
                                        p = db.query(ProjectTable).filter(ProjectTable.id == project_id).first()
                                        if p:
                                            if tracked_repos:
                                                p.tracked_repos = tracked_repos
                                                import asyncio
                                                from app.services.github_service import sync_project_webhooks
                                                asyncio.create_task(sync_project_webhooks(project_id, tracked_repos, p.created_by))
                                            if tracked_channels:
                                                p.tracked_channels = tracked_channels
                                            db.commit()
                                            data["project"]["tracked_repos"] = tracked_repos
                                            data["project"]["tracked_channels"] = tracked_channels
                                            print(f"[BLUEPRINT] ✅ Injected tracking fields for project {project_id}")
                                    except Exception as e:
                                        print(f"[BLUEPRINT] ❌ Error injecting tracking fields: {e}")
                                    finally:
                                        db.close()
                                yield f"data: {json.dumps(data)}\n"
                                continue
                        except json.JSONDecodeError:
                            pass
                
                yield f"{line}\n"
                
        except Exception as e:
            print(f"[BLUEPRINT] ❌ Stream error: {e}")
            import json
            yield f"data: {json.dumps({'error': f'Backend streaming error: {str(e)}', 'status': 500})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/clover")
async def proxy_clover(payload: CloverRequest, request: Request):
    internal_api_key = os.getenv("INTERNAL_API_KEY", "")
    if not internal_api_key:
        print("[CLOVER] ❌ Missing INTERNAL_API_KEY")
        sys.stdout.flush()
        return JSONResponse(status_code=500, content={"error": "AI service not configured"})
        
    if payload.project_id:
        db = SessionLocal()
        try:
            p = db.query(ProjectTable).filter(ProjectTable.id == payload.project_id).first()
            if p:
                context_str = f"[SYSTEM CONTEXT] User is viewing project '{p.name}'."
                if p.description:
                    context_str += f" Description: {p.description}."
                if payload.page:
                    context_str += f" Currently on page: {payload.page}."
                
                # Prepend context to the question
                payload.question = f"{context_str}\n\nUser Question: {payload.question}"
                print(f"[CLOVER] ✅ Injected project context for {payload.project_id}")
        except Exception as e:
            print(f"[CLOVER] ❌ Error injecting project context: {e}")
        finally:
            db.close()
            
    body = payload.model_dump()
    print("[CLOVER] 🔄 Forwarding clover request to AI service as a stream")
    sys.stdout.flush()
    
    return StreamingResponse(
        post_clover_data_stream(body),
        media_type="text/event-stream"
    )

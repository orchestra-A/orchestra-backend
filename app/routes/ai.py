import sys
import os
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
import httpx

from app.schemas.ai import BlueprintRequest, CloverRequest
from app.services.ai_service import get_team_data, post_blueprint_data, post_clover_data_stream

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
        
    body = payload.model_dump()
    print("[BLUEPRINT] 🔄 Forwarding blueprint request to AI service")
    sys.stdout.flush()
    
    try:
        response = await post_blueprint_data(body)
        if response.status_code != 200:
            print(f"[BLUEPRINT] ❌ AI service returned non-200: {response.status_code}")
            sys.stdout.flush()
            return JSONResponse(status_code=response.status_code, content={"error": "AI service error", "detail": response.text})
            
        print("[BLUEPRINT] ✅ Blueprint data received, returning to frontend")
        sys.stdout.flush()
        return JSONResponse(status_code=200, content=response.json())
        
    except httpx.RequestError as e:
        print(f"[BLUEPRINT] ❌ Network error or timeout: {str(e)}")
        sys.stdout.flush()
        return JSONResponse(status_code=504, content={"error": "AI service timeout or unreachable"})


@router.post("/clover")
async def proxy_clover(payload: CloverRequest, request: Request):
    internal_api_key = os.getenv("INTERNAL_API_KEY", "")
    if not internal_api_key:
        print("[CLOVER] ❌ Missing INTERNAL_API_KEY")
        sys.stdout.flush()
        return JSONResponse(status_code=500, content={"error": "AI service not configured"})
        
    body = payload.model_dump()
    print("[CLOVER] 🔄 Forwarding clover request to AI service as a stream")
    sys.stdout.flush()
    
    return StreamingResponse(
        post_clover_data_stream(body),
        media_type="text/event-stream"
    )

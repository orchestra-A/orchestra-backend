import os
import requests
from fastapi import APIRouter

router = APIRouter()


@router.get("/graph")
async def get_graph():
    try:
        ai_url = os.getenv("GRAPH_API_URL", "https://orchestra-ai-36zm.onrender.com")
        api_key = os.getenv("INTERNAL_API_KEY", "")
        response = requests.get(
            f"{ai_url}/graph", 
            headers={"x-api-key": api_key},
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"error": str(exc), "nodes": [], "edges": []}

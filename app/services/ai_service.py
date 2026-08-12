import sys
import httpx
from app.core.config import AI_SERVICE_URL, INTERNAL_API_KEY

async def get_team_data():
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AI_SERVICE_URL}/team",
            headers={"x-api-key": INTERNAL_API_KEY},
            timeout=30.0
        )
    return response


async def post_blueprint_data(body: dict):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AI_SERVICE_URL}/blueprint",
            json=body,
            headers={"x-api-key": INTERNAL_API_KEY},
            timeout=120.0
        )
    return response


async def post_clover_data_stream(body: dict):
    client = httpx.AsyncClient()
    try:
        async with client.stream(
            "POST",
            f"{AI_SERVICE_URL}/clover",
            json=body,
            headers={"x-api-key": INTERNAL_API_KEY},
            timeout=120.0
        ) as response:
            if response.status_code != 200:
                error_body = await response.aread()
                yield error_body
                return
            async for chunk in response.aiter_raw():
                yield chunk
    finally:
        await client.aclose()


async def delete_ai_project(project_id: str):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{AI_SERVICE_URL}/projects/{project_id}",
                headers={"x-api-key": INTERNAL_API_KEY},
                timeout=30.0
            )
            print(f"[AI SERVICE] Cleaned up project {project_id} in Neo4j, status: {response.status_code}")
            sys.stdout.flush()
    except Exception as e:
        print(f"[AI SERVICE] Failed to clean up project {project_id} in Neo4j: {e}")
        sys.stdout.flush()

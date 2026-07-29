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


async def post_clover_data(body: dict):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AI_SERVICE_URL}/clover",
            json=body,
            headers={"x-api-key": INTERNAL_API_KEY},
            timeout=120.0
        )
    return response

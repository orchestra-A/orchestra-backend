import json
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Response
from database import SessionLocal
from models_sql import EventTable
from app.services.event_service import log_webhook_payload, process_and_save

router = APIRouter()


@router.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()
    log_webhook_payload("GENERIC", payload)
    return {"received": True, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/test/simulate-webhook")
async def simulate_webhook(request: Request):
    payload = await request.json()
    log_webhook_payload("SIMULATED", payload)
    return {
        "simulated": True,
        "payload_received": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/webhook/figma")
async def receive_figma(request: Request):
    payload = await request.json()
    log_webhook_payload("FIGMA", payload)
    normalized = process_and_save("figma", "figma", payload)
    return {
        "received": True,
        "platform": "figma",
        "normalized_summary": normalized.action_summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/events")
async def get_events():
    db = SessionLocal()
    try:
        db_events = db.query(EventTable).all()
        events = []
        for e in db_events:
            events.append(
                {
                    "id": e.id,
                    "platform": e.platform,
                    "event_type": e.event_type,
                    "actor": e.actor,
                    "timestamp": e.timestamp,
                    "repo": e.repo,
                    "channel": e.channel,
                    "action_summary": e.action_summary,
                    "raw_metadata": e.raw_metadata,
                }
            )
        result = {"total": len(events), "events": events}
        formatted = json.dumps(result, indent=4)
        return Response(content=formatted, media_type="application/json")
    finally:
        db.close()

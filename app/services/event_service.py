import json
import sys
from datetime import datetime, timezone
from models import NormalizedEvent
from normalizer import normalize_event

def log_webhook_payload(platform: str, payload: dict) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    separator = "=" * 60
    print(separator)
    print(f"Incoming webhook received!")
    print(f"Platform  : {platform}")
    print(f"Timestamp : {timestamp}")
    print("Payload:")
    print(json.dumps(payload, indent=2))
    print(separator)
    sys.stdout.flush()


def save_normalized_event(event: NormalizedEvent) -> None:
    from database import SessionLocal
    from models_sql import EventTable

    db = SessionLocal()
    try:
        new_event = EventTable(
            id=event.id,
            platform=event.platform,
            event_type=event.event_type,
            actor=event.actor,
            timestamp=event.timestamp,
            repo=event.repo,
            channel=event.channel,
            action_summary=event.action_summary,
            raw_metadata=event.raw_metadata,
        )
        db.add(new_event)
        db.commit()
        print(f"[SAVED] Normalized event saved to database")
    except Exception as e:
        print(f"[SAVED] Error saving event to database: {e}")
        db.rollback()
    finally:
        db.close()
    sys.stdout.flush()


def process_and_save(platform: str, event_type: str, payload: dict) -> NormalizedEvent:
    normalized = normalize_event(event_type, payload)
    print(f"[NORMALIZED] {normalized.action_summary}")
    sys.stdout.flush()
    save_normalized_event(normalized)
    return normalized

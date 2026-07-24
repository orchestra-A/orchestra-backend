import sys
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.utils.websocket_manager import manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Add this browser to the connected list
    await manager.connect(websocket)

    # Send a welcome message so Member 5 knows connection succeeded
    await websocket.send_json(
        {
            "type": "connection_established",
            "message": "Connected to Timeline Orchestra live updates",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    try:
        # Keep the connection alive forever
        # Wait for any message from the browser
        # Browser can send "ping" to check if connection is still alive
        while True:
            data = await websocket.receive_text()

            if data == "ping":
                # Browser is checking if we're still here — respond
                await websocket.send_json(
                    {
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                print(f"[WEBSOCKET] Ping received — pong sent")
                sys.stdout.flush()

    except WebSocketDisconnect:
        # Browser closed the tab — remove from list
        manager.disconnect(websocket)

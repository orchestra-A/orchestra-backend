from typing import List
from fastapi import WebSocket
import sys

class ConnectionManager:
    def __init__(self):
        # List of all currently connected browsers
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        # Accept the connection request from browser
        # Add it to our active list
        await websocket.accept()
        self.active_connections.append(websocket)
        print(
            f"[WEBSOCKET] ✅ New browser connected. Total connected: {len(self.active_connections)}"
        )
        sys.stdout.flush()

    def disconnect(self, websocket: WebSocket):
        # Browser closed the tab — remove from list
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(
            f"[WEBSOCKET] ❌ Browser disconnected. Total connected: {len(self.active_connections)}"
        )
        sys.stdout.flush()

    async def broadcast(self, message: dict):
        # Send message to every connected browser simultaneously
        # If any connection is broken, remove it silently
        disconnected = []

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                # Connection broke — mark for removal
                disconnected.append(connection)

        # Clean up broken connections
        for connection in disconnected:
            self.active_connections.remove(connection)

        print(
            f"[WEBSOCKET] 📡 Broadcast sent to {len(self.active_connections)} browser(s)"
        )
        print(f"[WEBSOCKET] Message: {message}")
        sys.stdout.flush()


# Create one single manager that lives as long as the server runs
# Every route uses this same manager
manager = ConnectionManager()

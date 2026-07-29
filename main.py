# bootstrap wrapper for orchestra-backend
from app.main import app
from app.utils.websocket_manager import manager
from app.services.graph_service import sync_task_status_to_neo4j

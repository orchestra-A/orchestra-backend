from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class BlueprintRequest(BaseModel):
    name: str
    description: str
    tech_stack: List[str]
    created_by: str
    members: List[str] = []
    tracked_repos: List[str] = []
    tracked_channels: List[str] = []

class AddMemberRequest(BaseModel):
    username: Optional[str] = None
    user_id: Optional[str] = None
    skills: List[str] = []
    project_id: Optional[str] = None

class RemoveMemberRequest(BaseModel):
    project_id: str
    user_id: str

class AddTaskRequest(BaseModel):
    project_id: str
    title: str
    description: str = ""
    track: str
    assigned_to: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "project_id": "proj_12345678",
                    "title": "Set up database schema",
                    "description": "Define the SQL models for users and tasks.",
                    "track": "backend",
                    "assigned_to": "usr_789012"
                }
            ]
        }
    }

class CloverRequest(BaseModel):
    question: str
    user_id: str
    conversation_history: List[Dict[str, Any]] = []
    project_id: Optional[str] = None
    page: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "question": "How do I add a new endpoint?",
                    "user_id": "usr_123456",
                    "conversation_history": [
                        {"role": "user", "content": "Hi"},
                        {"role": "assistant", "content": "Hello!"}
                    ],
                    "project_id": "proj_abc123"
                }
            ]
        }
    }

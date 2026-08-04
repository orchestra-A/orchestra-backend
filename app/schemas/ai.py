from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class BlueprintRequest(BaseModel):
    name: str
    description: str
    tech_stack: List[str]
    created_by: str
    members: List[str] = []

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Orchestra Dashboard",
                    "description": "A frontend dashboard for managing projects.",
                    "tech_stack": ["React", "TypeScript", "Tailwind CSS"],
                    "created_by": "usr_789012",
                    "members": ["usr_123456"]
                }
            ]
        }
    }

class CloverRequest(BaseModel):
    question: str
    user_id: str
    conversation_history: List[Dict[str, Any]] = []
    project_id: Optional[str] = None

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

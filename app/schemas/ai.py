from pydantic import BaseModel
from typing import List, Dict, Any

class BlueprintRequest(BaseModel):
    name: str
    description: str
    tech_stack: List[str]
    members: List[str] = []

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Orchestra Dashboard",
                    "description": "A frontend dashboard for managing projects.",
                    "tech_stack": ["React", "TypeScript", "Tailwind CSS"],
                    "members": ["usr_123456"]
                }
            ]
        }
    }

class CloverRequest(BaseModel):
    question: str
    conversation_history: List[Dict[str, Any]] = []

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "question": "How do I add a new endpoint?",
                    "conversation_history": [
                        {"role": "user", "content": "Hi"},
                        {"role": "assistant", "content": "Hello!"}
                    ]
                }
            ]
        }
    }

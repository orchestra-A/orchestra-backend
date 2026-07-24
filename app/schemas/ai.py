from pydantic import BaseModel
from typing import List, Dict, Any

class BlueprintRequest(BaseModel):
    name: str
    description: str
    tech_stack: List[str]
    members: List[str] = []

class CloverRequest(BaseModel):
    question: str
    conversation_history: List[Dict[str, Any]] = []

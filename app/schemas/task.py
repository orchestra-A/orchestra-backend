from typing import Optional
from pydantic import BaseModel

class TaskStatusUpdate(BaseModel):
    status: str

class TaskAssignRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assigned_to: Optional[str] = None
    track: Optional[str] = None


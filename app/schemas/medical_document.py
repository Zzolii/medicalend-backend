# Path: backend/app/schemas/medical_document.py

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class MedicalDocumentOut(BaseModel):
    id: int
    episode_id: int
    appointment_id: Optional[int] = None
    uploaded_by_user_id: Optional[int] = None
    file_name: str
    stored_name: str
    file_url: str
    mime_type: str
    created_at: datetime

    class Config:
        from_attributes = True
# Path: backend/app/schemas/care_note.py

from datetime import datetime

from pydantic import BaseModel


class CareNoteCreate(BaseModel):
    text: str


class CareNoteOut(BaseModel):
    id: int
    episode_id: int
    author_user_id: int
    text: str
    created_at: datetime

    class Config:
        from_attributes = True

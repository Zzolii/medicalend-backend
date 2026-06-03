# Path: backend/app/schemas/care_episode.py

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class CareEpisodeBase(BaseModel):
    patient_id: int
    title: str
    status: str = "open"

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Titlul episodului este obligatoriu.")
        return cleaned


class CareEpisodeCreate(BaseModel):
    patient_id: int
    title: str

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Titlul episodului este obligatoriu.")
        return cleaned


class CareEpisodeUpdate(BaseModel):
    patient_id: Optional[int] = None
    title: Optional[str] = None
    status: Optional[str] = None

    @field_validator("title")
    @classmethod
    def validate_optional_title(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Titlul episodului nu poate fi gol.")
        return cleaned


class CareEpisodeOut(CareEpisodeBase):
    id: int
    owner_provider_id: int
    created_at: datetime

    class Config:
        from_attributes = True
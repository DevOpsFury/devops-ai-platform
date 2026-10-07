from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeCreate(BaseModel):
    id: UUID | None = None
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=100_000)
    source: str = Field(default="manual", max_length=500)


class KnowledgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    content: str
    source: str
    created_at: datetime
    updated_at: datetime


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=20_000)
    environment: str = Field(default="unknown", max_length=80)


class ApprovalCreate(BaseModel):
    incident_id: str | None = None
    requested_action: str = Field(min_length=1, max_length=10_000)
    risk_level: Literal["low", "medium", "high", "critical"]
    requested_by: str = Field(min_length=1, max_length=120)


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    decided_by: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=4_000)

"""Conversation Hub Pydantic models."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ConversationMessage(BaseModel):
    role: str
    content: str
    timestamp: float


class Conversation(BaseModel):
    id: str
    title: str
    model: str
    created_at: float
    updated_at: float
    message_count: int = 0
    messages: List[ConversationMessage] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    id: str
    title: str
    model: str
    created_at: float
    updated_at: float
    message_count: int = 0


class ConversationListResponse(BaseModel):
    conversations: List[ConversationSummary]


class ConversationCreateRequest(BaseModel):
    title: Optional[str] = None
    model: str
    id: Optional[str] = None


class ConversationEnsureRequest(BaseModel):
    id: str
    model: str
    title: Optional[str] = None


class ConversationUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1)


class AppendMessageRequest(BaseModel):
    role: str
    content: str

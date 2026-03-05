"""Pydantic request/response models."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None  # "google" | "ollama" | "azure"


class ChatResponse(BaseModel):
    content: str
    provider: str
    session_id: str


class ModelInfo(BaseModel):
    id: str
    provider: str


class ModelsResponse(BaseModel):
    models: List[ModelInfo]
    default: Optional[str] = None
    default_provider: Optional[str] = None


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
    model: Optional[str] = None


class ConversationUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1)


class SettingsRequest(BaseModel):
    # Google
    google_api_key: Optional[str] = None
    # Azure
    azure_api_key: Optional[str] = None
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    azure_api_version: Optional[str] = None
    # Ollama
    ollama_host: Optional[str] = None


class SettingsResponse(BaseModel):
    status: str
    message: str


class ClusterSettingsRequest(BaseModel):
    kube_server: str = ""


class ClusterSettingsResponse(BaseModel):
    kube_server: str

"""Pydantic request models."""
from __future__ import annotations

from pydantic import BaseModel


class GithubTokenRequest(BaseModel):
    token: str


class ScrapeRequest(BaseModel):
    repos: list[str] = []
    websites: list[str] = []


class TrainRequest(BaseModel):
    model: str = "qwen2.5:7b-instruct"
    adapter_name: str = ""
    gpu_node_pool: str = ""

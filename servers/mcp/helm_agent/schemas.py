"""Helm agent request models."""
from __future__ import annotations

from pydantic import BaseModel


class RepoAddRequest(BaseModel):
    repo_name: str
    repo_url: str


class UpgradeInstallRequest(BaseModel):
    release_name: str
    chart: str
    version: str | None = None
    namespace: str = "default"
    create_namespace: bool = False
    set_values: dict[str, str] = {}
    set_file_values: dict[str, str] = {}


class ConfigureRequest(BaseModel):
    release_name: str
    chart: str
    namespace: str = "default"
    set_values: dict[str, str] = {}


class UninstallRequest(BaseModel):
    release_name: str
    namespace: str = "default"


class KubectlApplyRequest(BaseModel):
    url: str

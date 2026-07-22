"""Pydantic request/response models."""
from datetime import datetime

from pydantic import BaseModel, EmailStr, ConfigDict


# ── Auth ──
class RegisterIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr


# ── Résumés ──
class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: str
    filename: str
    keywords: list
    keyword_status: str


class KeywordsUpdate(BaseModel):
    keywords: list[str]


# ── Applications ──
class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    url: str
    title: str
    company: str
    role: str
    stipend: str
    platform: str
    status: str
    applied_at: datetime


class StatusUpdate(BaseModel):
    status: str


# ── Apply profile (per-application details platforms don't store) ──
class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    location: str = ""
    course_duration: str = ""


class ProfileIn(BaseModel):
    location: str = ""
    course_duration: str = ""


# ── Jobs (agent queue) ──
class JobCreate(BaseModel):
    kind: str            # search | apply | sync
    payload: dict = {}


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    status: str
    payload: dict
    result: dict
    error: str


class JobResult(BaseModel):
    status: str          # done | failed
    result: dict = {}
    error: str = ""


# ── Agent pairing / status ──
class PairTokenOut(BaseModel):
    token: str
    expires_in_min: int
    command: str              # ready-to-run one-liner (terminal fallback, bash)
    server_url: str = ""      # so the UI can build per-OS commands
    download_mac: str = ""    # packaged macOS app URL (empty if not published yet)
    download_windows: str = ""  # packaged Windows app URL (empty if not published yet)


class PairIn(BaseModel):
    token: str
    device_name: str = "my computer"


class PairOut(BaseModel):
    agent_key: str
    device_id: int


class AgentStatusOut(BaseModel):
    connected: bool
    device_name: str | None = None
    last_seen: datetime | None = None
    paused: bool = False


class AgentControlOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    paused: bool = False
    stop_seq: int = 0

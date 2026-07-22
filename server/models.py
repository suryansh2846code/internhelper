"""Database models — per-user résumés, applications, and the agent job queue."""
from datetime import datetime, timezone

from sqlalchemy import String, Text, ForeignKey, DateTime, JSON, LargeBinary, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.db import Base


def _now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    resumes: Mapped[list["Resume"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    devices: Mapped[list["AgentDevice"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(120))
    filename: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # file bytes (stateless)
    text: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    keyword_status: Mapped[str] = mapped_column(String(20), default="ready")  # extracting|ready|error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="resumes")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    url: Mapped[str] = mapped_column(String(700))
    title: Mapped[str] = mapped_column(String(400), default="")
    company: Mapped[str] = mapped_column(String(300), default="")
    role: Mapped[str] = mapped_column(String(120), default="")
    stipend: Mapped[str] = mapped_column(String(120), default="")
    platform: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(30), default="applied")
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="applications")


class AgentProfile(Base):
    """Per-user applicant details that some platforms (Unstop) ask for on every
    application and don't pull from the account profile — the user's city and
    course duration. One row per user; injected into apply jobs."""
    __tablename__ = "agent_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    location: Mapped[str] = mapped_column(String(120), default="")
    course_duration: Mapped[str] = mapped_column(String(40), default="")

    user: Mapped[User] = relationship()


class AgentDevice(Base):
    """A user's paired local agent (their computer). Heartbeats mark it online."""
    __tablename__ = "agent_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="my computer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="devices")


class Job(Base):
    """Work queued for a user's local agent (search / apply / sync)."""
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # search | apply | sync
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued|running|done|failed
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="jobs")

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, Float, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(50), primary_key=True, index=True)
    value = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Team(Base):
    __tablename__ = "teams"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    token_prefix = Column(String(32), nullable=False)  # Display e.g. "tg_9a8b..."
    test_quota_limit = Column(Integer, default=5, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    dispatches = relationship("ImageDispatch", back_populates="team", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="team", cascade="all, delete-orphan")


class ImageDispatch(Base):
    __tablename__ = "image_dispatches"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id = Column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    img_id = Column(String(128), nullable=False, index=True)
    file_name = Column(String(255), nullable=False)
    mode = Column(String(20), nullable=False, index=True)  # "train" or "test"
    dispatched_at = Column(DateTime(timezone=True), default=utc_now)
    finished_send_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    team = relationship("Team", back_populates="dispatches")
    submissions = relationship("Submission", back_populates="dispatch")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    dispatch_id = Column(String(36), ForeignKey("image_dispatches.id", ondelete="SET NULL"), nullable=True, index=True)
    team_id = Column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    img_id = Column(String(128), nullable=False, index=True)
    mode = Column(String(20), nullable=False, index=True)  # "train" or "test"
    received_at = Column(DateTime(timezone=True), default=utc_now)
    duration_seconds = Column(Float, nullable=True)  # Time between image finish send and submission arrival
    json_payload = Column(JSON, nullable=False)
    payload_sha256 = Column(String(64), nullable=False)
    s3_backup_path = Column(String(255), nullable=True)

    # Relationships
    team = relationship("Team", back_populates="submissions")
    dispatch = relationship("ImageDispatch", back_populates="submissions")

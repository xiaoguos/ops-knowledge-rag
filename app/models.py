from datetime import datetime
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from .platform import Base, now, uid


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String(80), index=True)
    owner_id: Mapped[str] = mapped_column(String(32))
    active_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "revision"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(255))
    department: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(80))
    digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    embedding_model: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id"), index=True
    )
    heading: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list] = mapped_column(Vector(512).with_variant(JSON, "sqlite"))
    lexical: Mapped[str | None] = mapped_column(
        TSVECTOR().with_variant(Text, "sqlite"), nullable=True
    )


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String(80), index=True)
    owner_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from rag_app.models.chat import Citation


class ConversationRecord(BaseModel):
    conversation_id: str
    session_id: str
    user_id: str | None = None
    title: str = "新对话"
    summary: str | None = None
    message_count: int = 0
    summary_message_count: int = 0
    last_message_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    summary_updated_at: datetime | None = None
    status: str = "active"


class ConversationMessage(BaseModel):
    turn_id: str
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation] = Field(default_factory=list)
    evidence_sufficient: bool | None = None
    abstain_reason: str = ""
    created_at: datetime
    model: str | None = None


class ConversationDetail(ConversationRecord):
    messages: list[ConversationMessage] = Field(default_factory=list)

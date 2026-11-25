from typing import Any

import pytest
from rag_app.config import Settings
from rag_app.models.conversation import ConversationRecord
from rag_app.services.agicto import AGICTOClient
from rag_app.services.memory import ConversationMemory


class FakeStore:
    def __init__(
        self,
        *,
        conversation: ConversationRecord,
        turns: list[dict[str, Any]],
    ) -> None:
        self.conversation = conversation
        self.turns = turns
        self.recent_limit: int | None = None
        self.summary_update: dict[str, Any] | None = None

    async def get_conversation(
        self,
        conversation_id: str,
        session_id: str,
    ) -> ConversationRecord | None:
        if (
            self.conversation.conversation_id == conversation_id
            and self.conversation.session_id == session_id
        ):
            return self.conversation
        return None

    async def get_recent_turns(
        self,
        conversation_id: str,
        session_id: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        self.recent_limit = limit
        return self.turns[-limit:]

    async def get_turns(
        self,
        conversation_id: str,
        session_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self.turns[offset : offset + limit]

    async def update_conversation_summary(
        self,
        *,
        conversation_id: str,
        session_id: str,
        summary: str,
        summarized_message_count: int,
    ) -> None:
        self.summary_update = {
            "conversation_id": conversation_id,
            "session_id": session_id,
            "summary": summary,
            "summarized_message_count": summarized_message_count,
        }


class FakeAGICTO:
    def __init__(self, summary: str) -> None:
        self.summary = summary
        self.calls: list[dict[str, Any]] = []

    async def summarize_conversation(
        self,
        previous_summary: str,
        turns: list[dict[str, Any]],
    ) -> str:
        self.calls.append({"previous_summary": previous_summary, "turns": turns})
        return self.summary


def make_conversation(
    *,
    message_count: int,
    summary_message_count: int,
    summary: str = "",
) -> ConversationRecord:
    return ConversationRecord(
        conversation_id="conversation-1",
        session_id="session-1",
        title="测试会话",
        summary=summary,
        message_count=message_count,
        summary_message_count=summary_message_count,
    )


def test_fit_messages_respects_character_budget_and_drops_orphan_assistant() -> None:
    messages = [
        {"role": "user", "content": "1234"},
        {"role": "assistant", "content": "123456"},
    ]

    assert ConversationMemory._fit_messages(messages, 6) == []
    fitted = ConversationMemory._fit_messages(messages, 12)
    assert fitted == messages


@pytest.mark.asyncio
async def test_load_context_returns_summary_and_budgeted_recent_messages() -> None:
    turns = [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二问"},
        {"role": "assistant", "content": "第二答"},
    ]
    store = FakeStore(
        conversation=make_conversation(
            message_count=4,
            summary_message_count=0,
            summary="这是已有摘要",
        ),
        turns=turns,
    )
    memory = ConversationMemory(
        settings=Settings(memory_recent_messages=3, memory_context_max_chars=100),
        store=store,  # type: ignore[arg-type]
        agicto=FakeAGICTO("unused"),  # type: ignore[arg-type]
    )

    summary, messages = await memory.load_context("conversation-1", "session-1")

    assert summary == "这是已有摘要"
    assert store.recent_limit == 3
    assert messages == [
        {"role": "user", "content": "第二问"},
        {"role": "assistant", "content": "第二答"},
    ]


@pytest.mark.asyncio
async def test_refresh_summary_only_summarizes_pending_messages() -> None:
    turns = [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二问"},
        {"role": "assistant", "content": "第二答"},
    ]
    store = FakeStore(
        conversation=make_conversation(
            message_count=4,
            summary_message_count=2,
            summary="第一轮摘要",
        ),
        turns=turns,
    )
    agicto = FakeAGICTO("第一轮和第二轮摘要")
    memory = ConversationMemory(
        settings=Settings(
            memory_summary_trigger_messages=2,
            memory_summary_window_messages=10,
            memory_summary_max_chars=100,
        ),
        store=store,  # type: ignore[arg-type]
        agicto=agicto,  # type: ignore[arg-type]
    )

    await memory.refresh_summary("conversation-1", "session-1")

    assert agicto.calls[0]["previous_summary"] == "第一轮摘要"
    assert agicto.calls[0]["turns"] == turns[2:4]
    assert store.summary_update == {
        "conversation_id": "conversation-1",
        "session_id": "session-1",
        "summary": "第一轮和第二轮摘要",
        "summarized_message_count": 4,
    }

    store.conversation = make_conversation(
        message_count=4,
        summary_message_count=4,
        summary="第一轮和第二轮摘要",
    )
    await memory.refresh_summary("conversation-1", "session-1")
    assert len(agicto.calls) == 1


@pytest.mark.asyncio
async def test_summarize_conversation_falls_back_without_fast_model() -> None:
    client = AGICTOClient(Settings(agicto_fast_model=""))

    summary = await client.summarize_conversation(
        "已有摘要",
        [{"role": "user", "content": "新问题"}],
    )

    assert summary == "已有摘要"

from __future__ import annotations

from typing import Any

from rag_app.config import Settings
from rag_app.services.agicto import AGICTOClient
from rag_app.services.elasticsearch import ElasticsearchStore


class ConversationMemory:
    def __init__(
        self,
        *,
        settings: Settings,
        store: ElasticsearchStore,
        agicto: AGICTOClient,
    ) -> None:
        self.settings = settings
        self.store = store
        self.agicto = agicto

    async def load_context(
        self,
        conversation_id: str,
        session_id: str,
    ) -> tuple[str, list[dict[str, str]]]:
        conversation = await self.store.get_conversation(conversation_id, session_id)
        summary = (conversation.summary or "") if conversation else ""
        turns = await self.store.get_recent_turns(
            conversation_id,
            session_id,
            limit=self.settings.memory_recent_messages,
        )
        messages = [
            {"role": turn["role"], "content": turn["content"]}
            for turn in turns
            if turn.get("role") in {"user", "assistant"} and turn.get("content")
        ]
        return summary, self._fit_messages(messages, self.settings.memory_context_max_chars)

    async def append_turn(
        self,
        *,
        turn_id: str,
        conversation_id: str,
        session_id: str,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
        evidence_sufficient: bool | None = None,
        abstain_reason: str = "",
    ) -> None:
        await self.store.append_turn(
            turn_id=turn_id,
            conversation_id=conversation_id,
            session_id=session_id,
            role=role,
            content=content,
            citations=citations,
            evidence_sufficient=evidence_sufficient,
            abstain_reason=abstain_reason,
        )

    async def refresh_summary(self, conversation_id: str, session_id: str) -> None:
        conversation = await self.store.get_conversation(conversation_id, session_id)
        if conversation is None:
            return
        pending_messages = conversation.message_count - conversation.summary_message_count
        if pending_messages < self.settings.memory_summary_trigger_messages:
            return

        turns = await self.store.get_turns(
            conversation_id,
            session_id,
            limit=self.settings.memory_summary_window_messages,
            offset=conversation.summary_message_count,
        )
        if not turns:
            return
        summary = await self.agicto.summarize_conversation(
            conversation.summary or "",
            turns,
        )
        summary = summary.strip()[: self.settings.memory_summary_max_chars]
        if not summary:
            return
        await self.store.update_conversation_summary(
            conversation_id=conversation_id,
            session_id=session_id,
            summary=summary,
            summarized_message_count=conversation.summary_message_count + len(turns),
        )

    @staticmethod
    def _fit_messages(
        messages: list[dict[str, str]],
        max_chars: int,
    ) -> list[dict[str, str]]:
        if max_chars <= 0:
            return []
        selected: list[dict[str, str]] = []
        remaining = max_chars
        for message in reversed(messages):
            content = message["content"].strip()
            if not content:
                continue
            if len(content) > remaining:
                if not selected and remaining > 0:
                    selected.append({**message, "content": content[-remaining:]})
                break
            selected.append({**message, "content": content})
            remaining -= len(content)
        selected.reverse()
        if selected and selected[0]["role"] == "assistant":
            selected.pop(0)
        return selected

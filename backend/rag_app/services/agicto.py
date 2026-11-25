from __future__ import annotations

import json
import re
from typing import Any

import httpx

from rag_app.config import Settings


class AGICTOError(RuntimeError):
    pass


class AGICTOClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: httpx.AsyncClient | None = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.agicto_base_url and self.settings.agicto_api_key)

    def _require_configuration(self) -> None:
        if not self.configured:
            raise AGICTOError("AGICTO_BASE_URL and AGICTO_API_KEY must be configured.")
        if not self.settings.agicto_chat_model:
            raise AGICTOError("AGICTO_CHAT_MODEL must be configured.")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.agicto_base_url.rstrip("/"),
                headers={"Authorization": f"Bearer {self.settings.agicto_api_key}"},
                timeout=self.settings.agicto_timeout_seconds,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        self._require_configuration()
        payload: dict[str, Any] = {
            "model": model or self.settings.agicto_chat_model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        response = await (await self._get_client()).post("/chat/completions", json=payload)
        if response.is_error:
            raise AGICTOError(f"AGICTO chat failed: {response.status_code} {response.text}")

        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AGICTOError("AGICTO returned an unexpected chat response.") from exc

    async def rewrite_query(
        self,
        question: str,
        history: list[dict[str, str]],
        *,
        conversation_summary: str = "",
    ) -> str:
        if not self.settings.agicto_fast_model:
            return question
        history_text = "\n".join(f"{item['role']}: {item['content']}" for item in history[-6:])
        summary_text = f"会话摘要：\n{conversation_summary}\n\n" if conversation_summary else ""
        return await self.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "把多轮对话中的最新问题改写为一个不依赖上下文的独立检索问题。"
                        "只输出改写后的问题，不要解释。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"{summary_text}历史对话：\n{history_text}\n\n"
                        f"最新问题：{question}"
                    ),
                },
            ],
            model=self.settings.agicto_fast_model,
            temperature=0,
        )

    async def summarize_conversation(
        self,
        previous_summary: str,
        turns: list[dict[str, Any]],
    ) -> str:
        if not self.settings.agicto_fast_model:
            return previous_summary
        history_text = "\n".join(
            f"{turn.get('role')}: {turn.get('content', '')}"
            for turn in turns
            if turn.get("role") in {"user", "assistant"} and turn.get("content")
        )
        return await self.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "压缩多轮对话记忆。保留用户意图、讨论主题、关键实体、已确认约束、"
                        "已经解决的问题和仍未解决的问题。保留必要的指代关系，但不要添加"
                        "文档事实，不要推断新结论，不要把它当作回答证据。只输出简洁中文摘要。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"已有摘要：\n{previous_summary or '无'}\n\n"
                        f"新增对话：\n{history_text}"
                    ),
                },
            ],
            model=self.settings.agicto_fast_model,
            temperature=0,
        )

    async def plan_retrieval_queries(self, question: str) -> list[str]:
        if not self.settings.agicto_fast_model:
            return [question]
        response = await self.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "把用户问题拆成适合独立检索的子问题。"
                        "单意图问题返回一个子问题；多意图问题最多返回三个。"
                        '只输出 JSON，格式为 {"queries": ["子问题1", "子问题2"]}。'
                    ),
                },
                {"role": "user", "content": question},
            ],
            model=self.settings.agicto_fast_model,
            temperature=0,
        )
        queries = self._parse_query_plan(response)
        return queries or [question]

    async def generate_answer(
        self,
        question: str,
        context: str,
        history: list[dict[str, str]],
        subqueries: list[str] | None = None,
        conversation_summary: str = "",
    ) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是私有文档问答助手。只能依据用户提供的证据回答。"
                    "每个事实性结论后必须使用 [E1]、[E2] 形式标注来源。"
                    "证据不足时明确回答无法从文档确认，不得使用外部知识补全。"
                    "不要自行生成页码或文档链接。"
                ),
            }
        ]
        if conversation_summary or history:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "多轮上下文（只用于理解指代和延续话题，不作为事实依据）：\n"
                        f"会话摘要：{conversation_summary or '无'}\n"
                        "最近对话：\n"
                        + "\n".join(
                            f"{item['role']}: {item['content']}" for item in history[-4:]
                        )
                    ),
                }
            )
        if subqueries and len(subqueries) > 1:
            messages.append(
                {
                    "role": "user",
                    "content": "请按以下子问题逐项回答，每个子问题下都必须给出引用：\n"
                    + "\n".join(
                        f"{index}. {query}"
                        for index, query in enumerate(subqueries, start=1)
                    ),
                }
            )
        messages.append(
            {
                "role": "user",
                "content": f"问题：{question}\n\n可用证据：\n{context}",
            }
        )
        return await self.chat(messages)

    async def repair_answer(
        self,
        question: str,
        draft_answer: str,
        context: str,
        *,
        invalid_ids: list[str],
        valid_ids: list[str],
    ) -> str:
        invalid_text = "、".join(invalid_ids) if invalid_ids else "无"
        valid_text = "、".join(valid_ids) if valid_ids else "无"
        return await self.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "修复回答中的证据引用。只能使用给出的合法编号。"
                        "无效编号对应的结论必须删除，或者改绑定到能够支持该结论的合法编号。"
                        "不得新增事实，不得改变已正确的事实和结构。"
                        "不得在正文、注释或修复说明中提及无效编号。"
                        "输出前必须检查所有 [E数字] 均属于合法编号。"
                        "仍然输出完整的修复后回答。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"问题：{question}\n\n"
                        f"合法编号：{valid_text}\n"
                        f"无效编号：{invalid_text}\n\n"
                        f"当前回答：\n{draft_answer}\n\n"
                        f"可用证据：\n{context}"
                    ),
                },
            ],
            temperature=0,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.configured or not self.settings.agicto_embedding_model:
            raise AGICTOError("AGICTO embedding configuration is incomplete.")
        response = await (await self._get_client()).post(
            "/embeddings",
            json={
                "model": self.settings.agicto_embedding_model,
                "input": texts,
                "dimensions": self.settings.agicto_embedding_dimensions,
            },
        )
        if response.is_error:
            raise AGICTOError(f"AGICTO embedding failed: {response.status_code} {response.text}")
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            error = data["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise AGICTOError(f"AGICTO embedding failed: {message}")
        try:
            ordered = sorted(data["data"], key=lambda item: item["index"])
            return [item["embedding"] for item in ordered]
        except (KeyError, TypeError) as exc:
            raise AGICTOError("AGICTO returned an unexpected embedding response.") from exc

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int,
    ) -> list[dict[str, Any]]:
        if not self.configured or not self.settings.agicto_rerank_model:
            return []
        response = await (await self._get_client()).post(
            "/rerank",
            json={
                "model": self.settings.agicto_rerank_model,
                "query": query,
                "documents": documents,
                "top_n": top_n,
            },
        )
        if response.is_error:
            raise AGICTOError(f"AGICTO rerank failed: {response.status_code} {response.text}")
        data = response.json()
        results = data.get("results")
        if not isinstance(results, list):
            raise AGICTOError("AGICTO returned an unexpected rerank response.")
        return results

    @staticmethod
    def _parse_query_plan(value: str) -> list[str]:
        cleaned = value.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return []
        queries = payload.get("queries") if isinstance(payload, dict) else None
        if not isinstance(queries, list):
            return []
        return [query.strip() for query in queries if isinstance(query, str) and query.strip()]

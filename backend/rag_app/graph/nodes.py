from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

from rag_app.config import Settings
from rag_app.services.agicto import AGICTOClient
from rag_app.services.elasticsearch import ElasticsearchStore
from rag_app.services.memory import ConversationMemory

EVIDENCE_PATTERN = re.compile(r"\[(E\d+)\]")
MULTI_QUERY_PATTERN = re.compile(
    r"(?:[?？].*[?？])|分别|各自|对比|区别|不同"
)


class RAGNodes:
    def __init__(
        self,
        *,
        settings: Settings,
        store: ElasticsearchStore,
        agicto: AGICTOClient,
        memory: ConversationMemory | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.agicto = agicto
        self.memory = memory or ConversationMemory(
            settings=settings,
            store=store,
            agicto=agicto,
        )

    async def load_context(self, state: dict[str, Any]) -> dict[str, Any]:
        summary, messages = await self.memory.load_context(
            state["conversation_id"],
            state["session_id"],
        )
        return {
            "messages": messages,
            "conversation_summary": summary,
            "retrieval_round": 0,
            "repair_round": 0,
            "trace": ["load_context"],
        }

    async def contextualize_query(self, state: dict[str, Any]) -> dict[str, Any]:
        question = state["current_query"].strip()
        if not state.get("messages"):
            return {"standalone_query": question, "trace": ["contextualize_query:direct"]}
        rewritten = await self.agicto.rewrite_query(
            question,
            state["messages"],
            conversation_summary=state.get("conversation_summary", ""),
        )
        return {
            "standalone_query": rewritten.strip() or question,
            "trace": ["contextualize_query:rewritten"],
        }

    async def plan_retrieval(self, state: dict[str, Any]) -> dict[str, Any]:
        question = state["standalone_query"]
        if not MULTI_QUERY_PATTERN.search(question):
            return {
                "retrieval_queries": [question],
                "missing_retrieval_queries": [],
                "trace": ["plan_retrieval:single_query"],
            }
        queries = await self.agicto.plan_retrieval_queries(question)
        queries = self._sanitize_queries(question, queries)
        return {
            "retrieval_queries": queries,
            "missing_retrieval_queries": [],
            "trace": [f"plan_retrieval:{len(queries)}_queries"],
        }

    async def retrieve(self, state: dict[str, Any]) -> dict[str, Any]:
        queries = state["retrieval_queries"]
        query_vectors: list[list[float] | None] = [None] * len(queries)
        if self.settings.agicto_embedding_model:
            query_vectors = list(await self.agicto.embed(queries))
        result_sets = await asyncio.gather(
            *(
                self.store.search_hybrid(
                    query,
                    query_vector=query_vector,
                    size=self.settings.retrieval_candidates,
                )
                for query, query_vector in zip(queries, query_vectors, strict=True)
            )
        )
        candidates = self._merge_retrieval_results(queries, result_sets)
        return {
            "retrieved_candidates": candidates,
            "trace": [f"retrieve:{len(queries)}x:{len(candidates)}"],
        }

    async def rerank(self, state: dict[str, Any]) -> dict[str, Any]:
        candidates = state.get("retrieved_candidates", [])
        if not candidates:
            return {"reranked_evidence": [], "trace": ["rerank:empty"]}

        if self.settings.agicto_rerank_model:
            documents = [candidate["text"] for candidate in candidates]
            query_results = await asyncio.gather(
                *(
                    self.agicto.rerank(
                        query,
                        documents,
                        top_n=min(self.settings.rerank_top_k, len(documents)),
                    )
                    for query in state["retrieval_queries"]
                )
            )
            scores: dict[str, float] = {}
            for results in query_results:
                for result in results:
                    index = int(result["index"])
                    chunk_id = candidates[index]["chunk_id"]
                    score = float(result.get("relevance_score", 0))
                    scores[chunk_id] = max(scores.get(chunk_id, 0.0), score)
            evidence: list[dict[str, Any]] = []
            for candidate in candidates:
                score = scores.get(candidate["chunk_id"])
                if score is None:
                    continue
                evidence.append({**candidate, "score": score})
            evidence.sort(key=lambda item: item["score"], reverse=True)
            evidence = evidence[: self.settings.rerank_top_k]
        else:
            evidence = [
                {**candidate, "score": candidate["retrieval_score"]}
                for candidate in candidates[: self.settings.rerank_top_k]
            ]
        return {
            "reranked_evidence": evidence,
            "trace": [f"rerank:{len(evidence)}"],
        }

    async def assess_evidence(self, state: dict[str, Any]) -> dict[str, Any]:
        evidence = state.get("reranked_evidence", [])
        if not evidence:
            return {
                "evidence_sufficient": False,
                "insufficiency_reason": "empty_retrieval",
                "missing_retrieval_queries": state.get("retrieval_queries", []),
                "trace": ["assess_evidence:empty"],
            }
        top_score = float(evidence[0].get("score", 0))
        missing_queries = [
            query
            for query in state.get("retrieval_queries", [])
            if not any(
                query in item.get("matched_queries", [])
                and float(item.get("score", 0)) >= self.settings.min_evidence_score
                for item in evidence
            )
        ]
        sufficient = top_score >= self.settings.min_evidence_score and not missing_queries
        return {
            "evidence_sufficient": sufficient,
            "insufficiency_reason": (
                ""
                if sufficient
                else (
                    "missing_subquery_evidence"
                    if missing_queries
                    else "low_relevance"
                )
            ),
            "missing_retrieval_queries": missing_queries,
            "trace": [f"assess_evidence:{sufficient}"],
        }

    async def rewrite_for_retry(self, state: dict[str, Any]) -> dict[str, Any]:
        queries = state["retrieval_queries"]
        missing = set(state.get("missing_retrieval_queries", []))
        rewritten_queries = list(queries)
        for index, query in enumerate(queries):
            if missing and query not in missing:
                continue
            if not self.settings.agicto_fast_model:
                continue
            rewritten = await self.agicto.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "改写检索问题，补充同义词和可能出现的文档术语。"
                            "只输出改写后的问题。"
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                model=self.settings.agicto_fast_model,
                temperature=0.2,
            )
            rewritten_queries[index] = rewritten.strip() or query
        return {
            "retrieval_queries": rewritten_queries,
            "retrieval_round": state.get("retrieval_round", 0) + 1,
            "trace": ["rewrite_for_retry"],
        }

    async def compose_context(self, state: dict[str, Any]) -> dict[str, Any]:
        evidence_map: dict[str, dict[str, Any]] = {}
        context_parts: list[str] = []
        for index, evidence in enumerate(state.get("reranked_evidence", []), start=1):
            evidence_id = f"E{index}"
            evidence_map[evidence_id] = evidence
            heading = " > ".join(evidence.get("heading_path", []))
            context_parts.append(
                f"[{evidence_id}] 文档：{evidence.get('document_title', '')}\n"
                f"章节：{heading}\n页码：{evidence.get('page_start')}\n"
                f"原文：{evidence.get('text', '')}"
            )
        return {
            "context_pack": "\n\n".join(context_parts),
            "evidence_map": evidence_map,
            "trace": [f"compose_context:{len(evidence_map)}"],
        }

    async def generate(self, state: dict[str, Any]) -> dict[str, Any]:
        draft = await self.agicto.generate_answer(
            state["standalone_query"],
            state["context_pack"],
            state.get("messages", []),
            state.get("retrieval_queries", []),
            state.get("conversation_summary", ""),
        )
        return {
            "draft_answer": draft,
            "trace": [f"generate:repair={state.get('repair_round', 0)}"],
        }

    async def verify_citations(self, state: dict[str, Any]) -> dict[str, Any]:
        answer = state.get("draft_answer", "")
        evidence_map = state.get("evidence_map", {})
        citation_ids = EVIDENCE_PATTERN.findall(answer)
        invalid_ids = sorted({item for item in citation_ids if item not in evidence_map})
        has_citation = bool(citation_ids)
        valid = has_citation and not invalid_ids
        citations = self._build_citations(citation_ids, evidence_map)
        if valid:
            failure_reason = ""
        elif invalid_ids:
            failure_reason = "invalid_citation"
        else:
            failure_reason = "missing_citation"
        return {
            "citation_check": {
                "valid": valid,
                "invalid_ids": invalid_ids,
                "has_citation": has_citation,
                "failure_reason": failure_reason,
            },
            "citations": citations,
            "invalid_evidence_ids": invalid_ids,
            "valid_evidence_ids": list(evidence_map),
            "final_answer": answer if valid else "",
            "trace": [f"verify_citations:{valid}"],
        }

    async def repair_citations(self, state: dict[str, Any]) -> dict[str, Any]:
        invalid_ids = state.get("citation_check", {}).get("invalid_ids", [])
        valid_ids = list(state.get("evidence_map", {}))
        original_answer = state.get("draft_answer", "")
        repaired = await self.agicto.repair_answer(
            state["standalone_query"],
            original_answer,
            state.get("context_pack", ""),
            invalid_ids=invalid_ids,
            valid_ids=valid_ids,
        )
        repaired = self._sanitize_citation_markers(repaired, valid_ids)
        if not self._has_valid_citation(repaired, valid_ids):
            repaired = self._sanitize_citation_markers(original_answer, valid_ids)
        repair_round = state.get("repair_round", 0) + 1
        return {
            "draft_answer": repaired,
            "repair_round": repair_round,
            "citation_repair_feedback": {
                "invalid_ids": invalid_ids,
                "valid_ids": valid_ids,
            },
            "trace": [f"repair_citations:{repair_round}"],
        }

    @staticmethod
    def _build_citations(
        citation_ids: list[str],
        evidence_map: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for evidence_id in citation_ids:
            if evidence_id in seen or evidence_id not in evidence_map:
                continue
            seen.add(evidence_id)
            evidence = evidence_map[evidence_id]
            citations.append(
                {
                    "evidence_id": evidence_id,
                    "chunk_id": evidence["chunk_id"],
                    "doc_id": evidence["doc_id"],
                    "title": evidence.get("document_title", ""),
                    "heading_path": evidence.get("heading_path", []),
                    "page_start": evidence.get("page_start", 1),
                    "page_end": evidence.get("page_end", evidence.get("page_start", 1)),
                    "source_spans": evidence.get("source_spans", []),
                    "file_url": f"/api/documents/{evidence['doc_id']}/file",
                }
            )
        return citations

    async def abstain(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("invalid_evidence_ids"):
            reason = "invalid_citation_after_repair"
        elif state.get("insufficiency_reason"):
            reason = state["insufficiency_reason"]
        else:
            reason = "insufficient_evidence"
        return {
            "final_answer": "无法从当前私有文档中找到足够证据回答这个问题。",
            "citations": [],
            "evidence_sufficient": False,
            "abstain_reason": reason,
            "trace": ["abstain"],
        }

    async def persist_turn(self, state: dict[str, Any]) -> dict[str, Any]:
        conversation_id = state["conversation_id"]
        session_id = state["session_id"]
        await self.memory.append_turn(
            turn_id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            session_id=session_id,
            role="user",
            content=state["current_query"],
        )
        await self.memory.append_turn(
            turn_id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            session_id=session_id,
            role="assistant",
            content=state["final_answer"],
            citations=state.get("citations", []),
            evidence_sufficient=state.get("evidence_sufficient"),
            abstain_reason=state.get("abstain_reason", ""),
        )
        return {
            "status": "completed",
            "trace": ["persist_turn"],
        }

    @staticmethod
    def route_after_assessment(state: dict[str, Any]) -> str:
        if state.get("evidence_sufficient"):
            return "compose_context"
        if state.get("retrieval_round", 0) < 1:
            return "rewrite_for_retry"
        return "abstain"

    @staticmethod
    def route_after_verification(state: dict[str, Any]) -> str:
        if state.get("citation_check", {}).get("valid"):
            return "persist_turn"
        if state.get("repair_round", 0) < 1:
            return "repair_citations"
        return "abstain"

    @staticmethod
    def _sanitize_queries(question: str, queries: list[str]) -> list[str]:
        cleaned: list[str] = []
        for query in queries:
            value = query.strip()
            if value and value not in cleaned:
                cleaned.append(value)
            if len(cleaned) == 3:
                break
        return cleaned or [question]

    @staticmethod
    def _sanitize_citation_markers(answer: str, valid_ids: list[str]) -> str:
        valid = set(valid_ids)
        return EVIDENCE_PATTERN.sub(
            lambda match: match.group(0) if match.group(1) in valid else "",
            answer,
        )

    @staticmethod
    def _has_valid_citation(answer: str, valid_ids: list[str]) -> bool:
        valid = set(valid_ids)
        return any(item in valid for item in EVIDENCE_PATTERN.findall(answer))

    @staticmethod
    def _merge_retrieval_results(
        queries: list[str],
        result_sets: list[list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for query, results in zip(queries, result_sets, strict=True):
            for candidate in results:
                chunk_id = candidate["chunk_id"]
                item = merged.setdefault(
                    chunk_id,
                    {
                        **candidate,
                        "matched_queries": [],
                        "query_scores": {},
                    },
                )
                item["query_scores"][query] = float(candidate.get("retrieval_score", 0))
                if query not in item["matched_queries"]:
                    item["matched_queries"].append(query)

        for item in merged.values():
            scores = list(item["query_scores"].values())
            item["retrieval_score"] = max(scores) + 0.1 * (len(scores) - 1)
        return sorted(
            merged.values(),
            key=lambda item: item["retrieval_score"],
            reverse=True,
        )

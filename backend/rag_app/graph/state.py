from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class RAGState(TypedDict, total=False):
    conversation_id: str
    session_id: str
    request_id: str
    current_query: str
    messages: list[dict[str, str]]
    conversation_summary: str
    standalone_query: str
    retrieval_queries: list[str]
    missing_retrieval_queries: list[str]
    retrieved_candidates: list[dict[str, Any]]
    reranked_evidence: list[dict[str, Any]]
    retrieval_round: int
    evidence_sufficient: bool
    insufficiency_reason: str
    context_pack: str
    evidence_map: dict[str, dict[str, Any]]
    draft_answer: str
    final_answer: str
    citations: list[dict[str, Any]]
    citation_check: dict[str, Any]
    invalid_evidence_ids: list[str]
    valid_evidence_ids: list[str]
    citation_repair_feedback: dict[str, Any]
    repair_round: int
    abstain_reason: str
    status: str
    error: str | None
    trace: Annotated[list[str], operator.add]

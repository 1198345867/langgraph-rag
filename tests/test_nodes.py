import pytest
from rag_app.config import Settings
from rag_app.graph.nodes import RAGNodes


def make_nodes() -> RAGNodes:
    return RAGNodes(
        settings=Settings(),
        store=object(),  # type: ignore[arg-type]
        agicto=object(),  # type: ignore[arg-type]
    )


class FakeAGICTO:
    def __init__(self) -> None:
        self.repair_calls: list[dict[str, object]] = []

    async def plan_retrieval_queries(self, question: str) -> list[str]:
        return ["投诉处理流程是什么？", "一般投诉的时限是多少？"]

    async def repair_answer(
        self,
        question: str,
        draft_answer: str,
        context: str,
        *,
        invalid_ids: list[str],
        valid_ids: list[str],
    ) -> str:
        self.repair_calls.append(
            {
                "question": question,
                "draft_answer": draft_answer,
                "context": context,
                "invalid_ids": invalid_ids,
                "valid_ids": valid_ids,
            }
        )
        return "修复后的结论 [E1]。"


class InvalidMarkerAGICTO(FakeAGICTO):
    async def repair_answer(
        self,
        question: str,
        draft_answer: str,
        context: str,
        *,
        invalid_ids: list[str],
        valid_ids: list[str],
    ) -> str:
        return f"修复后的结论 [E1]，误引 [{invalid_ids[0]}]。"


class NoCitationAGICTO(FakeAGICTO):
    async def repair_answer(
        self,
        question: str,
        draft_answer: str,
        context: str,
        *,
        invalid_ids: list[str],
        valid_ids: list[str],
    ) -> str:
        return f"修复说明：已删除 [{invalid_ids[0]}]。"


@pytest.mark.asyncio
async def test_verify_citations_rejects_unknown_evidence() -> None:
    nodes = make_nodes()
    state = {
        "draft_answer": "结论一 [E1]，结论二 [E9]。",
        "evidence_map": {
            "E1": {
                "chunk_id": "chunk-1",
                "doc_id": "doc-1",
                "document_title": "示例文档",
                "heading_path": ["第一章"],
                "page_start": 2,
                "page_end": 2,
                "source_spans": [
                    {
                        "page_number": 2,
                        "bbox": [10, 10, 100, 30],
                        "page_width": 600,
                        "page_height": 800,
                        "quote": "示例原文",
                    }
                ],
            }
        },
    }

    result = await nodes.verify_citations(state)

    assert result["citation_check"]["valid"] is False
    assert result["citation_check"]["invalid_ids"] == ["E9"]
    assert result["citation_check"]["failure_reason"] == "invalid_citation"
    assert result["final_answer"] == ""


@pytest.mark.asyncio
async def test_verify_citations_builds_backend_citation_metadata() -> None:
    nodes = make_nodes()
    state = {
        "draft_answer": "结论 [E1]。",
        "evidence_map": {
            "E1": {
                "chunk_id": "chunk-1",
                "doc_id": "doc-1",
                "document_title": "示例文档",
                "heading_path": ["第一章"],
                "page_start": 3,
                "page_end": 3,
                "source_spans": [],
            }
        },
    }

    result = await nodes.verify_citations(state)

    assert result["citation_check"]["valid"] is True
    assert result["final_answer"] == "结论 [E1]。"
    assert result["citations"][0]["page_start"] == 3
    assert result["citations"][0]["file_url"] == "/api/documents/doc-1/file"


@pytest.mark.asyncio
async def test_abstain_uses_private_document_message() -> None:
    nodes = make_nodes()

    result = await nodes.abstain({})

    assert result["final_answer"] == "无法从当前私有文档中找到足够证据回答这个问题。"
    assert result["citations"] == []
    assert result["evidence_sufficient"] is False
    assert result["abstain_reason"] == "insufficient_evidence"


@pytest.mark.asyncio
async def test_plan_retrieval_decomposes_multi_intent_query() -> None:
    nodes = RAGNodes(
        settings=Settings(),
        store=object(),  # type: ignore[arg-type]
        agicto=FakeAGICTO(),  # type: ignore[arg-type]
    )

    result = await nodes.plan_retrieval(
        {"standalone_query": "投诉处理流程是什么？一般投诉的时限是多少？"}
    )

    assert result["retrieval_queries"] == [
        "投诉处理流程是什么？",
        "一般投诉的时限是多少？",
    ]
    assert result["trace"] == ["plan_retrieval:2_queries"]


@pytest.mark.asyncio
async def test_repair_citations_uses_invalid_and_valid_ids() -> None:
    agicto = FakeAGICTO()
    nodes = RAGNodes(
        settings=Settings(),
        store=object(),  # type: ignore[arg-type]
        agicto=agicto,  # type: ignore[arg-type]
    )

    result = await nodes.repair_citations(
        {
            "standalone_query": "问题",
            "draft_answer": "结论 [E9]。",
            "context_pack": "[E1] 证据正文",
            "citation_check": {"invalid_ids": ["E9"]},
            "evidence_map": {"E1": {"chunk_id": "chunk-1"}},
        }
    )

    assert result["draft_answer"] == "修复后的结论 [E1]。"
    assert result["repair_round"] == 1
    assert agicto.repair_calls[0]["invalid_ids"] == ["E9"]
    assert agicto.repair_calls[0]["valid_ids"] == ["E1"]


@pytest.mark.asyncio
async def test_repair_citations_strips_invalid_markers_from_repaired_answer() -> None:
    nodes = RAGNodes(
        settings=Settings(),
        store=object(),  # type: ignore[arg-type]
        agicto=InvalidMarkerAGICTO(),  # type: ignore[arg-type]
    )

    result = await nodes.repair_citations(
        {
            "standalone_query": "问题",
            "draft_answer": "原始结论 [E1]，误引 [E9]。",
            "context_pack": "[E1] 证据正文",
            "citation_check": {"invalid_ids": ["E9"]},
            "evidence_map": {"E1": {"chunk_id": "chunk-1"}},
        }
    )

    assert result["draft_answer"] == "修复后的结论 [E1]，误引 。"


@pytest.mark.asyncio
async def test_repair_citations_falls_back_when_repaired_answer_has_no_citation() -> None:
    nodes = RAGNodes(
        settings=Settings(),
        store=object(),  # type: ignore[arg-type]
        agicto=NoCitationAGICTO(),  # type: ignore[arg-type]
    )

    result = await nodes.repair_citations(
        {
            "standalone_query": "问题",
            "draft_answer": "原始结论 [E1]，误引 [E9]。",
            "context_pack": "[E1] 证据正文",
            "citation_check": {"invalid_ids": ["E9"]},
            "evidence_map": {"E1": {"chunk_id": "chunk-1"}},
        }
    )

    assert result["draft_answer"] == "原始结论 [E1]，误引 。"


def test_merge_retrieval_results_deduplicates_and_tracks_queries() -> None:
    merged = RAGNodes._merge_retrieval_results(
        ["问题一", "问题二"],
        [
            [{"chunk_id": "c1", "text": "一", "retrieval_score": 0.8}],
            [
                {"chunk_id": "c1", "text": "一", "retrieval_score": 0.6},
                {"chunk_id": "c2", "text": "二", "retrieval_score": 0.7},
            ],
        ],
    )

    assert [item["chunk_id"] for item in merged] == ["c1", "c2"]
    assert merged[0]["matched_queries"] == ["问题一", "问题二"]
    assert merged[0]["query_scores"] == {"问题一": 0.8, "问题二": 0.6}


def test_route_after_verification_repairs_then_abstains() -> None:
    assert (
        RAGNodes.route_after_verification(
            {"citation_check": {"valid": False}, "repair_round": 0}
        )
        == "repair_citations"
    )
    assert (
        RAGNodes.route_after_verification(
            {"citation_check": {"valid": False}, "repair_round": 1}
        )
        == "abstain"
    )

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from rag_app.graph.nodes import RAGNodes
from rag_app.graph.state import RAGState


class RAGWorkflow:
    def __init__(self, nodes: RAGNodes) -> None:
        self.nodes = nodes
        graph = StateGraph(RAGState)
        graph.add_node("load_context", nodes.load_context)
        graph.add_node("contextualize_query", nodes.contextualize_query)
        graph.add_node("plan_retrieval", nodes.plan_retrieval)
        graph.add_node("retrieve", nodes.retrieve)
        graph.add_node("rerank", nodes.rerank)
        graph.add_node("assess_evidence", nodes.assess_evidence)
        graph.add_node("rewrite_for_retry", nodes.rewrite_for_retry)
        graph.add_node("compose_context", nodes.compose_context)
        graph.add_node("generate", nodes.generate)
        graph.add_node("verify_citations", nodes.verify_citations)
        graph.add_node("repair_citations", nodes.repair_citations)
        graph.add_node("abstain", nodes.abstain)
        graph.add_node("persist_turn", nodes.persist_turn)

        graph.add_edge(START, "load_context")
        graph.add_edge("load_context", "contextualize_query")
        graph.add_edge("contextualize_query", "plan_retrieval")
        graph.add_edge("plan_retrieval", "retrieve")
        graph.add_edge("retrieve", "rerank")
        graph.add_edge("rerank", "assess_evidence")
        graph.add_conditional_edges(
            "assess_evidence",
            nodes.route_after_assessment,
            {
                "compose_context": "compose_context",
                "rewrite_for_retry": "rewrite_for_retry",
                "abstain": "abstain",
            },
        )
        graph.add_edge("rewrite_for_retry", "retrieve")
        graph.add_edge("compose_context", "generate")
        graph.add_edge("generate", "verify_citations")
        graph.add_conditional_edges(
            "verify_citations",
            nodes.route_after_verification,
            {
                "repair_citations": "repair_citations",
                "persist_turn": "persist_turn",
                "abstain": "abstain",
            },
        )
        graph.add_edge("repair_citations", "verify_citations")
        graph.add_edge("abstain", "persist_turn")
        graph.add_edge("persist_turn", END)

        self.graph = graph.compile()

    async def run(
        self,
        *,
        conversation_id: str,
        session_id: str,
        question: str,
        request_id: str,
    ) -> dict[str, Any]:
        return await self.graph.ainvoke(
            {
                "conversation_id": conversation_id,
                "session_id": session_id,
                "request_id": request_id,
                "current_query": question,
                "trace": [],
            }
        )

"""把私有文档问答暴露为 MCP 工具，供任意支持 MCP 的客户端调用。

复用与 HTTP 接口相同的 RAG 工作流与 Elasticsearch 索引，不另建一套检索逻辑。
通过 stdio 传输，启动方式：

    uv run python backend/mcp_server.py
"""

from __future__ import annotations

import uuid
from typing import Any

from mcp.server.mcpserver import MCPServer
from rag_app.bootstrap import ApplicationServices
from rag_app.config import get_settings
from rag_app.models.chat import Citation

# MCP 客户端没有浏览器 cookie，用固定会话标识隔离对话记录
SESSION_ID = "mcp"

mcp = MCPServer(
    name="private-doc-rag",
    instructions="私有制度文档问答服务，可先列出入库文档，再携引用提问。",
)

_services: ApplicationServices | None = None


def services() -> ApplicationServices:
    """首次调用时创建服务，保证异步客户端建立在运行中的事件循环上。"""
    global _services
    if _services is None:
        _services = ApplicationServices.create(get_settings())
    return _services


@mcp.tool(
    description=(
        "就私有制度文档提问，返回带 [E1] 引用的答案。"
        "首次提问可不传 conversation_id，多轮追问时把上一轮返回值原样传回。"
    )
)
async def ask_documents(question: str, conversation_id: str = "") -> dict[str, Any]:
    app = services()
    target = conversation_id or uuid.uuid4().hex
    state = await app.workflow.run(
        conversation_id=target,
        session_id=SESSION_ID,
        question=question,
        request_id=uuid.uuid4().hex,
    )
    citations = [Citation.model_validate(item) for item in state.get("citations", [])]
    return {
        "conversation_id": target,
        "answer": state.get("final_answer", ""),
        "citations": [citation.model_dump(mode="json") for citation in citations],
        "evidence_sufficient": state.get("evidence_sufficient", False),
        "retrieval_round": state.get("retrieval_round", 0),
        "abstain_reason": state.get("abstain_reason", ""),
    }


@mcp.tool(
    description="只做检索，返回片段原文与来源，不生成答案，适合需要自行组织上下文的上层 Agent。"
)
async def search_documents(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    app = services()
    query_vector = None
    if app.settings.agicto_embedding_model:
        query_vector = (await app.agicto.embed([query]))[0]
    hits = await app.store.search_hybrid(query, query_vector=query_vector, size=top_k)
    return [
        {
            "chunk_id": hit["chunk_id"],
            "doc_id": hit["doc_id"],
            "title": hit["document_title"],
            "heading_path": hit["heading_path"],
            "page_start": hit["page_start"],
            "page_end": hit["page_end"],
            "fusion_score": round(float(hit["fusion_score"]), 6),
            "text": hit["text"],
        }
        for hit in hits
    ]


@mcp.tool(description="列出当前已入库的文档及其解析状态，用于确认可问答的范围。")
async def list_documents() -> list[dict[str, Any]]:
    records = await services().store.list_documents()
    return [
        {
            "doc_id": record.doc_id,
            "title": record.title,
            "file_name": record.file_name,
            "page_count": record.page_count,
            "parse_status": record.parse_status.value,
        }
        for record in records
    ]


if __name__ == "__main__":
    mcp.run()

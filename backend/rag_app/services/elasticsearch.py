from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from elasticsearch import AsyncElasticsearch, NotFoundError
from elasticsearch.helpers import async_bulk

from rag_app.config import Settings
from rag_app.models.conversation import ConversationRecord
from rag_app.models.document import (
    ChunkRecord,
    DocumentRecord,
    SectionNode,
)


class ElasticsearchStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        auth: tuple[str, str] | None = None
        if settings.es_username:
            auth = (settings.es_username, settings.es_password)
        self.client = AsyncElasticsearch(
            settings.es_url,
            basic_auth=auth,
            request_timeout=30,
        )

    async def close(self) -> None:
        await self.client.close()

    async def ping(self) -> bool:
        return bool(await self.client.ping())

    async def ensure_indices(self) -> None:
        await self._ensure_index(
            self.settings.es_documents_index,
            {
                "properties": {
                    "doc_id": {"type": "keyword"},
                    "version_id": {"type": "keyword"},
                    "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "file_name": {"type": "keyword"},
                    "file_hash": {"type": "keyword"},
                    "page_count": {"type": "integer"},
                    "parse_status": {"type": "keyword"},
                    "storage_uri": {"type": "keyword", "index": False},
                    "active_version": {"type": "keyword"},
                    "uploaded_by": {"type": "keyword"},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                    "embedding_model": {"type": "keyword"},
                    "chunker_version": {"type": "keyword"},
                    "error_message": {"type": "text", "index": False},
                }
            },
        )
        await self._ensure_index(
            self.settings.es_sections_index,
            {
                "properties": {
                    "section_id": {"type": "keyword"},
                    "doc_id": {"type": "keyword"},
                    "version_id": {"type": "keyword"},
                    "parent_section_id": {"type": "keyword"},
                    "child_ids": {"type": "keyword"},
                    "level": {"type": "integer"},
                    "order": {"type": "integer"},
                    "heading": {"type": "text"},
                    "heading_path": {"type": "text"},
                    "page_start": {"type": "integer"},
                    "page_end": {"type": "integer"},
                    "is_leaf": {"type": "boolean"},
                    "summary": {"type": "text"},
                }
            },
        )
        await self._ensure_index(
            self.settings.es_chunks_index,
            {"properties": self._chunk_properties()},
        )
        await self._ensure_index(
            self.settings.es_conversations_index,
            {
                "properties": {
                    "conversation_id": {"type": "keyword"},
                    "session_id": {"type": "keyword"},
                    "user_id": {"type": "keyword"},
                    "title": {"type": "text"},
                    "summary": {"type": "text"},
                    "message_count": {"type": "integer"},
                    "summary_message_count": {"type": "integer"},
                    "last_message_at": {"type": "date"},
                    "summary_updated_at": {"type": "date"},
                    "status": {"type": "keyword"},
                }
            },
        )
        await self._ensure_index(
            self.settings.es_turns_index,
            {
                "properties": {
                    "turn_id": {"type": "keyword"},
                    "conversation_id": {"type": "keyword"},
                    "session_id": {"type": "keyword"},
                    "role": {"type": "keyword"},
                    "content": {"type": "text", "index": False},
                    "citations": {"type": "object", "enabled": False},
                    "evidence_sufficient": {"type": "boolean"},
                    "abstain_reason": {"type": "keyword"},
                    "created_at": {"type": "date"},
                    "model": {"type": "keyword"},
                    "token_usage": {"type": "object", "enabled": False},
                }
            },
        )

    async def _ensure_index(self, index: str, mappings: dict[str, Any]) -> None:
        if await self.client.indices.exists(index=index):
            return
        await self.client.indices.create(
            index=index,
            mappings=mappings,
            settings={"number_of_shards": 1, "number_of_replicas": 0},
        )

    def _chunk_properties(self) -> dict[str, Any]:
        analyzer = "ik_max_word" if self.settings.es_use_ik else "standard"
        search_analyzer = "ik_smart" if self.settings.es_use_ik else "standard"
        return {
            "chunk_id": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "version_id": {"type": "keyword"},
            "document_title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "section_id": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "content_type": {"type": "keyword"},
            "text": {
                "type": "text",
                "analyzer": analyzer,
                "search_analyzer": search_analyzer,
            },
            "heading_path": {
                "type": "text",
                "analyzer": analyzer,
                "search_analyzer": search_analyzer,
            },
            "page_start": {"type": "integer"},
            "page_end": {"type": "integer"},
            "source_spans": {
                "type": "nested",
                "properties": {
                    "page_number": {"type": "integer"},
                    "bbox": {"type": "float"},
                    "page_width": {"type": "float"},
                    "page_height": {"type": "float"},
                    "quote": {"type": "text", "index": False},
                },
            },
            "embedding": {
                "type": "dense_vector",
                "dims": self.settings.agicto_embedding_dimensions,
                "index": True,
                "similarity": "cosine",
            },
            "embedding_model": {"type": "keyword"},
            "char_count": {"type": "integer"},
            "prev_chunk_id": {"type": "keyword"},
            "next_chunk_id": {"type": "keyword"},
            "is_current": {"type": "boolean"},
        }

    async def index_document(self, document: DocumentRecord) -> None:
        await self.client.index(
            index=self.settings.es_documents_index,
            id=document.doc_id,
            document=document.to_es(),
            refresh="wait_for",
        )

    async def get_document(self, doc_id: str) -> DocumentRecord | None:
        try:
            response = await self.client.get(index=self.settings.es_documents_index, id=doc_id)
        except NotFoundError:
            return None
        return DocumentRecord.model_validate(response["_source"])

    async def list_documents(self, limit: int = 100) -> list[DocumentRecord]:
        response = await self.client.search(
            index=self.settings.es_documents_index,
            query={"match_all": {}},
            sort=[{"created_at": {"order": "desc"}}],
            size=limit,
        )
        return [
            DocumentRecord.model_validate(hit["_source"])
            for hit in response["hits"]["hits"]
        ]

    async def index_sections(self, sections: list[SectionNode]) -> None:
        if not sections:
            return
        operations = [
            {
                "_op_type": "index",
                "_index": self.settings.es_sections_index,
                "_id": section.section_id,
                "_source": section.model_dump(mode="json"),
            }
            for section in sections
        ]
        await async_bulk(self.client, operations, refresh="wait_for")

    async def index_chunks(self, chunks: list[ChunkRecord]) -> None:
        if not chunks:
            return
        operations = [
            {
                "_op_type": "index",
                "_index": self.settings.es_chunks_index,
                "_id": chunk.chunk_id,
                "_source": chunk.model_dump(mode="json"),
            }
            for chunk in chunks
        ]
        await async_bulk(self.client, operations, refresh="wait_for")

    async def deactivate_previous_versions(self, doc_id: str, keep_version_id: str) -> None:
        await self.client.update_by_query(
            index=self.settings.es_chunks_index,
            query={
                "bool": {
                    "filter": [{"term": {"doc_id": doc_id}}],
                    "must_not": [{"term": {"version_id": keep_version_id}}],
                }
            },
            script={"source": "ctx._source.is_current = false", "lang": "painless"},
            refresh=True,
            conflicts="proceed",
        )

    async def search_hybrid(
        self,
        query: str,
        *,
        query_vector: list[float] | None,
        size: int,
    ) -> list[dict[str, Any]]:
        bm25_hits = await self._bm25_search(query, size)
        vector_hits = await self._vector_search(query_vector, size) if query_vector else []
        return self._reciprocal_rank_fusion(bm25_hits, vector_hits)

    async def _bm25_search(self, query: str, size: int) -> list[dict[str, Any]]:
        response = await self.client.search(
            index=self.settings.es_chunks_index,
            query={
                "bool": {
                    "filter": [{"term": {"is_current": True}}],
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["text^3", "heading_path^2", "document_title"],
                            }
                        }
                    ],
                }
            },
            size=size,
        )
        return [self._hit_to_candidate(hit) for hit in response["hits"]["hits"]]

    async def _vector_search(
        self,
        query_vector: list[float],
        size: int,
    ) -> list[dict[str, Any]]:
        response = await self.client.search(
            index=self.settings.es_chunks_index,
            knn={
                "field": "embedding",
                "query_vector": query_vector,
                "k": size,
                "num_candidates": max(size * 4, 50),
                "filter": {"term": {"is_current": True}},
            },
            size=size,
        )
        return [self._hit_to_candidate(hit) for hit in response["hits"]["hits"]]

    @staticmethod
    def _hit_to_candidate(hit: dict[str, Any]) -> dict[str, Any]:
        return {
            "score": float(hit.get("_score") or 0.0),
            **hit["_source"],
        }

    @staticmethod
    def _reciprocal_rank_fusion(
        bm25_hits: list[dict[str, Any]],
        vector_hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        raw_scores: dict[str, float] = {}
        for source_name, hits in (("bm25", bm25_hits), ("vector", vector_hits)):
            for rank, hit in enumerate(hits, start=1):
                chunk_id = hit["chunk_id"]
                candidate = merged.setdefault(chunk_id, {**hit, "fusion_score": 0.0})
                candidate["fusion_score"] += 1.0 / (60 + rank)
                candidate[f"{source_name}_rank"] = rank
                raw_scores[chunk_id] = max(raw_scores.get(chunk_id, 0.0), hit["score"])

        if not merged:
            return []
        max_fusion = max(item["fusion_score"] for item in merged.values())
        for chunk_id, item in merged.items():
            item["retrieval_score"] = item["fusion_score"] / max_fusion
            item["native_score"] = raw_scores[chunk_id]
        return sorted(
            merged.values(),
            key=lambda item: (item["retrieval_score"], item["native_score"]),
            reverse=True,
        )

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
        now = datetime.now(UTC)
        await self.client.index(
            index=self.settings.es_turns_index,
            id=turn_id,
            document={
                "turn_id": turn_id,
                "conversation_id": conversation_id,
                "session_id": session_id,
                "role": role,
                "content": content,
                "citations": citations or [],
                "evidence_sufficient": evidence_sufficient,
                "abstain_reason": abstain_reason,
                "created_at": now,
                "model": self.settings.agicto_chat_model or None,
                "token_usage": {},
            },
            refresh="wait_for",
        )
        title = content[:80].strip() if role == "user" else "新对话"
        await self.client.update(
            index=self.settings.es_conversations_index,
            id=conversation_id,
            script={
                "source": (
                    "ctx._source.conversation_id = params.conversation_id;"
                    "ctx._source.session_id = params.session_id;"
                    "ctx._source.last_message_at = params.now;"
                    "ctx._source.status = 'active';"
                    "ctx._source.message_count = (ctx._source.message_count ?: 0) + 1;"
                    "if (ctx._source.summary == null) { ctx._source.summary = ''; }"
                    "if (ctx._source.summary_message_count == null) {"
                    "  ctx._source.summary_message_count = 0;"
                    "}"
                    "if (ctx._source.title == null || ctx._source.title == '') {"
                    "  ctx._source.title = params.title;"
                    "}"
                ),
                "params": {
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                    "title": title,
                    "now": now.isoformat(),
                },
            },
            upsert={
                "conversation_id": conversation_id,
                "session_id": session_id,
                "user_id": None,
                "title": title,
                "summary": "",
                "message_count": 0,
                "summary_message_count": 0,
                "last_message_at": now,
                "status": "active",
            },
            scripted_upsert=True,
            refresh="wait_for",
        )

    async def get_conversation(
        self,
        conversation_id: str,
        session_id: str,
    ) -> ConversationRecord | None:
        response = await self.client.search(
            index=self.settings.es_conversations_index,
            query={
                "bool": {
                    "filter": [
                        {"term": {"conversation_id": conversation_id}},
                        {"term": {"session_id": session_id}},
                    ]
                }
            },
            size=1,
        )
        hits = response["hits"]["hits"]
        if not hits:
            return None
        return ConversationRecord.model_validate(hits[0]["_source"])

    async def list_conversations(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[ConversationRecord]:
        response = await self.client.search(
            index=self.settings.es_conversations_index,
            query={"term": {"session_id": session_id}},
            sort=[{"last_message_at": {"order": "desc"}}],
            size=limit,
        )
        return [
            ConversationRecord.model_validate(hit["_source"])
            for hit in response["hits"]["hits"]
        ]

    async def update_conversation_summary(
        self,
        *,
        conversation_id: str,
        session_id: str,
        summary: str,
        summarized_message_count: int,
    ) -> None:
        conversation = await self.get_conversation(conversation_id, session_id)
        if conversation is None:
            return
        await self.client.update(
            index=self.settings.es_conversations_index,
            id=conversation_id,
            doc={
                "summary": summary,
                "summary_message_count": summarized_message_count,
                "summary_updated_at": datetime.now(UTC),
            },
            refresh="wait_for",
        )

    async def get_turns(
        self,
        conversation_id: str,
        session_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        response = await self.client.search(
            index=self.settings.es_turns_index,
            query={
                "bool": {
                    "filter": [
                        {"term": {"conversation_id": conversation_id}},
                        {"term": {"session_id": session_id}},
                    ]
                }
            },
            sort=[{"created_at": {"order": "asc"}}],
            from_=max(offset, 0),
            size=min(limit, 1000),
        )
        return [hit["_source"] for hit in response["hits"]["hits"]]

    async def delete_conversation(
        self,
        conversation_id: str,
        session_id: str,
    ) -> bool:
        conversation = await self.get_conversation(conversation_id, session_id)
        if conversation is None:
            return False
        await self.client.delete_by_query(
            index=self.settings.es_turns_index,
            query={
                "bool": {
                    "filter": [
                        {"term": {"conversation_id": conversation_id}},
                        {"term": {"session_id": session_id}},
                    ]
                }
            },
            refresh=True,
            conflicts="proceed",
        )
        try:
            await self.client.delete(
                index=self.settings.es_conversations_index,
                id=conversation_id,
                refresh="wait_for",
            )
        except NotFoundError:
            return False
        return True

    async def get_recent_turns(
        self,
        conversation_id: str,
        session_id: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        response = await self.client.search(
            index=self.settings.es_turns_index,
            query={
                "bool": {
                    "filter": [
                        {"term": {"conversation_id": conversation_id}},
                        {"term": {"session_id": session_id}},
                    ]
                }
            },
            sort=[{"created_at": {"order": "desc"}}],
            size=limit,
        )
        turns = [hit["_source"] for hit in response["hits"]["hits"]]
        return list(reversed(turns))

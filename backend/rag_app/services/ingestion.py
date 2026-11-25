from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from rag_app.config import Settings
from rag_app.models.document import DocumentRecord, ParseStatus
from rag_app.services.agicto import AGICTOClient
from rag_app.services.chunking import HierarchicalChunker
from rag_app.services.elasticsearch import ElasticsearchStore
from rag_app.services.mineru import MinerUAdapter


class IngestionService:
    def __init__(
        self,
        settings: Settings,
        store: ElasticsearchStore,
        mineru: MinerUAdapter,
        agicto: AGICTOClient,
    ) -> None:
        self.settings = settings
        self.store = store
        self.mineru = mineru
        self.agicto = agicto
        self.chunker = HierarchicalChunker(settings)

    async def save_upload(self, upload: UploadFile) -> DocumentRecord:
        original_name = Path(upload.filename or "document.pdf").name
        if not original_name.lower().endswith(".pdf"):
            raise ValueError("Only PDF uploads are supported.")

        doc_id = uuid.uuid4().hex
        version_id = uuid.uuid4().hex
        target_dir = self.settings.upload_dir / doc_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / original_name

        digest = hashlib.sha256()
        async with aiofiles.open(target_path, "wb") as output:
            while chunk := await upload.read(1024 * 1024):
                digest.update(chunk)
                await output.write(chunk)

        record = DocumentRecord(
            doc_id=doc_id,
            version_id=version_id,
            title=Path(original_name).stem,
            file_name=original_name,
            file_hash=digest.hexdigest(),
            storage_uri=str(target_path),
            parse_status=ParseStatus.PENDING,
        )
        await self.store.index_document(record)
        return record

    async def ingest(
        self,
        doc_id: str,
        *,
        source_path: Path | None = None,
    ) -> None:
        document_record = await self.store.get_document(doc_id)
        if document_record is None:
            raise ValueError(f"Document {doc_id} does not exist.")

        try:
            document_record.parse_status = ParseStatus.PARSING
            document_record.updated_at = datetime.now(UTC)
            await self.store.index_document(document_record)

            parsed = await self.mineru.parse(
                source_path or Path(document_record.storage_uri),
                doc_id=document_record.doc_id,
                version_id=document_record.version_id,
                title=document_record.title,
            )
            chunked = self.chunker.chunk(parsed)

            document_record.parse_status = ParseStatus.INDEXING
            document_record.page_count = max(
                (block.page_number for block in parsed.blocks),
                default=0,
            )
            await self.store.index_document(document_record)

            if self.agicto.settings.agicto_embedding_model:
                embeddings = await self._embed_chunks([chunk.text for chunk in chunked.chunks])
                for chunk, embedding in zip(chunked.chunks, embeddings, strict=True):
                    chunk.embedding = embedding
                    chunk.embedding_model = self.settings.agicto_embedding_model
                document_record.embedding_model = self.settings.agicto_embedding_model

            await self.store.index_sections(chunked.sections)
            await self.store.index_chunks(chunked.chunks)
            await self.store.deactivate_previous_versions(
                document_record.doc_id,
                document_record.version_id,
            )

            document_record.parse_status = ParseStatus.COMPLETED
            document_record.active_version = document_record.version_id
            document_record.error_message = None
            document_record.updated_at = datetime.now(UTC)
            await self.store.index_document(document_record)
        except Exception as exc:
            document_record.parse_status = ParseStatus.FAILED
            document_record.error_message = str(exc)
            document_record.updated_at = datetime.now(UTC)
            await self.store.index_document(document_record)
            raise

    async def _embed_chunks(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        batch_size = 10
        for start in range(0, len(texts), batch_size):
            embeddings.extend(await self.agicto.embed(texts[start : start + batch_size]))
        return embeddings

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ParseStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"


class BlockType(StrEnum):
    TEXT = "text"
    TITLE = "title"
    TABLE = "table"
    FORMULA = "formula"
    LIST = "list"
    CAPTION = "caption"
    IMAGE = "image"


class SourceSpan(BaseModel):
    page_number: int
    bbox: list[float] | None = None
    page_width: float | None = None
    page_height: float | None = None
    quote: str


class ParsedBlock(BaseModel):
    block_id: str
    block_type: BlockType = BlockType.TEXT
    text: str
    page_number: int
    bbox: list[float] | None = None
    page_width: float | None = None
    page_height: float | None = None
    level: int | None = None
    order: int = 0


class ParsedDocument(BaseModel):
    doc_id: str
    version_id: str
    title: str
    source_path: str
    blocks: list[ParsedBlock]


class SectionNode(BaseModel):
    section_id: str
    doc_id: str
    version_id: str
    parent_section_id: str | None = None
    child_ids: list[str] = Field(default_factory=list)
    level: int
    order: int
    heading: str
    heading_path: list[str]
    page_start: int
    page_end: int
    is_leaf: bool = True
    summary: str | None = None


class ChunkRecord(BaseModel):
    chunk_id: str
    doc_id: str
    version_id: str
    document_title: str
    section_id: str
    chunk_index: int
    content_type: str
    text: str
    heading_path: list[str]
    page_start: int
    page_end: int
    source_spans: list[SourceSpan]
    char_count: int
    prev_chunk_id: str | None = None
    next_chunk_id: str | None = None
    embedding: list[float] | None = None
    embedding_model: str | None = None
    is_current: bool = True


class ChunkedDocument(BaseModel):
    document: ParsedDocument
    sections: list[SectionNode]
    chunks: list[ChunkRecord]


class DocumentRecord(BaseModel):
    doc_id: str
    version_id: str
    title: str
    file_name: str
    file_hash: str
    page_count: int = 0
    parse_status: ParseStatus = ParseStatus.PENDING
    storage_uri: str
    active_version: str | None = None
    uploaded_by: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    embedding_model: str | None = None
    chunker_version: str = "hierarchical-v1"
    error_message: str | None = None

    def to_es(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

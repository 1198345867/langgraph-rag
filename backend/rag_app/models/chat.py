from pydantic import BaseModel, Field

from rag_app.models.document import SourceSpan


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None


class Citation(BaseModel):
    evidence_id: str
    chunk_id: str
    doc_id: str
    title: str
    heading_path: list[str]
    page_start: int
    page_end: int
    source_spans: list[SourceSpan]
    file_url: str


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    citations: list[Citation]
    evidence_sufficient: bool
    retrieval_round: int
    retrieval_queries: list[str] = Field(default_factory=list)
    missing_retrieval_queries: list[str] = Field(default_factory=list)
    abstain_reason: str = ""
    invalid_evidence_ids: list[str] = Field(default_factory=list)
    repair_attempts: int = 0
    trace: list[str] = Field(default_factory=list)

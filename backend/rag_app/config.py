from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    es_url: str = "http://127.0.0.1:9200"
    es_username: str = ""
    es_password: str = ""
    es_documents_index: str = "rag_documents"
    es_sections_index: str = "rag_sections"
    es_chunks_index: str = "rag_chunks"
    es_conversations_index: str = "rag_conversations"
    es_turns_index: str = "rag_turns"
    es_use_ik: bool = False

    agicto_base_url: str = ""
    agicto_api_key: str = ""
    agicto_chat_model: str = ""
    agicto_fast_model: str = ""
    agicto_embedding_model: str = ""
    agicto_rerank_model: str = ""
    agicto_embedding_dimensions: int = 1024
    agicto_timeout_seconds: float = 90.0

    mineru_command: str = "mineru"
    mineru_api_key: str = ""
    mineru_base_url: str = "https://mineru.net/api/v4"
    mineru_model_version: str = "vlm"
    mineru_poll_interval_seconds: float = 2.0
    mineru_poll_timeout_seconds: float = 600.0
    mineru_output_dir: Path = Path("data/mineru")
    data_dir: Path = Path("data")
    upload_dir: Path = Path("data/uploads")

    chunk_target_chars: int = 500
    chunk_max_section_chars: int = 1000
    chunk_overlap_ratio: float = 0.15
    retrieval_candidates: int = 30
    rerank_top_k: int = 8
    min_rerank_score: float = 0.25
    min_fusion_score: float = 0.25
    memory_recent_messages: int = 12
    memory_context_max_chars: int = 6000
    memory_summary_trigger_messages: int = 12
    memory_summary_window_messages: int = 24
    memory_summary_max_chars: int = 1200

    @field_validator("app_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def prepare_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.mineru_output_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare_directories()
    return settings

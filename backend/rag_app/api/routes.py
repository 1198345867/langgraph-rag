from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from rag_app.bootstrap import ApplicationServices
from rag_app.models.chat import ChatRequest, ChatResponse, Citation
from rag_app.models.conversation import (
    ConversationDetail,
    ConversationMessage,
    ConversationRecord,
)
from rag_app.models.document import DocumentRecord

router = APIRouter()


def services_from(request: Request) -> ApplicationServices:
    return request.app.state.services


@router.get("/session")
async def session(request: Request) -> dict[str, str]:
    return {"session_id": request.state.session_id}


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    services = services_from(request)
    try:
        es_available = await services.store.ping()
    except Exception:
        es_available = False
    return {
        "status": "ok",
        "elasticsearch": es_available,
        "agicto_configured": services.agicto.configured,
        "chat_model": services.settings.agicto_chat_model or None,
        "embedding_model": services.settings.agicto_embedding_model or None,
        "mineru_api_configured": bool(services.settings.mineru_api_key),
    }


@router.get("/documents")
async def list_documents(request: Request) -> list[DocumentRecord]:
    services = services_from(request)
    try:
        return await services.store.list_documents()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/conversations")
async def list_conversations(request: Request) -> list[ConversationRecord]:
    services = services_from(request)
    try:
        return await services.store.list_conversations(request.state.session_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/conversations/{conversation_id}")
async def get_conversation(request: Request, conversation_id: str) -> ConversationDetail:
    services = services_from(request)
    session_id = request.state.session_id
    try:
        conversation = await services.store.get_conversation(conversation_id, session_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        turns = await services.store.get_turns(conversation_id, session_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ConversationDetail(
        **conversation.model_dump(),
        messages=[ConversationMessage.model_validate(turn) for turn in turns],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(request: Request, conversation_id: str) -> Response:
    services = services_from(request)
    try:
        deleted = await services.store.delete_conversation(
            conversation_id,
            request.state.session_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return Response(status_code=204)


@router.post("/documents", status_code=202)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
) -> dict[str, str]:
    services = services_from(request)
    try:
        record = await services.ingestion.save_upload(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    background_tasks.add_task(services.ingestion.ingest, record.doc_id)
    return {
        "doc_id": record.doc_id,
        "version_id": record.version_id,
        "status": record.parse_status,
    }


@router.get("/documents/{doc_id}/file")
async def get_document_file(request: Request, doc_id: str) -> FileResponse:
    services = services_from(request)
    try:
        record = await services.store.get_document(doc_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    file_path = Path(record.storage_uri).resolve()
    upload_root = services.settings.upload_dir.resolve()
    if upload_root not in file_path.parents or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found.")
    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=record.file_name,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: ChatRequest,
) -> ChatResponse:
    services = services_from(request)
    session_id = request.state.session_id
    try:
        if payload.conversation_id:
            conversation = await services.store.get_conversation(
                payload.conversation_id,
                session_id,
            )
            if conversation is None:
                raise HTTPException(status_code=404, detail="Conversation not found.")
            conversation_id = payload.conversation_id
        else:
            conversation_id = uuid.uuid4().hex
        state = await services.workflow.run(
            conversation_id=conversation_id,
            session_id=session_id,
            question=payload.message,
            request_id=uuid.uuid4().hex,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    background_tasks.add_task(
        services.memory.refresh_summary,
        conversation_id,
        session_id,
    )
    citations = [Citation.model_validate(item) for item in state.get("citations", [])]
    return ChatResponse(
        conversation_id=conversation_id,
        answer=state.get("final_answer", ""),
        citations=citations,
        evidence_sufficient=state.get("evidence_sufficient", False),
        retrieval_round=state.get("retrieval_round", 0),
        retrieval_queries=state.get("retrieval_queries", []),
        missing_retrieval_queries=state.get("missing_retrieval_queries", []),
        abstain_reason=state.get("abstain_reason", ""),
        invalid_evidence_ids=state.get("invalid_evidence_ids", []),
        repair_attempts=state.get("repair_round", 0),
        trace=state.get("trace", []),
    )

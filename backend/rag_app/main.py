from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from rag_app.api.routes import router
from rag_app.bootstrap import ApplicationServices
from rag_app.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    services = ApplicationServices.create(settings)
    app.state.services = services
    try:
        await services.store.ensure_indices()
    except Exception:
        logger.warning(
            "Elasticsearch is unavailable during startup; API will remain available.",
            exc_info=True,
        )
    yield
    await services.close()


app = FastAPI(
    title="LangGraph RAG",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def anonymous_session(request: Request, call_next):
    session_id = request.cookies.get("rag_session") or uuid.uuid4().hex
    request.state.session_id = session_id
    response = await call_next(request)
    if request.cookies.get("rag_session") != session_id:
        response.set_cookie(
            "rag_session",
            session_id,
            httponly=True,
            samesite="lax",
            secure=settings.app_env == "production",
            max_age=60 * 60 * 24 * 30,
        )
    return response


app.include_router(router, prefix="/api")

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pmaa_web.api.auth import router as auth_router
from pmaa_web.api.calendar import router as calendar_router
from pmaa_web.api.conversations import router as conversations_router
from pmaa_web.api.daily_briefs import router as daily_briefs_router
from pmaa_web.api.email import router as email_router
from pmaa_web.api.health import router as health_router
from pmaa_web.api.knowledge import router as knowledge_router
from pmaa_web.api.memories import router as memories_router
from pmaa_web.api.monitors import router as monitors_router
from pmaa_web.api.runs import router as runs_router
from pmaa_web.auth_middleware import AuthenticationMiddleware
from pmaa_web.config import get_settings
from pmaa_web.database import create_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.app_env == "development":
        await create_schema()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(AuthenticationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(conversations_router, prefix=settings.api_prefix)
app.include_router(runs_router, prefix=settings.api_prefix)
app.include_router(knowledge_router, prefix=settings.api_prefix)
app.include_router(memories_router, prefix=settings.api_prefix)
app.include_router(email_router, prefix=settings.api_prefix)
app.include_router(calendar_router, prefix=settings.api_prefix)
app.include_router(daily_briefs_router, prefix=settings.api_prefix)
app.include_router(monitors_router, prefix=settings.api_prefix)

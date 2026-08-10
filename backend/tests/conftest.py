from __future__ import annotations

import os

import pytest_asyncio

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./.pytest-pmaa.db"
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
os.environ["EMAIL_ENABLED"] = "false"
os.environ["WEB_SEARCH_PROVIDER"] = "disabled"
os.environ["TASK_EXECUTION_MODE"] = "local"
os.environ["AUTOMATION_SCHEDULER_ENABLED"] = "false"
os.environ["AUTH_ENABLED"] = "false"

from pmaa_web.database import Base, engine  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def database_schema():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)

"""
conftest.py — Shared pytest fixtures for the DarkAtlas test suite.

Event-loop strategy:
  - Database CREATE/DROP: uses a plain synchronous session fixture that spins up
    its own isolated asyncio event loop (asyncio.new_event_loop). This is
    completely outside pytest-asyncio's event loop so there is no scope clash.
  - Schema CREATE/DROP (tables): async function-scoped fixture — runs on the
    same per-test event loop that pytest-asyncio manages. This is safe because
    the engine is re-used across function-scoped calls.
  - All other fixtures (client, auth_headers) are also function-scoped async,
    matching the per-test event loop perfectly.
"""

import asyncio
import os

import asyncpg
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from typing import AsyncGenerator

from app.main import app as fastapi_app
from app.core.database import get_db
from app.models.base import Base


# Import all models so SQLAlchemy registers their tables with Base.metadata
import app.models.user          # noqa: F401
import app.models.asset         # noqa: F401
import app.models.relationship  # noqa: F401

# ─── Connection parameters — resolved from env vars (match Docker config) ─────
_HOST     = os.getenv("POSTGRES_SERVER", "localhost")
_PORT     = int(os.getenv("POSTGRES_PORT", "5432"))
_USER     = os.getenv("POSTGRES_USER", "postgres")
_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
_TEST_DB  = "darkatlas_test"
_ADMIN_DSN = f"postgresql://{_USER}:{_PASSWORD}@{_HOST}:{_PORT}/postgres"

TEST_DATABASE_URL = (
    f"postgresql+asyncpg://{_USER}:{_PASSWORD}@{_HOST}:{_PORT}/{_TEST_DB}"
)

# Engine created with NullPool to avoid event loop reuse conflicts in pytest
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    poolclass=NullPool,
    echo=False,
    future=True,
)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ─── Session-scoped SYNC fixture: create & drop the test database ─────────────
# Uses asyncio.new_event_loop() so it is 100% independent of pytest-asyncio's
# per-function event loop — no event loop scope clash.

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """
    Create 'darkatlas_test' before all tests; drop it (WITH FORCE) after.
    Intentionally synchronous to avoid event loop scope conflicts with
    pytest-asyncio's per-function event loop.
    """

    async def _create():
        conn = await asyncpg.connect(_ADMIN_DSN)
        try:
            await conn.execute(f'CREATE DATABASE "{_TEST_DB}"')
        except asyncpg.exceptions.DuplicateDatabaseError:
            pass  # exists from a previously interrupted run
        finally:
            await conn.close()

    async def _drop():
        # Dispose the SQLAlchemy pool before we drop the database
        await test_engine.dispose()
        conn = await asyncpg.connect(_ADMIN_DSN)
        try:
            # WITH (FORCE) — terminates remaining connections (Postgres 13+)
            await conn.execute(
                f'DROP DATABASE IF EXISTS "{_TEST_DB}" WITH (FORCE)'
            )
        finally:
            await conn.close()

    # Setup: run in a fresh, isolated event loop
    _setup_loop = asyncio.new_event_loop()
    try:
        _setup_loop.run_until_complete(_create())
    finally:
        _setup_loop.close()

    yield  # ← all tests run here

    # Teardown: run in another fresh, isolated event loop
    _teardown_loop = asyncio.new_event_loop()
    try:
        _teardown_loop.run_until_complete(_drop())
    finally:
        _teardown_loop.close()




@pytest_asyncio.fixture(scope="function")
async def db_schema(setup_test_database):
    """
    Create all ORM tables before the test, drop them after.
    Runs on pytest-asyncio's per-function event loop — perfectly aligned.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)



@pytest_asyncio.fixture(scope="function")
async def client(db_schema) -> AsyncGenerator[AsyncClient, None]:
    """
    Async HTTP test client with get_db overridden to use the test database.
    Each request gets its own session: commits on success, rolls back on error.
    """
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with TestSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test"
    ) as ac:
        yield ac

    fastapi_app.dependency_overrides.clear()




@pytest_asyncio.fixture(scope="function")
async def auth_headers(client: AsyncClient) -> dict:
    """Register and log in the primary test user; return Bearer token headers."""
    await client.post(
        "/api/v1/auth/register",
        json={"username": "testuser", "password": "testpass123"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "testuser", "password": "testpass123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="function")
async def second_auth_headers(client: AsyncClient) -> dict:
    """Register and log in a second user (different tenant) for isolation tests."""
    await client.post(
        "/api/v1/auth/register",
        json={"username": "otheruser", "password": "testpass123"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "otheruser", "password": "testpass123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}




SAMPLE_DATASET = [
    {
        "id": "a1",
        "type": "domain",
        "value": "example.com",
        "status": "active",
        "source": "scan",
        "tags": ["root"],
        "metadata": {},
    },
    {
        "id": "a2",
        "type": "subdomain",
        "value": "api.example.com",
        "status": "active",
        "source": "scan",
        "tags": ["prod"],
        "metadata": {},
        "parent": "a1",
    },
    {
        "id": "a3",
        "type": "certificate",
        "value": "CN=api.example.com",
        "status": "active",
        "source": "scan",
        "tags": ["ssl"],
        "metadata": {"issuer": "Let's Encrypt", "expires": "2026-12-01"},
        "covers": "a2",
    },
]

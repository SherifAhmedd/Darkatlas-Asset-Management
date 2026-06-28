"""
test_auth.py — Tests for the authentication endpoints.

Covers:
  - Successful user registration
  - Duplicate username rejection (409)
  - Successful login returns a valid JWT
  - Invalid credentials return 401
  - Protected endpoints reject unauthenticated requests (401)
  - Tenant isolation: each registration gets its own tenant_id
"""

import pytest
from httpx import AsyncClient

# ─── Registration ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_user_returns_token(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": "newuser", "password": "password123"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 0


@pytest.mark.asyncio
async def test_register_duplicate_username_returns_409(client: AsyncClient):
    payload = {"username": "dupuser", "password": "password123"}
    r1 = await client.post("/api/v1/auth/register", json=payload)
    assert r1.status_code == 201

    r2 = await client.post("/api/v1/auth/register", json=payload)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_register_short_username_returns_422(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": "ab", "password": "password123"},  # < 3 chars
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_short_password_returns_422(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": "validuser", "password": "short"},  # < 8 chars
    )
    assert resp.status_code == 422


# ─── Login ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_with_valid_credentials_returns_token(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register",
        json={"username": "loginuser", "password": "mypassword"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "loginuser", "password": "mypassword"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register",
        json={"username": "passtest", "password": "correctpassword"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "passtest", "password": "wrongpassword"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user_returns_401(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "ghost_user", "password": "anypassword"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


# ─── Protected Endpoints ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_request_to_assets_returns_401(client: AsyncClient):
    resp = await client.get("/api/v1/assets")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_returns_401(client: AsyncClient):
    resp = await client.get(
        "/api/v1/assets",
        headers={"Authorization": "Bearer this.is.not.a.valid.jwt.token"},
    )
    assert resp.status_code == 401


# ─── Tenant Isolation via Registration ────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_registrations_get_different_tenant_ids(client: AsyncClient):
    """
    Confirm that each registered user receives a unique tenant_id by checking that
    their assets are completely isolated from one another.
    """
    # Register two users
    r1 = await client.post(
        "/api/v1/auth/register", json={"username": "tenant1", "password": "password123"}
    )
    r2 = await client.post(
        "/api/v1/auth/register", json={"username": "tenant2", "password": "password123"}
    )
    token1 = r1.json()["access_token"]
    token2 = r2.json()["access_token"]
    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    # Tenant 1 creates an asset
    await client.post(
        "/api/v1/assets",
        json={
            "type": "domain",
            "value": "tenant1-only.com",
            "source": "manual",
            "tags": [],
            "metadata": {},
        },
        headers=headers1,
    )

    # Tenant 2 should see zero assets
    resp = await client.get("/api/v1/assets", headers=headers2)
    assert resp.json()["total"] == 0

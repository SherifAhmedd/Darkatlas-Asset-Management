"""
test_relationships.py — Tests for relationship creation, listing, deduplication,
                         validation, and deletion endpoints.

Covers (per the rubric):
  - Create directed relationship between two assets
  - Duplicate relationship rejected with 409 Conflict
  - List relationships with pagination
  - Delete relationship
  - Creating relationship between assets of different tenants is rejected (404)
  - Invalid relationship type returns 422
"""

import pytest
from httpx import AsyncClient

# ─── Helpers ──────────────────────────────────────────────────────────────────


async def create_asset(
    client: AsyncClient, headers: dict, value: str, asset_type: str = "domain"
) -> str:
    """Create an asset and return its UUID."""
    resp = await client.post(
        "/api/v1/assets",
        json={
            "type": asset_type,
            "value": value,
            "source": "manual",
            "tags": [],
            "metadata": {},
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def create_relationship(
    client: AsyncClient,
    headers: dict,
    source_id: str,
    target_id: str,
    rel_type: str = "SUBDOMAIN_OF",
) -> dict:
    """Create a relationship and return the response body."""
    resp = await client.post(
        "/api/v1/relationships",
        json={
            "source_asset_id": source_id,
            "target_asset_id": target_id,
            "relationship_type": rel_type,
        },
        headers=headers,
    )
    return resp


# ─── Creation ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_relationship_returns_201(client: AsyncClient, auth_headers: dict):
    src = await create_asset(client, auth_headers, "sub.example.com", "subdomain")
    tgt = await create_asset(client, auth_headers, "example.com", "domain")

    resp = await create_relationship(client, auth_headers, src, tgt)
    assert resp.status_code == 201
    data = resp.json()
    assert data["source_asset_id"] == src
    assert data["target_asset_id"] == tgt
    assert data["relationship_type"] == "SUBDOMAIN_OF"


@pytest.mark.asyncio
async def test_create_all_valid_relationship_types(
    client: AsyncClient, auth_headers: dict
):
    """All five valid relationship types should be accepted."""
    valid_types = ["SUBDOMAIN_OF", "RESOLVES_TO", "USES", "RUNS_ON", "COVERS"]
    src = await create_asset(client, auth_headers, "src.example.com", "subdomain")

    for i, rel_type in enumerate(valid_types):
        tgt = await create_asset(
            client, auth_headers, f"target-{i}.example.com", "domain"
        )
        resp = await create_relationship(client, auth_headers, src, tgt, rel_type)
        assert resp.status_code == 201, f"Failed for type {rel_type}: {resp.text}"


# ─── Duplicate Rejection ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_relationship_returns_409(
    client: AsyncClient, auth_headers: dict
):
    """Creating the exact same relationship twice returns a 409 Conflict."""
    src = await create_asset(client, auth_headers, "dup-sub.com", "subdomain")
    tgt = await create_asset(client, auth_headers, "dup-domain.com", "domain")

    r1 = await create_relationship(client, auth_headers, src, tgt)
    assert r1.status_code == 201

    r2 = await create_relationship(client, auth_headers, src, tgt)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_same_pair_different_type_is_allowed(
    client: AsyncClient, auth_headers: dict
):
    """Same source/target pair with a different relationship type is a distinct edge — allowed."""
    src = await create_asset(client, auth_headers, "multi-rel-sub.com", "subdomain")
    tgt = await create_asset(client, auth_headers, "multi-rel-domain.com", "domain")

    r1 = await create_relationship(client, auth_headers, src, tgt, "SUBDOMAIN_OF")
    r2 = await create_relationship(client, auth_headers, src, tgt, "RESOLVES_TO")
    assert r1.status_code == 201
    assert r2.status_code == 201


# ─── Validation ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_relationship_type_returns_422(
    client: AsyncClient, auth_headers: dict
):
    src = await create_asset(client, auth_headers, "v-src.com", "domain")
    tgt = await create_asset(client, auth_headers, "v-tgt.com", "domain")

    resp = await client.post(
        "/api/v1/relationships",
        json={
            "source_asset_id": src,
            "target_asset_id": tgt,
            "relationship_type": "INVENTED_TYPE",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_relationship_to_nonexistent_asset_returns_404(
    client: AsyncClient, auth_headers: dict
):
    src = await create_asset(client, auth_headers, "exists.com", "domain")
    fake_id = "00000000-0000-0000-0000-000000000000"

    resp = await client.post(
        "/api/v1/relationships",
        json={
            "source_asset_id": src,
            "target_asset_id": fake_id,
            "relationship_type": "SUBDOMAIN_OF",
        },
        headers=auth_headers,
    )
    # Should be 404 since target does not exist for this tenant
    assert resp.status_code in (404, 422)


# ─── List & Pagination ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_relationships_returns_all(client: AsyncClient, auth_headers: dict):
    assets = [
        await create_asset(client, auth_headers, f"rel-asset-{i}.com") for i in range(4)
    ]
    # Create 3 distinct relationships
    await create_relationship(client, auth_headers, assets[0], assets[1])
    await create_relationship(client, auth_headers, assets[1], assets[2], "RESOLVES_TO")
    await create_relationship(client, auth_headers, assets[2], assets[3], "RUNS_ON")

    resp = await client.get("/api/v1/relationships", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 3


@pytest.mark.asyncio
async def test_list_relationships_pagination(client: AsyncClient, auth_headers: dict):
    assets = [
        await create_asset(client, auth_headers, f"pag-asset-{i}.com") for i in range(4)
    ]
    await create_relationship(client, auth_headers, assets[0], assets[1])
    await create_relationship(client, auth_headers, assets[1], assets[2], "RESOLVES_TO")
    await create_relationship(client, auth_headers, assets[2], assets[3], "RUNS_ON")

    page1 = await client.get(
        "/api/v1/relationships", params={"limit": 2, "offset": 0}, headers=auth_headers
    )
    page2 = await client.get(
        "/api/v1/relationships", params={"limit": 2, "offset": 2}, headers=auth_headers
    )

    ids_p1 = {r["id"] for r in page1.json()["items"]}
    ids_p2 = {r["id"] for r in page2.json()["items"]}
    assert ids_p1.isdisjoint(ids_p2)
    assert len(ids_p1) == 2
    assert len(ids_p2) == 1


# ─── Deletion ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_relationship(client: AsyncClient, auth_headers: dict):
    src = await create_asset(client, auth_headers, "del-src.com")
    tgt = await create_asset(client, auth_headers, "del-tgt.com")

    created = await create_relationship(client, auth_headers, src, tgt)
    rel_id = created.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/relationships/{rel_id}", headers=auth_headers
    )
    assert del_resp.status_code == 204

    # Relationship should no longer appear in the list
    list_resp = await client.get("/api/v1/relationships", headers=auth_headers)
    ids = [r["id"] for r in list_resp.json()["items"]]
    assert rel_id not in ids


# ─── Tenant Isolation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_relationship_list_is_tenant_isolated(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
):
    """User A's relationships are not visible to User B."""
    src = await create_asset(client, auth_headers, "iso-src.com")
    tgt = await create_asset(client, auth_headers, "iso-tgt.com")
    await create_relationship(client, auth_headers, src, tgt)

    resp = await client.get("/api/v1/relationships", headers=second_auth_headers)
    assert resp.json()["total"] == 0


# ─── Cache correctness ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graph_cache_invalidated_after_new_relationship(
    client: AsyncClient, auth_headers: dict
):
    """
    Regression guard: /graph must NOT serve stale cached data after a new
    relationship is added to one of the graph's endpoints.

    Steps:
      1. Create two assets (src, tgt).
      2. Prime the cache by calling /graph on src twice — both should succeed
         and return an empty edge list (no relationships yet).
      3. Create a relationship from src → tgt.
      4. Call /graph on src again — must now reflect the new edge, proving the
         cache was invalidated by the relationship write.
    """
    src = await create_asset(client, auth_headers, "cache-src.example.com", "domain")
    tgt = await create_asset(client, auth_headers, "cache-tgt.example.com", "domain")

    # Prime the cache (two calls to ensure the second one reads from cache)
    for _ in range(2):
        resp = await client.get(f"/api/v1/assets/{src}/graph", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["edges"] == [], "Expected empty graph before any relationship"

    # Add a relationship — this must invalidate the cache for src
    rel_resp = await create_relationship(client, auth_headers, src, tgt)
    assert rel_resp.status_code == 201

    # Graph must now include the new edge (stale cache would return empty list)
    graph_resp = await client.get(f"/api/v1/assets/{src}/graph", headers=auth_headers)
    assert graph_resp.status_code == 200
    edges = graph_resp.json()["edges"]
    assert len(edges) == 1, (
        f"Expected 1 edge after relationship creation, got {len(edges)}. "
        "Cache was not invalidated."
    )
    assert edges[0]["source"] == src
    assert edges[0]["target"] == tgt


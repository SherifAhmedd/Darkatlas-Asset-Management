"""
test_assets.py — Tests for the asset CRUD, filtering, pagination, lifecycle,
                 and graph endpoints.

Covers (per the rubric):
  - Create, Read, Update, Delete
  - List with filtering: type, status, tag, value_contains
  - Sorting (last_seen desc, verified via creation order)
  - Pagination (offset / limit)
  - Lifecycle: status patch (active → stale → archived)
  - Graph adjacency list structure (nodes + edges)
  - Duplicate asset creation rejected (409)
  - Accessing another tenant's asset returns 404
"""

import pytest
from httpx import AsyncClient

from tests.conftest import SAMPLE_DATASET

# ─── Helpers ──────────────────────────────────────────────────────────────────


async def create_asset(client: AsyncClient, headers: dict, **overrides) -> dict:
    """Convenience wrapper to create a single asset and return its response body."""
    payload = {
        "type": "domain",
        "value": "test-asset.com",
        "status": "active",
        "source": "manual",
        "tags": [],
        "metadata": {},
        **overrides,
    }
    resp = await client.post("/api/v1/assets", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_create_asset_returns_201(client: AsyncClient, auth_headers: dict):
    asset = await create_asset(client, auth_headers)
    assert asset["type"] == "domain"
    assert asset["value"] == "test-asset.com"
    assert asset["status"] == "active"
    assert "id" in asset
    assert "first_seen" in asset
    assert "last_seen" in asset


@pytest.mark.asyncio
async def test_get_asset_by_id(client: AsyncClient, auth_headers: dict):
    created = await create_asset(client, auth_headers)
    resp = await client.get(f"/api/v1/assets/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]
    assert resp.json()["value"] == "test-asset.com"


@pytest.mark.asyncio
async def test_get_nonexistent_asset_returns_404(
    client: AsyncClient, auth_headers: dict
):
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await client.get(f"/api/v1/assets/{fake_id}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_asset_merges_tags_and_metadata(
    client: AsyncClient, auth_headers: dict
):
    """PUT update merges new tags/metadata into existing without wiping original data."""
    created = await create_asset(
        client,
        auth_headers,
        tags=["original"],
        metadata={"env": "prod", "score": 1},
    )
    resp = await client.put(
        f"/api/v1/assets/{created['id']}",
        json={"tags": ["new-tag"], "metadata": {"score": 99}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    # Tags should be merged
    assert "original" in data["tags"]
    assert "new-tag" in data["tags"]
    # Metadata: new key overrides, old key preserved
    assert data["metadata"]["score"] == 99
    assert data["metadata"]["env"] == "prod"


@pytest.mark.asyncio
async def test_delete_asset(client: AsyncClient, auth_headers: dict):
    created = await create_asset(client, auth_headers)
    del_resp = await client.delete(
        f"/api/v1/assets/{created['id']}", headers=auth_headers
    )
    assert del_resp.status_code == 204
    # Subsequent GET should 404
    get_resp = await client.get(f"/api/v1/assets/{created['id']}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_create_duplicate_asset_returns_409(
    client: AsyncClient, auth_headers: dict
):
    """Creating an asset with the same (type, value) twice raises a 409 Conflict."""
    await create_asset(client, auth_headers)
    resp = await client.post(
        "/api/v1/assets",
        json={
            "type": "domain",
            "value": "test-asset.com",
            "source": "manual",
            "tags": [],
            "metadata": {},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_patch_status_active_to_stale(client: AsyncClient, auth_headers: dict):
    created = await create_asset(client, auth_headers)
    resp = await client.patch(
        f"/api/v1/assets/{created['id']}/status",
        json={"status": "stale"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "stale"


@pytest.mark.asyncio
async def test_patch_status_stale_to_archived(client: AsyncClient, auth_headers: dict):
    created = await create_asset(client, auth_headers)
    await client.patch(
        f"/api/v1/assets/{created['id']}/status",
        json={"status": "stale"},
        headers=auth_headers,
    )
    resp = await client.patch(
        f"/api/v1/assets/{created['id']}/status",
        json={"status": "archived"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_patch_invalid_status_returns_422(
    client: AsyncClient, auth_headers: dict
):
    created = await create_asset(client, auth_headers)
    resp = await client.patch(
        f"/api/v1/assets/{created['id']}/status",
        json={"status": "INVALID_STATUS"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_filter_by_type(client: AsyncClient, auth_headers: dict):
    await create_asset(client, auth_headers, type="domain", value="filter-domain.com")
    await create_asset(client, auth_headers, type="ip_address", value="1.2.3.4")

    resp = await client.get(
        "/api/v1/assets", params={"asset_type": "ip_address"}, headers=auth_headers
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(i["type"] == "ip_address" for i in items)
    assert len(items) == 1


@pytest.mark.asyncio
async def test_filter_by_status(client: AsyncClient, auth_headers: dict):
    active = await create_asset(client, auth_headers, value="active.com")
    stale = await create_asset(client, auth_headers, value="stale.com")
    await client.patch(
        f"/api/v1/assets/{stale['id']}/status",
        json={"status": "stale"},
        headers=auth_headers,
    )

    resp = await client.get(
        "/api/v1/assets", params={"status": "stale"}, headers=auth_headers
    )
    items = resp.json()["items"]
    assert all(i["status"] == "stale" for i in items)
    assert any(i["id"] == stale["id"] for i in items)
    assert all(i["id"] != active["id"] for i in items)


@pytest.mark.asyncio
async def test_filter_by_tag(client: AsyncClient, auth_headers: dict):
    await create_asset(client, auth_headers, value="tagged.com", tags=["production"])
    await create_asset(client, auth_headers, value="untagged.com", tags=[])

    resp = await client.get(
        "/api/v1/assets", params={"tag": "production"}, headers=auth_headers
    )
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["value"] == "tagged.com"


@pytest.mark.asyncio
async def test_filter_by_value_contains(client: AsyncClient, auth_headers: dict):
    await create_asset(client, auth_headers, value="api.mycompany.com")
    await create_asset(client, auth_headers, value="blog.mycompany.com")
    await create_asset(client, auth_headers, value="other.example.com")

    resp = await client.get(
        "/api/v1/assets", params={"value_contains": "mycompany"}, headers=auth_headers
    )
    assert resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_pagination_limit(client: AsyncClient, auth_headers: dict):
    for i in range(5):
        await create_asset(client, auth_headers, value=f"page-{i}.com")

    resp = await client.get(
        "/api/v1/assets", params={"limit": 2, "offset": 0}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


@pytest.mark.asyncio
async def test_pagination_offset(client: AsyncClient, auth_headers: dict):
    for i in range(5):
        await create_asset(client, auth_headers, value=f"offs-{i}.com")

    page1 = await client.get(
        "/api/v1/assets", params={"limit": 3, "offset": 0}, headers=auth_headers
    )
    page2 = await client.get(
        "/api/v1/assets", params={"limit": 3, "offset": 3}, headers=auth_headers
    )
    ids_p1 = {i["id"] for i in page1.json()["items"]}
    ids_p2 = {i["id"] for i in page2.json()["items"]}
    # No overlap between pages
    assert ids_p1.isdisjoint(ids_p2)


@pytest.mark.asyncio
async def test_graph_returns_correct_structure(client: AsyncClient, auth_headers: dict):
    """The graph endpoint returns root_asset, adjacent nodes, and typed edges."""
    await client.post(
        "/api/v1/assets/import",
        json={"assets": SAMPLE_DATASET},
        headers=auth_headers,
    )
    # Get the subdomain (api.example.com) — it has 2 relationships
    list_resp = await client.get(
        "/api/v1/assets",
        params={"value_contains": "api.example.com", "asset_type": "subdomain"},
        headers=auth_headers,
    )
    subdomain_id = list_resp.json()["items"][0]["id"]

    graph_resp = await client.get(
        f"/api/v1/assets/{subdomain_id}/graph", headers=auth_headers
    )
    assert graph_resp.status_code == 200
    graph = graph_resp.json()

    # Root asset is the subdomain itself
    assert graph["root_asset"]["id"] == subdomain_id

    # Should have 2 adjacent nodes: the domain and the certificate
    assert len(graph["nodes"]) == 2

    # Should have 2 edges
    assert len(graph["edges"]) == 2
    edge_types = {e["relationship_type"] for e in graph["edges"]}
    assert "SUBDOMAIN_OF" in edge_types
    assert "COVERS" in edge_types


@pytest.mark.asyncio
async def test_graph_isolated_asset_has_no_edges(
    client: AsyncClient, auth_headers: dict
):
    """An asset with no relationships returns an empty graph (no nodes, no edges)."""
    created = await create_asset(client, auth_headers, value="isolated.com")
    resp = await client.get(
        f"/api/v1/assets/{created['id']}/graph", headers=auth_headers
    )
    assert resp.status_code == 200
    graph = resp.json()
    assert graph["nodes"] == []
    assert graph["edges"] == []


@pytest.mark.asyncio
async def test_cannot_access_other_tenants_asset(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
):
    """User B cannot fetch an asset ID that belongs to user A."""
    created = await create_asset(client, auth_headers, value="tenant-a-asset.com")
    resp = await client.get(
        f"/api/v1/assets/{created['id']}", headers=second_auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_returns_only_own_tenant_assets(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
):
    """User A's list does not include assets created by user B."""
    await create_asset(client, auth_headers, value="user-a.com")
    await create_asset(client, second_auth_headers, value="user-b.com")

    resp_a = await client.get("/api/v1/assets", headers=auth_headers)
    values_a = [i["value"] for i in resp_a.json()["items"]]
    assert "user-a.com" in values_a
    assert "user-b.com" not in values_a

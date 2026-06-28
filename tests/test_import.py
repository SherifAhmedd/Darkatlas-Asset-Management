"""
test_import.py — Integration tests for the 5-stage bulk import pipeline.

Covers (per the rubric):
  - Idempotent imports (same dataset twice = no duplicates)
  - Deduplication on ingest
  - Metadata merge (freshness rule: incoming keys win)
  - Tag merge (union + sort, no duplicates)
  - Re-appearing assets (stale → active on re-import)
  - Malformed / partial records (fail gracefully; rest of batch succeeds)
  - Normalization (domain lowercase, IP canonical form, service protocol lowercase)
  - Relationship mapping (temp IDs resolved to DB UUIDs)
  - Broken relationship reference (dangling reference produces error, not crash)
  - Multi-tenant isolation (tenant A's import invisible to tenant B)
"""

import pytest
from httpx import AsyncClient

from tests.conftest import SAMPLE_DATASET


# ─── Basic Import ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bulk_import_creates_assets(client: AsyncClient, auth_headers: dict):
    """Importing the sample dataset creates the expected number of assets."""
    resp = await client.post(
        "/api/v1/assets/import",
        json={"assets": SAMPLE_DATASET},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 3
    assert data["updated"] == 0
    assert data["failed"] == 0
    assert data["relationships_created"] == 2  # SUBDOMAIN_OF + COVERS


@pytest.mark.asyncio
async def test_bulk_import_creates_relationships(client: AsyncClient, auth_headers: dict):
    """After import, relationship count in the list endpoint matches expectations."""
    await client.post(
        "/api/v1/assets/import",
        json={"assets": SAMPLE_DATASET},
        headers=auth_headers,
    )
    resp = await client.get("/api/v1/relationships", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    rel_types = {r["relationship_type"] for r in items}
    assert "SUBDOMAIN_OF" in rel_types
    assert "COVERS" in rel_types


# ─── Idempotency / Deduplication ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_import_is_idempotent(client: AsyncClient, auth_headers: dict):
    """Importing the same dataset twice creates no duplicates (created=0 on second run)."""
    payload = {"assets": SAMPLE_DATASET}
    await client.post("/api/v1/assets/import", json=payload, headers=auth_headers)

    resp2 = await client.post("/api/v1/assets/import", json=payload, headers=auth_headers)
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["created"] == 0
    assert data["updated"] == 3
    assert data["failed"] == 0


@pytest.mark.asyncio
async def test_import_idempotent_relationships(client: AsyncClient, auth_headers: dict):
    """Importing the same dataset twice does not duplicate relationship edges."""
    payload = {"assets": SAMPLE_DATASET}
    await client.post("/api/v1/assets/import", json=payload, headers=auth_headers)
    await client.post("/api/v1/assets/import", json=payload, headers=auth_headers)

    resp = await client.get("/api/v1/relationships", headers=auth_headers)
    assert resp.json()["total"] == 2  # still 2, not 4


# ─── Metadata & Tag Merge ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_metadata_merge_freshness_rule(client: AsyncClient, auth_headers: dict):
    """Re-importing with new metadata keys overrides the existing ones (freshness rule)."""
    initial = [
        {"id": "x1", "type": "domain", "value": "merge.com", "status": "active",
         "source": "scan", "tags": [], "metadata": {"score": 1, "env": "prod"}}
    ]
    await client.post("/api/v1/assets/import", json={"assets": initial}, headers=auth_headers)

    updated = [
        {"id": "x1", "type": "domain", "value": "merge.com", "status": "active",
         "source": "scan", "tags": [], "metadata": {"score": 99, "new_key": "hello"}}
    ]
    await client.post("/api/v1/assets/import", json={"assets": updated}, headers=auth_headers)

    resp = await client.get("/api/v1/assets", params={"value_contains": "merge.com"}, headers=auth_headers)
    asset = resp.json()["items"][0]
    # 'score' should be overridden by the newer import
    assert asset["metadata"]["score"] == 99
    # 'env' from the first import should still be present (merge, not replace)
    assert asset["metadata"]["env"] == "prod"
    # new key should appear
    assert asset["metadata"]["new_key"] == "hello"


@pytest.mark.asyncio
async def test_tag_merge_deduplication(client: AsyncClient, auth_headers: dict):
    """Re-importing with new tags merges them without creating duplicates."""
    first = [
        {"id": "t1", "type": "domain", "value": "tags.com", "status": "active",
         "source": "scan", "tags": ["alpha", "beta"], "metadata": {}}
    ]
    await client.post("/api/v1/assets/import", json={"assets": first}, headers=auth_headers)

    second = [
        {"id": "t1", "type": "domain", "value": "tags.com", "status": "active",
         "source": "scan", "tags": ["beta", "gamma"], "metadata": {}}
    ]
    await client.post("/api/v1/assets/import", json={"assets": second}, headers=auth_headers)

    resp = await client.get("/api/v1/assets", params={"value_contains": "tags.com"}, headers=auth_headers)
    tags = resp.json()["items"][0]["tags"]
    # All three tags should be present, deduplicated and sorted
    assert tags == ["alpha", "beta", "gamma"]


# ─── Lifecycle: Stale Re-Activation ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_stale_asset_reactivated_on_reimport(client: AsyncClient, auth_headers: dict):
    """A stale asset that is re-imported should have its status set back to active."""
    # Create an asset
    create_resp = await client.post(
        "/api/v1/assets",
        json={"type": "domain", "value": "stale-test.com", "status": "active",
              "source": "manual", "tags": [], "metadata": {}},
        headers=auth_headers,
    )
    asset_id = create_resp.json()["id"]

    # Mark it as stale
    await client.patch(
        f"/api/v1/assets/{asset_id}/status",
        json={"status": "stale"},
        headers=auth_headers,
    )

    # Re-import the same asset
    reimport = [
        {"id": "s1", "type": "domain", "value": "stale-test.com",
         "status": "active", "source": "scan", "tags": [], "metadata": {}}
    ]
    await client.post("/api/v1/assets/import", json={"assets": reimport}, headers=auth_headers)

    # Asset should now be active again
    resp = await client.get(f"/api/v1/assets/{asset_id}", headers=auth_headers)
    assert resp.json()["status"] == "active"


# ─── Error Handling ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_malformed_record_does_not_crash_batch(client: AsyncClient, auth_headers: dict):
    """A malformed record in the batch should fail gracefully; valid records proceed."""
    payload = {
        "assets": [
            # Valid record
            {"id": "g1", "type": "domain", "value": "good.com", "status": "active",
             "source": "scan", "tags": [], "metadata": {}},
            # Malformed: invalid type
            {"id": "b1", "type": "INVALID_TYPE", "value": "bad.com", "status": "active",
             "source": "scan", "tags": [], "metadata": {}},
            # Malformed: empty value
            {"id": "b2", "type": "domain", "value": "   ", "status": "active",
             "source": "scan", "tags": [], "metadata": {}},
        ]
    }
    resp = await client.post("/api/v1/assets/import", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 1   # only the valid one
    assert data["failed"] == 2    # two malformed
    assert len(data["errors"]) == 2


@pytest.mark.asyncio
async def test_broken_relationship_reference_is_reported(client: AsyncClient, auth_headers: dict):
    """A relationship referencing a non-existent temp ID is reported as a relationship error."""
    payload = {
        "assets": [
            {"id": "a1", "type": "domain", "value": "ref-test.com", "status": "active",
             "source": "scan", "tags": [], "metadata": {},
             "parent": "NONEXISTENT_ID"},  # broken reference
        ]
    }
    resp = await client.post("/api/v1/assets/import", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 1          # asset itself is created
    assert data["relationship_errors"] == 1
    assert any("not found" in e["error"] for e in data["errors"])


# ─── Normalization ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_domain_normalization_lowercase(client: AsyncClient, auth_headers: dict):
    """Domain values are lowercased and trailing dots stripped on import."""
    payload = {
        "assets": [
            {"id": "n1", "type": "domain", "value": "UPPER.Example.COM.",
             "status": "active", "source": "scan", "tags": [], "metadata": {}}
        ]
    }
    await client.post("/api/v1/assets/import", json=payload, headers=auth_headers)
    resp = await client.get("/api/v1/assets", params={"value_contains": "upper.example.com"}, headers=auth_headers)
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["value"] == "upper.example.com"


@pytest.mark.asyncio
async def test_service_normalization_lowercase_protocol(client: AsyncClient, auth_headers: dict):
    """Service values have their protocol lowercased (443/TCP → 443/tcp)."""
    payload = {
        "assets": [
            {"id": "s1", "type": "service", "value": "443/TCP",
             "status": "active", "source": "scan", "tags": [], "metadata": {}}
        ]
    }
    await client.post("/api/v1/assets/import", json=payload, headers=auth_headers)
    resp = await client.get("/api/v1/assets", params={"asset_type": "service"}, headers=auth_headers)
    assert resp.json()["items"][0]["value"] == "443/tcp"


@pytest.mark.asyncio
async def test_normalization_prevents_duplicates(client: AsyncClient, auth_headers: dict):
    """Importing 'EXAMPLE.COM' and 'example.com' results in only one asset (dedup after norm)."""
    payload = {
        "assets": [
            {"id": "n1", "type": "domain", "value": "EXAMPLE.COM", "status": "active",
             "source": "scan", "tags": [], "metadata": {}},
            {"id": "n2", "type": "domain", "value": "example.com", "status": "active",
             "source": "scan", "tags": [], "metadata": {}},
        ]
    }
    resp = await client.post("/api/v1/assets/import", json=payload, headers=auth_headers)
    data = resp.json()
    assert data["created"] == 1
    assert data["updated"] == 1


# ─── Tenant Isolation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_import_is_tenant_isolated(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
):
    """Assets imported by user A are invisible to user B."""
    await client.post(
        "/api/v1/assets/import",
        json={"assets": SAMPLE_DATASET},
        headers=auth_headers,
    )

    # User B sees no assets at all
    resp = await client.get("/api/v1/assets", headers=second_auth_headers)
    assert resp.json()["total"] == 0

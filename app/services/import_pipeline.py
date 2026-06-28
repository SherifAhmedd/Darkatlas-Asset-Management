import ipaddress
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.relationship import Relationship
from app.repositories.asset_repository import AssetRepository
from app.repositories.relationship_repository import RelationshipRepository
from app.schemas.import_schema import (
    ImportAssetItem,
    ImportError,
    ImportResult,
)

# Mapping from payload linkage key → relationship type enum value
LINKAGE_MAP = {
    "parent": "SUBDOMAIN_OF",
    "resolves_to": "RESOLVES_TO",
    "covers": "COVERS",
    "runs_on": "RUNS_ON",
    "uses": "USES",
}


class ImportPipeline:
    """
    5-Stage Idempotent Bulk Import Pipeline.

    Stage 1: Validation    — Validate each item's schema (non-blocking per item)
    Stage 2: Normalization — Canonicalize values (lowercase domains, strip spaces)
    Stage 3: Deduplication — Bulk lookup existing assets by (type, value)
    Stage 4: Merge/Create  — Merge metadata + tags into existing OR create new
    Stage 5: Relationships — Map temp IDs to DB UUIDs and write graph edges
    """

    def __init__(self, db: AsyncSession, tenant_id: UUID):
        self.db = db
        self.tenant_id = tenant_id
        self.asset_repo = AssetRepository(db=db, tenant_id=tenant_id)
        self.rel_repo = RelationshipRepository(db=db, tenant_id=tenant_id)

    async def execute(self, raw_items: List[Dict[str, Any]]) -> ImportResult:
        """Run all 5 stages and return detailed statistics."""
        errors: List[ImportError] = []

        # Stage 1: Validation
        valid_items: List[ImportAssetItem] = []
        for index, raw in enumerate(raw_items):
            try:
                item = ImportAssetItem(**raw)
                valid_items.append(item)
            except Exception as e:
                errors.append(
                    ImportError(
                        index=index,
                        temp_id=raw.get("id"),
                        value=raw.get("value"),
                        error=str(e),
                    )
                )

        # Stage 2: Normalization
        for item in valid_items:
            item.value = self._normalize(item.type, item.value)

        # Stage 3: Deduplication
        pairs: List[Tuple[str, str]] = [(item.type, item.value) for item in valid_items]
        existing_map: Dict[Tuple[str, str], Asset] = (
            await self.asset_repo.get_existing_by_type_value_pairs(pairs)
        )

        # Stage 4: Merge / Create
        created_count = 0
        updated_count = 0
        # Maps temp_id → DB UUID for Stage 5
        temp_id_to_uuid: Dict[str, UUID] = {}

        now = datetime.now(timezone.utc)

        for item in valid_items:
            key = (item.type, item.value)
            existing = existing_map.get(key)

            if existing:
                # Asset already exists — merge and update
                if existing.status in ("stale", "archived"):
                    existing.status = "active"

                existing.last_seen = now

                # Metadata: incoming keys override existing (freshness rule)
                merged_metadata = dict(existing.asset_metadata)
                merged_metadata.update(item.metadata)
                existing.asset_metadata = merged_metadata

                # Tags: merge, deduplicate, sort for determinism
                existing.tags = sorted(list(set(existing.tags + item.tags)))

                await self.db.flush()
                temp_id_to_uuid[item.id] = existing.id
                updated_count += 1

            else:
                # New asset — create it
                new_asset = Asset(
                    tenant_id=self.tenant_id,
                    type=item.type,
                    value=item.value,
                    status=item.status,
                    source=item.source,
                    tags=sorted(list(set(item.tags))),
                    asset_metadata=item.metadata,
                    first_seen=now,
                    last_seen=now,
                )
                self.db.add(new_asset)
                await self.db.flush()
                await self.db.refresh(new_asset)

                # Add to existing_map so subsequent duplicates in the same batch get merged
                existing_map[key] = new_asset

                temp_id_to_uuid[item.id] = new_asset.id
                created_count += 1

        # Stage 5: Relationship Mapping
        relationships_created = 0
        relationship_errors = 0
        candidate_edges: List[Tuple[UUID, UUID, str]] = []

        for item in valid_items:
            source_uuid = temp_id_to_uuid.get(item.id)
            if not source_uuid:
                continue

            for linkage_key, rel_type in LINKAGE_MAP.items():
                target_temp_id = getattr(item, linkage_key, None)
                if not target_temp_id:
                    continue

                target_uuid = temp_id_to_uuid.get(target_temp_id)
                if not target_uuid:
                    # Target reference not found in this batch
                    errors.append(
                        ImportError(
                            index=-1,
                            temp_id=item.id,
                            value=item.value,
                            error=(
                                f"Relationship mapping failed: "
                                f"Target reference '{target_temp_id}' not found in batch"
                            ),
                        )
                    )
                    relationship_errors += 1
                    continue

                candidate_edges.append((source_uuid, target_uuid, rel_type))

        # Deduplicate against existing relationships in DB
        if candidate_edges:
            already_existing = await self.rel_repo.get_existing_by_edge_tuples(
                candidate_edges
            )

            for source_uuid, target_uuid, rel_type in candidate_edges:
                if (source_uuid, target_uuid, rel_type) in already_existing:
                    continue  # Skip duplicates

                new_rel = Relationship(
                    tenant_id=self.tenant_id,
                    source_asset_id=source_uuid,
                    target_asset_id=target_uuid,
                    relationship_type=rel_type,
                )
                self.db.add(new_rel)
                relationships_created += 1

            await self.db.flush()

        return ImportResult(
            status="completed",
            processed=len(raw_items),
            created=created_count,
            updated=updated_count,
            failed=len([e for e in errors if e.index >= 0]),
            relationships_created=relationships_created,
            relationship_errors=relationship_errors,
            errors=errors,
        )

    # Normalization Helpers

    def _normalize(self, asset_type: str, value: str) -> str:
        """Canonicalize asset values based on type."""
        value = value.strip()

        if asset_type in ("domain", "subdomain"):
            return value.lower().rstrip(".")

        if asset_type == "ip_address":
            try:
                # Validates and normalizes IP (handles leading zeros etc.)
                return str(ipaddress.ip_address(value))
            except ValueError:
                return (
                    value  # Return as-is; will surface as a validation error upstream
                )

        if asset_type == "service":
            # Normalize protocol to lowercase: "443/TCP" → "443/tcp"
            if "/" in value:
                port, proto = value.split("/", 1)
                return f"{port.strip()}/{proto.strip().lower()}"
            return value

        if asset_type == "technology":
            return value.lower()

        return value

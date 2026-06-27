from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.relationship import Relationship
from app.repositories.asset_repository import AssetRepository
from app.repositories.relationship_repository import RelationshipRepository
from app.schemas.asset import (
    AssetCreateRequest,
    AssetUpdateRequest,
    AssetGraphResponse,
    GraphNode,
    GraphEdge,
)
from app.core.exceptions import NotFoundException, ConflictException


class AssetService:
    """
    Business logic layer for asset operations.
    Coordinates between the AssetRepository and RelationshipRepository.
    """

    def __init__(self, db: AsyncSession, tenant_id: UUID):
        self.db = db
        self.tenant_id = tenant_id
        self.asset_repo = AssetRepository(db=db, tenant_id=tenant_id)
        self.rel_repo = RelationshipRepository(db=db, tenant_id=tenant_id)

    async def get_by_id(self, asset_id: UUID) -> Asset:
        """Fetch a single asset by ID. Raises NotFoundException if not found."""
        asset = await self.asset_repo.get_by_id(asset_id)
        if not asset:
            raise NotFoundException(
                message="Asset not found",
                detail={"asset_id": str(asset_id)}
            )
        return asset

    async def list_assets(
        self,
        asset_type: Optional[str] = None,
        status: Optional[str] = None,
        tag: Optional[str] = None,
        value_contains: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[Asset]:
        """List assets with optional filters and pagination."""
        return await self.asset_repo.get_filtered(
            asset_type=asset_type,
            status=status,
            tag=tag,
            value_contains=value_contains,
            offset=offset,
            limit=limit,
        )

    async def create_asset(self, payload: AssetCreateRequest) -> Asset:
        """
        Create a new asset.
        Raises ConflictException if an asset with the same (type, value)
        already exists for this tenant.
        """
        # Check for duplicate
        existing = await self.asset_repo.get_existing_by_type_value_pairs(
            [(payload.type, payload.value)]
        )
        if existing:
            raise ConflictException(
                message="An asset with this type and value already exists",
                detail={"type": payload.type, "value": payload.value}
            )

        now = datetime.now(timezone.utc)
        new_asset = Asset(
            tenant_id=self.tenant_id,
            type=payload.type,
            value=payload.value.strip(),
            status=payload.status,
            source=payload.source,
            tags=sorted(list(set(payload.tags))),
            metadata=payload.metadata,
            first_seen=now,
            last_seen=now,
        )
        return await self.asset_repo.create(new_asset)

    async def update_asset(self, asset_id: UUID, payload: AssetUpdateRequest) -> Asset:
        """Update mutable fields (tags, metadata, source) of an existing asset."""
        asset = await self.get_by_id(asset_id)

        if payload.tags is not None:
            # Merge and deduplicate tags deterministically
            asset.tags = sorted(list(set(asset.tags + payload.tags)))
        if payload.metadata is not None:
            # Incoming keys override existing ones (freshness rule)
            merged = dict(asset.metadata)
            merged.update(payload.metadata)
            asset.metadata = merged
        if payload.source is not None:
            asset.source = payload.source

        asset.last_seen = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(asset)
        return asset

    async def update_status(self, asset_id: UUID, new_status: str) -> Asset:
        """Patch only the lifecycle status of an asset."""
        asset = await self.asset_repo.update_status(asset_id, new_status)
        if not asset:
            raise NotFoundException(
                message="Asset not found",
                detail={"asset_id": str(asset_id)}
            )
        return asset

    async def delete_asset(self, asset_id: UUID) -> None:
        """Delete an asset by ID. Raises NotFoundException if not found."""
        deleted = await self.asset_repo.delete_by_id(asset_id)
        if not deleted:
            raise NotFoundException(
                message="Asset not found",
                detail={"asset_id": str(asset_id)}
            )

    async def get_graph(self, asset_id: UUID) -> AssetGraphResponse:
        """
        Build the adjacency list graph for a given asset.
        Returns the root asset, all adjacent assets as nodes,
        and all relationships as edges.
        """
        root = await self.get_by_id(asset_id)
        relationships: Sequence[Relationship] = await self.rel_repo.get_adjacent(asset_id)

        # Collect all unique adjacent asset IDs
        adjacent_ids: set[UUID] = set()
        for rel in relationships:
            if rel.source_asset_id != asset_id:
                adjacent_ids.add(rel.source_asset_id)
            if rel.target_asset_id != asset_id:
                adjacent_ids.add(rel.target_asset_id)

        # Fetch adjacent assets in bulk
        nodes: list[GraphNode] = []
        for adj_id in adjacent_ids:
            adj_asset = await self.asset_repo.get_by_id(adj_id)
            if adj_asset:
                nodes.append(GraphNode(
                    id=adj_asset.id,
                    type=adj_asset.type,
                    value=adj_asset.value,
                    status=adj_asset.status,
                ))

        edges = [
            GraphEdge(
                source=rel.source_asset_id,
                target=rel.target_asset_id,
                relationship_type=rel.relationship_type,
            )
            for rel in relationships
        ]

        return AssetGraphResponse(
            root_asset=GraphNode(
                id=root.id,
                type=root.type,
                value=root.value,
                status=root.status,
            ),
            nodes=nodes,
            edges=edges,
        )

from typing import Sequence
from uuid import UUID
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.relationship import Relationship
from app.repositories.base_repository import BaseRepository


class RelationshipRepository(BaseRepository[Relationship]):
    """
    Relationship-specific repository providing graph traversal
    and bulk deduplication utilities for the import pipeline.
    """

    def __init__(self, db: AsyncSession, tenant_id: UUID):
        super().__init__(model=Relationship, db=db, tenant_id=tenant_id)

    async def get_adjacent(self, asset_id: UUID) -> Sequence[Relationship]:
        """
        Fetch all relationships where the asset is either source OR target.
        Used by GET /assets/{id}/graph to build the adjacency list.
        """
        result = await self.db.execute(
            select(Relationship).where(
                Relationship.tenant_id == self.tenant_id,
                (Relationship.source_asset_id == asset_id)
                | (Relationship.target_asset_id == asset_id),
            )
        )
        return result.scalars().all()

    async def get_existing_by_edge_tuples(
        self,
        edges: list[tuple[UUID, UUID, str]],
    ) -> set[tuple[UUID, UUID, str]]:
        """
        Bulk deduplication check for the import pipeline Stage 5.

        Accepts a list of (source_id, target_id, relationship_type) tuples and
        returns the subset that already exists in the database as a set — so we
        can skip inserting duplicates without triggering unique constraint errors.
        """
        if not edges:
            return set()

        result = await self.db.execute(
            select(
                Relationship.source_asset_id,
                Relationship.target_asset_id,
                Relationship.relationship_type,
            ).where(
                Relationship.tenant_id == self.tenant_id,
                tuple_(
                    Relationship.source_asset_id,
                    Relationship.target_asset_id,
                    Relationship.relationship_type,
                ).in_(edges),
            )
        )
        rows = result.all()
        return {(r.source_asset_id, r.target_asset_id, r.relationship_type) for r in rows}

    async def get_by_source(self, source_asset_id: UUID) -> Sequence[Relationship]:
        """Fetch all outgoing relationships from a given source asset."""
        result = await self.db.execute(
            select(Relationship).where(
                Relationship.tenant_id == self.tenant_id,
                Relationship.source_asset_id == source_asset_id,
            )
        )
        return result.scalars().all()

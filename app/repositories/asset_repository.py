from typing import Optional, Sequence
from uuid import UUID
from sqlalchemy import select, update, and_, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.repositories.base_repository import BaseRepository


class AssetRepository(BaseRepository[Asset]):
    """
    Asset-specific repository with advanced query capabilities:
    - Filtered, paginated listing
    - Deduplication lookups by (type, value) pairs
    - Status updates for lifecycle management
    """

    def __init__(self, db: AsyncSession, tenant_id: UUID):
        super().__init__(model=Asset, db=db, tenant_id=tenant_id)

    async def get_filtered(
        self,
        asset_type: Optional[str] = None,
        status: Optional[str] = None,
        tag: Optional[str] = None,
        value_contains: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[Asset]:
        """
        List assets with optional filters:
        - asset_type: Filter by asset type enum value
        - status: Filter by lifecycle status (active/stale/archived)
        - tag: Filter assets that contain this tag in their tags array
        - value_contains: Case-insensitive substring match on asset value
        """
        filters = [Asset.tenant_id == self.tenant_id]

        if asset_type:
            filters.append(Asset.type == asset_type)
        if status:
            filters.append(Asset.status == status)
        if tag:
            # PostgreSQL ARRAY contains operator
            filters.append(Asset.tags.contains([tag]))
        if value_contains:
            filters.append(Asset.value.ilike(f"%{value_contains}%"))

        result = await self.db.execute(
            select(Asset)
            .where(and_(*filters))
            .order_by(Asset.last_seen.desc())
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()

    async def get_existing_by_type_value_pairs(
        self, pairs: list[tuple[str, str]]
    ) -> dict[tuple[str, str], Asset]:
        """
        Bulk deduplication lookup used by the import pipeline.

        Fetches all existing assets matching any (type, value) pair in the batch
        and returns them as a dict keyed by (type, value) for O(1) lookups.
        Uses SQLAlchemy's tuple_() for a proper PostgreSQL composite IN clause.
        """
        if not pairs:
            return {}

        result = await self.db.execute(
            select(Asset).where(
                Asset.tenant_id == self.tenant_id,
                tuple_(Asset.type, Asset.value).in_(pairs),
            )
        )
        assets = result.scalars().all()
        return {(a.type, a.value): a for a in assets}

    async def update_status(self, asset_id: UUID, new_status: str) -> Optional[Asset]:
        """
        Update an asset's lifecycle status (active / stale / archived).
        Returns the updated asset or None if not found for this tenant.
        """
        result = await self.db.execute(
            update(Asset)
            .where(
                Asset.id == asset_id,
                Asset.tenant_id == self.tenant_id,
            )
            .values(status=new_status)
            .returning(Asset)
        )
        return result.scalar_one_or_none()

from typing import Sequence
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.relationship import Relationship
from app.repositories.relationship_repository import RelationshipRepository
from app.repositories.asset_repository import AssetRepository
from app.schemas.relationship import RelationshipCreateRequest
from app.core.exceptions import NotFoundException, ConflictException


class RelationshipService:
    """
    Business logic for relationship CRUD.
    Validates that both assets exist for this tenant before
    creating a link, and prevents duplicate relationships.
    """

    def __init__(self, db: AsyncSession, tenant_id: UUID):
        self.db = db
        self.tenant_id = tenant_id
        self.rel_repo = RelationshipRepository(db=db, tenant_id=tenant_id)
        self.asset_repo = AssetRepository(db=db, tenant_id=tenant_id)

    async def create_relationship(
        self, payload: RelationshipCreateRequest
    ) -> Relationship:
        """
        Create a relationship link between two assets.

        Validates:
        - Both source and target assets exist for this tenant
        - The relationship does not already exist (no duplicates)
        """
        # Verify source asset belongs to this tenant
        source = await self.asset_repo.get_by_id(payload.source_asset_id)
        if not source:
            raise NotFoundException(
                message="Source asset not found",
                detail={"source_asset_id": str(payload.source_asset_id)}
            )

        # Verify target asset belongs to this tenant
        target = await self.asset_repo.get_by_id(payload.target_asset_id)
        if not target:
            raise NotFoundException(
                message="Target asset not found",
                detail={"target_asset_id": str(payload.target_asset_id)}
            )

        # Check for duplicate relationship
        existing = await self.rel_repo.get_existing_by_edge_tuples(
            [(payload.source_asset_id, payload.target_asset_id, payload.relationship_type)]
        )
        if existing:
            raise ConflictException(
                message="This relationship already exists",
                detail={
                    "source_asset_id": str(payload.source_asset_id),
                    "target_asset_id": str(payload.target_asset_id),
                    "relationship_type": payload.relationship_type,
                }
            )

        new_rel = Relationship(
            tenant_id=self.tenant_id,
            source_asset_id=payload.source_asset_id,
            target_asset_id=payload.target_asset_id,
            relationship_type=payload.relationship_type,
        )
        return await self.rel_repo.create(new_rel)

    async def list_relationships(
        self,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[Relationship]:
        """List all relationships for this tenant with pagination."""
        return await self.rel_repo.get_all(offset=offset, limit=limit)

    async def delete_relationship(self, relationship_id: UUID) -> None:
        """Delete a relationship by ID. Raises NotFoundException if not found."""
        deleted = await self.rel_repo.delete_by_id(relationship_id)
        if not deleted:
            raise NotFoundException(
                message="Relationship not found",
                detail={"relationship_id": str(relationship_id)}
            )

from typing import Generic, Optional, Sequence, Type, TypeVar
from uuid import UUID
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Generic repository providing common CRUD operations.

    Every read/write operation is automatically scoped to the
    authenticated user's tenant_id — preventing cross-org data leakage.
    """

    def __init__(self, model: Type[ModelType], db: AsyncSession, tenant_id: UUID):
        self.model = model
        self.db = db
        self.tenant_id = tenant_id

    async def get_by_id(self, resource_id: UUID) -> Optional[ModelType]:
        """Fetch a single record by primary key, scoped to this tenant."""
        result = await self.db.execute(
            select(self.model).where(
                self.model.id == resource_id,
                self.model.tenant_id == self.tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[ModelType]:
        """Fetch all records for this tenant with pagination."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.tenant_id == self.tenant_id)
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()

    async def create(self, obj: ModelType) -> ModelType:
        """Persist a new record and flush to get the generated ID."""
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete_by_id(self, resource_id: UUID) -> bool:
        """
        Delete a record by primary key scoped to this tenant.
        Returns True if a row was deleted, False if not found.
        """
        result = await self.db.execute(
            delete(self.model).where(
                self.model.id == resource_id,
                self.model.tenant_id == self.tenant_id,
            )
        )
        return result.rowcount > 0

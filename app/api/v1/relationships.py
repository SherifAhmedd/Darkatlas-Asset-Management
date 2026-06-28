from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import CurrentUserDep
from app.services.relationship_service import RelationshipService
from app.schemas.relationship import (
    RelationshipCreateRequest,
    RelationshipResponse,
    RelationshipListResponse,
)

router = APIRouter(prefix="/relationships", tags=["relationships"])


def get_relationship_service(
    current_user: CurrentUserDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RelationshipService:
    """Dependency that builds RelationshipService with the current user's tenant context."""
    return RelationshipService(db=db, tenant_id=current_user.tenant_id)


RelationshipServiceDep = Annotated[RelationshipService, Depends(get_relationship_service)]


@router.post(
    "",
    response_model=RelationshipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a relationship link between two assets",
)
async def create_relationship(
    payload: RelationshipCreateRequest,
    service: RelationshipServiceDep,
) -> RelationshipResponse:
    """
    Create a directed relationship between two assets.

    Both source and target assets must exist and belong to the same tenant.
    Duplicate relationships are rejected with a `409 Conflict`.

    **Relationship types:** `SUBDOMAIN_OF`, `RESOLVES_TO`, `USES`, `RUNS_ON`, `COVERS`
    """
    rel = await service.create_relationship(payload)
    return RelationshipResponse.model_validate(rel)


@router.get(
    "",
    response_model=RelationshipListResponse,
    summary="List all relationships for this tenant",
)
async def list_relationships(
    service: RelationshipServiceDep,
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
) -> RelationshipListResponse:
    items = await service.list_relationships(offset=offset, limit=limit)
    return RelationshipListResponse(
        items=[RelationshipResponse.model_validate(r) for r in items],
        total=len(items),
        offset=offset,
        limit=limit,
    )


@router.delete(
    "/{relationship_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a relationship by ID",
)
async def delete_relationship(
    relationship_id: UUID,
    service: RelationshipServiceDep,
) -> None:
    await service.delete_relationship(relationship_id)

from typing import Annotated, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import CurrentUserDep
from app.services.asset_service import AssetService
from app.services.import_pipeline import ImportPipeline
from app.schemas.asset import (
    AssetCreateRequest,
    AssetUpdateRequest,
    AssetStatusPatchRequest,
    AssetResponse,
    AssetListResponse,
    AssetGraphResponse,
)
from app.schemas.import_schema import BulkImportRequest, ImportResult

router = APIRouter(prefix="/assets", tags=["assets"])


def get_asset_service(
    current_user: CurrentUserDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AssetService:
    """Dependency that builds the AssetService with the current user's tenant context."""
    return AssetService(db=db, tenant_id=current_user.tenant_id)


AssetServiceDep = Annotated[AssetService, Depends(get_asset_service)]


# ─── CRUD Endpoints ───────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=AssetListResponse,
    summary="List assets with optional filters and pagination",
)
async def list_assets(
    service: AssetServiceDep,
    asset_type: Optional[str] = Query(None, description="Filter by asset type"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    tag: Optional[str] = Query(None, description="Filter by tag name"),
    value_contains: Optional[str] = Query(None, description="Substring search on value"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
) -> AssetListResponse:
    items = await service.list_assets(
        asset_type=asset_type,
        status=status_filter,
        tag=tag,
        value_contains=value_contains,
        offset=offset,
        limit=limit,
    )
    return AssetListResponse(
        items=[AssetResponse.model_validate(a) for a in items],
        total=len(items),
        offset=offset,
        limit=limit,
    )


@router.post(
    "",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new asset",
)
async def create_asset(
    payload: AssetCreateRequest,
    service: AssetServiceDep,
) -> AssetResponse:
    asset = await service.create_asset(payload)
    return AssetResponse.model_validate(asset)


@router.get(
    "/{asset_id}",
    response_model=AssetResponse,
    summary="Get a single asset by ID",
)
async def get_asset(
    asset_id: UUID,
    service: AssetServiceDep,
) -> AssetResponse:
    asset = await service.get_by_id(asset_id)
    return AssetResponse.model_validate(asset)


@router.put(
    "/{asset_id}",
    response_model=AssetResponse,
    summary="Update asset tags, metadata, or source",
)
async def update_asset(
    asset_id: UUID,
    payload: AssetUpdateRequest,
    service: AssetServiceDep,
) -> AssetResponse:
    asset = await service.update_asset(asset_id, payload)
    return AssetResponse.model_validate(asset)


@router.patch(
    "/{asset_id}/status",
    response_model=AssetResponse,
    summary="Patch the lifecycle status of an asset (active / stale / archived)",
)
async def patch_asset_status(
    asset_id: UUID,
    payload: AssetStatusPatchRequest,
    service: AssetServiceDep,
) -> AssetResponse:
    asset = await service.update_status(asset_id, payload.status)
    return AssetResponse.model_validate(asset)


@router.delete(
    "/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an asset by ID",
)
async def delete_asset(
    asset_id: UUID,
    service: AssetServiceDep,
) -> None:
    await service.delete_asset(asset_id)


# ─── Graph Endpoint ───────────────────────────────────────────────────────────

@router.get(
    "/{asset_id}/graph",
    response_model=AssetGraphResponse,
    summary="Get the relationship graph for an asset (JSON adjacency list)",
)
async def get_asset_graph(
    asset_id: UUID,
    service: AssetServiceDep,
) -> AssetGraphResponse:
    return await service.get_graph(asset_id)


# ─── Bulk Import Endpoint ─────────────────────────────────────────────────────

@router.post(
    "/import",
    response_model=ImportResult,
    summary="Bulk import assets through the 5-stage idempotent pipeline",
)
async def bulk_import_assets(
    payload: BulkImportRequest,
    current_user: CurrentUserDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ImportResult:
    """
    Bulk-import a list of assets through the 5-stage idempotent pipeline.

    **Pipeline stages:**
    1. **Validation** — schema check per item (non-blocking, collects errors)
    2. **Normalization** — canonicalize domains, IPs, services, technologies
    3. **Deduplication** — bulk lookup by `(type, value)` per tenant
    4. **Merge / Create** — merge metadata & tags into existing, or create new
    5. **Relationships** — map temp IDs to DB UUIDs and write graph edges

    Returns detailed statistics: created, updated, failed, relationships_created.
    """
    pipeline = ImportPipeline(db=db, tenant_id=current_user.tenant_id)
    return await pipeline.execute(payload.assets)

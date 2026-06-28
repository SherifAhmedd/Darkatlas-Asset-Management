from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, field_validator, Field

# ─── Enums as Literals ────────────────────────────────────────────────────────

ASSET_TYPES = [
    "domain",
    "subdomain",
    "ip_address",
    "service",
    "certificate",
    "technology",
]
ASSET_STATUSES = ["active", "stale", "archived"]


# ─── Request Schemas ──────────────────────────────────────────────────────────


class AssetCreateRequest(BaseModel):
    """Schema for creating a single asset manually."""

    type: str
    value: str
    status: str = "active"
    source: str = "manual"
    tags: List[str] = []
    metadata: Dict[str, Any] = {}

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ASSET_TYPES:
            raise ValueError(f"Invalid asset type. Must be one of: {ASSET_TYPES}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ASSET_STATUSES:
            raise ValueError(f"Invalid status. Must be one of: {ASSET_STATUSES}")
        return v

    @field_validator("value")
    @classmethod
    def value_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Asset value must not be empty")
        return v


class AssetUpdateRequest(BaseModel):
    """Schema for updating an existing asset's mutable fields."""

    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    source: Optional[str] = None


class AssetStatusPatchRequest(BaseModel):
    """Schema for patching an asset's lifecycle status only."""

    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ASSET_STATUSES:
            raise ValueError(f"Invalid status. Must be one of: {ASSET_STATUSES}")
        return v


# ─── Response Schemas ─────────────────────────────────────────────────────────


class AssetResponse(BaseModel):
    """Full asset response schema returned from API endpoints."""

    id: UUID
    tenant_id: UUID
    type: str
    value: str
    status: str
    source: str
    first_seen: datetime
    last_seen: datetime
    tags: List[str]
    metadata: Dict[str, Any] = Field(..., validation_alias="asset_metadata")

    model_config = {"from_attributes": True}


class AssetListResponse(BaseModel):
    """Paginated list of assets."""

    items: List[AssetResponse]
    total: int
    offset: int
    limit: int


# ─── Graph Response Schemas ───────────────────────────────────────────────────


class GraphNode(BaseModel):
    """Represents a single asset node in the graph."""

    id: UUID
    type: str
    value: str
    status: str


class GraphEdge(BaseModel):
    """Represents a single relationship edge in the graph."""

    source: UUID
    target: UUID
    relationship_type: str


class AssetGraphResponse(BaseModel):
    """JSON adjacency list response for GET /assets/{id}/graph."""

    root_asset: GraphNode
    nodes: List[GraphNode]
    edges: List[GraphEdge]

from uuid import UUID
from typing import List
from pydantic import BaseModel, field_validator, ValidationInfo

RELATIONSHIP_TYPES = ["SUBDOMAIN_OF", "RESOLVES_TO", "USES", "RUNS_ON", "COVERS"]


# ─── Request Schemas ──────────────────────────────────────────────────────────


class RelationshipCreateRequest(BaseModel):
    """Schema for creating a single relationship link between two assets."""

    source_asset_id: UUID
    target_asset_id: UUID
    relationship_type: str

    @field_validator("relationship_type")
    @classmethod
    def validate_relationship_type(cls, v: str) -> str:
        v = v.upper()
        if v not in RELATIONSHIP_TYPES:
            raise ValueError(
                f"Invalid relationship_type. Must be one of: {RELATIONSHIP_TYPES}"
            )
        return v

    @field_validator("target_asset_id")
    @classmethod
    def source_target_must_differ(cls, v: UUID, info: ValidationInfo) -> UUID:
        if "source_asset_id" in info.data and v == info.data["source_asset_id"]:
            raise ValueError("source_asset_id and target_asset_id must be different")
        return v


# ─── Response Schemas ─────────────────────────────────────────────────────────


class RelationshipResponse(BaseModel):
    """Full relationship response schema."""

    id: UUID
    tenant_id: UUID
    source_asset_id: UUID
    target_asset_id: UUID
    relationship_type: str

    model_config = {"from_attributes": True}


class RelationshipListResponse(BaseModel):
    """Paginated list of relationships."""

    items: List[RelationshipResponse]
    total: int
    offset: int
    limit: int

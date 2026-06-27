from typing import Any, Dict, List, Optional
from pydantic import BaseModel, field_validator, model_validator


ASSET_TYPES = ["domain", "subdomain", "ip_address", "service", "certificate", "technology"]
ASSET_STATUSES = ["active", "stale", "archived"]
RELATIONSHIP_TYPES = ["SUBDOMAIN_OF", "RESOLVES_TO", "USES", "RUNS_ON", "COVERS"]


class ImportAssetItem(BaseModel):
    """
    A single asset item inside a bulk import payload.

    The `id` field is a temporary string identifier (e.g. "a1", "a2") used
    only within this batch to define relationships between items.
    It is NOT the database UUID.
    """
    id: str  # temporary local reference ID (e.g. "a1")
    type: str
    value: str
    status: str = "active"
    source: str = "import"
    tags: List[str] = []
    metadata: Dict[str, Any] = {}

    # Relationship linkage keys (all reference other items' `id` in this batch)
    parent: Optional[str] = None        # → SUBDOMAIN_OF
    resolves_to: Optional[str] = None   # → RESOLVES_TO
    covers: Optional[str] = None        # → COVERS
    runs_on: Optional[str] = None       # → RUNS_ON
    uses: Optional[str] = None          # → USES

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ASSET_TYPES:
            raise ValueError(f"type must be one of {ASSET_TYPES}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ASSET_STATUSES:
            raise ValueError(f"status must be one of {ASSET_STATUSES}")
        return v

    @field_validator("value")
    @classmethod
    def value_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("value must not be empty")
        return v


class BulkImportRequest(BaseModel):
    """Bulk import payload — a list of asset items to ingest."""
    assets: List[Dict[str, Any]]  # Raw dicts to allow per-item validation errors


# ─── Response Schemas ──────────────────────────────────────────────────────────

class ImportError(BaseModel):
    """Details of a single failed item in the import batch."""
    index: int
    temp_id: Optional[str] = None
    value: Optional[str] = None
    error: str


class ImportResult(BaseModel):
    """
    Detailed observability response returned after a bulk import.
    Summarizes exactly what happened during each stage of the pipeline.
    """
    status: str = "completed"
    processed: int
    created: int
    updated: int
    failed: int
    relationships_created: int
    relationship_errors: int
    errors: List[ImportError] = []

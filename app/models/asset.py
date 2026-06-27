import uuid
from sqlalchemy import Column, String, DateTime, Enum, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from app.models.base import Base

class Asset(Base):
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    type = Column(
        Enum("domain", "subdomain", "ip_address", "service", "certificate", "technology", name="assettype"),
        nullable=False
    )
    value = Column(String, nullable=False)
    status = Column(
        Enum("active", "stale", "archived", name="assetstatus"),
        nullable=False,
        default="active"
    )
    first_seen = Column(DateTime(timezone=True), nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=False)
    source = Column(String, nullable=False, default="import")
    tags = Column(ARRAY(String), nullable=False, default=list)
    metadata = Column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("tenant_id", "type", "value", name="uq_asset_tenant_type_value"),
    )

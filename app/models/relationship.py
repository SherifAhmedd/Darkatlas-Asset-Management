import uuid
from sqlalchemy import Column, Enum, UniqueConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base


class Relationship(Base):
    __tablename__ = "relationships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    source_asset_id = Column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    target_asset_id = Column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type = Column(
        Enum(
            "SUBDOMAIN_OF",
            "RESOLVES_TO",
            "USES",
            "RUNS_ON",
            "COVERS",
            name="relationshiptype",
        ),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_asset_id",
            "target_asset_id",
            "relationship_type",
            name="uq_relationship_details",
        ),
    )

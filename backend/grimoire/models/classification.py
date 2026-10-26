"""Codex reclassification: the Codex snapshot and every classification decision.

Old values are kept beside new ones so any applied result can be reverted.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from grimoire.database import Base


class CodexProduct(Base):
    """One row of the Codex catalog dump plus its match to a Grimoire file."""

    __tablename__ = "codex_products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # Codex uuid
    slug: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(500), nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    level_range_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level_range_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dtrpg_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    grimoire_product_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=True
    )
    match_method: Mapped[str] = mapped_column(String(20), default="none")
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_pilot: Mapped[bool] = mapped_column(Boolean, default=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ClassificationRun(Base):
    """One named batch run (or the deterministic vocab migration)."""

    __tablename__ = "classification_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    effort: Mapped[str] = mapped_column(String(20), nullable=False)
    # Comma-joined when a run spans several batches (10,000-request limit).
    batch_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="created")
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class ClassificationResult(Base):
    """One product's decision within a run, old and new values side by side."""

    __tablename__ = "classification_results"
    __table_args__ = (UniqueConstraint("run_id", "codex_product_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("classification_runs.id"), nullable=False, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=True, index=True
    )
    codex_product_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("codex_products.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf|description|vocab

    product_type_old: Mapped[str | None] = mapped_column(String(50), nullable=True)
    product_type_new: Mapped[str | None] = mapped_column(String(50), nullable=True)
    level_min_old: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level_min_new: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level_max_old: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level_max_new: Mapped[int | None] = mapped_column(Integer, nullable=True)

    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    type_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    level_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exported_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

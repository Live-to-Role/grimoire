"""RunNote model - GM notes about running products/adventures."""

from datetime import datetime, UTC

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from grimoire.database import Base


class RunNote(Base):
    """A GM's note about running a product/adventure."""

    __tablename__ = "run_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )

    note_type: Mapped[str] = mapped_column(String(20), nullable=False)  # prep_tip, modification, warning, review
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    spoiler_level: Mapped[str] = mapped_column(String(20), default="none")  # none, minor, major, endgame

    shared_to_codex: Mapped[bool] = mapped_column(Boolean, default=False)
    codex_note_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), default="private")  # private, anonymous, public

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="run_notes")
    campaign: Mapped["Campaign | None"] = relationship("Campaign", back_populates="run_notes")

    def __repr__(self) -> str:
        return f"<RunNote(id={self.id}, title='{self.title}', type='{self.note_type}')>"

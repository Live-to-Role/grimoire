"""MonsterEntry model - extracted bestiary entries (see bestiary tools spec)."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from grimoire.database import Base


class MonsterEntry(Base):
    """A monster entry extracted from an owned bestiary PDF.

    Only review_status == "confirmed" entries feed the bestiary tools.
    JSON-in-Text fields: attacks, special_abilities, environments, flags.
    """

    __tablename__ = "monster_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    system_profile: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Normalized combatant statline (ascending AC, normalized attack bonuses)
    ac: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hd_dice: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hd_value: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    hp_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    attacks: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    move: Mapped[str | None] = mapped_column(String(100), nullable=True)
    special_abilities: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    environments: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list

    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    flags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of validation problems
    review_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<MonsterEntry(id={self.id}, name='{self.name}', status='{self.review_status}')>"

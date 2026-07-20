"""BestiaryFavorite model - a saved bestiary query (see bestiary scoping spec)."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from grimoire.database import Base


class BestiaryFavorite(Base):
    """A named, saved bestiary query.

    `config` is JSON-in-Text (the ProcessingQueue.config convention) holding
    the whole query: product_ids, environment, system_profile, hd_min, hd_max,
    q, and table_size. review_status is deliberately excluded - it is a
    workflow toggle, not part of a question about monsters.
    """

    __tablename__ = "bestiary_favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    config: Mapped[str] = mapped_column(Text, nullable=False)  # JSON object

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<BestiaryFavorite(id={self.id}, name='{self.name}')>"

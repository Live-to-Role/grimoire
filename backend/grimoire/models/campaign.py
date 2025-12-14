"""Campaign management models."""

from datetime import datetime, UTC

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Table
from sqlalchemy.orm import relationship

from grimoire.database import Base


# Association table for campaign-product many-to-many
campaign_products = Table(
    "campaign_products",
    Base.metadata,
    Column("campaign_id", Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("product_id", Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    Column("added_at", DateTime, default=lambda: datetime.now(UTC)),
    Column("notes", Text, nullable=True),
)


class Campaign(Base):
    """A campaign that groups products together."""

    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    game_system = Column(String(100), nullable=True)
    
    status = Column(String(50), default="active")  # active, paused, completed, archived
    
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    
    player_count = Column(Integer, nullable=True)
    session_count = Column(Integer, default=0)
    
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    products = relationship(
        "Product",
        secondary=campaign_products,
        backref="campaigns",
    )


class Session(Base):
    """A game session within a campaign."""

    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    
    session_number = Column(Integer, nullable=False)
    title = Column(String(255), nullable=True)
    
    scheduled_date = Column(DateTime, nullable=True)
    actual_date = Column(DateTime, nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    
    summary = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    
    status = Column(String(50), default="planned")  # planned, completed, cancelled
    
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    campaign = relationship("Campaign", backref="sessions")

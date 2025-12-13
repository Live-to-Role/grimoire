"""Contribution queue model for offline Codex submissions."""

from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from grimoire.database import Base


class ContributionStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"


class ContributionQueue(Base):
    """Queue for Codex contributions awaiting submission."""

    __tablename__ = "contribution_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    
    status = Column(SQLEnum(ContributionStatus), default=ContributionStatus.PENDING, nullable=False)
    
    # The data to contribute
    contribution_data = Column(Text, nullable=False)  # JSON string
    file_hash = Column(String(64), nullable=True)
    
    # Tracking
    attempts = Column(Integer, default=0)
    last_attempt_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Codex response
    codex_product_id = Column(String(64), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", backref="contributions")

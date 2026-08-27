"""Contribution queue model for offline Codex submissions."""

from datetime import datetime, UTC
from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import backref, relationship

from grimoire.database import Base


class ContributionStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"   # Codex says "approved"; do not add a fourth spelling
    REJECTED = "rejected"
    FAILED = "failed"

    # Codex outcomes that are neither success nor failure. Both used to be
    # mis-filed: `no_change` is a 200 and was recorded as SUBMITTED when
    # nothing was submitted, and `duplicate_pending` is a 400 and was recorded
    # as a permanent failure though it only means "you already sent this".
    NO_CHANGE = "no_change"                    # Codex already had everything
    DUPLICATE_PENDING = "duplicate_pending"    # an identical hash is still queued


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
    #
    # `codex_product_id` has fewer sources than it looks. Once Codex's
    # moderation parity change lands there is no `applied` response for a
    # Grimoire sync at all — the queued path returns 201 with a contribution
    # id and no product id, and for a new_product the Codex Product does not
    # exist until a moderator approves. So after parity this is filled only by
    # a `no_change` response or by polling.
    codex_product_id = Column(String(64), nullable=True)

    # Codex's own id for the queued contribution. Polling is impossible
    # without it, and `submit_contribution` used to log it and throw it away.
    codex_contribution_id = Column(String(64), nullable=True)

    # Fields Codex's merge guard refused to overwrite, as a JSON array. The
    # response still says "applied", so this is the only signal that a sync
    # wrote less than it sent.
    warnings = Column(Text, nullable=True)

    # SHA-256 of the payload as submitted. A rejected contribution must not be
    # re-sent until the local data actually changes, and Codex's own
    # duplicate_pending cannot help — it only guards against a *pending* twin.
    payload_hash = Column(String(64), nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    # delete-orphan: product_id is NOT NULL, so the default cascade's
    # nullify-on-parent-delete raises IntegrityError. See embedding.py.
    product = relationship(
        "Product",
        backref=backref("contributions", cascade="all, delete-orphan"),
    )

"""Exclusion rules model for filtering files during scanning."""

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from grimoire.database import Base


class ExclusionRuleType(str, Enum):
    """Types of exclusion rules."""
    FOLDER_PATH = "folder_path"      # Match full folder path pattern
    FOLDER_NAME = "folder_name"      # Match folder name anywhere in path
    FILENAME = "filename"            # Match filename pattern (glob)
    SIZE_MIN = "size_min"            # Exclude files smaller than (bytes)
    SIZE_MAX = "size_max"            # Exclude files larger than (bytes)
    REGEX = "regex"                  # Full regex pattern on path


class ExclusionRule(Base):
    """A rule for excluding files from library scanning."""

    __tablename__ = "exclusion_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)  # Pre-configured rule
    priority: Mapped[int] = mapped_column(Integer, default=0)  # Higher = checked first
    
    # Stats
    files_excluded: Mapped[int] = mapped_column(Integer, default=0)
    last_matched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ExclusionRule(id={self.id}, type='{self.rule_type}', pattern='{self.pattern}')>"


# Default exclusion rules to be seeded on first run
DEFAULT_EXCLUSION_RULES = [
    # System folders
    {"rule_type": "folder_name", "pattern": "__MACOSX", "description": "macOS resource forks", "priority": 100},
    {"rule_type": "folder_name", "pattern": ".git", "description": "Git repositories", "priority": 100},
    {"rule_type": "folder_name", "pattern": ".svn", "description": "SVN repositories", "priority": 100},
    {"rule_type": "folder_name", "pattern": "@eaDir", "description": "Synology thumbnails", "priority": 100},
    {"rule_type": "folder_name", "pattern": ".@__thumb", "description": "QNAP thumbnails", "priority": 100},
    {"rule_type": "folder_name", "pattern": "#recycle", "description": "NAS recycle bins", "priority": 100},
    {"rule_type": "folder_name", "pattern": "$RECYCLE.BIN", "description": "Windows recycle bin", "priority": 100},
    {"rule_type": "folder_name", "pattern": ".Trash", "description": "Trash folders", "priority": 100},
    
    # Common unwanted files
    {"rule_type": "filename", "pattern": "*.tmp", "description": "Temporary files", "priority": 90},
    {"rule_type": "filename", "pattern": "~$*", "description": "Office temp files", "priority": 90},
    {"rule_type": "filename", "pattern": "._*", "description": "macOS metadata files", "priority": 90},
    {"rule_type": "filename", "pattern": ".DS_Store", "description": "macOS folder metadata", "priority": 90},
    {"rule_type": "filename", "pattern": "Thumbs.db", "description": "Windows thumbnails", "priority": 90},
    
    # Size limits
    {"rule_type": "size_min", "pattern": "10240", "description": "Files under 10KB (likely corrupt)", "priority": 80},
]

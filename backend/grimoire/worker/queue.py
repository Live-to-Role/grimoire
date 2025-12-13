"""Huey task queue configuration.

Uses SQLite storage for simplicity. Can be swapped to Redis later for production.
"""

from pathlib import Path

from huey import SqliteHuey

from grimoire.config import settings

db_path = settings.data_dir / "huey.db"
db_path.parent.mkdir(parents=True, exist_ok=True)

huey = SqliteHuey(
    name="grimoire",
    filename=str(db_path),
    immediate=False,
)

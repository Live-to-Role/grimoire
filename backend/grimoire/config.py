"""Application configuration using pydantic-settings."""

import secrets
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve paths relative to the backend directory (parent of grimoire package)
# so the database is always in the same place regardless of working directory.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_DATA_DIR = _BACKEND_DIR / "data"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_file: str = ""  # Path to log file, empty = no file logging
    debug: bool = False

    # Database
    database_url: str = f"sqlite+aiosqlite:///{_DEFAULT_DATA_DIR / 'grimoire.db'}"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Paths
    data_dir: Path = _DEFAULT_DATA_DIR
    library_path: Path = Path("./pdfs")
    covers_dir: Path = _DEFAULT_DATA_DIR / "covers"

    # Processing
    max_concurrent_processing: int = 3
    cover_thumbnail_size: int = 300
    
    # OCR (Tesseract) - empty string uses system PATH (Linux/Docker default)
    tesseract_cmd: str = ""

    # Security
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    
    # Codex API
    codex_api_url: str = "https://codex-api.livetorole.com/api/v1"
    codex_api_key: str = ""  # Optional, for contributions
    codex_contribute_enabled: bool = False  # Opt-in
    codex_timeout: int = 10  # seconds
    
    # Rate limiting (disabled by default for native/local deployment)
    rate_limit_enabled: bool = False
    rate_limit_requests: int = 100  # requests per window
    rate_limit_window: int = 60  # seconds
    ai_rate_limit_requests: int = 10  # AI endpoints are more expensive
    ai_rate_limit_window: int = 60
    
    @field_validator('secret_key')
    @classmethod
    def warn_default_secret(cls, v: str) -> str:
        """Warn if using auto-generated secret (won't persist across restarts)."""
        import warnings
        if len(v) == 43:  # Length of secrets.token_urlsafe(32)
            warnings.warn(
                "Using auto-generated SECRET_KEY. Set SECRET_KEY environment variable for production.",
                UserWarning
            )
        return v

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.covers_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()

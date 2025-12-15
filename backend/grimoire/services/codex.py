"""
Codex API client for TTRPG product metadata lookup.

Codex is the community-curated database of tabletop RPG products.
This client handles product identification by file hash or title,
and optionally contributes new identifications back to Codex.
"""

import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

from grimoire.config import settings

logger = logging.getLogger(__name__)


class MatchType(str, Enum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    NONE = "none"


class IdentificationSource(str, Enum):
    CODEX_HASH = "codex_hash"
    CODEX_TITLE = "codex_title"
    AI = "ai"
    MANUAL = "manual"


@dataclass
class CodexProduct:
    """Product data from Codex API."""
    id: str
    title: str
    publisher: str | None = None
    author: str | None = None
    game_system: str | None = None
    game_system_slug: str | None = None
    genre: str | None = None
    product_type: str | None = None
    publication_year: int | None = None
    page_count: int | None = None
    level_range_min: int | None = None
    level_range_max: int | None = None
    party_size_min: int | None = None
    party_size_max: int | None = None
    estimated_runtime: str | None = None
    description: str | None = None
    cover_url: str | None = None
    dtrpg_url: str | None = None
    tags: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CodexProduct":
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            publisher=data.get("publisher"),
            author=data.get("author"),
            game_system=data.get("game_system"),
            game_system_slug=data.get("game_system_slug"),
            genre=data.get("genre"),
            product_type=data.get("product_type"),
            publication_year=data.get("publication_year"),
            page_count=data.get("page_count"),
            level_range_min=data.get("level_range_min"),
            level_range_max=data.get("level_range_max"),
            party_size_min=data.get("party_size_min"),
            party_size_max=data.get("party_size_max"),
            estimated_runtime=data.get("estimated_runtime"),
            description=data.get("description"),
            cover_url=data.get("cover_url"),
            dtrpg_url=data.get("dtrpg_url"),
            tags=data.get("tags"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "publisher": self.publisher,
            "author": self.author,
            "game_system": self.game_system,
            "game_system_slug": self.game_system_slug,
            "genre": self.genre,
            "product_type": self.product_type,
            "publication_year": self.publication_year,
            "page_count": self.page_count,
            "level_range_min": self.level_range_min,
            "level_range_max": self.level_range_max,
            "party_size_min": self.party_size_min,
            "party_size_max": self.party_size_max,
            "estimated_runtime": self.estimated_runtime,
            "description": self.description,
            "cover_url": self.cover_url,
            "dtrpg_url": self.dtrpg_url,
            "tags": self.tags,
        }


@dataclass
class CodexMatch:
    """Result of a Codex identification lookup."""
    match_type: MatchType
    confidence: float
    product: CodexProduct | None
    suggestions: list[CodexProduct] | None = None
    source: IdentificationSource | None = None


@dataclass
class ContributionResult:
    """Result of a contribution submission to Codex."""
    success: bool
    status: str | None = None  # "applied" or "pending"
    product_id: str | None = None  # UUID if status=applied
    product_slug: str | None = None
    contribution_id: str | None = None  # UUID if status=pending
    message: str | None = None
    reason: str | None = None  # Error reason if success=False

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> "ContributionResult":
        """Create from Codex API response."""
        return cls(
            success=True,
            status=data.get("status"),
            product_id=data.get("product_id"),
            product_slug=data.get("product_slug"),
            contribution_id=data.get("contribution_id"),
            message=data.get("message"),
        )

    @classmethod
    def failure(cls, reason: str) -> "ContributionResult":
        """Create a failure result."""
        return cls(success=False, reason=reason)


@dataclass
class Identification:
    """Result of the full identification chain."""
    source: IdentificationSource
    data: CodexProduct | dict[str, Any] | None
    confidence: float
    needs_confirmation: bool = False
    suggestions: list[CodexProduct] | None = None


# Mock data for development (will be replaced by real API calls)
MOCK_PRODUCTS: dict[str, dict] = {
    # Known file hashes map to products
    "mock_hash_tomb_of_serpent_kings": {
        "id": "codex-001",
        "title": "Tomb of the Serpent Kings",
        "publisher": "Skerples",
        "game_system": "OSR",
        "game_system_slug": "osr",
        "product_type": "Adventure",
        "publication_year": 2018,
        "page_count": 22,
        "level_range_min": 1,
        "level_range_max": 3,
        "description": "A classic introductory dungeon for OSR games, teaching players dungeon-crawling skills.",
        "tags": ["dungeon", "beginner-friendly", "free"],
    },
    "mock_hash_hot_springs": {
        "id": "codex-002",
        "title": "Hot Springs Island",
        "publisher": "Swordfish Islands",
        "game_system": "System Agnostic",
        "game_system_slug": "system-agnostic",
        "product_type": "Sourcebook",
        "publication_year": 2017,
        "page_count": 192,
        "description": "A system-neutral setting book for a tropical hex-crawl adventure.",
        "tags": ["hexcrawl", "sandbox", "tropical", "setting"],
    },
}

# Title-based fuzzy matches
MOCK_TITLE_MATCHES: dict[str, tuple[float, dict]] = {
    "tomb of the serpent kings": (0.95, MOCK_PRODUCTS["mock_hash_tomb_of_serpent_kings"]),
    "serpent kings": (0.75, MOCK_PRODUCTS["mock_hash_tomb_of_serpent_kings"]),
    "hot springs island": (0.98, MOCK_PRODUCTS["mock_hash_hot_springs"]),
    "hot springs": (0.70, MOCK_PRODUCTS["mock_hash_hot_springs"]),
}


def compute_file_hash(file_path: str | Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    path = Path(file_path)
    
    with open(path, "rb") as f:
        # Read in 64KB chunks for memory efficiency
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    
    return sha256.hexdigest()


class CodexClient:
    """Client for the Codex TTRPG metadata API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 10.0,
        use_mock: bool | None = None,  # None = auto-detect based on API key
    ):
        self.base_url = base_url or settings.codex_api_url
        self.api_key = api_key or settings.codex_api_key or None
        self.timeout = timeout or settings.codex_timeout
        # Auto-detect mock mode: use real API if we have an API key
        if use_mock is None:
            self.use_mock = not bool(self.api_key)
        else:
            self.use_mock = use_mock
        self._available: bool | None = None

    async def is_available(self) -> bool:
        """Check if Codex API is reachable."""
        if self.use_mock:
            return True
        
        if self._available is not None:
            return self._available
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/health")
                self._available = response.status_code == 200
        except Exception:
            self._available = False
        
        return self._available

    async def identify_by_hash(self, file_hash: str) -> CodexMatch | None:
        """
        Look up a product by file hash.
        This is the fastest and most accurate identification method.
        """
        if self.use_mock:
            return self._mock_identify_by_hash(file_hash)
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/identify",
                    params={"hash": file_hash},
                )
                response.raise_for_status()
                data = response.json()
                
                if data["match"] == "exact":
                    return CodexMatch(
                        match_type=MatchType.EXACT,
                        confidence=1.0,
                        product=CodexProduct.from_dict(data["product"]),
                        source=IdentificationSource.CODEX_HASH,
                    )
                return None
        except Exception as e:
            logger.warning(f"Codex hash lookup failed: {e}")
            return None

    async def identify_by_title(
        self,
        title: str,
        filename: str | None = None,
    ) -> CodexMatch | None:
        """
        Fuzzy match by title/filename.
        Returns matches above confidence threshold.
        """
        if self.use_mock:
            return self._mock_identify_by_title(title, filename)
        
        try:
            params = {"title": title}
            if filename:
                params["filename"] = filename
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/identify",
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                
                if data["match"] in ("exact", "fuzzy"):
                    return CodexMatch(
                        match_type=MatchType(data["match"]),
                        confidence=data["confidence"],
                        product=CodexProduct.from_dict(data["product"]) if data.get("product") else None,
                        suggestions=[CodexProduct.from_dict(s) for s in data.get("suggestions", [])],
                        source=IdentificationSource.CODEX_TITLE,
                    )
                return None
        except Exception as e:
            logger.warning(f"Codex title lookup failed: {e}")
            return None

    async def contribute(
        self,
        product_data: dict[str, Any],
        file_hash: str | None = None,
        existing_product_id: str | None = None,
    ) -> ContributionResult:
        """
        Contribute new or corrected product data back to Codex.
        Requires API key and user opt-in.
        
        Args:
            product_data: The product metadata to contribute
            file_hash: SHA-256 hash of the source file
            existing_product_id: Codex product UUID if editing existing product
        
        Returns:
            ContributionResult with status and IDs from Codex
        """
        if not self.api_key:
            logger.debug("Codex contribution skipped: no API key configured")
            return ContributionResult.failure("no_api_key")
        
        if self.use_mock:
            logger.info(f"Mock: Would contribute product '{product_data.get('title')}' to Codex")
            return ContributionResult(
                success=True,
                status="pending",
                message="Mock contribution queued",
            )
        
        # Build payload with contribution_type for explicit control
        payload: dict[str, Any] = {
            "data": product_data,
            "file_hash": file_hash,
            "source": "grimoire",
        }
        
        if existing_product_id:
            payload["contribution_type"] = "edit_product"
            payload["product"] = existing_product_id
        else:
            payload["contribution_type"] = "new_product"
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.post(
                    f"{self.base_url}/contributions/",
                    json=payload,
                    headers={"Authorization": f"Token {self.api_key}"},
                )
                response.raise_for_status()
                data = response.json()
                
                result = ContributionResult.from_response(data)
                logger.info(
                    f"Contribution submitted: status={result.status}, "
                    f"product_id={result.product_id or result.contribution_id}"
                )
                return result
                
        except httpx.HTTPStatusError as e:
            error_detail = e.response.text[:200] if e.response.text else "No details"
            logger.warning(f"Codex contribution failed: {e.response.status_code} - {error_detail}")
            return ContributionResult.failure(f"http_error_{e.response.status_code}: {error_detail}")
        except Exception as e:
            logger.warning(f"Codex contribution failed: {e}")
            return ContributionResult.failure(str(e))

    async def search(
        self,
        query: str,
        game_system: str | None = None,
        product_type: str | None = None,
        limit: int = 20,
    ) -> list[CodexProduct]:
        """Search Codex for products."""
        if self.use_mock:
            return self._mock_search(query)
        
        try:
            params = {"q": query, "limit": limit}
            if game_system:
                params["system"] = game_system
            if product_type:
                params["type"] = product_type
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/search",
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                return [CodexProduct.from_dict(p) for p in data.get("results", [])]
        except Exception as e:
            logger.warning(f"Codex search failed: {e}")
            return []

    # Mock implementations for development
    def _mock_identify_by_hash(self, file_hash: str) -> CodexMatch | None:
        """Mock hash lookup - returns None since we don't have real hashes."""
        # In production, this would match known file hashes
        # For mock, we'll return None to simulate unknown files
        return None

    def _mock_identify_by_title(self, title: str, filename: str | None = None) -> CodexMatch | None:
        """Mock title lookup with fuzzy matching."""
        search_term = (title or filename or "").lower().strip()
        
        # Check for matches
        best_match = None
        best_confidence = 0.0
        
        for pattern, (confidence, product_data) in MOCK_TITLE_MATCHES.items():
            if pattern in search_term or search_term in pattern:
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = product_data
        
        if best_match and best_confidence > 0.5:
            return CodexMatch(
                match_type=MatchType.EXACT if best_confidence > 0.9 else MatchType.FUZZY,
                confidence=best_confidence,
                product=CodexProduct.from_dict(best_match),
                source=IdentificationSource.CODEX_TITLE,
            )
        
        return None

    def _mock_search(self, query: str) -> list[CodexProduct]:
        """Mock search returns matching products."""
        query_lower = query.lower()
        results = []
        
        for product_data in MOCK_PRODUCTS.values():
            if (
                query_lower in product_data["title"].lower()
                or query_lower in (product_data.get("publisher") or "").lower()
                or query_lower in (product_data.get("game_system") or "").lower()
            ):
                results.append(CodexProduct.from_dict(product_data))
        
        return results


# Singleton client instance
_codex_client: CodexClient | None = None


def get_codex_client(use_mock: bool | None = None, refresh: bool = False) -> CodexClient:
    """Get or create the Codex client singleton.
    
    Args:
        use_mock: Force mock mode on/off. None = auto-detect based on API key.
        refresh: If True, recreate the client (useful when settings change).
    """
    global _codex_client
    if _codex_client is None or refresh:
        _codex_client = CodexClient(use_mock=use_mock)
    return _codex_client


def reset_codex_client():
    """Reset the singleton client. Call when Codex settings change."""
    global _codex_client
    _codex_client = None

"""
Codex API client for TTRPG product metadata lookup.

Codex is the community-curated database of tabletop RPG products.
This client handles product identification by file hash or title,
and optionally contributes new identifications back to Codex.
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

from grimoire.config import settings

logger = logging.getLogger(__name__)

# How long a reachability verdict stays good. Long enough that a library-wide
# sync costs one `/health` call a minute rather than one per product; short
# enough that a throttled or blipped check does not disable Codex for the
# lifetime of the process, which is what an unbounded cache used to do.
AVAILABILITY_TTL_SECONDS = 60.0


class CodexLookupError(Exception):
    """Codex could not be asked — as distinct from Codex having no match.

    ⚠️ These two must never collapse into one answer. `identify_by_hash` and
    `identify_by_title` used to return `None` for both, and
    `should_contribute` reads a `None` match as "new product, contribute it".
    So a throttle, a timeout or a 500 mid-walk did not stall a sync: it turned
    every remaining product into a new-product contribution for things Codex
    already holds. Codex's own comment blames precisely that pattern for 919
    duplicate products.
    """


class MatchType(str, Enum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    NONE = "none"


class IdentificationSource(str, Enum):
    CODEX_HASH = "codex_hash"
    CODEX_TITLE = "codex_title"
    AI = "ai"
    MANUAL = "manual"


#: Credit roles that mean "wrote it". Codex models credits as structured
#: roles (author, co_author, artist, cartographer, editor, layout, ...) while
#: Grimoire has a single `author` string, so the flattening has to choose.
#: Only writing roles qualify — a cartographer in the author field is worse
#: than an empty one.
AUTHOR_CREDIT_ROLES = frozenset({"author", "co_author"})

#: Codex `error` codes that arrive as 4xx but describe an ordinary outcome
#: rather than a fault. Recording these as failures made benign results look
#: permanent, and discarded the ids they carry.
BENIGN_CONTRIBUTION_ERRORS = frozenset({"duplicate_pending"})


def _name_of(value: Any) -> str | None:
    """Codex now nests what it used to send flat. Accept both."""
    if isinstance(value, dict):
        return value.get("name") or None
    return value or None


def _resolve_game_system(data: dict[str, Any]) -> tuple[str | None, str | None]:
    """The primary system's name and slug, or `(None, None)` if ambiguous.

    `/identify` sends `game_system` as an object, and as `null` whenever no
    link has been nominated primary — even when `game_systems` is populated.
    A lone candidate is unambiguous and worth using; several are a guess, so
    they are left unset rather than picked between. The captured fixture is
    exactly that case: two systems, neither primary.
    """
    system = data.get("game_system")
    if isinstance(system, dict):
        return system.get("name") or None, system.get("slug") or None
    if isinstance(system, str) and system:
        return system, data.get("game_system_slug")

    candidates = data.get("game_systems") or []
    primary = [s for s in candidates if s.get("is_primary")]
    chosen = primary if len(primary) == 1 else candidates
    if len(chosen) == 1:
        return chosen[0].get("name") or None, chosen[0].get("slug") or None
    return None, data.get("game_system_slug")


def _resolve_publication_year(data: dict[str, Any]) -> int | None:
    """Codex replaced `publication_year` with an ISO `publication_date`."""
    year = data.get("publication_year")
    if year:
        try:
            return int(year)
        except (TypeError, ValueError):
            pass
    raw = data.get("publication_date")
    if raw:
        try:
            return date.fromisoformat(raw).year
        except (TypeError, ValueError):
            return None
    return None


def _resolve_author(data: dict[str, Any]) -> str | None:
    """Flatten `credits` into Grimoire's single comma-separated author string."""
    author = data.get("author")
    if isinstance(author, str) and author:
        return author

    names: list[str] = []
    for credit in data.get("credits") or []:
        if (credit.get("role") or "").lower() not in AUTHOR_CREDIT_ROLES:
            continue
        name = _name_of(credit.get("author"))
        if name and name not in names:
            names.append(name)
    return ", ".join(names) or None


def _resolve_dtrpg_url(data: dict[str, Any]) -> str | None:
    """The `dtrpg_url` column is gone from Codex; `links` carries it now."""
    url = data.get("dtrpg_url")
    if url:
        return url
    for link in data.get("links") or []:
        href = link.get("url") or ""
        if (link.get("label") or "").lower() == "drivethrurpg" or "drivethrurpg.com" in href:
            return href or None
    return None


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
    dtrpg_id: str | None = None
    links: list[dict] = field(default_factory=list)
    tags: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CodexProduct":
        """Build from an `/identify` payload, in either the flat or nested shape.

        ⚠️ Every field here must come out a scalar. `sync_product_from_codex`
        maps them straight onto `Product` columns, so a `dict` reaching
        `publisher` raises `sqlite3.ProgrammingError` mid-commit and poisons
        the session for every product after it. `genre` has no source in the
        current payload — Codex replaced it with `themes`/`tags`, which are
        not the same thing — so it stays unset rather than being guessed at.
        """
        game_system, game_system_slug = _resolve_game_system(data)
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            publisher=_name_of(data.get("publisher")),
            author=_resolve_author(data),
            game_system=game_system,
            game_system_slug=game_system_slug,
            genre=data.get("genre"),
            product_type=data.get("product_type"),
            publication_year=_resolve_publication_year(data),
            page_count=data.get("page_count"),
            level_range_min=data.get("level_range_min"),
            level_range_max=data.get("level_range_max"),
            party_size_min=data.get("party_size_min"),
            party_size_max=data.get("party_size_max"),
            estimated_runtime=data.get("estimated_runtime"),
            description=data.get("description"),
            cover_url=data.get("cover_url"),
            dtrpg_url=_resolve_dtrpg_url(data),
            dtrpg_id=data.get("dtrpg_id") or None,
            links=data.get("links") or [],
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
            "dtrpg_id": self.dtrpg_id,
            "links": self.links,
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

    #: Codex's machine-readable `error` key, for outcomes that are ordinary
    #: rather than exceptional — `duplicate_pending` chief among them.
    error_code: str | None = None
    #: Fields Codex's merge guard declined to overwrite. The response still
    #: reads "applied", so this is the only evidence it wrote less than it was
    #: sent — "a refusal nobody can see is its own bug", in Codex's words.
    warnings: list[str] = field(default_factory=list)
    #: The Codex product a `no_change` names — a free link between the local
    #: product and the Codex one, previously discarded.
    existing_product_id: str | None = None
    #: The queued contribution a `duplicate_pending` names.
    existing_contribution_id: str | None = None

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
            warnings=list(data.get("warnings") or []),
            existing_product_id=data.get("existing_product_id"),
            existing_contribution_id=data.get("existing_contribution_id"),
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
        self._available_checked_at: float | None = None

    def _identify_headers(self) -> dict[str, str]:
        """Authenticate `/identify` when we hold a token.

        `IdentifyView` is `AllowAny`, so this is not required — but its
        `IdentifyRateThrottle` subclasses `AnonRateThrottle`, whose
        `get_cache_key` returns `None` for an authenticated request. The
        60/minute ceiling therefore applies only because Grimoire was calling
        anonymously, and it is keyed by IP, so it was shared with every other
        anonymous caller behind the same address. Sending the token we already
        hold removes the limit rather than working around it.
        """
        return {"Authorization": f"Token {self.api_key}"} if self.api_key else {}

    async def is_available(self) -> bool:
        """Check if Codex API is reachable, cached for `AVAILABILITY_TTL_SECONDS`.

        The verdict expires. It used to be cached for the life of the object,
        which meant one throttled `/health` check left `is_available()` False
        until the process restarted — and `sync_product_from_codex` reports an
        unavailable Codex as `skipped`, not `failed`, so the sync looked clean.
        """
        if self.use_mock:
            return True

        if self._available is not None and self._available_checked_at is not None:
            if time.monotonic() - self._available_checked_at < AVAILABILITY_TTL_SECONDS:
                return self._available

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/health")
                self._available = response.status_code == 200
        except Exception:
            self._available = False

        self._available_checked_at = time.monotonic()
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
                    headers=self._identify_headers(),
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
            # Raise, never return None: None means "Codex has no match", which
            # callers act on by contributing a new product. See CodexLookupError.
            logger.warning(f"Codex hash lookup failed: {e}")
            raise CodexLookupError(f"hash lookup failed: {e}") from e

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
                    headers=self._identify_headers(),
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
            raise CodexLookupError(f"title lookup failed: {e}") from e

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
            # Some of Codex's 400s are ordinary outcomes rather than errors.
            # `duplicate_pending` just means this file hash is already queued,
            # and it carries the existing contribution's id — which the old
            # code flattened into a message string and lost.
            try:
                body = e.response.json()
            except Exception:
                body = {}
            error_code = body.get("error")
            if error_code in BENIGN_CONTRIBUTION_ERRORS:
                logger.info(f"Codex contribution outcome: {error_code}")
                return ContributionResult(
                    success=False,
                    error_code=error_code,
                    reason=error_code,
                    message=body.get("message"),
                    existing_product_id=body.get("existing_product_id"),
                    existing_contribution_id=body.get("existing_contribution_id"),
                )

            error_detail = e.response.text[:200] if e.response.text else "No details"
            logger.warning(f"Codex contribution failed: {e.response.status_code} - {error_detail}")
            return ContributionResult.failure(f"http_error_{e.response.status_code}: {error_detail}")
        except Exception as e:
            logger.warning(f"Codex contribution failed: {e}")
            return ContributionResult.failure(str(e))

    async def get_contribution(self, contribution_id: str) -> dict[str, Any] | None:
        """Read a submitted contribution back, for its status and review notes.

        This is the only way Grimoire learns a contribution's fate. On the
        queued path the apply runs at approval — long after the submission
        response returned `pending` — so the held-back `warnings` never appear
        inline; Codex stores them in `review_notes`.

        ⚠️ `review_notes` is only trustworthy once Codex's parity plan Phase 1
        lands. Today both API review paths assign the moderator's own notes
        over whatever `approve_contribution` appended, so the warnings survive
        only on the Django-admin route. Treat the field as present-if-present.
        """
        if self.use_mock or not self.api_key:
            return None

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.base_url}/contributions/{contribution_id}/",
                    headers={"Authorization": f"Token {self.api_key}"},
                )
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.warning(f"Could not read contribution {contribution_id}: {e}")
            raise CodexLookupError(f"contribution read failed: {e}") from e

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


def get_codex_client(
    use_mock: bool | None = None,
    refresh: bool = False,
    api_key: str | None = None,
) -> CodexClient:
    """Get or create the Codex client singleton.

    Args:
        use_mock: Force mock mode on/off. None = auto-detect based on API key.
        refresh: If True, recreate the client (useful when settings change).
        api_key: Override API key (e.g. from database settings).
    """
    global _codex_client

    # Rebuild only when the configuration actually changed. This used to read
    # `or api_key`, which rebuilt on every call that passed a key — and
    # `sync_product_from_codex` passes one per product, so each product got a
    # client with a cold availability cache and paid for its own `/health`
    # call. Comparing against the live client keeps a changed key taking
    # effect without a restart, which is the behaviour that guard was for.
    stale = (
        _codex_client is None
        or refresh
        or (api_key is not None and api_key != _codex_client.api_key)
        or (use_mock is not None and use_mock != _codex_client.use_mock)
    )
    if stale:
        _codex_client = CodexClient(use_mock=use_mock, api_key=api_key)
    return _codex_client


def reset_codex_client():
    """Reset the singleton client. Call when Codex settings change."""
    global _codex_client
    _codex_client = None

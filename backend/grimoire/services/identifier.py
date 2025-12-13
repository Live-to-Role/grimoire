"""
Product identification service.

Implements the identification chain:
1. Codex by file hash (instant, exact)
2. Codex by title (fast, fuzzy)
3. AI identification (slow, costs money)
4. Manual (user input)

Users can choose which methods to use and in what order.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from grimoire.services.codex import (
    CodexClient,
    CodexMatch,
    CodexProduct,
    IdentificationSource,
    MatchType,
    compute_file_hash,
    get_codex_client,
)

logger = logging.getLogger(__name__)


class IdentificationMethod(str, Enum):
    """Available identification methods."""
    CODEX = "codex"
    AI = "ai"
    MANUAL = "manual"


@dataclass
class IdentificationResult:
    """Result of product identification."""
    source: IdentificationSource
    confidence: float
    needs_confirmation: bool
    
    # Identified metadata
    title: str | None = None
    publisher: str | None = None
    game_system: str | None = None
    product_type: str | None = None
    publication_year: int | None = None
    level_range_min: int | None = None
    level_range_max: int | None = None
    party_size_min: int | None = None
    party_size_max: int | None = None
    estimated_runtime: str | None = None
    description: str | None = None
    
    # For fuzzy matches, alternative suggestions
    suggestions: list[CodexProduct] | None = None
    
    # Codex product ID if matched
    codex_product_id: str | None = None
    
    # Raw data for debugging
    raw_data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "confidence": self.confidence,
            "needs_confirmation": self.needs_confirmation,
            "title": self.title,
            "publisher": self.publisher,
            "game_system": self.game_system,
            "product_type": self.product_type,
            "publication_year": self.publication_year,
            "level_range_min": self.level_range_min,
            "level_range_max": self.level_range_max,
            "party_size_min": self.party_size_min,
            "party_size_max": self.party_size_max,
            "estimated_runtime": self.estimated_runtime,
            "description": self.description,
            "codex_product_id": self.codex_product_id,
            "suggestions": [s.to_dict() for s in self.suggestions] if self.suggestions else None,
        }

    @classmethod
    def from_codex_product(
        cls,
        product: CodexProduct,
        source: IdentificationSource,
        confidence: float,
        needs_confirmation: bool = False,
        suggestions: list[CodexProduct] | None = None,
    ) -> "IdentificationResult":
        return cls(
            source=source,
            confidence=confidence,
            needs_confirmation=needs_confirmation,
            title=product.title,
            publisher=product.publisher,
            game_system=product.game_system,
            product_type=product.product_type,
            publication_year=product.publication_year,
            level_range_min=product.level_range_min,
            level_range_max=product.level_range_max,
            party_size_min=product.party_size_min,
            party_size_max=product.party_size_max,
            estimated_runtime=product.estimated_runtime,
            description=product.description,
            codex_product_id=product.id,
            suggestions=suggestions,
            raw_data=product.to_dict(),
        )

    @classmethod
    def from_ai_result(
        cls,
        ai_data: dict[str, Any],
        confidence: float,
    ) -> "IdentificationResult":
        return cls(
            source=IdentificationSource.AI,
            confidence=confidence,
            needs_confirmation=confidence < 0.9,
            title=ai_data.get("title"),
            publisher=ai_data.get("publisher"),
            game_system=ai_data.get("game_system"),
            product_type=ai_data.get("product_type"),
            publication_year=ai_data.get("publication_year"),
            level_range_min=ai_data.get("level_range_min"),
            level_range_max=ai_data.get("level_range_max"),
            description=ai_data.get("description"),
            raw_data=ai_data,
        )

    @classmethod
    def manual_required(cls) -> "IdentificationResult":
        return cls(
            source=IdentificationSource.MANUAL,
            confidence=0.0,
            needs_confirmation=True,
        )


@dataclass
class IdentificationConfig:
    """Configuration for identification process."""
    use_codex: bool = True
    use_ai: bool = True
    ai_provider: str | None = None  # "openai", "anthropic", "ollama"
    ai_model: str | None = None
    confidence_threshold: float = 0.8  # Below this, require confirmation
    contribute_to_codex: bool = False
    codex_api_key: str | None = None


async def identify_product(
    file_path: str,
    file_hash: str | None = None,
    title_hint: str | None = None,
    filename: str | None = None,
    extracted_text: str | None = None,
    config: IdentificationConfig | None = None,
) -> IdentificationResult:
    """
    Identify a product using the configured identification chain.
    
    Args:
        file_path: Path to the PDF file
        file_hash: Pre-computed SHA-256 hash (computed if not provided)
        title_hint: Embedded title from PDF metadata
        filename: Original filename
        extracted_text: Pre-extracted text for AI identification
        config: Identification configuration
    
    Returns:
        IdentificationResult with metadata and confidence
    """
    config = config or IdentificationConfig()
    codex = get_codex_client()
    
    # Compute hash if not provided and Codex is enabled
    if config.use_codex and not file_hash:
        try:
            file_hash = compute_file_hash(file_path)
        except Exception as e:
            logger.warning(f"Failed to compute file hash: {e}")
    
    # 1. Try Codex hash lookup (fastest, most accurate)
    if config.use_codex and file_hash:
        match = await codex.identify_by_hash(file_hash)
        if match and match.product:
            logger.info(f"Codex hash match: {match.product.title}")
            return IdentificationResult.from_codex_product(
                product=match.product,
                source=IdentificationSource.CODEX_HASH,
                confidence=1.0,
                needs_confirmation=False,
            )
    
    # 2. Try Codex title/filename lookup (fast, fuzzy)
    if config.use_codex:
        search_title = title_hint or filename
        if search_title:
            match = await codex.identify_by_title(search_title, filename)
            if match and match.product:
                needs_confirmation = match.confidence < config.confidence_threshold
                logger.info(
                    f"Codex title match: {match.product.title} "
                    f"(confidence: {match.confidence:.2f}, confirm: {needs_confirmation})"
                )
                return IdentificationResult.from_codex_product(
                    product=match.product,
                    source=IdentificationSource.CODEX_TITLE,
                    confidence=match.confidence,
                    needs_confirmation=needs_confirmation,
                    suggestions=match.suggestions,
                )
    
    # 3. Try AI identification (slow, costs money)
    if config.use_ai and extracted_text:
        try:
            from grimoire.processors.ai_identifier import identify_product as ai_identify
            
            ai_result = await ai_identify(
                text=extracted_text,
                provider=config.ai_provider or "anthropic",
                model=config.ai_model,
            )
            
            if ai_result and "error" not in ai_result:
                confidence_str = ai_result.get("confidence", "medium")
                confidence = {"high": 0.9, "medium": 0.7, "low": 0.5}.get(confidence_str, 0.6)
                
                logger.info(f"AI identification: {ai_result.get('title')} (confidence: {confidence_str})")
                
                result = IdentificationResult.from_ai_result(ai_result, confidence)
                
                # Optionally contribute to Codex
                if config.contribute_to_codex and config.codex_api_key:
                    codex_with_key = CodexClient(api_key=config.codex_api_key)
                    await codex_with_key.contribute(ai_result, file_hash)
                
                return result
        except Exception as e:
            logger.warning(f"AI identification failed: {e}")
    
    # 4. Manual identification required
    logger.info("No automatic identification possible, manual input required")
    return IdentificationResult.manual_required()


async def identify_with_method(
    file_path: str,
    method: IdentificationMethod,
    file_hash: str | None = None,
    title_hint: str | None = None,
    filename: str | None = None,
    extracted_text: str | None = None,
    ai_provider: str | None = None,
    ai_model: str | None = None,
) -> IdentificationResult:
    """
    Identify using a specific method only.
    Useful when user wants to force a particular identification method.
    """
    config = IdentificationConfig(
        use_codex=method == IdentificationMethod.CODEX,
        use_ai=method == IdentificationMethod.AI,
        ai_provider=ai_provider,
        ai_model=ai_model,
    )
    
    if method == IdentificationMethod.MANUAL:
        return IdentificationResult.manual_required()
    
    return await identify_product(
        file_path=file_path,
        file_hash=file_hash,
        title_hint=title_hint,
        filename=filename,
        extracted_text=extracted_text,
        config=config,
    )

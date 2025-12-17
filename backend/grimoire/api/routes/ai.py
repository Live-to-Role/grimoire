"""AI and Codex identification API endpoints."""

from dataclasses import asdict
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from grimoire.api.deps import DbSession
from grimoire.models import Product, Tag, ProductTag
from grimoire.services.processor import get_extracted_text
from grimoire.services.identifier import (
    IdentificationMethod,
    IdentificationConfig,
    identify_product as identify_product_chain,
    identify_with_method,
)
from grimoire.services.codex import get_codex_client
from grimoire.processors.ai_identifier import estimate_cost, estimate_batch_cost


router = APIRouter()


class IdentifyRequest(BaseModel):
    """Request to identify a product."""

    method: str | None = Field(None, description="Identification method: codex, ai, or auto (default)")
    provider: str | None = Field(None, description="AI provider (openai, anthropic, ollama)")
    model: str | None = Field(None, description="Specific model to use")
    apply: bool = Field(True, description="Apply identified metadata to product")
    use_codex: bool = Field(True, description="Try Codex lookup first")
    use_ai: bool = Field(True, description="Fall back to AI if Codex fails")
    contribute_to_codex: bool = Field(False, description="Contribute identification to Codex")
    codex_api_key: str | None = Field(None, description="Codex API key for contributions")


class BulkIdentifyRequest(BaseModel):
    """Request to identify multiple products."""

    product_ids: list[int] = Field(..., min_length=1)
    provider: str | None = None
    model: str | None = None
    apply: bool = True


@router.get("/providers")
async def get_providers(db: DbSession) -> dict:
    """Get available AI providers, checking both env vars and database settings."""
    import json
    import os
    from grimoire.models import Setting
    from grimoire.processors.ai_identifier import check_ollama_available, get_ollama_url
    
    # Check environment variables first
    openai_available = bool(os.getenv("OPENAI_API_KEY"))
    anthropic_available = bool(os.getenv("ANTHROPIC_API_KEY"))
    
    # Also check database settings for API keys
    if not openai_available:
        query = select(Setting).where(Setting.key == "openai_api_key")
        result = await db.execute(query)
        setting = result.scalar_one_or_none()
        if setting:
            try:
                openai_available = bool(json.loads(setting.value))
            except (json.JSONDecodeError, TypeError):
                pass
    
    if not anthropic_available:
        query = select(Setting).where(Setting.key == "anthropic_api_key")
        result = await db.execute(query)
        setting = result.scalar_one_or_none()
        if setting:
            try:
                anthropic_available = bool(json.loads(setting.value))
            except (json.JSONDecodeError, TypeError):
                pass
    
    # Get Ollama URL from database or env var
    ollama_url = await get_ollama_url()
    
    providers = {
        "openai": openai_available,
        "anthropic": anthropic_available,
        "ollama": check_ollama_available(ollama_url),
    }
    
    return {
        "providers": providers,
        "any_available": any(providers.values()),
    }


@router.get("/codex/status")
async def get_codex_status(db: DbSession) -> dict:
    """Check Codex API availability."""
    import json
    from grimoire.models import Setting
    from grimoire.services.codex import CodexClient
    from grimoire.config import settings as app_settings
    
    # Get API key from database settings (where frontend saves it)
    query = select(Setting).where(Setting.key == "codex_api_key")
    result = await db.execute(query)
    setting = result.scalar_one_or_none()
    db_api_key = json.loads(setting.value) if setting else None
    
    # Use API key from DB if set, otherwise fall back to env var
    api_key = db_api_key or app_settings.codex_api_key
    
    # Create client with the correct API key
    codex = CodexClient(api_key=api_key)
    available = await codex.is_available()
    return {
        "available": available,
        "mock_mode": codex.use_mock,
        "base_url": codex.base_url,
    }


@router.post("/identify/{product_id}")
async def identify_product_endpoint(
    db: DbSession,
    product_id: int,
    request: IdentifyRequest,
) -> dict:
    """
    Identify a product using the identification chain.
    
    Priority (configurable):
    1. Codex by file hash (instant, exact)
    2. Codex by title (fast, fuzzy)
    3. AI identification (slow, costs money)
    4. Manual (user input)
    """
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Get extracted text for AI fallback
    extracted_text = get_extracted_text(product)
    
    # If specific method requested, use only that method
    if request.method:
        try:
            method = IdentificationMethod(request.method)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid method: {request.method}. Use 'codex', 'ai', or 'manual'"
            )
        
        if method == IdentificationMethod.AI and not extracted_text:
            raise HTTPException(
                status_code=400,
                detail="Text not extracted yet. Run extraction first for AI identification."
            )
        
        identification = await identify_with_method(
            file_path=product.file_path,
            method=method,
            file_hash=product.file_hash,
            title_hint=product.title,
            filename=product.file_name,
            extracted_text=extracted_text,
            ai_provider=request.provider,
            ai_model=request.model,
        )
    else:
        # Use full identification chain
        config = IdentificationConfig(
            use_codex=request.use_codex,
            use_ai=request.use_ai and extracted_text is not None,
            ai_provider=request.provider,
            ai_model=request.model,
            contribute_to_codex=request.contribute_to_codex,
            codex_api_key=request.codex_api_key,
        )
        
        identification = await identify_product_chain(
            file_path=product.file_path,
            file_hash=product.file_hash,
            title_hint=product.title,
            filename=product.file_name,
            extracted_text=extracted_text,
            config=config,
        )

    # Apply if requested and not needing confirmation (or user explicitly wants to apply)
    applied = False
    if request.apply and not identification.needs_confirmation:
        if identification.title:
            product.title = identification.title
        if identification.author:
            product.author = identification.author
        if identification.game_system:
            product.game_system = identification.game_system
        if identification.genre:
            product.genre = identification.genre
        if identification.product_type:
            product.product_type = identification.product_type
        if identification.publisher:
            product.publisher = identification.publisher
        if identification.publication_year:
            product.publication_year = identification.publication_year
        if identification.level_range_min:
            product.level_range_min = identification.level_range_min
        if identification.level_range_max:
            product.level_range_max = identification.level_range_max
        if identification.party_size_min:
            product.party_size_min = identification.party_size_min
        if identification.party_size_max:
            product.party_size_max = identification.party_size_max
        if identification.estimated_runtime:
            product.estimated_runtime = identification.estimated_runtime

        product.ai_identified = True
        await db.commit()
        applied = True

    return {
        "product_id": product_id,
        "identification": identification.to_dict(),
        "applied": applied,
        "needs_confirmation": identification.needs_confirmation,
    }


@router.post("/identify/{product_id}/confirm")
async def confirm_identification(
    db: DbSession,
    product_id: int,
    confirmed_data: dict,
) -> dict:
    """
    Confirm and apply a fuzzy identification match.
    Used when identification.needs_confirmation is True.
    """
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Apply confirmed data
    if confirmed_data.get("title"):
        product.title = confirmed_data["title"]
    if confirmed_data.get("author"):
        product.author = confirmed_data["author"]
    if confirmed_data.get("game_system"):
        product.game_system = confirmed_data["game_system"]
    if confirmed_data.get("genre"):
        product.genre = confirmed_data["genre"]
    if confirmed_data.get("product_type"):
        product.product_type = confirmed_data["product_type"]
    if confirmed_data.get("publisher"):
        product.publisher = confirmed_data["publisher"]
    if confirmed_data.get("publication_year"):
        product.publication_year = confirmed_data["publication_year"]
    if confirmed_data.get("level_range_min"):
        product.level_range_min = confirmed_data["level_range_min"]
    if confirmed_data.get("level_range_max"):
        product.level_range_max = confirmed_data["level_range_max"]
    if confirmed_data.get("party_size_min"):
        product.party_size_min = confirmed_data["party_size_min"]
    if confirmed_data.get("party_size_max"):
        product.party_size_max = confirmed_data["party_size_max"]
    if confirmed_data.get("estimated_runtime"):
        product.estimated_runtime = confirmed_data["estimated_runtime"]

    product.ai_identified = True
    await db.commit()

    return {
        "product_id": product_id,
        "applied": True,
        "data": confirmed_data,
    }


@router.post("/identify-batch")
async def identify_batch(
    db: DbSession,
    request: BulkIdentifyRequest,
) -> dict:
    """Identify multiple products using AI."""
    from grimoire.processors.ai_identifier import identify_product as ai_identify

    products_query = select(Product).where(Product.id.in_(request.product_ids))
    products_result = await db.execute(products_query)
    products = list(products_result.scalars().all())

    results = []
    success = 0
    failed = 0

    for product in products:
        text = get_extracted_text(product)
        if not text:
            results.append({
                "product_id": product.id,
                "error": "Text not extracted",
            })
            failed += 1
            continue

        identification = await ai_identify(text, request.provider, request.model)

        if "error" in identification:
            results.append({
                "product_id": product.id,
                "error": identification["error"],
            })
            failed += 1
            continue

        if request.apply:
            if identification.get("game_system"):
                product.game_system = identification["game_system"]
            if identification.get("genre"):
                product.genre = identification["genre"]
            if identification.get("product_type"):
                product.product_type = identification["product_type"]
            if identification.get("publisher"):
                product.publisher = identification["publisher"]
            if identification.get("author"):
                product.author = identification["author"]
            if identification.get("title"):
                product.title = identification["title"]
            if identification.get("publication_year"):
                product.publication_year = identification["publication_year"]
            if identification.get("level_range_min"):
                product.level_range_min = identification["level_range_min"]
            if identification.get("level_range_max"):
                product.level_range_max = identification["level_range_max"]

            product.ai_identified = True

        results.append({
            "product_id": product.id,
            "identification": identification,
        })
        success += 1

    if request.apply:
        await db.commit()

    return {
        "total": len(products),
        "success": success,
        "failed": failed,
        "results": results,
    }


class SuggestTagsRequest(BaseModel):
    """Request to suggest tags for a product."""
    provider: str | None = Field(None, description="AI provider")
    model: str | None = Field(None, description="Specific model")
    apply: bool = Field(False, description="Automatically apply suggested tags")


@router.post("/suggest-tags/{product_id}")
async def suggest_tags_endpoint(
    db: DbSession,
    product_id: int,
    request: SuggestTagsRequest,
) -> dict:
    """Suggest tags for a product using AI."""
    from grimoire.processors.ai_identifier import suggest_tags, flatten_suggested_tags

    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    text = get_extracted_text(product)
    if not text:
        raise HTTPException(
            status_code=400,
            detail="Text not extracted yet. Run extraction first."
        )

    suggestions = await suggest_tags(text, request.provider, request.model)

    if "error" in suggestions:
        raise HTTPException(status_code=500, detail=suggestions["error"])

    applied_tags = []
    if request.apply:
        flat_tags = flatten_suggested_tags(suggestions)
        for tag_name in flat_tags:
            # Find or create tag
            tag_query = select(Tag).where(Tag.name == tag_name)
            tag_result = await db.execute(tag_query)
            tag = tag_result.scalar_one_or_none()
            
            if not tag:
                tag = Tag(name=tag_name, category="ai")
                db.add(tag)
                await db.flush()
            
            # Check if product already has this tag
            pt_query = select(ProductTag).where(
                ProductTag.product_id == product_id,
                ProductTag.tag_id == tag.id
            )
            pt_result = await db.execute(pt_query)
            existing = pt_result.scalar_one_or_none()
            
            if not existing:
                product_tag = ProductTag(
                    product_id=product_id,
                    tag_id=tag.id,
                    source="ai",
                    confidence=0.8 if suggestions.get("confidence") == "high" else 0.6
                )
                db.add(product_tag)
                applied_tags.append(tag_name)
        
        await db.commit()

    return {
        "product_id": product_id,
        "suggestions": suggestions,
        "applied_tags": applied_tags if request.apply else None,
    }


@router.post("/identify-all")
async def identify_all(
    db: DbSession,
    provider: str | None = Query(None, description="AI provider"),
    model: str | None = Query(None, description="Specific model"),
    apply: bool = Query(True, description="Apply to products"),
    force: bool = Query(False, description="Re-identify already identified products"),
    delay: float = Query(1.5, ge=0, le=30, description="Delay between requests in seconds"),
) -> dict:
    """Identify all products that haven't been identified yet."""
    import asyncio
    import logging
    logger = logging.getLogger(__name__)
    from grimoire.processors.ai_identifier import identify_product as ai_identify

    if force:
        query = select(Product).where(Product.text_extracted == True)
    else:
        query = select(Product).where(
            Product.text_extracted == True,
            Product.ai_identified == False,
        )

    result = await db.execute(query)
    products = list(result.scalars().all())
    
    logger.info(f"Starting AI identification for {len(products)} products with provider={provider}, model={model}")

    success = 0
    failed = 0
    errors = []

    for i, product in enumerate(products):
        text = get_extracted_text(product)
        if not text:
            failed += 1
            errors.append(f"{product.file_name}: No extracted text")
            logger.warning(f"[{i+1}/{len(products)}] {product.file_name}: No extracted text")
            continue

        try:
            identification = await ai_identify(text, provider, model)
        except Exception as e:
            failed += 1
            errors.append(f"{product.file_name}: {str(e)}")
            logger.error(f"[{i+1}/{len(products)}] {product.file_name}: Exception - {e}")
            continue

        if "error" in identification:
            failed += 1
            errors.append(f"{product.file_name}: {identification['error']}")
            logger.warning(f"[{i+1}/{len(products)}] {product.file_name}: {identification['error']}")
            continue
        
        logger.info(f"[{i+1}/{len(products)}] Identified: {product.file_name}")
        
        # Add delay between requests to avoid rate limits
        if delay > 0 and i < len(products) - 1:
            await asyncio.sleep(delay)

        if apply:
            if identification.get("game_system"):
                product.game_system = identification["game_system"]
            if identification.get("genre"):
                product.genre = identification["genre"]
            if identification.get("product_type"):
                product.product_type = identification["product_type"]
            if identification.get("publisher"):
                product.publisher = identification["publisher"]
            if identification.get("author"):
                product.author = identification["author"]
            if identification.get("title"):
                product.title = identification["title"]
            if identification.get("publication_year"):
                product.publication_year = identification["publication_year"]
            if identification.get("level_range_min"):
                product.level_range_min = identification["level_range_min"]
            if identification.get("level_range_max"):
                product.level_range_max = identification["level_range_max"]

            product.ai_identified = True

        success += 1

    if apply:
        await db.commit()
    
    logger.info(f"AI identification complete: {success} succeeded, {failed} failed out of {len(products)} total")

    return {
        "message": "Batch identification completed",
        "total": len(products),
        "success": success,
        "failed": failed,
        "errors": errors[:10],
    }


class CostEstimateRequest(BaseModel):
    """Request to estimate AI processing cost."""
    product_ids: list[int] = Field(..., description="Product IDs to estimate")
    provider: str | None = Field(None, description="AI provider")
    model: str | None = Field(None, description="Specific model")
    task_type: str = Field("identify", description="Task type: identify or suggest_tags")


@router.post("/estimate-cost")
async def estimate_processing_cost(
    db: DbSession,
    request: CostEstimateRequest,
) -> dict:
    """Estimate the cost of AI processing for products."""
    query = select(Product).where(Product.id.in_(request.product_ids))
    result = await db.execute(query)
    products = list(result.scalars().all())
    
    if not products:
        raise HTTPException(status_code=404, detail="No products found")
    
    # Get extracted text for each product
    texts = []
    products_with_text = []
    products_without_text = []
    
    for product in products:
        text = get_extracted_text(product)
        if text:
            texts.append(text)
            products_with_text.append(product.id)
        else:
            products_without_text.append(product.id)
    
    if not texts:
        return {
            "error": "No products have extracted text",
            "products_without_text": products_without_text,
        }
    
    estimate = estimate_batch_cost(
        texts,
        request.provider,
        request.model,
        request.task_type,
    )
    
    estimate["products_with_text"] = len(products_with_text)
    estimate["products_without_text"] = len(products_without_text)
    
    return estimate


@router.get("/estimate-cost/{product_id}")
async def estimate_single_cost(
    db: DbSession,
    product_id: int,
    provider: str | None = Query(None),
    model: str | None = Query(None),
    task_type: str = Query("identify"),
) -> dict:
    """Estimate the cost of AI processing for a single product."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    text = get_extracted_text(product)
    if not text:
        raise HTTPException(
            status_code=400,
            detail="Product has no extracted text"
        )
    
    estimate = estimate_cost(text, provider, model, task_type)
    
    return {
        "product_id": product_id,
        "provider": estimate.provider,
        "model": estimate.model,
        "input_tokens": estimate.input_tokens,
        "estimated_output_tokens": estimate.estimated_output_tokens,
        "input_cost_usd": round(estimate.input_cost, 6),
        "output_cost_usd": round(estimate.output_cost, 6),
        "total_cost_usd": round(estimate.total_cost, 6),
        "is_free": estimate.is_free,
    }


@router.get("/pricing")
async def get_model_pricing() -> dict:
    """Get current model pricing information."""
    from grimoire.processors.ai_identifier import MODEL_PRICING, DEFAULT_MODELS
    
    return {
        "pricing": MODEL_PRICING,
        "default_models": DEFAULT_MODELS,
        "note": "Prices are per 1M tokens in USD",
    }

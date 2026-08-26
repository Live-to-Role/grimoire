"""Queue processor service - processes items from the ProcessingQueue table."""

import asyncio
import json
import logging
import time
from datetime import datetime, UTC
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.database import async_session_maker
from grimoire.models import ProcessingQueue, Product
from grimoire.processors.text_extractor import extract_with_ocr, TESSERACT_AVAILABLE

logger = logging.getLogger(__name__)


async def _commit_with_retry(db: AsyncSession, max_retries: int = 5) -> None:
    """Commit with retry on 'database is locked' errors.

    After a lock error SQLAlchemy invalidates the session, so we must
    rollback before retrying.  We snapshot dirty object state before
    the attempt and restore it after rollback.
    """
    for attempt in range(max_retries):
        # Snapshot pending attribute changes before commit/flush can fail
        dirty_snapshots: list[tuple[object, dict]] = []
        for obj in list(db.dirty):
            attrs = {
                col.key: getattr(obj, col.key)
                for col in obj.__class__.__table__.columns
            }
            dirty_snapshots.append((obj, attrs))

        try:
            await db.commit()
            return
        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                logger.warning(f"DB locked on commit, retrying ({attempt + 1}/{max_retries})...")
                await db.rollback()

                # Re-apply dirty attributes so they get flushed on retry
                for obj, attrs in dirty_snapshots:
                    for k, v in attrs.items():
                        setattr(obj, k, v)

                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            raise

# Task type handlers
TASK_HANDLERS = {}

# DB-backed pause flag ("Grimoire Paused"). Stored in the settings table so the
# API process and the dedicated worker process share it across the process
# boundary.
PROCESSING_PAUSED_KEY = "processing_paused"

# Last time the queue worker completed a loop iteration. Written even while
# paused, so diagnostics can tell "paused on purpose" apart from "the worker
# process is not running" — the two look identical from the queue counts alone.
WORKER_HEARTBEAT_KEY = "queue_worker_heartbeat"

# A heartbeat older than this means the worker process is gone or wedged. The
# loop ticks at most every poll_interval (2s) plus one task, so this is loose
# enough to survive a single long extraction.
WORKER_HEARTBEAT_STALE_SECONDS = 120

# Below this many non-whitespace chars, an OCR result counts as "no text".
MIN_EXTRACTED_CHARS = 20

# Extraction cost guard: skip PDFs above these thresholds at worker pickup
# (before any file open / detection / OCR) so one giant scanned file can't
# stall the whole sequential queue.
MAX_EXTRACTION_FILE_MB = 250
MAX_EXTRACTION_PAGES = 1000


def parse_paused(value: str | None) -> bool:
    """Decode a stored pause flag. Anything unreadable counts as paused."""
    if value is None:
        return True
    try:
        return bool(json.loads(value))
    except (json.JSONDecodeError, TypeError):
        return True


async def is_processing_paused(session_maker=None) -> bool:
    """Return whether background processing is paused. Defaults to True (paused).

    Opens its own DB session (or a provided one, for tests) so it works from any
    process. Default-True implements "the app starts paused".
    """
    from grimoire.models import Setting

    maker = session_maker or async_session_maker
    async with maker() as session:
        result = await session.execute(
            select(Setting).where(Setting.key == PROCESSING_PAUSED_KEY)
        )
        setting = result.scalar_one_or_none()

    return parse_paused(setting.value if setting else None)


async def set_processing_paused(paused: bool, session_maker=None) -> None:
    """Persist the pause flag behind "Grimoire Paused" / "Grimoire Working"."""
    from grimoire.models import Setting

    maker = session_maker or async_session_maker
    value = json.dumps(bool(paused))
    async with maker() as session:
        result = await session.execute(
            select(Setting).where(Setting.key == PROCESSING_PAUSED_KEY)
        )
        setting = result.scalar_one_or_none()
        if setting is None:
            session.add(Setting(key=PROCESSING_PAUSED_KEY, value=value))
        else:
            setting.value = value
        await session.commit()


async def touch_worker_heartbeat(session_maker=None) -> None:
    """Record that the queue worker is alive right now."""
    from grimoire.models import Setting

    maker = session_maker or async_session_maker
    value = datetime.now(UTC).isoformat()
    try:
        async with maker() as session:
            result = await session.execute(
                select(Setting).where(Setting.key == WORKER_HEARTBEAT_KEY)
            )
            setting = result.scalar_one_or_none()
            if setting is None:
                session.add(Setting(key=WORKER_HEARTBEAT_KEY, value=value))
            else:
                setting.value = value
            await session.commit()
    except Exception as e:
        # A heartbeat is diagnostics, never a reason to stop draining the queue.
        logger.debug(f"Could not write worker heartbeat: {e}")


def parse_heartbeat(value: str | None) -> datetime | None:
    """Decode a stored heartbeat. Anything unreadable counts as no heartbeat."""
    if value is None:
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


async def get_worker_heartbeat(session_maker=None) -> datetime | None:
    """Return the queue worker's last heartbeat, or None if it never ran."""
    from grimoire.models import Setting

    maker = session_maker or async_session_maker
    async with maker() as session:
        result = await session.execute(
            select(Setting).where(Setting.key == WORKER_HEARTBEAT_KEY)
        )
        setting = result.scalar_one_or_none()

    return parse_heartbeat(setting.value if setting else None)


def register_handler(task_type: str):
    """Decorator to register a task handler."""
    def decorator(func):
        TASK_HANDLERS[task_type] = func
        return func
    return decorator


@register_handler("cover")
async def handle_cover_task(db: AsyncSession, product: Product) -> bool:
    """Handle cover extraction task."""
    from grimoire.services.processor import process_cover_sync

    success = await asyncio.to_thread(process_cover_sync, product)
    if success:
        await db.commit()
    return success


# Simple TTL cache for settings (avoids DB query per task)
_settings_cache: dict[str, tuple[float, any]] = {}
_SETTINGS_CACHE_TTL = 60.0  # seconds


async def get_setting(db: AsyncSession, key: str, default=None):
    """Get a setting value from the database, with 60-second TTL cache."""
    from grimoire.models import Setting
    import json

    now = time.monotonic()
    if key in _settings_cache:
        cached_time, cached_value = _settings_cache[key]
        if now - cached_time < _SETTINGS_CACHE_TTL:
            return cached_value

    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        try:
            value = json.loads(setting.value)
        except (json.JSONDecodeError, TypeError):
            value = setting.value
    else:
        value = default

    _settings_cache[key] = (now, value)
    return value


def _oversized_skip_reason(product) -> str | None:
    """Return a reason string if a product is too large to extract, else None.

    Size is the primary guard and never opens the file. The page check only
    fires when `page_count` is already populated (set during cover extraction);
    a None page_count is not treated as a reason to open the PDF.

    Assumes a real Product with a numeric `file_size`; tests mocking a
    product must set `file_size` explicitly, or `MagicMock > int` will trip
    the guard.
    """
    size_mb = (product.file_size or 0) / (1024 * 1024)
    if size_mb > MAX_EXTRACTION_FILE_MB:
        return f"oversized: {size_mb:.0f} MB (limit {MAX_EXTRACTION_FILE_MB} MB)"
    if product.page_count and product.page_count > MAX_EXTRACTION_PAGES:
        return f"oversized: {product.page_count} pages (limit {MAX_EXTRACTION_PAGES})"
    return None


def is_processing_disposition_blocked(product) -> bool:
    """True if a product is image-only or permanently unextractable and must be
    skipped by every text-extraction / AI-identify re-queue path."""
    return bool(
        getattr(product, "is_image_content", False)
        or getattr(product, "text_unextractable", False)
    )


async def queue_ai_identify_if_enabled(db: AsyncSession, product: Product) -> bool:
    """Queue AI identification task if auto-identify is enabled and a provider is available."""
    auto_identify = await get_setting(db, "auto_identify_on_scan", False)
    if not auto_identify:
        return False

    # Check if already identified
    if product.ai_identified:
        return False

    # AI-identify needs real extracted text and a content-bearing PDF.
    if not product.text_extracted or is_processing_disposition_blocked(product):
        return False

    # Check if any AI provider is actually available before queuing
    from grimoire.processors.ai_identifier import get_setting_from_db, check_ollama_available
    import os

    provider = await get_setting(db, "auto_identify_provider", "ollama")
    if provider == "openai":
        key = os.getenv("OPENAI_API_KEY", "") or await get_setting_from_db("openai_api_key")
        if not key:
            return False
    elif provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "") or await get_setting_from_db("anthropic_api_key")
        if not key:
            return False
    elif provider == "ollama":
        if not check_ollama_available():
            return False

    # Queue AI identify task
    ai_item = ProcessingQueue(
        product_id=product.id,
        task_type="ai_identify",
        priority=3,  # Lower than text extraction
        status="pending",
    )
    db.add(ai_item)
    logger.info(f"Queued AI identification for product {product.id}")
    return True


def _diagnose_pdf_unextractable(path: str) -> str | None:
    """Return a permanent-failure reason if the PDF can't be opened/decrypted,
    else None (treat as transient and retry). Runs in a worker thread."""
    import fitz
    try:
        doc = fitz.open(path)
    except Exception:
        return "corrupt pdf"
    try:
        if doc.is_encrypted and not doc.authenticate(""):
            return "encrypted"
    finally:
        doc.close()
    return None


@register_handler("text")
async def handle_text_task(db: AsyncSession, product: Product) -> bool:
    """Handle text extraction task.

    If the PDF is detected as image-based (needs OCR), queues an ocr_text task instead.
    After successful extraction, queues AI identification if enabled.
    """
    from grimoire.services.processor import process_text_extraction_sync
    from grimoire.services.fts_service import update_search_vector
    from grimoire.processors.text_extractor import assess_text_layer
    from pathlib import Path

    # Guard: skip PDFs too large/long to extract before any file open or OCR.
    reason = _oversized_skip_reason(product)
    if reason:
        product.text_unextractable = True
        product.extraction_error = reason
        await db.commit()
        raise TaskError(f"Product {product.id} '{product.file_name}': {reason}")

    # Check if this is image content (maps, stock art) or needs OCR
    pdf_path = Path(product.file_path)
    if pdf_path.exists():
        from grimoire.processors.image_classifier import detect_image_content
        img_detection = await asyncio.to_thread(
            detect_image_content, pdf_path, product.file_name, product.file_path
        )
        if img_detection["is_image_content"]:
            classification = img_detection["classification"]

            product.is_image_content = True
            if classification:
                product.product_type = classification

                # Auto-tag with built-in tag
                from grimoire.models import Tag, ProductTag
                tag_result = await db.execute(
                    select(Tag).where(Tag.name == classification, Tag.is_builtin == True)
                )
                tag = tag_result.scalar_one_or_none()
                if tag:
                    existing_pt = await db.execute(
                        select(ProductTag).where(
                            ProductTag.product_id == product.id,
                            ProductTag.tag_id == tag.id,
                        )
                    )
                    if not existing_pt.scalar_one_or_none():
                        db.add(ProductTag(
                            product_id=product.id,
                            tag_id=tag.id,
                            source="auto",
                        ))

            # Queue image extraction
            img_item = ProcessingQueue(
                product_id=product.id,
                task_type="extract_images",
                priority=2,
                status="pending",
            )
            db.add(img_item)
            await db.commit()
            logger.info(f"Product {product.id} classified as '{classification}': {img_detection['reason']}")
            return True

        # Not image content — check if it still needs OCR
        detection = await asyncio.to_thread(assess_text_layer, pdf_path)
        if detection["needs_ocr"]:
            ocr_item = ProcessingQueue(
                product_id=product.id,
                task_type="ocr_text",
                priority=1,
                status="pending",
            )
            db.add(ocr_item)
            await db.commit()
            logger.info(f"Product {product.id} needs OCR: {detection['reason']}")
            return True

    # Run sync extraction in thread pool
    success = await asyncio.to_thread(process_text_extraction_sync, product, False)
    if success:
        await db.commit()
        # Also update the FTS index
        await update_search_vector(db, product)
        # Queue AI identification if enabled
        await queue_ai_identify_if_enabled(db, product)
        await db.commit()
        return True

    # Extraction failed. A missing file is transient — retry, do not flag.
    if not pdf_path.exists():
        return False

    # Diagnose whether the PDF is permanently unextractable (encrypted/corrupt)
    # vs a transient error we should retry.
    reason = await asyncio.to_thread(_diagnose_pdf_unextractable, str(pdf_path))
    if reason:
        product.text_unextractable = True
        product.extraction_error = reason
        await db.commit()
        raise TaskError(f"Product {product.id} '{product.file_name}': {reason}")
    return False


@register_handler("ocr_text")
async def handle_ocr_text_task(db: AsyncSession, product: Product) -> bool:
    """Handle OCR text extraction task for image-based PDFs.

    This is a separate queue for slow OCR processing.
    """
    from grimoire.services.fts_service import update_search_vector
    from grimoire.config import settings
    from pathlib import Path
    import json

    # Guard: skip PDFs too large/long to extract before any file open or OCR.
    reason = _oversized_skip_reason(product)
    if reason:
        product.text_unextractable = True
        product.extraction_error = reason
        await db.commit()
        raise TaskError(f"Product {product.id} '{product.file_name}': {reason}")

    if not TESSERACT_AVAILABLE:
        logger.error("OCR task failed: pytesseract/pdf2image not available")
        return False
    
    pdf_path = Path(product.file_path)
    if not pdf_path.exists():
        return False
    
    try:
        # OCR is extremely CPU-heavy — must run in thread
        markdown_text = await asyncio.to_thread(
            extract_with_ocr, pdf_path, dpi=200, lang="eng"
        )

        if len((markdown_text or "").strip()) < MIN_EXTRACTED_CHARS:
            product.text_unextractable = True
            product.extraction_error = "no text after ocr"
            await db.commit()
            raise TaskError(
                f"Product {product.id} '{product.file_name}': no text after OCR"
            )

        # File I/O in thread too
        def _save_ocr_result():
            import fitz
            doc = fitz.open(str(pdf_path))
            total_pages = len(doc)
            doc.close()

            text_dir = settings.data_dir / "text"
            text_dir.mkdir(parents=True, exist_ok=True)
            text_file = text_dir / f"{product.id}.json"

            from grimoire.processors.text_extractor import split_pages_by_markers

            result = {
                "markdown": markdown_text,
                "total_pages": total_pages,
                "pages_extracted": f"1-{total_pages}",
                "method": "tesseract_ocr",
                "char_count": len(markdown_text),
                "ocr_used": True,
            }
            pages = split_pages_by_markers(markdown_text)
            if pages:
                result["pages"] = pages

            with open(text_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            return str(text_file), total_pages

        text_file_path, _ = await asyncio.to_thread(_save_ocr_result)

        product.extracted_text_path = text_file_path
        product.text_extracted = True
        await db.commit()
        
        # Update FTS index
        await update_search_vector(db, product)
        
        # Queue AI identification if enabled
        await queue_ai_identify_if_enabled(db, product)
        await db.commit()
        
        logger.info(f"OCR extraction completed for product {product.id}: {len(markdown_text)} chars")
        return True
        
    except TaskError:
        raise
    except Exception as e:
        logger.error(f"OCR extraction failed for product {product.id}: {e}")
        return False


@register_handler("extract_images")
async def handle_extract_images_task(db: AsyncSession, product: Product) -> bool:
    """Handle image extraction task for maps/stock art PDFs."""
    from grimoire.processors.image_extractor import extract_images
    from grimoire.config import settings

    pdf_path = Path(product.file_path)
    if not pdf_path.exists():
        return False

    output_dir = settings.data_dir / "images" / str(product.id)

    result = await asyncio.to_thread(extract_images, pdf_path, output_dir)

    product.images_extracted = True
    product.image_count = result["image_count"]
    await db.commit()

    logger.info(f"Extracted {result['image_count']} images from product {product.id}")
    return True


class TaskError(Exception):
    """Exception for task failures with specific error messages."""
    pass


@register_handler("fts_index")
async def handle_fts_index_task(db: AsyncSession, product: Product) -> bool:
    """Handle FTS indexing task for products with extracted text."""
    from grimoire.services.fts_service import update_search_vector, check_fts_available
    
    # Check if FTS5 table exists
    if not await check_fts_available(db):
        raise TaskError("FTS5 table 'products_fts' does not exist. Run database migrations.")
    
    if not product.text_extracted:
        raise TaskError(f"Product {product.id} has no extracted text (text_extracted=False)")
    
    success = await update_search_vector(db, product)
    if not success:
        raise TaskError(f"FTS indexing failed for product {product.id}")
    return True


@register_handler("embed")
async def handle_embed_task(db: AsyncSession, product: Product) -> bool:
    """Handle embedding generation task for semantic search."""
    from grimoire.services.processor import get_extracted_text
    from grimoire.services.embeddings import generate_embeddings, build_metadata_preamble, build_chunks_for_product
    from grimoire.models import ProductEmbedding
    from sqlalchemy import delete

    if not product.text_extracted:
        raise TaskError(f"Product {product.id} has no extracted text (text_extracted=False)")

    # Read product attributes in async context before entering thread
    extracted_text_path = product.extracted_text_path
    if not extracted_text_path:
        raise TaskError(f"Product {product.id} has no extracted_text_path")

    # Read file from disk in thread to avoid blocking the event loop
    def _read_extracted_text(path: str) -> tuple[str | None, list[dict] | None]:
        import json
        from pathlib import Path
        text_path = Path(path)
        if not text_path.exists():
            return None, None
        try:
            with open(text_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("markdown"), data.get("pages")
        except Exception:
            return None, None

    text, pages = await asyncio.to_thread(_read_extracted_text, extracted_text_path)
    if not text:
        raise TaskError(
            f"Product {product.id} '{product.file_name}' has no embeddable text "
            f"(file: {extracted_text_path})"
        )

    # Metadata preamble becomes its own leading chunk(s); content chunks carry
    # page anchors when the extraction JSON has them.
    preamble = build_metadata_preamble(product)
    chunk_tuples = build_chunks_for_product(preamble, pages, text)

    # Chunk and embed BEFORE touching the DB to avoid holding a write
    # transaction open during the slow Ollama/OpenAI call.
    embeddings = await generate_embeddings([c for c, _, _ in chunk_tuples])

    # Now do all DB writes quickly.
    # ⚠️ The body index is cleared FIRST. Its rowids are embedding ids, so once
    # the rows below are deleted there is nothing left to resolve them from and
    # the old text would stay findable forever.
    from grimoire.services.fts_service import (
        clear_product_chunk_index,
        index_product_chunks,
    )

    await clear_product_chunk_index(db, product.id)
    await db.execute(
        delete(ProductEmbedding).where(ProductEmbedding.product_id == product.id)
    )

    for i, ((chunk, page_start, page_end), emb_result) in enumerate(zip(chunk_tuples, embeddings)):
        embedding_record = ProductEmbedding(
            product_id=product.id,
            chunk_index=i,
            chunk_text=chunk[:1000],
            embedding_model=emb_result.model,
            embedding_dim=len(emb_result.embedding),
            page_start=page_start,
            page_end=page_end,
        )
        embedding_record.set_embedding_vector(emb_result.embedding)
        db.add(embedding_record)

    # Compute and store per-product averaged vector
    from grimoire.models.product_search_vector import ProductSearchVector, compute_weighted_average_vector
    from grimoire.services.embeddings import invalidate_vector_cache

    chunk_vectors = [emb_result.embedding for emb_result in embeddings]
    avg_vector = compute_weighted_average_vector(chunk_vectors, metadata_weight=2.0)

    existing_sv = await db.execute(
        select(ProductSearchVector).where(ProductSearchVector.product_id == product.id)
    )
    sv = existing_sv.scalar_one_or_none()
    if sv:
        sv.set_vector(avg_vector)
        sv.embedding_model = embeddings[0].model
    else:
        sv = ProductSearchVector(
            product_id=product.id,
            embedding_model=embeddings[0].model,
            embedding_dim=len(avg_vector),
        )
        sv.set_vector(avg_vector)
        db.add(sv)

    # Flush so the new embedding rows have ids; the body index keys on them.
    await db.flush()
    await index_product_chunks(db, product.id)

    await db.commit()
    invalidate_vector_cache()
    return True


@register_handler("identify")
async def handle_identify_task(db: AsyncSession, product: Product) -> bool:
    """Handle AI identification task."""
    from grimoire.services.codex import get_codex_client
    from grimoire.services.sync_service import get_codex_settings_from_db

    # Read API key from DB (where the frontend saves it) so we don't
    # fall back to mock mode when the key is only stored in the database.
    _, api_key = await get_codex_settings_from_db(db)
    client = get_codex_client(api_key=api_key)
    
    # Try hash lookup first
    match = await client.identify_by_hash(product.file_hash)
    
    if not match or not match.product:
        # Fall back to title lookup
        match = await client.identify_by_title(
            title=product.title or product.file_name,
            filename=product.file_name,
        )
    
    if match and match.product:
        codex_product = match.product
        
        # Update product with Codex data
        if codex_product.title and not product.title:
            product.title = codex_product.title
        if codex_product.publisher and not product.publisher:
            product.publisher = codex_product.publisher
        if codex_product.game_system and not product.game_system:
            product.game_system = codex_product.game_system
        if codex_product.product_type and not product.product_type:
            product.product_type = codex_product.product_type
        if codex_product.publication_year and not product.publication_year:
            product.publication_year = codex_product.publication_year
        
        product.ai_identified = True
        product.identification_confidence = match.confidence
        product.updated_at = datetime.now(UTC)
        await db.commit()
        return True
    
    return False


@register_handler("ai_identify")
async def handle_ai_identify_task(db: AsyncSession, product: Product, config: dict | None = None) -> bool:
    """Handle AI identification task using configured provider."""
    from grimoire.processors.ai_identifier import identify_product
    from grimoire.services.processor import get_extracted_text

    # Use provider from queue item config, falling back to settings
    if config and config.get("provider"):
        provider = config["provider"]
    else:
        provider = await get_setting(db, "auto_identify_provider", "ollama")

    # Read product attributes in async context before entering thread
    extracted_text_path = product.extracted_text_path
    text_extracted = product.text_extracted

    def _read_text(path: str | None, extracted: bool) -> str | None:
        if not extracted or not path:
            return None
        import json
        from pathlib import Path
        text_path = Path(path)
        if not text_path.exists():
            return None
        try:
            with open(text_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("markdown")
        except Exception:
            return None

    # Get extracted text — file I/O, run in thread
    text = await asyncio.to_thread(_read_text, extracted_text_path, text_extracted)
    if not text or len(text) < 100:
        raise TaskError(f"Insufficient text for AI identification ({len(text) if text else 0} chars)")

    # Call AI identifier with filename as hint
    identification = await identify_product(text, provider=provider, filename=product.file_name)

    if "error" in identification:
        raise TaskError(f"AI identify ({provider}): {identification['error']}")

    # Apply identification results
    if identification.get("game_system"):
        game_system = identification["game_system"]
        if isinstance(game_system, list):
            game_system = ", ".join(str(g) for g in game_system)
        product.game_system = game_system
    if identification.get("genre"):
        genre = identification["genre"]
        if isinstance(genre, list):
            genre = ", ".join(str(g) for g in genre)
        product.genre = genre
    if identification.get("product_type"):
        product_type = identification["product_type"]
        if isinstance(product_type, list):
            product_type = ", ".join(str(p) for p in product_type)
        product.product_type = product_type
    if identification.get("publisher"):
        publisher = identification["publisher"]
        if isinstance(publisher, list):
            publisher = ", ".join(str(p) for p in publisher)
        product.publisher = publisher
    if identification.get("author"):
        author = identification["author"]
        if isinstance(author, list):
            author = ", ".join(str(a) for a in author)
        product.author = author
    if identification.get("title"):
        title = identification["title"]
        if isinstance(title, list):
            title = ", ".join(str(t) for t in title)
        product.title = title
    if identification.get("publication_year"):
        product.publication_year = identification["publication_year"]
    if identification.get("level_range_min"):
        product.level_range_min = identification["level_range_min"]
    if identification.get("level_range_max"):
        product.level_range_max = identification["level_range_max"]

    product.ai_identified = True
    product.updated_at = datetime.now(UTC)
    await db.commit()

    logger.info(f"AI identified product {product.id} using {provider}")
    return True


@register_handler("monster_extract")
async def handle_monster_extract_task(
    db: AsyncSession, product: Product, config: dict | None = None
) -> bool:
    """Extract monster entries from a bestiary product (segment -> LLM -> pending rows)."""
    from sqlalchemy import delete, select as _select

    from grimoire.models.monster_entry import MonsterEntry
    from grimoire.processors import monster_normalizer
    from grimoire.processors.monster_segmenter import segment_pages
    from grimoire.processors.system_profiles import PROFILES
    from grimoire.services import processor as _processor

    config = config or {}
    profile_id = config.get("system_profile")
    if profile_id not in PROFILES:
        # Permanent — no retry can ever fix an unrecognized profile id.
        raise TaskError(
            f"monster_extract: unknown system profile '{profile_id}' for '{product.file_name}'"
        )
    profile = PROFILES[profile_id]

    pages = _processor.get_extracted_pages(product)
    if not pages:
        # Permanent until a human re-runs extraction — retrying this task
        # alone can't produce page-anchored text.
        raise TaskError(
            f"monster_extract: no page-anchored text for '{product.file_name}' "
            "(re-run text extraction first)"
        )

    candidates = segment_pages(pages, profile)
    logger.info(f"monster_extract: {len(candidates)} candidates in '{product.file_name}'")

    if not candidates:
        # Reporting success here is the silent failure this guard exists to
        # remove: a wrong-profile run saves nothing and the queue says
        # "completed" with no signal to the owner.
        raise TaskError(
            f"monster_extract: no stat blocks found in '{product.file_name}' "
            f"using the '{profile_id}' profile"
        )

    # Fail fast, before the (slow, sequential) LLM loop, if no provider can
    # possibly work — otherwise every candidate silently no-ops and the task
    # reports "completed" with zero rows saved and no signal to the owner.
    if await monster_normalizer.resolve_provider(config.get("provider")) is None:
        raise TaskError(
            f"monster_extract: no AI provider configured for '{product.file_name}' "
            "(set an OpenAI or Anthropic API key)"
        )

    # LLM loop runs FIRST, accumulating normalized entries in a local list —
    # no DB writes here. A 200-page bestiary is hundreds of sequential LLM
    # calls (tens of minutes); if the delete+commit happened up front (as it
    # did before this fix) the write transaction would sit open for that
    # entire duration, and every other write in the app (confirming an
    # entry, toggling pause/resume, queueing anything) would hit SQLite's
    # 30s busy_timeout and fail. Keeping the loop DB-free also means a
    # worker restart mid-run no longer discards every LLM call already paid
    # for — nothing is written until the short transaction below.
    entries: list[dict] = []
    failed = 0
    for candidate in candidates:
        try:
            entry = await monster_normalizer.normalize_candidate(
                candidate, profile,
                provider=config.get("provider"), model=config.get("model"),
            )
        except Exception as exc:
            failed += 1
            logger.warning(f"monster_extract: candidate '{candidate.name_guess}' failed: {exc}")
            continue
        if entry is None:
            continue
        entries.append(entry)

    # Every candidate errored (as opposed to some being legitimately
    # rejected as "not a monster") — that's provider/transport trouble, not
    # a normal empty result. Fail loudly rather than reporting success with
    # nothing saved.
    if candidates and failed == len(candidates):
        raise TaskError(
            f"monster_extract: all {failed} candidates failed to normalize "
            f"for '{product.file_name}'"
        )

    # Short write window: delete stale pending/rejected rows, re-read the
    # confirmed keys (this reflects any review the owner did WHILE the run
    # was in flight, since it's read here rather than before the loop),
    # filter the accumulated entries against those keys, insert survivors,
    # commit once. Never touch confirmed rows.
    await db.execute(
        delete(MonsterEntry).where(
            MonsterEntry.product_id == product.id,
            MonsterEntry.review_status.in_(["pending", "rejected"]),
        )
    )
    result = await db.execute(
        _select(MonsterEntry.name, MonsterEntry.page_number).where(
            MonsterEntry.product_id == product.id,
            MonsterEntry.review_status == "confirmed",
        )
    )
    confirmed_keys = {(row.name, row.page_number) for row in result}

    saved = 0
    for entry in entries:
        if (entry["name"], entry["page_number"]) in confirmed_keys:
            continue
        db.add(MonsterEntry(product_id=product.id, **entry))
        saved += 1

    await db.commit()
    logger.info(
        f"monster_extract: saved {saved} pending entries for '{product.file_name}' "
        f"({failed} candidates failed)"
    )
    return True


async def _process_item_with_session(db: AsyncSession, item: ProcessingQueue) -> bool:
    """Process a queue item using an existing session.

    Args:
        db: Active database session
        item: The queue item to process (already loaded)

    Returns:
        True if successful, False otherwise
    """
    if item.status != "pending":
        logger.debug(f"Queue item {item.id} is not pending (status: {item.status})")
        return False

    # Mark as processing
    item.status = "processing"
    item.started_at = datetime.now(UTC)
    item.attempts += 1
    await _commit_with_retry(db)

    # Get the product
    product_result = await db.execute(
        select(Product).where(Product.id == item.product_id)
    )
    product = product_result.scalar_one_or_none()

    if not product:
        item.status = "failed"
        item.error_message = "Product not found"
        item.completed_at = datetime.now(UTC)
        await _commit_with_retry(db)
        return False

    handler = TASK_HANDLERS.get(item.task_type)
    if not handler:
        item.status = "failed"
        item.error_message = f"Unknown task type: {item.task_type}"
        item.completed_at = datetime.now(UTC)
        await _commit_with_retry(db)
        return False

    # Parse config from queue item if present
    import json as _json
    item_config = None
    if item.config:
        try:
            item_config = _json.loads(item.config)
        except Exception:
            pass

    try:
        # Pass config to handlers that accept it
        import inspect
        sig = inspect.signature(handler)
        if "config" in sig.parameters:
            success = await handler(db, product, config=item_config)
        else:
            success = await handler(db, product)

        if success:
            item.status = "completed"
            logger.info(f"Queue item {item.id} completed successfully")
        elif item.attempts >= item.max_attempts:
            item.status = "failed"
            item.error_message = "Max attempts reached"
            logger.warning(
                f"Queue item {item.id} ({item.task_type}) failed for "
                f"'{product.file_name}': max attempts reached"
            )
        else:
            item.status = "pending"
            logger.warning(
                f"Queue item {item.id} ({item.task_type}) failed for "
                f"'{product.file_name}', will retry (attempt {item.attempts}/{item.max_attempts})"
            )
        item.completed_at = datetime.now(UTC)

        await _commit_with_retry(db)

        # Emit SSE event
        from grimoire.services.event_bus import event_bus
        if success:
            await event_bus.publish("queue", {
                "type": "task_completed",
                "id": item.id,
                "task_type": item.task_type,
                "product_id": item.product_id,
            })
        elif item.status == "failed":
            await event_bus.publish("queue", {
                "type": "task_failed",
                "id": item.id,
                "task_type": item.task_type,
                "product_id": item.product_id,
                "error": item.error_message,
            })

        return success

    except Exception as e:
        logger.error(
            f"Queue item {item.id} ({item.task_type}) error for "
            f"'{product.file_name}': {e}"
        )
        item.error_message = str(e)[:500]
        # TaskError = permanent failure (bad data, missing prereqs) — no retry
        if isinstance(e, TaskError):
            item.status = "failed"
        else:
            item.status = "failed" if item.attempts >= item.max_attempts else "pending"
        item.completed_at = datetime.now(UTC)
        try:
            await _commit_with_retry(db)
        except Exception:
            logger.error(f"Failed to update status for queue item {item.id} after error")

        from grimoire.services.event_bus import event_bus
        await event_bus.publish("queue", {
            "type": "task_failed",
            "id": item.id,
            "task_type": item.task_type,
            "product_id": item.product_id,
            "error": str(e)[:200],
        })

        return False


async def process_queue_item(item_id: int) -> bool:
    """Process a single queue item by ID (for external API callers).

    Args:
        item_id: ID of the queue item to process

    Returns:
        True if successful, False otherwise
    """
    async with async_session_maker() as db:
        query = select(ProcessingQueue).where(ProcessingQueue.id == item_id)
        result = await db.execute(query)
        item = result.scalar_one_or_none()

        if not item:
            logger.warning(f"Queue item {item_id} not found")
            return False

        return await _process_item_with_session(db, item)


async def get_next_pending_item(db: AsyncSession, task_type: str | None = None) -> ProcessingQueue | None:
    """
    Get the next pending item from the queue.

    Priority order:
    1. By priority (highest first)
    2. By file_size (smallest first — drain fast majority, avoiding head-of-line blocking)
    3. By created_at (oldest first - FIFO within same priority and size)
    """
    query = (
        select(ProcessingQueue)
        .join(Product, ProcessingQueue.product_id == Product.id)
        .where(ProcessingQueue.status == "pending")
    )

    if task_type:
        query = query.where(ProcessingQueue.task_type == task_type)

    query = query.order_by(
        ProcessingQueue.priority.desc(),
        Product.file_size.asc(),  # Smallest files first — drain fast majority
        ProcessingQueue.created_at.asc(),
    ).limit(1)

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_pending_batch(db: AsyncSession, batch_size: int) -> list[ProcessingQueue]:
    """
    Get a batch of pending items from the queue, ordered by priority.

    Returns up to batch_size items. Priority order:
    1. Highest priority number first
    2. Smallest file size first — drain fast majority, avoiding head-of-line blocking
    3. Oldest created_at first (FIFO within same priority and size)
    """
    query = (
        select(ProcessingQueue)
        # LEFT OUTER join (not inner): SQLite FK enforcement is off and there is
        # no ORM cascade from Product -> ProcessingQueue, so deleting a product
        # (dedup resolution, bulk delete, folder delete) can orphan its pending
        # queue rows. An inner join would silently hide those rows forever; the
        # outer join lets them surface (Product.file_size is NULL, which SQLite
        # sorts first under ASC) so the worker still picks them up, fails them
        # with "Product not found", and self-cleans — same as before this join
        # was added.
        .outerjoin(Product, ProcessingQueue.product_id == Product.id)
        .where(ProcessingQueue.status == "pending")
        .order_by(
            ProcessingQueue.priority.desc(),
            Product.file_size.asc(),  # smallest files first — drain fast majority
            ProcessingQueue.created_at.asc(),
        )
        .limit(batch_size)
    )

    result = await db.execute(query)
    return list(result.scalars().all())


async def _auto_requeue_embeddings(db: AsyncSession, batch_size: int = 100) -> int:
    """
    Auto-queue more products for embedding if none are pending/processing.

    Called by the worker loop to ensure continuous embedding progress
    without requiring manual button clicks.

    Returns the number of newly queued items.
    """
    from grimoire.models import ProductEmbedding
    from grimoire.services.embeddings import SENTENCE_TRANSFORMERS_AVAILABLE
    from grimoire.processors.ai_identifier import get_setting_from_db, check_ollama_available, get_ollama_url
    import os

    # Check if any embedding provider is available
    openai_available = bool(os.getenv("OPENAI_API_KEY")) or bool(await get_setting_from_db("openai_api_key"))
    ollama_url = await get_ollama_url()
    ollama_available = check_ollama_available(ollama_url)
    if not (openai_available or ollama_available or SENTENCE_TRANSFORMERS_AVAILABLE):
        return 0

    # Only requeue if there are no pending/processing embed tasks
    pending_query = select(ProcessingQueue.id).where(
        ProcessingQueue.task_type == "embed",
        ProcessingQueue.status.in_(["pending", "processing"]),
    ).limit(1)
    pending_result = await db.execute(pending_query)
    if pending_result.scalar_one_or_none() is not None:
        return 0

    # Find products with extracted text but no embeddings
    embedded_query = select(ProductEmbedding.product_id).distinct()
    embedded_result = await db.execute(embedded_query)
    embedded_ids = set(embedded_result.scalars().all())

    products_query = select(Product).where(
        Product.text_extracted == True,
        Product.extracted_text_path.isnot(None),
        Product.text_unextractable == False,
        Product.is_image_content == False,
    )
    if embedded_ids:
        products_query = products_query.where(Product.id.notin_(embedded_ids))
    products_query = products_query.limit(batch_size)

    result = await db.execute(products_query)
    products = list(result.scalars().all())

    if not products:
        return 0

    queued = 0
    for product in products:
        # Skip if already has a failed entry (avoid retry loops)
        existing = await db.execute(
            select(ProcessingQueue.id).where(
                ProcessingQueue.product_id == product.id,
                ProcessingQueue.task_type == "embed",
                ProcessingQueue.status == "failed",
            ).limit(1)
        )
        if existing.scalar_one_or_none():
            continue

        item = ProcessingQueue(
            product_id=product.id,
            task_type="embed",
            priority=9,
            status="pending",
        )
        db.add(item)
        queued += 1

    if queued > 0:
        await db.commit()
        logger.info(f"Auto-queued {queued} products for embedding generation")

    return queued


async def run_queue_worker(
    poll_interval: float = 2.0,
    batch_size: int = 10,
    stop_event: asyncio.Event | None = None,
    max_concurrent: int | None = None,
) -> None:
    """
    Run the queue worker continuously with concurrent task processing.

    Fetches a batch of pending items each cycle and processes them concurrently,
    limited by a semaphore to prevent resource exhaustion.

    Args:
        poll_interval: Seconds between polling when queue is empty
        batch_size: Max items to fetch per poll cycle
        stop_event: Event to signal worker to stop
        max_concurrent: Max simultaneous tasks (defaults to config value)
    """
    from grimoire.config import settings

    if max_concurrent is None:
        max_concurrent = settings.max_concurrent_processing

    # Reset any items stuck in "processing" from a previous crash
    async with async_session_maker() as db:
        stuck = await db.execute(
            select(ProcessingQueue).where(ProcessingQueue.status == "processing")
        )
        stuck_items = stuck.scalars().all()
        if stuck_items:
            for item in stuck_items:
                item.status = "pending"
                item.started_at = None
            await db.commit()
            logger.info(f"Reset {len(stuck_items)} stuck 'processing' items to 'pending'")

    logger.info(
        f"Queue worker started ("
        f"batch_size={batch_size}, poll_interval={poll_interval}s)"
    )

    while True:
        if stop_event and stop_event.is_set():
            logger.info("Queue worker stopping")
            break

        await touch_worker_heartbeat()

        # Wait while paused ("Grimoire Paused"). Re-read the DB flag each cycle
        # so the API's pause/resume takes effect across the process boundary.
        while await is_processing_paused():
            if stop_event and stop_event.is_set():
                break
            # Keep beating while paused: a paused worker is still a live one,
            # and diagnostics needs to tell those two states apart.
            await touch_worker_heartbeat()
            await asyncio.sleep(1.0)

        if stop_event and stop_event.is_set():
            continue

        try:
            async with async_session_maker() as db:
                items = await get_pending_batch(db, batch_size)

            if not items:
                # Auto-queue embeddings when queue is idle
                async with async_session_maker() as requeue_db:
                    await _auto_requeue_embeddings(requeue_db)
                await asyncio.sleep(poll_interval)
                continue

            # Process items sequentially to avoid SQLite write contention.
            # Ollama/embedding calls are sequential on the server side anyway,
            # so concurrent DB sessions just cause lock errors without speedup.
            succeeded = 0
            failed = 0
            failed_details: list[str] = []
            for item in items:
                try:
                    result = await process_queue_item(item.id)
                    if result is True:
                        succeeded += 1
                    else:
                        failed += 1
                        failed_details.append(
                            f"  - item {item.id} ({item.task_type}) product_id={item.product_id}"
                        )
                except Exception as e:
                    logger.error(f"Queue task raised exception: {e}")
                    failed += 1
                    failed_details.append(
                        f"  - item {item.id} ({item.task_type}) product_id={item.product_id}: {e}"
                    )

            logger.info(
                f"Batch complete: {succeeded} succeeded, {failed} failed "
                f"out of {len(items)}"
            )
            if failed_details:
                # Look up filenames for failed items
                failed_product_ids = {
                    item.product_id for item in items
                }
                async with async_session_maker() as lookup_db:
                    result = await lookup_db.execute(
                        select(Product.id, Product.file_name).where(
                            Product.id.in_(failed_product_ids)
                        )
                    )
                    name_map = dict(result.all())
                # Re-build details with filenames
                enriched: list[str] = []
                for detail in failed_details:
                    for pid, fname in name_map.items():
                        detail = detail.replace(
                            f"product_id={pid}",
                            f"'{fname}'"
                        )
                    enriched.append(detail)
                logger.warning(
                    "Failed items:\n" + "\n".join(enriched)
                )

            from grimoire.services.event_bus import event_bus
            await event_bus.publish("queue", {
                "type": "batch_complete",
                "succeeded": succeeded,
                "failed": failed,
                "total": len(items),
            })

            # If we got a full batch, immediately poll again (more items likely)
            if len(items) >= batch_size:
                continue

        except Exception as e:
            logger.error(f"Queue worker error: {e}")

        await asyncio.sleep(poll_interval)

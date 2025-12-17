# Grimoire Contribution Enrichment Implementation Plan

**Status:** ✅ Implemented  
**Date:** December 2024  
**Context:** Implementing Grimoire-side changes to support richer Codex contributions

---

## Current State Analysis

### What Grimoire Already Has ✅

| Feature | Location | Notes |
|---------|----------|-------|
| **Contribution Queue** | `models/contribution.py` | `ContributionQueue` with pending/submitted/failed states |
| **Codex Client** | `services/codex.py` | `CodexClient.contribute()` with proper payload building |
| **Queue Management** | `services/contribution_service.py` | Queue/submit/retry logic |
| **Sync Service** | `services/sync_service.py` | `build_contribution_data()`, settings from DB |
| **Cover Extraction** | `services/processor.py` | `extract_cover_image()` using PyMuPDF → local JPEG |
| **PDF Metadata** | `services/metadata_extractor.py` | Comprehensive extraction from PDF props, text, filename |
| **Game System Detection** | `services/metadata_extractor.py` | `KNOWN_GAME_SYSTEMS` pattern matching on text |
| **Publisher Detection** | `services/metadata_extractor.py` | `KNOWN_PUBLISHERS` pattern matching |
| **Product Type Detection** | `services/metadata_extractor.py` | `PRODUCT_TYPE_KEYWORDS` classification |
| **File Hash** | `services/codex.py` | `compute_file_hash()` SHA-256 |
| **Settings UI** | `frontend/pages/Settings.tsx` | Codex API key, contribute toggle |

### What's Missing ❌

| Feature | Priority | Description |
|---------|----------|-------------|
| **Cover Image for Contribution** | HIGH | Convert local cover to base64 for API payload |
| **No-Change Detection** | HIGH | Skip contributions that add nothing new |
| **Rate-Limited Queue Processing** | MEDIUM | Background queue with rate limiting |
| **Product Matching Before Send** | MEDIUM | Check Codex before contributing (avoid duplicates) |
| **Sync Status UI** | LOW | Show queue status, pending count, estimated time |
| **Description Extraction** | LOW | Extract description/summary from PDF text |

---

## Implementation Phases

### Phase 1: Enrich Contribution Payload (HIGH PRIORITY)

**Goal:** Include cover image and all available metadata in contributions.

#### 1.1 Add Cover Image to Contribution Data

The cover is already extracted to disk. Add function to encode it for API submission:

```python
# services/contribution_service.py

import base64
from pathlib import Path

def get_cover_image_base64(product: Product, max_size_kb: int = 500) -> str | None:
    """
    Get product's cover image as base64 for contribution.
    Returns None if no cover or too large after optimization.
    """
    if not product.cover_extracted or not product.cover_image_path:
        return None
    
    cover_path = Path(product.cover_image_path)
    if not cover_path.exists():
        return None
    
    # Read and check size
    with open(cover_path, "rb") as f:
        data = f.read()
    
    # If under limit, return as-is
    if len(data) <= max_size_kb * 1024:
        return base64.b64encode(data).decode("utf-8")
    
    # Re-compress with lower quality
    from PIL import Image
    from io import BytesIO
    
    img = Image.open(cover_path)
    buffer = BytesIO()
    quality = 70
    
    while quality > 20:
        buffer.seek(0)
        buffer.truncate()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        if buffer.tell() <= max_size_kb * 1024:
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
        quality -= 10
    
    return None  # Too large even at lowest quality
```

#### 1.2 Update `build_contribution_data()` in sync_service.py

```python
def build_contribution_data(product: Product, include_cover: bool = True) -> dict[str, Any]:
    """Build comprehensive contribution data from a product."""
    from grimoire.services.contribution_service import get_cover_image_base64
    
    data = {
        "title": product.title,
        "publisher": product.publisher,
        "author": product.author,
        "game_system": product.game_system,
        "genre": product.genre,
        "product_type": product.product_type,
        "publication_year": product.publication_year,
        "page_count": product.page_count,
        "level_range_min": product.level_range_min,
        "level_range_max": product.level_range_max,
        "party_size_min": product.party_size_min,
        "party_size_max": product.party_size_max,
        "estimated_runtime": product.estimated_runtime,
    }
    
    # Add cover image if available
    if include_cover:
        cover_b64 = get_cover_image_base64(product)
        if cover_b64:
            data["cover_image"] = cover_b64
    
    # Remove None values
    return {k: v for k, v in data.items() if v is not None}
```

---

### Phase 2: No-Change Detection (HIGH PRIORITY)

**Goal:** Don't submit contributions that add nothing new to Codex.

#### 2.1 Fetch Existing Product from Codex Before Contributing

```python
# services/sync_service.py

async def should_contribute(
    product: Product,
    codex_client: CodexClient,
) -> tuple[bool, str]:
    """
    Check if this product's contribution would add value to Codex.
    
    Returns:
        Tuple of (should_contribute, reason)
    """
    # Try to find existing product in Codex
    match = await codex_client.identify_by_hash(product.file_hash)
    
    if not match or not match.product:
        # New product - always contribute
        return True, "new_product"
    
    codex_product = match.product
    local_data = build_contribution_data(product, include_cover=True)
    
    # Check if we have data Codex doesn't
    dominated_fields = [
        "publisher", "author", "game_system", "product_type",
        "publication_year", "page_count", "level_range_min", "level_range_max"
    ]
    
    for field in dominated_fields:
        local_value = local_data.get(field)
        codex_value = getattr(codex_product, field, None)
        
        if local_value and not codex_value:
            return True, f"has_{field}"
    
    # Check cover image
    if local_data.get("cover_image") and not codex_product.cover_url:
        return True, "has_cover_image"
    
    return False, "no_new_data"
```

#### 2.2 Integrate into Contribution Workflow

Update `queue_product_for_contribution()` to check first:

```python
async def queue_product_for_contribution(
    db: AsyncSession,
    product: Product,
    submit_immediately: bool = True,
    skip_no_change_check: bool = False,
) -> dict[str, Any]:
    # ... existing validation ...
    
    # Check if contribution adds value (unless skipped)
    if not skip_no_change_check:
        codex = get_codex_client()
        if await codex.is_available():
            should, reason = await should_contribute(product, codex)
            if not should:
                return {
                    "success": False,
                    "reason": "no_new_data",
                    "message": "Product already has complete data in Codex",
                }
    
    # ... rest of existing logic ...
```

---

### Phase 3: Rate-Limited Background Queue (MEDIUM PRIORITY)

**Goal:** Process contribution queue in background respecting rate limits.

#### 3.1 Queue Processor Service

```python
# services/contribution_queue_processor.py

import asyncio
import logging
from datetime import datetime, UTC

logger = logging.getLogger(__name__)

class ContributionQueueProcessor:
    """Background processor for contribution queue with rate limiting."""
    
    def __init__(
        self,
        rate_per_minute: int = 10,
        max_retries: int = 3,
    ):
        self.rate_per_minute = rate_per_minute
        self.min_interval = 60.0 / rate_per_minute
        self.max_retries = max_retries
        self.last_send_time: float = 0
        self.is_running = False
        self._task: asyncio.Task | None = None
    
    async def start(self, db_session_factory):
        """Start background processing."""
        if self.is_running:
            return
        
        self.is_running = True
        self._task = asyncio.create_task(
            self._process_loop(db_session_factory)
        )
        logger.info("Contribution queue processor started")
    
    def stop(self):
        """Stop background processing."""
        self.is_running = False
        if self._task:
            self._task.cancel()
        logger.info("Contribution queue processor stopped")
    
    async def _process_loop(self, db_session_factory):
        """Main processing loop."""
        while self.is_running:
            try:
                async with db_session_factory() as db:
                    pending = await get_pending_contributions(db)
                    
                    if not pending:
                        await asyncio.sleep(30)  # Check every 30s when idle
                        continue
                    
                    for contribution in pending:
                        if not self.is_running:
                            break
                        
                        if contribution.attempts >= self.max_retries:
                            continue
                        
                        # Rate limit
                        elapsed = asyncio.get_event_loop().time() - self.last_send_time
                        if elapsed < self.min_interval:
                            await asyncio.sleep(self.min_interval - elapsed)
                        
                        await self._process_one(db, contribution)
                        self.last_send_time = asyncio.get_event_loop().time()
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Queue processor error: {e}")
                await asyncio.sleep(60)  # Back off on error
    
    async def _process_one(self, db: AsyncSession, contribution: ContributionQueue):
        """Process a single contribution."""
        # Get API key from settings
        _, api_key = await get_codex_settings_from_db(db)
        if not api_key:
            return
        
        success = await submit_contribution(db, contribution, api_key)
        
        if success:
            logger.info(f"Submitted contribution {contribution.id}")
        else:
            logger.warning(f"Failed contribution {contribution.id}: {contribution.error_message}")
```

---

### Phase 4: Product Matching Enhancement (MEDIUM PRIORITY)

**Goal:** Better matching to decide between new_product vs edit_product contribution types.

#### 4.1 Enhance CodexClient with Product Check

```python
# services/codex.py - add method

async def check_product_exists(
    self,
    file_hash: str | None = None,
    title: str | None = None,
    publisher: str | None = None,
) -> tuple[bool, CodexProduct | None]:
    """
    Check if product exists in Codex.
    
    Returns:
        Tuple of (exists, product_if_found)
    """
    # Try hash first (exact match)
    if file_hash:
        match = await self.identify_by_hash(file_hash)
        if match and match.product:
            return True, match.product
    
    # Try title + publisher (likely match)
    if title:
        match = await self.identify_by_title(title)
        if match and match.product and match.confidence > 0.9:
            # If publisher matches too, high confidence
            if publisher and match.product.publisher:
                if publisher.lower() == match.product.publisher.lower():
                    return True, match.product
            elif match.confidence > 0.95:
                return True, match.product
    
    return False, None
```

#### 4.2 Update Contribution Creation

Set `contribution_type` based on matching:

```python
# In queue_product_for_contribution

exists, existing_product = await codex.check_product_exists(
    file_hash=product.file_hash,
    title=product.title,
    publisher=product.publisher,
)

contribution_type = "edit_product" if exists else "new_product"
existing_product_id = existing_product.id if existing_product else None
```

---

## Changes Required to Codex API

These need to be communicated back to the Codex project:

1. **Accept `cover_image` field** - Base64-encoded JPEG in contribution data
2. **Accept `author` field** - Already in Grimoire, might be missing in Codex schema
3. **Accept `genre` field** - Grimoire extracts this
4. **Return `no_change` status** - When contribution adds nothing new (optional - Grimoire can check first)

---

## Implementation Order

| Step | Task | Effort | Dependencies |
|------|------|--------|--------------|
| 1 | Add `get_cover_image_base64()` | 30 min | None |
| 2 | Update `build_contribution_data()` to include cover | 15 min | Step 1 |
| 3 | Add `should_contribute()` check | 45 min | Step 2 |
| 4 | Integrate no-change check into queue workflow | 30 min | Step 3 |
| 5 | Add background queue processor | 1 hour | Steps 1-4 |
| 6 | Add sync status API endpoint | 30 min | Step 5 |
| 7 | Frontend sync status UI (optional) | 1-2 hours | Step 6 |

---

## Testing Plan

1. **Unit Tests**
   - `test_get_cover_image_base64()` - with/without cover, size limits
   - `test_should_contribute()` - new product, existing with missing data, complete
   - `test_build_contribution_data()` - all fields populated

2. **Integration Tests**
   - Queue product → verify payload structure
   - Submit to mock Codex → verify response handling
   - Rate limiting behavior

3. **Manual Testing**
   - Real contribution to Codex staging/dev
   - Verify cover image appears correctly
   - Verify no-change detection works

---

## Open Questions (Resolved)

1. **Codex API field names** - ✅ Codex will accept `cover_image` as base64
2. **Max image size** - ✅ 500KB limit agreed
3. **Rate limits** - ✅ 10/min client-side, Codex: 30/5min burst, 60/hour sustained, 500/day
4. **Existing product ID format** - UUID string for `product` field in edit contributions

---

## Implementation Summary

### Files Modified

| File | Changes |
|------|---------|
| `services/contribution_service.py` | Added `get_cover_image_base64()` with progressive compression |
| `services/sync_service.py` | Added `should_contribute()`, updated `build_contribution_data()` with author/genre/cover_image |
| `services/codex.py` | Added `author` and `genre` fields to `CodexProduct` |
| `services/contribution_queue_processor.py` | **NEW** - Background queue processor with rate limiting |
| `api/routes/contributions.py` | Added `/queue/status` endpoint |
| `database.py` | Added `get_db_session()` context manager |
| `main.py` | Integrated contribution queue processor in app lifespan |

### Features Implemented

1. **Cover Image Contribution** - Extracts cover, compresses to <500KB, encodes as base64
2. **No-Change Detection** - Skips contributions when Codex already has complete data
3. **Rate-Limited Queue** - Background processor at 10/min with exponential backoff
4. **Queue Status API** - `/api/v1/contributions/queue/status` endpoint

### Codex API Contract (Confirmed)

Grimoire sends:
```json
{
  "title": "Adventure Name",
  "author": "John Doe",
  "genre": "horror",
  "cover_image_base64": "...",
  "publisher": "Publisher Name",
  "game_system": "DCC",
  "product_type": "Adventure",
  "publication_year": 2024,
  "page_count": 48,
  ...
}
```

Notes:
- `cover_image_base64`: max 500KB, with or without data URL prefix
- Codex also supports `authors` (array) and `genres` (array) - Grimoire currently sends single values
- Codex stores `cover_image_base64` in contribution data for moderation review

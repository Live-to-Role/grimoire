# Text Extraction & Search Implementation Plan

**Created**: December 14, 2024  
**Status**: Planning  
**Goal**: Enable users to search their library with queries like "encounter table with kobolds" or "adventures in a swamp"

---

## 1. Overview

This document outlines the implementation of comprehensive text extraction and search capabilities for Grimoire. The system follows a tiered approach where users have full control over processing, with clear cost estimates before any AI operations.

### 1.1 Design Principles

1. **User Choice First**: All processing is opt-in. Users decide what gets processed and when.
2. **Cost Transparency**: Always show estimated costs before AI operations execute.
3. **Privacy Respect**: Clear communication about AI provider data policies.
4. **Offline-First**: Core features work without cloud AI (Ollama default).
5. **Progressive Enhancement**: Basic search works immediately; AI enhances it.

---

## 2. Processing Tiers

### Tier 1: Quick Index (Lightweight)

**Purpose**: Fast identification and basic metadata for browsing.

| Component | Description | Automatic? |
|-----------|-------------|------------|
| Cover extraction | First page as thumbnail | ✅ During scan |
| PDF metadata | Page count, embedded title/author | ✅ During scan |
| Quick text (10 pages) | First 10 pages for identification | ⚙️ User setting |
| AI identification | Title, publisher, game system, type | ⚙️ User setting |

**When to use**: During library scan or when user opens a product detail page.

### Tier 2: Deep Index (Full Content)

**Purpose**: Enable comprehensive content search across entire PDFs.

| Component | Description | Automatic? |
|-----------|-------------|------------|
| Full text extraction | All pages to markdown | ❌ Manual trigger |
| Full-text search index | PostgreSQL FTS on extracted text | ❌ After extraction |
| Embeddings (optional) | Vector embeddings for semantic search | ❌ Manual trigger |

**When to use**: User explicitly requests "Index for search" or runs batch processing.

---

## 3. Storage Estimates

### 3.1 Text Storage

Based on typical RPG PDFs:

| PDF Size | Avg Pages | Extracted Text | Compressed |
|----------|-----------|----------------|------------|
| Small (1-5 MB) | 20-50 | ~100-250 KB | ~30-75 KB |
| Medium (5-20 MB) | 50-150 | ~250-750 KB | ~75-225 KB |
| Large (20-100 MB) | 150-400 | ~750 KB-2 MB | ~225-600 KB |
| Huge (100+ MB) | 400+ | ~2-5 MB | ~600 KB-1.5 MB |

**For a 6,000 PDF library (84 GB total):**

| Scenario | Raw Text | Compressed | With FTS Index |
|----------|----------|------------|----------------|
| Conservative (avg 300 KB/PDF) | ~1.8 GB | ~540 MB | ~2.5 GB |
| Moderate (avg 500 KB/PDF) | ~3 GB | ~900 MB | ~4 GB |
| Large files (avg 1 MB/PDF) | ~6 GB | ~1.8 GB | ~8 GB |

**Recommendation**: Store extracted text as compressed JSON files on disk (already implemented). Build FTS index in PostgreSQL referencing file paths.

### 3.2 Embedding Storage

If using embeddings for semantic search:

| Embedding Model | Dimensions | Per Chunk | Per PDF (avg 50 chunks) | 6,000 PDFs |
|-----------------|------------|-----------|-------------------------|------------|
| text-embedding-3-small | 1536 | 6 KB | 300 KB | ~1.8 GB |
| nomic-embed-text (Ollama) | 768 | 3 KB | 150 KB | ~900 MB |

**Total estimated storage for full implementation**: 3-10 GB depending on library composition.

---

## 4. AI Provider Configuration

### 4.1 Default: Ollama (Local, Free)

Ollama runs locally with no API costs and no data leaving the user's machine.

**Recommended models:**
- **Identification**: `llama3.2` or `mistral` (~7B parameters, fast)
- **Embeddings**: `nomic-embed-text` (optimized for retrieval)

**Setup requirement**: User must have Ollama installed and running.

### 4.2 Cloud Providers (Optional, Paid)

For users who want faster processing or don't have GPU:

| Provider | Identification Model | Embedding Model | Speed |
|----------|---------------------|-----------------|-------|
| OpenAI | gpt-4o-mini | text-embedding-3-small | Fast |
| Anthropic | claude-3-haiku | N/A (use OpenAI) | Fast |

### 4.3 Privacy Notice (Display to Users)

```
🔒 AI Privacy Information

When using cloud AI providers (OpenAI, Anthropic):
• Your PDF text is sent to the provider's API for processing
• Text is NOT used to train AI models
• Data is typically deleted within 30 days

Provider Policies:
• OpenAI: https://openai.com/policies/api-data-usage-policies
• Anthropic: https://www.anthropic.com/legal/privacy

For maximum privacy, use Ollama (local processing, no data leaves your computer).
```

---

## 5. Cost Estimation

### 5.1 Per-Operation Costs (Cloud AI)

| Operation | Input Tokens | Output Tokens | OpenAI Cost | Anthropic Cost |
|-----------|--------------|---------------|-------------|----------------|
| Identify (10 pages) | ~2,000 | ~150 | ~$0.0004 | ~$0.0007 |
| Identify (full PDF) | ~10,000 | ~150 | ~$0.002 | ~$0.003 |
| Suggest tags | ~2,000 | ~200 | ~$0.0005 | ~$0.0008 |
| Embed chunk (500 tokens) | 500 | N/A | ~$0.00001 | N/A |

### 5.2 Batch Cost Examples

| Operation | 100 PDFs | 1,000 PDFs | 6,000 PDFs |
|-----------|----------|------------|------------|
| AI Identification | ~$0.04 | ~$0.40 | ~$2.40 |
| Full Embedding (50 chunks/PDF) | ~$0.05 | ~$0.50 | ~$3.00 |
| Both | ~$0.09 | ~$0.90 | ~$5.40 |

**With Ollama**: $0.00 (local compute only)

### 5.3 Cost Warning UI

Before any batch AI operation, display:

```
┌─────────────────────────────────────────────────────────┐
│ 🤖 AI Processing Cost Estimate                          │
├─────────────────────────────────────────────────────────┤
│ Operation: Identify 247 products                        │
│ Provider: OpenAI (gpt-4o-mini)                          │
│                                                         │
│ Estimated tokens: ~494,000 input, ~37,050 output        │
│ Estimated cost: ~$0.10 USD                              │
│                                                         │
│ ⚡ Faster but costs money                               │
│    [Use OpenAI - ~$0.10]                                │
│                                                         │
│ 🏠 Free but slower (requires Ollama running)            │
│    [Use Ollama - Free]                                  │
│                                                         │
│ [Cancel]                                                │
└─────────────────────────────────────────────────────────┘
```

---

## 6. Search Architecture

### 6.1 Search Types

| Search Type | Technology | Example Query | Matches |
|-------------|------------|---------------|---------|
| Metadata | SQL LIKE/ILIKE | "curse of strahd" | Title, publisher fields |
| Full-text | PostgreSQL FTS | "kobold encounter" | Exact words in content |
| Semantic | Vector similarity | "swamp adventure" | "marsh exploration", "wetland quest" |

### 6.2 Hybrid Search Flow

```
User Query: "kobold encounter table"
         │
         ▼
┌─────────────────────────────────────────┐
│ 1. Metadata Search (instant)            │
│    WHERE title ILIKE '%kobold%'         │
│    → Products with "kobold" in title    │
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ 2. Full-Text Search (fast)              │
│    WHERE fts_vector @@ to_tsquery(...)  │
│    → Products containing those words    │
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ 3. Semantic Search (if enabled)         │
│    ORDER BY embedding <-> query_embed   │
│    → Products with similar meaning      │
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ 4. Merge & Rank Results                 │
│    Combine scores, deduplicate          │
│    → Final ranked result list           │
└─────────────────────────────────────────┘
```

### 6.3 Database Schema Additions

```sql
-- Add to Product table
ALTER TABLE products ADD COLUMN full_text_indexed BOOLEAN DEFAULT FALSE;
ALTER TABLE products ADD COLUMN fts_vector tsvector;
ALTER TABLE products ADD COLUMN embeddings_generated BOOLEAN DEFAULT FALSE;

-- Full-text search index
CREATE INDEX idx_products_fts ON products USING GIN(fts_vector);

-- Embeddings table (for semantic search)
CREATE TABLE product_embeddings (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding vector(1536),  -- or 768 for Ollama models
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(product_id, chunk_index)
);

CREATE INDEX idx_embeddings_vector ON product_embeddings 
    USING ivfflat (embedding vector_cosine_ops);
```

---

## 7. Implementation Phases

### Phase 1: Manual Extraction Triggers ← START HERE

**Goal**: Users can manually trigger text extraction and AI identification.

**Backend:**
- [ ] API endpoint: `POST /api/products/{id}/extract-text` (already exists)
- [ ] API endpoint: `POST /api/products/{id}/identify` with cost estimate
- [ ] API endpoint: `POST /api/bulk/extract-text` with progress tracking
- [ ] API endpoint: `POST /api/bulk/identify` with cost warning
- [ ] API endpoint: `GET /api/ai/estimate-cost` for batch operations
- [ ] API endpoint: `GET /api/ai/providers` with privacy info

**Frontend:**
- [ ] Product detail: "Extract Text" button
- [ ] Product detail: "AI Identify" button with cost estimate
- [ ] Library management: Batch processing panel
- [ ] Cost confirmation modal before AI operations
- [ ] Privacy notice modal (show once, remember preference)
- [ ] Progress indicator for batch operations

### Phase 2: User Settings for Auto-Processing

**Goal**: Users can opt-in to automatic processing during scan.

**Settings to add:**
- [ ] `auto_extract_quick_text`: Extract first 10 pages during scan (default: false)
- [ ] `auto_ai_identify`: Run AI identification during scan (default: false)
- [ ] `preferred_ai_provider`: "ollama" | "openai" | "anthropic" (default: "ollama")
- [ ] `ollama_model`: Model name for Ollama (default: "llama3.2")

**Implementation:**
- [ ] Settings API endpoints
- [ ] Settings UI panel
- [ ] Scanner integration (check settings, queue tasks)

### Phase 3: Full-Text Search

**Goal**: Search across all extracted text content.

**Implementation:**
- [ ] Add `fts_vector` column to Product model
- [ ] Migration to add column and index
- [ ] Update text extraction to populate FTS vector
- [ ] Search API: `GET /api/search?q=...&type=fulltext`
- [ ] Search UI with result highlighting

### Phase 4: Semantic Search (Optional Enhancement)

**Goal**: "Swamp adventure" finds "marsh exploration".

**Implementation:**
- [ ] Add pgvector extension to PostgreSQL
- [ ] ProductEmbedding model and table
- [ ] Chunking logic (split text into ~500 token chunks)
- [ ] Embedding generation (Ollama nomic-embed-text or OpenAI)
- [ ] Vector similarity search endpoint
- [ ] Hybrid search combining FTS + semantic
- [ ] UI toggle for semantic search

---

## 8. API Specifications

### 8.1 Cost Estimate Endpoint

```
GET /api/ai/estimate-cost?operation=identify&product_ids=1,2,3&provider=openai

Response:
{
  "operation": "identify",
  "product_count": 3,
  "provider": "openai",
  "model": "gpt-4o-mini",
  "estimated_input_tokens": 6000,
  "estimated_output_tokens": 450,
  "estimated_cost_usd": 0.0012,
  "is_free": false,
  "alternatives": [
    {
      "provider": "ollama",
      "model": "llama3.2",
      "estimated_cost_usd": 0,
      "is_free": true,
      "note": "Requires Ollama running locally"
    }
  ]
}
```

### 8.2 AI Provider Info Endpoint

```
GET /api/ai/providers

Response:
{
  "available": ["ollama", "openai"],
  "configured": {
    "ollama": {"url": "http://localhost:11434", "status": "connected"},
    "openai": {"status": "api_key_set"},
    "anthropic": {"status": "not_configured"}
  },
  "default": "ollama",
  "privacy_notice": {
    "ollama": "Local processing. No data leaves your computer.",
    "openai": "Data sent to OpenAI API. Not used for training. See: https://openai.com/policies/api-data-usage-policies",
    "anthropic": "Data sent to Anthropic API. Not used for training. See: https://www.anthropic.com/legal/privacy"
  }
}
```

### 8.3 Batch Identify with Confirmation

```
POST /api/bulk/identify
{
  "product_ids": [1, 2, 3, ...],
  "provider": "openai",
  "confirmed_cost": true  // Must be true after user sees estimate
}

Response:
{
  "job_id": "abc123",
  "status": "processing",
  "total": 247,
  "processed": 0,
  "estimated_cost_usd": 0.10
}
```

---

## 9. UI Mockups

### 9.1 Product Detail - Processing Section

```
┌─────────────────────────────────────────────────────────┐
│ Processing Status                                       │
├─────────────────────────────────────────────────────────┤
│ ✅ Cover Extracted                                      │
│ ❌ Text Extracted          [Extract Text]               │
│ ❌ AI Identified           [Identify with AI]           │
│ ❌ Indexed for Search      [Index for Search]           │
└─────────────────────────────────────────────────────────┘
```

### 9.2 Library Management - Batch Processing

```
┌─────────────────────────────────────────────────────────┐
│ Batch Processing                                        │
├─────────────────────────────────────────────────────────┤
│ Products without text extracted: 5,932                  │
│ [Extract All Text]                                      │
│                                                         │
│ Products without AI identification: 5,932               │
│ [Identify All with AI] → Shows cost estimate first      │
│                                                         │
│ Products not indexed for search: 5,932                  │
│ [Index All for Search]                                  │
└─────────────────────────────────────────────────────────┘
```

### 9.3 Settings - AI Configuration

```
┌─────────────────────────────────────────────────────────┐
│ AI Settings                                             │
├─────────────────────────────────────────────────────────┤
│ Preferred AI Provider:                                  │
│ ○ Ollama (Local, Free) ← Recommended                    │
│   Model: [llama3.2        ▼]                            │
│   Status: 🟢 Connected                                  │
│                                                         │
│ ○ OpenAI (Cloud, Paid)                                  │
│   API Key: [••••••••••••••••]                           │
│   Status: 🟢 Configured                                 │
│                                                         │
│ ○ Anthropic (Cloud, Paid)                               │
│   API Key: [Not configured  ]                           │
│   Status: ⚪ Not configured                             │
├─────────────────────────────────────────────────────────┤
│ Auto-Processing (during library scan):                  │
│ [ ] Extract quick text (first 10 pages)                 │
│ [ ] AI identify new products                            │
│     ⚠️ Will use preferred provider above                │
├─────────────────────────────────────────────────────────┤
│ 🔒 Privacy: View AI provider data policies              │
└─────────────────────────────────────────────────────────┘
```

---

## 10. Success Criteria

### Phase 1 Complete When:
- [ ] User can extract text from single product via UI
- [ ] User can trigger AI identification with cost shown first
- [ ] User can batch extract text with progress indicator
- [ ] User can batch identify with cost confirmation modal
- [ ] Privacy notice shown before first AI operation

### Phase 2 Complete When:
- [ ] Settings page allows configuring AI provider
- [ ] Settings allow enabling auto-processing during scan
- [ ] Scanner respects settings for Tier 1 processing

### Phase 3 Complete When:
- [ ] User can search "kobold encounter" and find matching content
- [ ] Search results show which page contains the match
- [ ] Full-text search works offline (no AI required)

### Phase 4 Complete When:
- [ ] User can search "swamp adventure" and find "marsh exploration"
- [ ] Semantic search toggle in search UI
- [ ] Clear cost indication for embedding generation

---

## 11. Performance Considerations for Large Libraries

### 11.1 Scale Targets

| Library Size | Products | Estimated Text | Chunks (500 tokens) | Concern Level |
|--------------|----------|----------------|---------------------|---------------|
| Small | <1,000 | <500 MB | <50,000 | Low |
| Medium | 1,000-10,000 | 500 MB - 5 GB | 50,000-500,000 | Medium |
| Large | 10,000-50,000 | 5-25 GB | 500,000-2.5M | High |
| Massive | 50,000+ | 25+ GB | 2.5M+ | Critical |

### 11.2 Text Extraction Performance

| Concern | Mitigation |
|---------|------------|
| **Single PDF blocking** | Use background queue (Huey) for all extraction |
| **Memory spikes** | Process one PDF at a time, stream to disk |
| **Slow Marker extraction** | PyMuPDF fallback for batch ops; Marker only on-demand |
| **Disk I/O bottleneck** | Store text files in sharded directories (e.g., `text/00/`, `text/01/`) |

**Batch extraction strategy:**
```
For 10,000 PDFs:
- Parallel workers: 4 (configurable based on CPU)
- Memory per worker: ~500 MB max
- Estimated time (PyMuPDF): 2-4 hours
- Estimated time (Marker): 20-40 hours
```

### 11.3 Database Query Performance

| Query Type | Rows | Unoptimized | With Indexes | Strategy |
|------------|------|-------------|--------------|----------|
| FTS search | 10K products | 500ms | <50ms | GIN index on tsvector |
| FTS search | 100K products | 5s | <100ms | GIN index + LIMIT |
| Vector search | 500K chunks | 10s | <200ms | IVFFlat index, probe limit |
| Vector search | 2M chunks | 60s | <500ms | HNSW index, partition by product |

**Required indexes:**
```sql
-- Full-text search (already fast with GIN)
CREATE INDEX idx_products_fts ON products USING GIN(fts_vector);

-- Vector search (critical for large scale)
-- IVFFlat: faster build, slower query
CREATE INDEX idx_embeddings_ivfflat ON product_embeddings 
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 1000);

-- HNSW: slower build, faster query (preferred for 100K+ chunks)
CREATE INDEX idx_embeddings_hnsw ON product_embeddings 
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

### 11.4 Embedding Generation at Scale

| Provider | 10K PDFs (500K chunks) | Time Estimate | Cost |
|----------|------------------------|---------------|------|
| OpenAI (batch) | Parallel API calls | 1-2 hours | ~$5 |
| Ollama (local) | Sequential | 10-20 hours | Free |
| Ollama (GPU) | Sequential w/ GPU | 2-5 hours | Free |

**Mitigation strategies:**
- **Rate limiting**: Respect API limits (OpenAI: 3,000 RPM)
- **Checkpointing**: Save progress every 100 products; resume on failure
- **Incremental**: Only embed new/changed products
- **Background processing**: Never block UI; show progress bar

### 11.5 Search Result Pagination

For large result sets:
```sql
-- Bad: Full scan then limit
SELECT * FROM products WHERE fts_vector @@ query ORDER BY ts_rank(...) LIMIT 20;

-- Good: Use cursor-based pagination with index
SELECT * FROM products 
WHERE fts_vector @@ query 
  AND id > :last_seen_id
ORDER BY id
LIMIT 20;

-- Best: Pre-compute ranks for hot queries (future optimization)
```

### 11.6 Memory Management

| Operation | Peak Memory | Strategy |
|-----------|-------------|----------|
| Text extraction | 500 MB/PDF max | Stream output, close files |
| FTS indexing | Minimal | PostgreSQL handles internally |
| Embedding generation | 1-2 GB (model) | Load model once, reuse |
| Search | ~100 MB | Limit result set, paginate |

**Frontend considerations:**
- Virtual scrolling for large product lists (already implemented)
- Lazy load search results
- Debounce search input (300ms)

### 11.7 Recommended Limits

| Setting | Default | Max Recommended | Reason |
|---------|---------|-----------------|--------|
| Batch extract size | 100 | 1,000 | Memory, progress feedback |
| Batch identify size | 50 | 500 | API rate limits |
| Search results per page | 20 | 100 | UI responsiveness |
| Concurrent extraction workers | 2 | 8 | CPU/memory balance |
| Vector search candidates | 100 | 1,000 | Query time |

### 11.8 Monitoring & Diagnostics

Add to admin/settings panel:
- Processing queue depth and throughput
- Average extraction time per PDF
- Search query latency (P50, P95)
- Database table sizes
- Index usage statistics

---

## 12. Open Questions

1. **Chunk storage**: Store chunks in DB or derive on-the-fly from stored markdown?
2. **Incremental updates**: How to handle re-scanning changed files?
3. **Search result preview**: Show snippet with highlighted match, or just page number?
4. **Embedding model lock-in**: What if user switches from OpenAI to Ollama embeddings?

---

## Next Steps

1. Review and approve this plan
2. Begin Phase 1 implementation: Manual extraction triggers

# Large Library Support Design

> Strategy for handling 20,000+ PDF libraries efficiently

## 0. Core Design Decisions

### Non-PDF Format Support

**Approach: Extensible format handlers, PDF-first**

| Format | Priority | Library | Notes |
|--------|----------|---------|-------|
| `.pdf` | P0 (now) | PyMuPDF | Primary format |
| `.epub` | P1 | ebooklib | Fiction, supplements |
| `.cbz/.cbr` | P1 | zipfile/rarfile | Comics, zines |
| `.djvu` | P2 | python-djvulibre | Legacy, rare |

```python
class FormatHandler(Protocol):
    extensions: list[str]
    
    def can_handle(self, path: Path) -> bool: ...
    def extract_cover(self, path: Path) -> bytes | None: ...
    def extract_text(self, path: Path) -> str: ...
    def get_page_count(self, path: Path) -> int: ...
    def get_metadata(self, path: Path) -> dict: ...

# Product model addition
file_format: Mapped[str] = mapped_column(String(10), default="pdf")
```

**Settings:**
```
enabled_formats: ["pdf", "epub", "cbz"]  # User configurable
```

### Quarantine Philosophy

**Approach: Track exclusions in DB, never move user files**

Grimoire should be non-destructive. Moving files breaks user organization and creates support headaches.

```python
class ExcludedFile(Base):
    """Track files that matched exclusion rules."""
    __tablename__ = "excluded_files"
    
    id: Mapped[int]
    file_path: Mapped[str]          # Full path
    file_name: Mapped[str]
    file_size: Mapped[int]
    rule_id: Mapped[int]            # FK to exclusion_rules
    rule_description: Mapped[str]   # Denormalized for display
    excluded_at: Mapped[datetime]
    user_override: Mapped[bool]     # True = include despite rule
```

**UI shows:**
- "47 files excluded" with expandable list
- Per-rule breakdown
- "Include anyway" button per file

### Re-scan Behavior

**Approach: Soft state changes, never auto-delete**

| Event | Action |
|-------|--------|
| Rule added | Preview → Confirm → Mark products `is_excluded=True` |
| Rule deleted | Mark previously excluded products for rescan |
| Rule modified | Re-evaluate on next scan |
| File disappears | Mark `is_missing=True`, keep record |
| File reappears | Clear `is_missing`, preserve metadata |

```python
# Product model additions
is_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
excluded_by_rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
exclusion_override: Mapped[bool] = mapped_column(Boolean, default=False)  # User forced include

is_missing: Mapped[bool] = mapped_column(Boolean, default=False)
missing_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

**Why preserve missing files:**
- User may have moved files temporarily
- Metadata, tags, collections are valuable
- Show "missing" indicator, let user resolve
- Auto-cleanup after 30 days (configurable) or manual

---

## 0.1 Exclusion Rules System

### Types of Exclusions

| Rule Type | Example | Use Case |
|-----------|---------|----------|
| **Folder path** | `/library/Archive/*` | Skip archived/backup folders |
| **Folder name** | `__MACOSX`, `.git` | System/hidden folders |
| **Filename pattern** | `*_preview.pdf`, `*.tmp` | Preview files, temp files |
| **File size min** | `< 100KB` | Skip corrupted/stub files |
| **File size max** | `> 500MB` | Skip huge map compilations |
| **Regex pattern** | `.*\(copy\).*` | Custom patterns |

### Data Model

```sql
CREATE TABLE exclusion_rules (
    id INTEGER PRIMARY KEY,
    rule_type TEXT NOT NULL,      -- 'folder_path', 'folder_name', 'filename', 'size_min', 'size_max', 'regex'
    pattern TEXT NOT NULL,        -- The pattern to match
    description TEXT,             -- User-friendly description
    enabled BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 0,   -- Higher = checked first
    created_at DATETIME,
    
    -- Stats
    files_excluded INTEGER DEFAULT 0,
    last_matched_at DATETIME
);
```

### Default Rules (Pre-configured)

```python
DEFAULT_EXCLUSIONS = [
    # System folders
    {"rule_type": "folder_name", "pattern": "__MACOSX", "description": "macOS resource forks"},
    {"rule_type": "folder_name", "pattern": ".git", "description": "Git repositories"},
    {"rule_type": "folder_name", "pattern": ".svn", "description": "SVN repositories"},
    {"rule_type": "folder_name", "pattern": "@eaDir", "description": "Synology thumbnails"},
    {"rule_type": "folder_name", "pattern": ".@__thumb", "description": "QNAP thumbnails"},
    {"rule_type": "folder_name", "pattern": "#recycle", "description": "NAS recycle bins"},
    
    # Common unwanted files
    {"rule_type": "filename", "pattern": "*.tmp", "description": "Temporary files"},
    {"rule_type": "filename", "pattern": "~$*", "description": "Office temp files"},
    {"rule_type": "filename", "pattern": "._*", "description": "macOS metadata"},
    {"rule_type": "filename", "pattern": "*_preview.pdf", "description": "Preview versions"},
    {"rule_type": "filename", "pattern": "*(1).pdf", "description": "Download duplicates"},
    
    # Size limits
    {"rule_type": "size_min", "pattern": "10240", "description": "Files under 10KB (likely corrupt)"},
]
```

### API Endpoints

```
GET    /api/v1/exclusions              # List all rules
POST   /api/v1/exclusions              # Create rule
PUT    /api/v1/exclusions/{id}         # Update rule
DELETE /api/v1/exclusions/{id}         # Delete rule
POST   /api/v1/exclusions/test         # Test pattern against library
GET    /api/v1/exclusions/stats        # Files excluded by each rule
POST   /api/v1/exclusions/preview      # Preview what would be excluded
```

### Scanner Integration

```python
class ExclusionMatcher:
    def __init__(self, rules: list[ExclusionRule]):
        self.rules = sorted(rules, key=lambda r: -r.priority)
        self._compile_patterns()
    
    def should_exclude(self, file_path: Path, file_size: int) -> tuple[bool, str | None]:
        """Check if file should be excluded. Returns (excluded, reason)."""
        for rule in self.rules:
            if not rule.enabled:
                continue
            if self._matches(rule, file_path, file_size):
                return True, rule.description
        return False, None
    
    def _matches(self, rule: ExclusionRule, path: Path, size: int) -> bool:
        match rule.rule_type:
            case "folder_path":
                return fnmatch(str(path.parent), rule.pattern)
            case "folder_name":
                return rule.pattern in path.parts
            case "filename":
                return fnmatch(path.name, rule.pattern)
            case "size_min":
                return size < int(rule.pattern)
            case "size_max":
                return size > int(rule.pattern)
            case "regex":
                return bool(re.match(rule.pattern, str(path)))
        return False
```

### UI Features

```
/settings/exclusions
├── Quick toggles for default rules
├── Add custom rule (wizard)
│   ├── Select type
│   ├── Enter pattern
│   └── Test against library (shows count)
├── Import/export rules
└── "Excluded files" log viewer
```

### Watched Folder Override

Each watched folder can have its own exclusion settings:
- Use global rules (default)
- Disable specific global rules
- Add folder-specific rules

```sql
ALTER TABLE watched_folders ADD COLUMN exclusion_mode TEXT DEFAULT 'global';
-- 'global' = use global rules
-- 'custom' = use folder-specific rules only
-- 'both' = global + folder-specific

CREATE TABLE folder_exclusion_overrides (
    folder_id INTEGER REFERENCES watched_folders(id),
    exclusion_rule_id INTEGER REFERENCES exclusion_rules(id),
    enabled BOOLEAN,  -- Override the global enabled state
    PRIMARY KEY (folder_id, exclusion_rule_id)
);
```

## 1. Duplicate Detection System

### Types of Duplicates

| Type | Detection Method | Example |
|------|------------------|---------|
| **Exact duplicate** | SHA-256 file hash | Same file in two folders |
| **Same content, different file** | Content hash (text) | Re-downloaded PDF |
| **Same product, different version** | Codex ID + page count | v1.0 vs v1.1 of same book |
| **Similar filename** | Fuzzy string matching | "Tomb of Horrors.pdf" vs "TombOfHorrors_v2.pdf" |

### Implementation

```
Product model additions:
- content_hash: str | None      # Hash of extracted text (detect reformatted dupes)
- duplicate_of_id: int | None   # FK to canonical product
- is_duplicate: bool            # Quick filter flag
- duplicate_reason: str | None  # "exact_file", "same_content", "same_product"
```

### Duplicate Resolution Options
1. **Keep newest** - Auto-select most recent file
2. **Keep largest** - Assume more pages = more complete
3. **Keep by path priority** - User defines folder precedence
4. **Manual review** - Flag for user decision
5. **Keep all** - Just mark as duplicates, don't hide

## 2. Batch Processing Architecture

### Scanning Phases

```
Phase 1: Discovery (fast, <1 min for 20K files)
├── Walk directories
├── Collect file paths + sizes
└── Store in scan_queue table

Phase 2: Hashing (medium, ~30 min for 20K files)
├── Process in batches of 100
├── Compute SHA-256
├── Check for duplicates
└── Create Product records (minimal data)

Phase 3: Metadata (slow, background)
├── Extract covers (on-demand or batch)
├── Extract text (on-demand or batch)
├── AI identification (optional, rate-limited)
└── Vector embeddings (optional)
```

### Progress Tracking

```sql
CREATE TABLE scan_jobs (
    id INTEGER PRIMARY KEY,
    started_at DATETIME,
    completed_at DATETIME,
    status TEXT,  -- 'scanning', 'hashing', 'processing', 'complete', 'failed'
    total_files INTEGER,
    processed_files INTEGER,
    duplicates_found INTEGER,
    errors INTEGER,
    current_phase TEXT,
    current_file TEXT
);
```

### API Endpoints

```
POST /api/v1/library/scan          # Start full scan
GET  /api/v1/library/scan/status   # Get progress
POST /api/v1/library/scan/cancel   # Cancel running scan
POST /api/v1/library/scan/resume   # Resume interrupted scan
```

## 3. Database Optimizations

### Additional Indexes

```sql
-- For duplicate detection
CREATE INDEX ix_products_content_hash ON products(content_hash);
CREATE INDEX ix_products_file_size ON products(file_size);
CREATE INDEX ix_products_duplicate_of ON products(duplicate_of_id);

-- For filtering
CREATE INDEX ix_products_publisher ON products(publisher);
CREATE INDEX ix_products_is_duplicate ON products(is_duplicate);

-- Composite for common queries
CREATE INDEX ix_products_system_type ON products(game_system, product_type);
CREATE INDEX ix_products_status ON products(text_extracted, ai_identified);
```

### Query Optimizations

1. **Use COUNT estimates** for large result sets
2. **Cursor-based pagination** instead of OFFSET for deep pages
3. **Materialized stats** - Pre-compute counts, refresh periodically
4. **Partial indexes** - Index only non-duplicate products

### PostgreSQL Migration Path

For >50K products or heavy concurrent use:
- Add `DATABASE_URL` support for PostgreSQL
- Use connection pooling (asyncpg)
- Enable full-text search with pg_trgm

## 4. Lazy/On-Demand Processing

### Processing Tiers

| Tier | Trigger | Data |
|------|---------|------|
| **T0: Minimal** | File discovered | path, name, size, hash |
| **T1: Basic** | Product viewed | cover, page count |
| **T2: Searchable** | User requests | full text extraction |
| **T3: Smart** | User requests | AI identification, embeddings |

### Implementation

```python
class ProcessingTier(Enum):
    MINIMAL = 0    # Just file info
    BASIC = 1      # + cover + page count
    SEARCHABLE = 2 # + full text
    SMART = 3      # + AI + embeddings

@router.post("/{product_id}/process")
async def process_product(
    product_id: int,
    tier: ProcessingTier = ProcessingTier.BASIC
):
    """Process a product to the requested tier."""
```

### Batch Processing Options

```
POST /api/v1/products/batch-process
{
    "filter": {"game_system": "D&D 5e"},
    "tier": "searchable",
    "limit": 100,
    "priority": "low"
}
```

## 5. Memory & Performance

### Streaming File Operations

- Hash files in 64KB chunks (already implemented)
- Extract text page-by-page, not whole PDF
- Generate thumbnails without loading full image

### Caching Strategy

| Data | Cache Location | TTL |
|------|----------------|-----|
| Product list counts | In-memory | 60s |
| Filter options (systems, types) | In-memory | 5 min |
| Cover thumbnails | Disk + CDN headers | 24h |
| Search results | Redis (future) | 5 min |

### Worker Configuration

```yaml
# For large libraries
worker:
  concurrent_tasks: 4        # Parallel processing
  batch_size: 50             # Products per batch
  memory_limit: 512MB        # Per worker
  timeout: 300               # 5 min per task
```

## 6. UI/UX for Large Libraries

### Virtual Scrolling
- Only render visible items
- Load pages as user scrolls
- Show skeleton loaders

### Duplicate Management UI
```
/library/duplicates
├── Group by: exact | content | product
├── Sort by: space wasted | count
├── Actions: keep one | keep all | review
└── Bulk operations
```

### Progress Indicators
- Scan progress bar with ETA
- Background processing status
- "X of Y products indexed"

## 7. Implementation Priority

### Phase 1: Foundation (This Sprint)
- [x] File hash already stored
- [ ] Add duplicate detection on scan
- [ ] Add `is_duplicate`, `duplicate_of_id` columns
- [ ] Duplicate detection API endpoint
- [ ] Scan progress tracking

### Phase 2: Scale (Next Sprint)  
- [ ] Batch processing with chunking
- [ ] Processing tiers (lazy extraction)
- [ ] Additional database indexes
- [ ] Cursor-based pagination

### Phase 3: Polish (Future)
- [ ] Duplicate management UI
- [ ] PostgreSQL support
- [ ] Redis caching
- [ ] Virtual scrolling frontend

## 8. Metrics to Track

```python
@dataclass
class LibraryStats:
    total_products: int
    total_size_bytes: int
    duplicates_count: int
    duplicates_size_bytes: int  # Space that could be saved
    unprocessed_count: int
    processing_queue_size: int
    avg_scan_time_ms: float
    avg_query_time_ms: float
```

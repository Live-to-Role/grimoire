# Grimoire: Project Planning Document

> A self-hosted digital library manager for tabletop RPG content with AI-powered organization, search, and content extraction.

**Repository:** https://github.com/Live-to-Role/grimoire  
**License:** GPL-3.0  
**Maintainer:** Live to Role LLC

---

## Table of Contents

1. [Project Vision](#1-project-vision)
2. [Target Users](#2-target-users)
3. [Technical Architecture](#3-technical-architecture)
4. [Feature Roadmap](#4-feature-roadmap)
5. [Database Schema](#5-database-schema)
6. [API Specification](#6-api-specification)
7. [Frontend Architecture](#7-frontend-architecture)
8. [UI/UX Guidelines](#8-uiux-guidelines)
9. [Security Requirements](#9-security-requirements)
10. [Performance Requirements](#10-performance-requirements)
11. [Accessibility Requirements](#11-accessibility-requirements)
12. [AI Integration](#12-ai-integration)
13. [File Processing Pipeline](#13-file-processing-pipeline)
14. [Project Structure](#14-project-structure)
15. [Development Standards](#15-development-standards)
16. [Testing Strategy](#16-testing-strategy)
17. [Deployment](#17-deployment)
18. [Contributing Guidelines](#18-contributing-guidelines)

---

## 1. Project Vision

### 1.1 Problem Statement

RPG enthusiasts accumulate large digital libraries (often 1,000+ PDFs) from DriveThruRPG, Kickstarter, Bundle of Holding, and other sources. Existing tools fail to help users:

- Find content they already own
- Discover what's useful for their current campaign
- Extract and use content (monsters, tables, maps) from their collection
- Search across their entire library semantically

### 1.2 Solution

Grimoire is a self-hosted application that:

- Scans local PDF folders and builds a searchable catalog
- Extracts covers, metadata, and content using AI assistance
- Enables full-text and semantic search across the entire library
- Extracts structured data (monsters, spells, random tables) for use in play
- Respects user privacy by keeping all files local (no cloud upload)
- Supports BYOK (Bring Your Own Key) for AI features
- Integrates with **Codex** (codex.livetorole.com) for community-curated metadata

### 1.2.1 The Live to Role Ecosystem

```
┌─────────────────────────────────────────────────────────────────┐
│                      LIVE TO ROLE                               │
│                   livetorole.com                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   CODEX                          GRIMOIRE                       │
│   codex.livetorole.com           github.com/Live-to-Role/       │
│                                  grimoire                       │
│   ┌─────────────────────┐       ┌─────────────────────┐        │
│   │ Community-curated   │       │ Self-hosted library │        │
│   │ TTRPG metadata      │◄─────►│ manager             │        │
│   │                     │  API  │                     │        │
│   │ • Product database  │       │ • PDF scanning      │        │
│   │ • Publisher info    │       │ • Cover extraction  │        │
│   │ • File hash lookup  │       │ • AI identification │        │
│   │ • Open editing      │       │ • Semantic search   │        │
│   │ • API access        │       │ • Entity extraction │        │
│   └─────────────────────┘       └─────────────────────┘        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Codex** is the Wikipedia of TTRPG products — an open, community-curated database of every adventure, sourcebook, and supplement ever published.

**Grimoire** uses Codex to instantly identify your PDFs and pulls rich metadata, while contributing new identifications back to benefit the community.

### 1.3 Design Principles

1. **Privacy First:** Files never leave the user's machine
2. **Graceful Degradation:** Fully functional without AI, enhanced with it
3. **Self-Hosted Simplicity:** One Docker command to run
4. **Community Driven:** Easy to contribute schemas, prompts, and metadata
5. **Extensible:** Plugin architecture for custom extractors and integrations

---

## 2. Target Users

### 2.1 Primary Personas

**The Digital Hoarder**
- Owns 500-5,000+ RPG PDFs
- Buys bundles, backs Kickstarters, collects sales
- Knows they own "something about swamps" but can't find it
- Technical enough to run Docker

**The Prep-Focused GM**
- Runs weekly games, needs content fast
- Wants to search "forest encounters for level 3" across all owned content
- Values random tables, monsters, and maps
- Willing to pay for tools that save prep time

**The System Hopper**
- Plays multiple systems (5e, DCC, Shadowdark, PF2e, etc.)
- Wants to convert or adapt content between systems
- Interested in structured extraction for cross-system use

### 2.2 Technical Assumptions

- Users can install Docker and run terminal commands
- Users have local storage for PDFs (not cloud-only)
- Users may or may not have dedicated GPUs
- Users understand API keys and can configure BYOK

---

## 3. Technical Architecture

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (React)                          │
│                     Mobile-First Responsive                      │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ REST API + WebSocket
                                │
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   Routes    │  │  Services   │  │   Background Workers    │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
         │                  │                      │
         │                  │                      │
┌────────┴───────┐  ┌───────┴────────┐  ┌─────────┴──────────────┐
│    SQLite      │  │  File System   │  │    AI Providers        │
│  + sqlite-vec  │  │  (User PDFs)   │  │  (BYOK / Ollama)       │
└────────────────┘  └────────────────┘  └────────────────────────┘
```

### 3.2 Technology Stack

#### Backend
| Component | Technology | Rationale |
|-----------|------------|-----------|
| Language | Python 3.11+ | Best PDF processing ecosystem |
| Framework | FastAPI | Async, fast, auto-docs, type hints |
| Database | SQLite | No server config, easy backup, portable |
| Vector Search | sqlite-vec | Keeps everything in SQLite |
| Task Queue | ARQ (Redis) or Huey (SQLite) | Background processing |
| PDF Processing | markdown-extractor layer | Multi-backend with column fixes |
| ↳ Primary | Marker | ML-based layout detection |
| ↳ Fallback 1 | PyMuPDF (fitz) | Fast block extraction |
| ↳ Fallback 2 | MarkItDown | Microsoft's converter |
| ↳ Fallback 3 | pdfplumber + custom | Column detection algorithm |
| ORM | SQLAlchemy 2.0 | Async support, type hints |
| Migrations | Alembic | Database versioning |

> **Note:** The PDF extraction layer is based on [markdown-extractor](https://github.com/madmichael/markdown-extractor), 
> which provides fixes for multi-column RPG layouts that the base libraries don't handle well.

#### Frontend
| Component | Technology | Rationale |
|-----------|------------|-----------|
| Framework | React 18+ | Your expertise, large ecosystem |
| Build Tool | Vite | Fast dev server, optimized builds |
| Styling | Tailwind CSS | Utility-first, mobile-first |
| State | Zustand or TanStack Query | Lightweight, focused tools |
| Router | React Router v6 | Standard routing |
| PDF Viewer | react-pdf or PDF.js | In-browser viewing |
| Icons | Lucide React | Clean, consistent |
| Forms | React Hook Form + Zod | Validation, type safety |

#### Infrastructure
| Component | Technology | Rationale |
|-----------|------------|-----------|
| Containerization | Docker + Docker Compose | Standard self-hosted deployment |
| Reverse Proxy | Caddy (optional) | Auto HTTPS, simple config |
| Process Manager | Supervisor or Docker health checks | Keep services running |

### 3.3 System Requirements

**Minimum:**
- 2 CPU cores
- 4GB RAM
- 10GB disk (plus PDF storage)
- Docker 20.10+

**Recommended:**
- 4+ CPU cores
- 8GB+ RAM
- SSD storage
- NVIDIA GPU with 4GB+ VRAM (for Marker acceleration)

**Optional:**
- GPU passthrough for Docker (NVIDIA Container Toolkit)
- Apple Silicon (MPS) support for macOS

---

## 4. Feature Roadmap

### 4.1 Version 0.1 - "It Works" (MVP)

**Goal:** Usable library manager without AI features

#### Core Features
- [x] Docker one-liner installation
- [x] Folder scanning with file watching
- [x] Cover image extraction (first page render)
- [x] Basic metadata extraction (page count, file size, embedded metadata)
- [x] Manual tagging system (game system, product type, level range)
- [x] Search by title, tags, and metadata
- [x] Filter by game system, product type, tags
- [x] Grid and list view for library
- [x] In-browser PDF viewer
- [x] Collections (user-created groupings)
- [x] Basic settings UI (folder paths, appearance)

#### Technical Requirements
- [x] SQLite database with migrations
- [x] FastAPI backend with OpenAPI documentation
- [x] React frontend with responsive design
- [x] Docker Compose configuration
- [x] Health check endpoints
- [x] Basic error handling and logging

### 4.2 Version 0.2 - "It's Smart"

**Goal:** AI-assisted organization and full-text search

#### Features
- [x] BYOK configuration UI (OpenAI, Anthropic, Google, Ollama)
- [x] AI product identification ("This PDF is Tomb of the Serpent Kings")
- [x] AI game system detection
- [x] AI-suggested tags (themes, content type)
- [x] Full-text extraction using PyMuPDF/pdfplumber
- [x] Full-text search across all content
- [x] Processing queue with progress indicators
- [x] Cost estimation before AI processing
- [x] Batch processing mode

### 4.3 Version 0.3 - "It's Powerful"

**Goal:** Deep content extraction and semantic search

#### Features
- [x] Marker integration for layout-aware extraction
- [x] Table of contents parsing
- [x] Random table detection and extraction
- [x] Stat block detection (system-aware)
- [x] Map/image extraction
- [x] Vector embeddings for semantic search
- [x] Natural language queries ("Find swamp adventures for level 3")
- [x] Similar content recommendations
- [x] GPU acceleration support

### 4.4 Version 0.4 - "It's Connected"

**Goal:** Structured data and integrations

#### Features
- [x] Structured extraction with JSON schemas
- [x] Monster/NPC extraction to structured format
- [x] Random table extraction to rollable format
- [x] Spell extraction
- [x] Export to Foundry VTT format
- [x] Export to Obsidian markdown
- [x] Campaign management (link products to campaigns)
- [x] Session prep assistant
- [x] Community metadata sync (opt-in)

### 4.5 Version 0.5 - "It's Connected to Codex"

**Goal:** Integration with the community metadata database

#### Features
- [x] Codex API integration for product identification (mock mode until Codex is live)
- [x] File hash lookup (instant identification for known products)
- [x] Fallback chain: Codex → AI → Manual
- [x] Opt-in contribution of new identifications back to Codex
- [x] Offline mode with graceful degradation (contribution queue)
- [x] Sync local edits when reconnected

### 4.6 Future Considerations

- Browser extension for DriveThruRPG integration
- Mobile companion app
- Multi-user support with permissions
- Plugin system for custom extractors
- Integration with VTTs (Foundry, Roll20)
- Integration with note-taking (Obsidian, Notion)

---

## 4A. Codex: Community TTRPG Metadata Database

> The community-curated database of tabletop RPG products — every adventure, sourcebook, and zine, cataloged and searchable.

**URLs:**
- `codex.livetorole.com` → Web app (browse, edit, contribute)
- `api.codex.livetorole.com` → API endpoints

### 4A.1 What Is Codex?

Codex is a Wikipedia-style open database of TTRPG product metadata. It serves as:

1. **For Grimoire users:** Automatic identification of PDFs by file hash or title
2. **For the community:** Browsable catalog of all TTRPG products
3. **For developers:** Free API for TTRPG product data
4. **For publishers:** Verified listings and discoverability

### 4A.2 Core Data Model

```
Publisher
├── id (UUID)
├── name
├── slug
├── website
├── description
├── founded_year
├── logo_url
└── products[] → Product

Author
├── id (UUID)
├── name
├── slug
├── bio
├── website
└── credits[] → ProductCredit

GameSystem
├── id (UUID)
├── name (e.g., "Dungeon Crawl Classics")
├── slug (e.g., "dcc")
├── publisher_id → Publisher
├── edition
├── parent_system_id → GameSystem (for variants/hacks)
├── year_released
└── products[] → Product

Product
├── id (UUID)
├── title
├── slug
├── publisher_id → Publisher
├── credits[] → ProductCredit (author, artist, editor, etc.)
├── game_system_id → GameSystem
├── product_type (adventure, sourcebook, supplement, bestiary, tools, magazine, core_rules)
├── 
├── Publication Info:
│   ├── publication_date
│   ├── page_count
│   ├── format (pdf, print, both)
│   ├── isbn
│   └── msrp
│
├── External IDs:
│   ├── dtrpg_id (DriveThruRPG product ID)
│   ├── dtrpg_url
│   ├── itch_id
│   └── other_urls[]
│
├── File Identification:
│   └── file_hashes[] → FileHash
│
├── Adventure-Specific (nullable):
│   ├── level_range_min
│   ├── level_range_max
│   ├── party_size_min
│   ├── party_size_max
│   ├── estimated_runtime (one-shot, 2-3 sessions, campaign)
│   └── setting
│
├── Community Data:
│   ├── tags[]
│   ├── themes[]
│   ├── content_warnings[]
│   ├── related_products[] (sequels, conversions, compilations)
│   └── average_rating
│
├── Cover Image:
│   ├── cover_url
│   └── thumbnail_url
│
└── Meta:
    ├── status (draft, published, verified)
    ├── created_by → User
    ├── created_at
    ├── updated_at
    └── revision_history[] → Revision

FileHash
├── id (UUID)
├── product_id → Product
├── hash_sha256
├── hash_md5 (for legacy matching)
├── file_size_bytes
├── source (user_contributed, publisher_verified)
├── contributed_by → User
└── created_at

ProductCredit
├── product_id → Product
├── author_id → Author
├── role (author, co-author, artist, cartographer, editor, layout)
└── notes

Revision
├── id (UUID)
├── product_id → Product
├── user_id → User
├── timestamp
├── changes (JSON diff)
└── comment
```

### 4A.3 API Endpoints

```yaml
# Base URL: api.codex.livetorole.com/v1

# Product Lookup (used by Grimoire)
GET /identify
  Query Parameters:
    - hash: string (SHA-256 file hash)
    - title: string (fuzzy match)
    - filename: string
  Response: 200 OK
    {
      "match": "exact" | "fuzzy" | "none",
      "confidence": float,
      "product": Product | null,
      "suggestions": [Product]  # If fuzzy/none
    }

# Product CRUD
GET /products
GET /products/{id}
GET /products/by-slug/{slug}
POST /products (authenticated)
PATCH /products/{id} (authenticated)

# Search
GET /search
  Query Parameters:
    - q: string
    - system: string
    - publisher: string
    - type: string
    - year_min: integer
    - year_max: integer
    - level_min: integer
    - level_max: integer

# Publishers
GET /publishers
GET /publishers/{id}
GET /publishers/{id}/products

# Game Systems
GET /systems
GET /systems/{id}
GET /systems/{id}/products

# Authors
GET /authors
GET /authors/{id}
GET /authors/{id}/credits

# Contributions (authenticated)
POST /contributions
  Request Body:
    {
      # Preferred format (explicit)
      "contribution_type": "new_product" | "edit_product",
      "product": UUID | null,  # Required for edit_product
      
      # Legacy format (still supported for backward compatibility)
      # "product_id": UUID | null,  # Auto-infers contribution_type
      
      "data": {...},
      "source": "grimoire" | "web" | "api",
      "file_hash": string | null
    }
  Response: 201 Created
    {
      "status": "applied" | "pending",
      "message": string,
      "product_id": UUID,      # If status=applied
      "product_slug": string,  # If status=applied  
      "contribution_id": UUID  # If status=pending
    }
  Authentication: Token {api_key}  # DRF Token auth, not Bearer

# User
GET /users/me
GET /users/{id}/contributions
```

### 4A.4 Grimoire ↔ Codex Integration

```python
# grimoire/services/codex.py

class CodexClient:
    """Client for the Codex TTRPG metadata API."""
    
    def __init__(self, base_url: str = "https://api.codex.livetorole.com/v1"):
        self.base_url = base_url
        self.timeout = 10
    
    async def identify_by_hash(self, file_hash: str) -> CodexMatch | None:
        """Look up a product by file hash. Fastest identification method."""
        response = await self.get("/identify", params={"hash": file_hash})
        if response["match"] == "exact":
            return CodexMatch(
                product=response["product"],
                confidence=1.0,
                source="codex_hash"
            )
        return None
    
    async def identify_by_title(self, title: str, filename: str = None) -> CodexMatch | None:
        """Fuzzy match by title/filename. Fallback when hash unknown."""
        params = {"title": title}
        if filename:
            params["filename"] = filename
        
        response = await self.get("/identify", params=params)
        if response["match"] in ("exact", "fuzzy") and response["confidence"] > 0.8:
            return CodexMatch(
                product=response["product"],
                confidence=response["confidence"],
                source="codex_title"
            )
        return None
    
    async def contribute(
        self,
        product_data: dict,
        file_hash: str = None,
        existing_product_id: str = None,  # Codex product UUID if editing
    ) -> ContributionResult:
        """Contribute new or corrected product data back to Codex."""
        if not self.api_key:
            return ContributionResult.failure("no_api_key")
        
        payload = {
            "data": product_data,
            "file_hash": file_hash,
            "source": "grimoire"
        }
        
        # Use explicit contribution_type for clarity
        if existing_product_id:
            payload["contribution_type"] = "edit_product"
            payload["product"] = existing_product_id
        else:
            payload["contribution_type"] = "new_product"
        
        response = await self.post(
            "/contributions",
            json=payload,
            headers={"Authorization": f"Token {self.api_key}"}  # DRF Token auth
        )
        
        return ContributionResult.from_response(response)


# Identification chain in Grimoire
async def identify_product(product: Product) -> Identification:
    """
    Identification priority:
    1. Codex by file hash (instant, exact)
    2. Codex by title (fast, fuzzy)
    3. AI identification (slow, costs money)
    4. Manual (user input)
    """
    codex = CodexClient()
    
    # 1. Try hash lookup first
    if product.file_hash:
        match = await codex.identify_by_hash(product.file_hash)
        if match:
            return Identification(source="codex", data=match.product, confidence=1.0)
    
    # 2. Try title/filename fuzzy match
    match = await codex.identify_by_title(
        title=product.embedded_title or product.file_name,
        filename=product.file_name
    )
    if match and match.confidence > 0.8:
        return Identification(source="codex", data=match.product, confidence=match.confidence)
    
    # 3. Fall back to AI (if configured)
    if await ai_enabled():
        quick_text = await extract_quick_text(product.file_path, max_pages=10)
        ai_result = await ai_identify_product(quick_text)
        
        # Optionally contribute back to Codex
        if settings.codex_contribute_enabled:
            await codex.contribute(ai_result.to_dict(), product.file_hash)
        
        return Identification(source="ai", data=ai_result, confidence=ai_result.confidence)
    
    # 4. Manual identification required
    return Identification(source="manual", data=None, confidence=0)
```

### 4A.5 Codex Feature Roadmap

**Phase 1: Foundation**
- [ ] Basic product database schema
- [ ] Web UI for browsing/searching
- [ ] User accounts and edit history
- [ ] API for Grimoire integration
- [ ] File hash registration

**Phase 2: Community**
- [ ] Wikipedia-style editing workflow
- [ ] Moderation tools
- [ ] Publisher verification badges
- [ ] Contribution leaderboards
- [ ] Discussion/comments on products

**Phase 3: Enrichment**
- [ ] Cover image hosting
- [ ] Series/product line tracking
- [ ] Cross-system product relationships
- [ ] Integration with DriveThruRPG affiliate links
- [ ] Publisher dashboards

### 4A.6 Tech Stack (Codex)

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Backend | FastAPI or Django | Django has better admin/auth built-in |
| Database | PostgreSQL | Full-text search, JSONB, production-ready |
| Cache | Redis | Session storage, rate limiting |
| Search | PostgreSQL FTS or Meilisearch | Fast product search |
| Hosting | Railway, Render, or VPS | Affordable for starting out |
| CDN | Cloudflare | Cover images, API caching |
| Auth | OAuth (Google, Discord, GitHub) | Easy onboarding |

---

## 5. Database Schema

### 5.1 Core Tables

```sql
-- Database version tracking
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Watched folders
CREATE TABLE watched_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    label TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    last_scanned_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Main product catalog
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- File information
    file_path TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    file_hash TEXT NOT NULL,  -- SHA-256 for change detection
    watched_folder_id INTEGER REFERENCES watched_folders(id),
    
    -- Basic metadata
    title TEXT,
    publisher TEXT,
    publication_year INTEGER,
    page_count INTEGER,
    
    -- Classification
    game_system TEXT,
    product_type TEXT,  -- adventure, sourcebook, supplement, tools, magazine
    
    -- Adventure-specific (nullable)
    level_range_min INTEGER,
    level_range_max INTEGER,
    party_size_min INTEGER,
    party_size_max INTEGER,
    estimated_runtime TEXT,  -- "one-shot", "2-3 sessions", "campaign"
    
    -- Processing status
    cover_extracted BOOLEAN DEFAULT FALSE,
    text_extracted BOOLEAN DEFAULT FALSE,
    deep_indexed BOOLEAN DEFAULT FALSE,
    ai_identified BOOLEAN DEFAULT FALSE,
    
    -- AI confidence scores
    identification_confidence REAL,
    system_detection_confidence REAL,
    
    -- Paths to extracted content
    cover_image_path TEXT,
    extracted_text_path TEXT,
    
    -- Timestamps
    file_modified_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_opened_at TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX idx_products_game_system ON products(game_system);
CREATE INDEX idx_products_product_type ON products(product_type);
CREATE INDEX idx_products_file_hash ON products(file_hash);
CREATE INDEX idx_products_title ON products(title);

-- Full-text search
CREATE VIRTUAL TABLE products_fts USING fts5(
    title,
    publisher,
    content='products',
    content_rowid='id'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER products_ai AFTER INSERT ON products BEGIN
    INSERT INTO products_fts(rowid, title, publisher)
    VALUES (new.id, new.title, new.publisher);
END;

CREATE TRIGGER products_ad AFTER DELETE ON products BEGIN
    INSERT INTO products_fts(products_fts, rowid, title, publisher)
    VALUES ('delete', old.id, old.title, old.publisher);
END;

CREATE TRIGGER products_au AFTER UPDATE ON products BEGIN
    INSERT INTO products_fts(products_fts, rowid, title, publisher)
    VALUES ('delete', old.id, old.title, old.publisher);
    INSERT INTO products_fts(rowid, title, publisher)
    VALUES (new.id, new.title, new.publisher);
END;

-- Tags (flexible metadata)
CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT,  -- 'theme', 'setting', 'content', 'custom'
    color TEXT,  -- Hex color for UI
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE product_tags (
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    source TEXT DEFAULT 'user',  -- 'user', 'ai', 'community'
    confidence REAL,  -- For AI-assigned tags
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (product_id, tag_id)
);

CREATE INDEX idx_product_tags_product ON product_tags(product_id);
CREATE INDEX idx_product_tags_tag ON product_tags(tag_id);

-- Collections (user groupings)
CREATE TABLE collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    color TEXT,
    icon TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE collection_products (
    collection_id INTEGER REFERENCES collections(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    sort_order INTEGER DEFAULT 0,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (collection_id, product_id)
);

-- Extracted content chunks (for semantic search)
CREATE TABLE content_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    
    chunk_type TEXT NOT NULL,  -- 'text', 'table', 'stat_block', 'header'
    content TEXT NOT NULL,
    content_markdown TEXT,
    
    -- Location in source
    page_number INTEGER,
    position_index INTEGER,  -- Order within page
    
    -- Metadata
    metadata JSON,
    
    -- Vector embedding (sqlite-vec)
    embedding BLOB,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_chunks_product ON content_chunks(product_id);
CREATE INDEX idx_chunks_type ON content_chunks(chunk_type);

-- Extracted entities (structured data)
CREATE TABLE extracted_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    
    entity_type TEXT NOT NULL,  -- 'monster', 'spell', 'npc', 'item', 'table'
    entity_name TEXT,
    entity_data JSON NOT NULL,  -- Structured data per schema
    
    -- Source location
    page_number INTEGER,
    source_text TEXT,
    
    -- Quality indicators
    extraction_method TEXT,  -- 'regex', 'ai', 'manual'
    confidence REAL,
    verified BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_entities_product ON extracted_entities(product_id);
CREATE INDEX idx_entities_type ON extracted_entities(entity_type);
CREATE INDEX idx_entities_name ON extracted_entities(entity_name);

-- Campaigns
CREATE TABLE campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    game_system TEXT,
    status TEXT DEFAULT 'planning',  -- 'planning', 'active', 'paused', 'completed'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE campaign_products (
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    status TEXT,  -- 'reference', 'planning', 'running', 'completed'
    notes TEXT,
    sort_order INTEGER DEFAULT 0,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (campaign_id, product_id)
);

-- Processing queue
CREATE TABLE processing_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL,  -- 'cover', 'text', 'deep_index', 'identify', 'extract'
    priority INTEGER DEFAULT 5,  -- 1=highest, 10=lowest
    status TEXT DEFAULT 'pending',  -- 'pending', 'processing', 'completed', 'failed'
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    error_message TEXT,
    estimated_cost REAL,  -- For AI tasks
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_queue_status ON processing_queue(status, priority);

-- User settings
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value JSON NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- AI provider configuration (encrypted values stored separately)
CREATE TABLE ai_providers (
    id TEXT PRIMARY KEY,  -- 'openai', 'anthropic', 'google', 'ollama'
    display_name TEXT NOT NULL,
    enabled BOOLEAN DEFAULT FALSE,
    config JSON,  -- Non-sensitive config
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5.2 Vector Search Setup

```sql
-- Using sqlite-vec extension
-- Load extension: SELECT load_extension('vec0');

-- Vector index for semantic search
CREATE VIRTUAL TABLE content_embeddings USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding FLOAT[1536]  -- OpenAI ada-002 dimensions, adjust for other models
);
```

---

## 6. API Specification

### 6.1 API Design Principles

1. **RESTful:** Standard HTTP methods and status codes
2. **JSON:** All request/response bodies in JSON
3. **Versioned:** API version in URL path (`/api/v1/`)
4. **Paginated:** List endpoints support pagination
5. **Filterable:** Query parameters for filtering
6. **Documented:** OpenAPI/Swagger auto-generated docs

### 6.2 Authentication

For v0.1 (single-user), no authentication required. Future versions will support:
- API key authentication for external integrations
- Session-based auth for multi-user

### 6.3 Core Endpoints

#### Products

```yaml
# List products with filtering and pagination
GET /api/v1/products
  Query Parameters:
    - page: integer (default: 1)
    - per_page: integer (default: 50, max: 100)
    - sort: string (title, created_at, updated_at, last_opened_at)
    - order: string (asc, desc)
    - search: string (full-text search)
    - game_system: string
    - product_type: string
    - tags: string (comma-separated tag IDs)
    - collection: integer (collection ID)
    - has_cover: boolean
    - is_indexed: boolean
  Response: 200 OK
    {
      "items": [Product],
      "total": integer,
      "page": integer,
      "per_page": integer,
      "pages": integer
    }

# Get single product
GET /api/v1/products/{id}
  Response: 200 OK
    {
      "id": integer,
      "file_path": string,
      "file_name": string,
      "title": string,
      "publisher": string,
      "game_system": string,
      "product_type": string,
      "page_count": integer,
      "cover_url": string | null,
      "tags": [Tag],
      "collections": [Collection],
      "processing_status": {
        "cover_extracted": boolean,
        "text_extracted": boolean,
        "deep_indexed": boolean,
        "ai_identified": boolean
      },
      "created_at": datetime,
      "updated_at": datetime
    }

# Update product metadata
PATCH /api/v1/products/{id}
  Request Body:
    {
      "title": string?,
      "publisher": string?,
      "game_system": string?,
      "product_type": string?,
      "level_range_min": integer?,
      "level_range_max": integer?
    }
  Response: 200 OK

# Delete product from library (does not delete file)
DELETE /api/v1/products/{id}
  Response: 204 No Content

# Get product cover image
GET /api/v1/products/{id}/cover
  Response: 200 OK (image/jpeg or image/png)

# Get product PDF for viewing
GET /api/v1/products/{id}/pdf
  Response: 200 OK (application/pdf)
  Headers:
    - Content-Disposition: inline
    - Accept-Ranges: bytes (for range requests)

# Trigger processing for a product
POST /api/v1/products/{id}/process
  Request Body:
    {
      "tasks": ["cover", "text", "deep_index", "identify", "extract"]
    }
  Response: 202 Accepted
    {
      "queue_ids": [integer]
    }
```

#### Tags

```yaml
# List all tags
GET /api/v1/tags
  Query Parameters:
    - category: string
  Response: 200 OK
    {
      "items": [Tag]
    }

# Create tag
POST /api/v1/tags
  Request Body:
    {
      "name": string,
      "category": string?,
      "color": string?
    }
  Response: 201 Created

# Update tag
PATCH /api/v1/tags/{id}
  Response: 200 OK

# Delete tag
DELETE /api/v1/tags/{id}
  Response: 204 No Content

# Add tag to product
POST /api/v1/products/{id}/tags
  Request Body:
    {
      "tag_id": integer
    }
  Response: 201 Created

# Remove tag from product
DELETE /api/v1/products/{id}/tags/{tag_id}
  Response: 204 No Content
```

#### Collections

```yaml
# List collections
GET /api/v1/collections
  Response: 200 OK

# Create collection
POST /api/v1/collections
  Request Body:
    {
      "name": string,
      "description": string?,
      "color": string?
    }
  Response: 201 Created

# Get collection with products
GET /api/v1/collections/{id}
  Response: 200 OK

# Update collection
PATCH /api/v1/collections/{id}
  Response: 200 OK

# Delete collection
DELETE /api/v1/collections/{id}
  Response: 204 No Content

# Add product to collection
POST /api/v1/collections/{id}/products
  Request Body:
    {
      "product_id": integer
    }
  Response: 201 Created

# Remove product from collection
DELETE /api/v1/collections/{id}/products/{product_id}
  Response: 204 No Content
```

#### Search

```yaml
# Full-text search
GET /api/v1/search
  Query Parameters:
    - q: string (required)
    - type: string (products, content, entities)
    - game_system: string
    - limit: integer (default: 20)
  Response: 200 OK
    {
      "results": [SearchResult],
      "total": integer,
      "query_time_ms": integer
    }

# Semantic search (requires AI)
POST /api/v1/search/semantic
  Request Body:
    {
      "query": string,
      "filters": {
        "game_system": string?,
        "product_type": string?,
        "entity_type": string?
      },
      "limit": integer
    }
  Response: 200 OK
    {
      "results": [SemanticSearchResult],
      "query_time_ms": integer
    }
```

#### Library Management

```yaml
# List watched folders
GET /api/v1/folders
  Response: 200 OK

# Add watched folder
POST /api/v1/folders
  Request Body:
    {
      "path": string,
      "label": string?
    }
  Response: 201 Created

# Remove watched folder
DELETE /api/v1/folders/{id}
  Query Parameters:
    - remove_products: boolean (default: false)
  Response: 204 No Content

# Trigger library scan
POST /api/v1/library/scan
  Request Body:
    {
      "folder_id": integer?,  # null = all folders
      "force": boolean  # Re-scan unchanged files
    }
  Response: 202 Accepted

# Get library statistics
GET /api/v1/library/stats
  Response: 200 OK
    {
      "total_products": integer,
      "total_pages": integer,
      "total_size_bytes": integer,
      "by_system": {string: integer},
      "by_type": {string: integer},
      "processing_status": {
        "pending": integer,
        "completed": integer,
        "failed": integer
      }
    }
```

#### Processing Queue

```yaml
# Get queue status
GET /api/v1/queue
  Query Parameters:
    - status: string (pending, processing, completed, failed)
  Response: 200 OK
    {
      "items": [QueueItem],
      "counts": {
        "pending": integer,
        "processing": integer,
        "completed": integer,
        "failed": integer
      }
    }

# Cancel queue item
DELETE /api/v1/queue/{id}
  Response: 204 No Content

# Retry failed item
POST /api/v1/queue/{id}/retry
  Response: 202 Accepted

# Clear completed/failed items
DELETE /api/v1/queue
  Query Parameters:
    - status: string (completed, failed)
  Response: 204 No Content
```

#### Settings

```yaml
# Get all settings
GET /api/v1/settings
  Response: 200 OK

# Update settings
PATCH /api/v1/settings
  Request Body:
    {
      "key": "value"
    }
  Response: 200 OK

# Get AI providers
GET /api/v1/settings/ai-providers
  Response: 200 OK

# Configure AI provider
PUT /api/v1/settings/ai-providers/{id}
  Request Body:
    {
      "enabled": boolean,
      "api_key": string?,  # Stored encrypted
      "model": string?,
      "base_url": string?  # For Ollama/custom
    }
  Response: 200 OK

# Test AI provider connection
POST /api/v1/settings/ai-providers/{id}/test
  Response: 200 OK
    {
      "success": boolean,
      "message": string,
      "model_info": object?
    }
```

#### Extracted Entities

```yaml
# List entities
GET /api/v1/entities
  Query Parameters:
    - type: string (monster, spell, item, table)
    - product_id: integer
    - search: string
  Response: 200 OK

# Get entity
GET /api/v1/entities/{id}
  Response: 200 OK

# Update entity (manual corrections)
PATCH /api/v1/entities/{id}
  Response: 200 OK

# Export entities
GET /api/v1/entities/export
  Query Parameters:
    - type: string
    - format: string (json, foundry, obsidian)
    - product_id: integer?
  Response: 200 OK
```

### 6.4 WebSocket Events

For real-time updates during processing:

```yaml
# Connection
WS /api/v1/ws

# Events (server -> client)
{
  "event": "scan_progress",
  "data": {
    "folder_id": integer,
    "scanned": integer,
    "total": integer,
    "current_file": string
  }
}

{
  "event": "processing_update",
  "data": {
    "queue_id": integer,
    "product_id": integer,
    "task_type": string,
    "status": string,
    "progress": float?
  }
}

{
  "event": "product_updated",
  "data": {
    "product_id": integer,
    "changes": [string]
  }
}
```

---

## 7. Frontend Architecture

### 7.1 Application Structure

```
frontend/
├── public/
│   ├── favicon.ico
│   └── manifest.json
├── src/
│   ├── main.tsx                 # Entry point
│   ├── App.tsx                  # Root component
│   ├── api/                     # API client
│   │   ├── client.ts            # Axios/fetch wrapper
│   │   ├── products.ts          # Product endpoints
│   │   ├── collections.ts
│   │   ├── search.ts
│   │   └── types.ts             # API response types
│   ├── components/
│   │   ├── ui/                  # Base UI components
│   │   │   ├── Button.tsx
│   │   │   ├── Input.tsx
│   │   │   ├── Modal.tsx
│   │   │   ├── Dropdown.tsx
│   │   │   ├── Toast.tsx
│   │   │   ├── Skeleton.tsx
│   │   │   └── index.ts
│   │   ├── layout/              # Layout components
│   │   │   ├── Header.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   ├── MobileNav.tsx
│   │   │   └── PageContainer.tsx
│   │   ├── library/             # Library-specific
│   │   │   ├── ProductCard.tsx
│   │   │   ├── ProductGrid.tsx
│   │   │   ├── ProductList.tsx
│   │   │   ├── ProductDetail.tsx
│   │   │   ├── CoverImage.tsx
│   │   │   ├── TagBadge.tsx
│   │   │   └── FilterPanel.tsx
│   │   ├── search/
│   │   │   ├── SearchBar.tsx
│   │   │   ├── SearchResults.tsx
│   │   │   └── SemanticSearch.tsx
│   │   ├── collections/
│   │   │   ├── CollectionCard.tsx
│   │   │   └── CollectionManager.tsx
│   │   ├── processing/
│   │   │   ├── QueueStatus.tsx
│   │   │   └── ProcessingProgress.tsx
│   │   └── settings/
│   │       ├── FolderManager.tsx
│   │       ├── AIProviderConfig.tsx
│   │       └── AppearanceSettings.tsx
│   ├── hooks/                   # Custom hooks
│   │   ├── useProducts.ts
│   │   ├── useSearch.ts
│   │   ├── useWebSocket.ts
│   │   ├── useLocalStorage.ts
│   │   └── useMediaQuery.ts
│   ├── pages/                   # Route pages
│   │   ├── Library.tsx
│   │   ├── Product.tsx
│   │   ├── Search.tsx
│   │   ├── Collections.tsx
│   │   ├── Collection.tsx
│   │   ├── Entities.tsx
│   │   ├── Queue.tsx
│   │   └── Settings.tsx
│   ├── store/                   # State management
│   │   ├── index.ts
│   │   ├── libraryStore.ts
│   │   └── settingsStore.ts
│   ├── styles/
│   │   └── globals.css          # Tailwind imports + custom
│   ├── utils/
│   │   ├── format.ts            # Formatters
│   │   ├── validation.ts
│   │   └── constants.ts
│   └── types/                   # TypeScript types
│       ├── product.ts
│       ├── collection.ts
│       └── index.ts
├── index.html
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
└── package.json
```

### 7.2 Key Components

#### ProductCard

```tsx
interface ProductCardProps {
  product: Product;
  view: 'grid' | 'list';
  selected?: boolean;
  onSelect?: (id: number) => void;
  onOpen?: (id: number) => void;
}
```

Features:
- Cover image with lazy loading and fallback
- Title, system badge, tag pills
- Context menu (right-click/long-press)
- Selection state for bulk actions
- Keyboard navigation support

#### SearchBar

```tsx
interface SearchBarProps {
  onSearch: (query: string) => void;
  suggestions?: string[];
  recentSearches?: string[];
  placeholder?: string;
}
```

Features:
- Debounced input
- Search suggestions dropdown
- Recent searches
- Clear button
- Keyboard shortcuts (Cmd/Ctrl+K to focus)

#### FilterPanel

```tsx
interface FilterPanelProps {
  filters: FilterState;
  onChange: (filters: FilterState) => void;
  gameSystems: string[];
  productTypes: string[];
  tags: Tag[];
}
```

Features:
- Collapsible sections
- Multi-select for tags
- Range inputs for level
- Active filter pills with remove
- Save filter presets

### 7.3 State Management

Using Zustand for global state:

```typescript
// libraryStore.ts
interface LibraryState {
  // View state
  viewMode: 'grid' | 'list';
  sortBy: 'title' | 'created_at' | 'updated_at';
  sortOrder: 'asc' | 'desc';
  
  // Filters
  filters: {
    search: string;
    gameSystem: string | null;
    productType: string | null;
    tags: number[];
    collection: number | null;
  };
  
  // Selection
  selectedIds: Set<number>;
  
  // Actions
  setViewMode: (mode: 'grid' | 'list') => void;
  setSort: (by: string, order: string) => void;
  setFilter: (key: string, value: any) => void;
  clearFilters: () => void;
  selectProduct: (id: number) => void;
  deselectProduct: (id: number) => void;
  clearSelection: () => void;
}
```

Using TanStack Query for server state:

```typescript
// useProducts.ts
export function useProducts(filters: FilterState) {
  return useQuery({
    queryKey: ['products', filters],
    queryFn: () => api.products.list(filters),
    staleTime: 30000,
  });
}

export function useProduct(id: number) {
  return useQuery({
    queryKey: ['product', id],
    queryFn: () => api.products.get(id),
  });
}

export function useUpdateProduct() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ id, data }) => api.products.update(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries(['product', id]);
      queryClient.invalidateQueries(['products']);
    },
  });
}
```

---

## 8. UI/UX Guidelines

### 8.1 Design System

#### Color Palette

```css
:root {
  /* Primary - Arcane Purple */
  --primary-50: #f5f3ff;
  --primary-100: #ede9fe;
  --primary-500: #8b5cf6;
  --primary-600: #7c3aed;
  --primary-700: #6d28d9;
  
  /* Neutral - Parchment tones */
  --neutral-50: #fafaf9;
  --neutral-100: #f5f5f4;
  --neutral-200: #e7e5e4;
  --neutral-800: #292524;
  --neutral-900: #1c1917;
  
  /* Accent - Gold for highlights */
  --accent-400: #fbbf24;
  --accent-500: #f59e0b;
  
  /* Semantic */
  --success: #22c55e;
  --warning: #f59e0b;
  --error: #ef4444;
  --info: #3b82f6;
  
  /* Dark mode overrides */
  .dark {
    --bg-primary: var(--neutral-900);
    --bg-secondary: var(--neutral-800);
    --text-primary: var(--neutral-100);
  }
}
```

#### Typography

```css
/* Font stack - system fonts for performance */
--font-sans: ui-sans-serif, system-ui, -apple-system, sans-serif;
--font-serif: ui-serif, Georgia, serif;  /* For flavor text */
--font-mono: ui-monospace, monospace;

/* Scale */
--text-xs: 0.75rem;
--text-sm: 0.875rem;
--text-base: 1rem;
--text-lg: 1.125rem;
--text-xl: 1.25rem;
--text-2xl: 1.5rem;
--text-3xl: 1.875rem;
```

#### Spacing

Use Tailwind's default spacing scale (4px base):
- `space-1`: 4px
- `space-2`: 8px
- `space-4`: 16px
- `space-6`: 24px
- `space-8`: 32px

#### Border Radius

```css
--radius-sm: 0.25rem;
--radius-md: 0.375rem;
--radius-lg: 0.5rem;
--radius-xl: 0.75rem;
```

### 8.2 Component Patterns

#### Cards

```
┌────────────────────────┐
│  ┌──────────────────┐  │
│  │                  │  │  Cover image (aspect-ratio: 3/4)
│  │      Cover       │  │
│  │                  │  │
│  └──────────────────┘  │
│  Title               │  │  Truncate with ellipsis
│  ┌────┐ ┌────┐       │  │  System badge + type badge
│  │ DCC│ │Adv │       │  │
│  └────┘ └────┘       │  │
│  ┌───┐┌───┐┌───┐     │  │  Tag pills (max 3, +N more)
│  │tag││tag││+2 │     │  │
│  └───┘└───┘└───┘     │  │
└────────────────────────┘
```

#### List Items

```
┌─────────────────────────────────────────────────────────────┐
│ ┌────┐                                                      │
│ │    │  Title of the Product                    ┌────┐     │
│ │    │  Publisher · 2023 · 48 pages            │ DCC │     │
│ └────┘  ┌───┐┌───┐┌───┐                        └────┘     │
│         │tag││tag││tag│                           ⋮       │
│         └───┘└───┘└───┘                                    │
└─────────────────────────────────────────────────────────────┘
```

#### Empty States

Always provide:
1. Illustration or icon
2. Explanatory text
3. Call to action

```
┌─────────────────────────────────────┐
│                                     │
│           📚 (icon)                │
│                                     │
│     No products found              │
│                                     │
│   Try adjusting your filters or    │
│   add a folder to watch.           │
│                                     │
│     [Add Folder] [Clear Filters]   │
│                                     │
└─────────────────────────────────────┘
```

### 8.3 Mobile-First Responsive Design

#### Breakpoints

```css
/* Mobile first - base styles are mobile */
/* sm: 640px - Large phones */
/* md: 768px - Tablets */
/* lg: 1024px - Laptops */
/* xl: 1280px - Desktops */
/* 2xl: 1536px - Large screens */
```

#### Layout Adaptations

**Library Grid:**
- Mobile: 2 columns
- sm: 3 columns
- md: 4 columns
- lg: 5 columns
- xl: 6 columns

**Navigation:**
- Mobile: Bottom tab bar + hamburger for secondary
- md+: Sidebar navigation

**Product Detail:**
- Mobile: Full-screen modal with back gesture
- md+: Slide-over panel or dedicated page

**Filters:**
- Mobile: Full-screen filter sheet
- md+: Sidebar filter panel

### 8.4 Interaction Patterns

#### Touch Targets

- Minimum 44x44px touch targets
- Adequate spacing between interactive elements
- Larger targets for primary actions

#### Gestures

- Swipe right on product card: Quick add to collection
- Swipe left: Delete/remove
- Long press: Context menu
- Pull to refresh on lists

#### Feedback

- Optimistic updates for fast-feeling UI
- Skeleton loading states
- Toast notifications for actions
- Progress indicators for long operations

#### Keyboard Navigation

- Tab order follows visual order
- Focus indicators visible
- Escape closes modals/dropdowns
- Enter activates focused element
- Arrow keys navigate grids/lists

---

## 9. Security Requirements

### 9.1 Threat Model

**In Scope:**
- Local network attackers (if exposed)
- Malicious PDF content
- API key exposure
- Path traversal attacks

**Out of Scope (v1):**
- Multi-user authentication
- Remote attackers (designed for local use)

### 9.2 Security Controls

#### Input Validation

```python
# All file paths must be within watched folders
def validate_file_path(path: str, watched_folders: list[str]) -> bool:
    resolved = Path(path).resolve()
    return any(
        resolved.is_relative_to(Path(folder).resolve())
        for folder in watched_folders
    )

# Sanitize filenames for cover images
def safe_filename(filename: str) -> str:
    # Remove path separators and null bytes
    sanitized = re.sub(r'[/\\<>:"|?*\x00]', '_', filename)
    # Limit length
    return sanitized[:255]
```

#### Path Traversal Prevention

- Never construct paths from user input directly
- Use `pathlib.Path.resolve()` and verify containment
- Reject paths containing `..`

#### API Key Storage

```python
# Use OS keyring when available, fallback to encrypted file
import keyring
from cryptography.fernet import Fernet

class SecretStorage:
    def __init__(self, app_name: str = "grimoire"):
        self.app_name = app_name
        self._fernet = None
    
    def store(self, key: str, value: str) -> None:
        try:
            keyring.set_password(self.app_name, key, value)
        except keyring.errors.NoKeyringError:
            self._store_encrypted(key, value)
    
    def retrieve(self, key: str) -> str | None:
        try:
            return keyring.get_password(self.app_name, key)
        except keyring.errors.NoKeyringError:
            return self._retrieve_encrypted(key)
```

#### PDF Processing Safety

- Process PDFs in isolated subprocess
- Set memory/time limits on extraction
- Disable JavaScript execution in PDF renderer
- Sanitize extracted text before database insertion

#### Headers and CORS

```python
# FastAPI security middleware
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response
```

### 9.3 Dependency Security

- Use `pip-audit` or `safety` for vulnerability scanning
- Pin dependencies with hashes in requirements
- Regular dependency updates via Dependabot
- Minimal dependencies where possible

---

## 10. Performance Requirements

### 10.1 Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Initial page load | < 2s | Time to interactive |
| Library grid render | < 100ms | 100 items visible |
| Search results | < 200ms | Full-text search |
| Semantic search | < 2s | Including embedding |
| Cover thumbnail load | < 500ms | Lazy loaded |
| PDF open | < 1s | First page visible |
| Scan 1000 PDFs | < 5 min | Metadata only |
| Deep index 1 PDF | < 30s | Without GPU |

### 10.2 Frontend Optimization

#### Code Splitting

```typescript
// Route-based splitting
const Library = lazy(() => import('./pages/Library'));
const Settings = lazy(() => import('./pages/Settings'));
const Entities = lazy(() => import('./pages/Entities'));
```

#### Image Optimization

- Generate thumbnails at multiple sizes (150px, 300px, 600px)
- Use WebP format with JPEG fallback
- Lazy load images outside viewport
- Use `loading="lazy"` and `decoding="async"`
- Implement blur-up placeholder pattern

```typescript
// Cover image component with optimization
function CoverImage({ productId, alt }: Props) {
  return (
    <picture>
      <source
        srcSet={`/api/v1/products/${productId}/cover?w=300&format=webp`}
        type="image/webp"
      />
      <img
        src={`/api/v1/products/${productId}/cover?w=300`}
        alt={alt}
        loading="lazy"
        decoding="async"
        className="aspect-[3/4] object-cover"
      />
    </picture>
  );
}
```

#### Virtual Scrolling

For large libraries (1000+ items):

```typescript
import { useVirtualizer } from '@tanstack/react-virtual';

function ProductGrid({ products }: Props) {
  const parentRef = useRef<HTMLDivElement>(null);
  
  const virtualizer = useVirtualizer({
    count: products.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 280,  // Card height
    overscan: 5,
  });
  
  // Render only visible items
}
```

### 10.3 Backend Optimization

#### Database Indexing

```sql
-- Ensure indexes exist for common queries
CREATE INDEX IF NOT EXISTS idx_products_game_system ON products(game_system);
CREATE INDEX IF NOT EXISTS idx_products_product_type ON products(product_type);
CREATE INDEX IF NOT EXISTS idx_products_created_at ON products(created_at);
CREATE INDEX IF NOT EXISTS idx_products_title_lower ON products(lower(title));

-- Analyze for query planner
ANALYZE;
```

#### Caching

```python
from functools import lru_cache
from cachetools import TTLCache

# In-memory cache for frequent queries
stats_cache = TTLCache(maxsize=100, ttl=60)

@lru_cache(maxsize=1000)
def get_cover_path(product_id: int) -> str | None:
    # Cached cover path lookup
    pass

# HTTP caching headers
@app.get("/api/v1/products/{id}/cover")
async def get_cover(id: int):
    return FileResponse(
        path,
        headers={
            "Cache-Control": "public, max-age=86400",  # 24 hours
            "ETag": file_hash,
        }
    )
```

#### Async Processing

```python
# Use async for I/O-bound operations
async def scan_folder(folder_path: str) -> list[dict]:
    files = []
    async for entry in aiofiles.os.scandir(folder_path):
        if entry.name.endswith('.pdf'):
            stat = await aiofiles.os.stat(entry.path)
            files.append({
                'path': entry.path,
                'size': stat.st_size,
                'modified': stat.st_mtime,
            })
    return files

# Background task queue for heavy processing
async def queue_processing(product_id: int, task_type: str):
    await task_queue.enqueue(
        process_product,
        product_id=product_id,
        task_type=task_type,
    )
```

#### Connection Pooling

```python
# SQLAlchemy async engine with pooling
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    "sqlite+aiosqlite:///grimoire.db",
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)
```

### 10.4 Resource Management

#### Memory Limits

```python
# Limit memory for PDF processing
import resource

def set_memory_limit(max_mb: int = 512):
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (max_mb * 1024 * 1024, hard))
```

#### Concurrent Processing Limits

```python
# Semaphore to limit concurrent PDF processing
pdf_semaphore = asyncio.Semaphore(3)  # Max 3 concurrent

async def process_pdf(path: str):
    async with pdf_semaphore:
        # Processing happens here
        pass
```

---

## 11. Accessibility Requirements

### 11.1 Standards

Target WCAG 2.1 Level AA compliance.

### 11.2 Requirements

#### Perceivable

- [ ] All images have alt text
- [ ] Cover images: `alt="{product title} cover"`
- [ ] Icons with meaning have aria-labels
- [ ] Color is not the only indicator (add icons/text)
- [ ] Minimum contrast ratio 4.5:1 for text
- [ ] Minimum contrast ratio 3:1 for large text/UI
- [ ] Text resizable to 200% without loss of function
- [ ] No content flashes more than 3 times per second

#### Operable

- [ ] All functionality keyboard accessible
- [ ] No keyboard traps
- [ ] Skip to main content link
- [ ] Focus order matches visual order
- [ ] Focus indicators visible (min 2px outline)
- [ ] Touch targets minimum 44x44px
- [ ] Sufficient time for interactions (or adjustable)
- [ ] Pause/stop for auto-updating content

#### Understandable

- [ ] Page language declared (`<html lang="en">`)
- [ ] Consistent navigation across pages
- [ ] Consistent identification of components
- [ ] Error messages identify the field and suggest fix
- [ ] Labels associated with form controls
- [ ] Instructions don't rely solely on sensory characteristics

#### Robust

- [ ] Valid HTML
- [ ] ARIA used correctly
- [ ] Name, role, value available for all UI components
- [ ] Status messages use ARIA live regions

### 11.3 Implementation

#### Focus Management

```typescript
// Focus trap for modals
import { FocusTrap } from '@headlessui/react';

function Modal({ open, onClose, children }) {
  return (
    <FocusTrap>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        {children}
      </div>
    </FocusTrap>
  );
}
```

#### Screen Reader Announcements

```typescript
// Live region for status updates
function ProcessingStatus({ status }) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className="sr-only"
    >
      {status}
    </div>
  );
}
```

#### Keyboard Navigation

```typescript
// Grid keyboard navigation
function ProductGrid({ products }) {
  const handleKeyDown = (e: KeyboardEvent, index: number) => {
    const cols = getColumnCount();
    let newIndex = index;
    
    switch (e.key) {
      case 'ArrowRight':
        newIndex = Math.min(index + 1, products.length - 1);
        break;
      case 'ArrowLeft':
        newIndex = Math.max(index - 1, 0);
        break;
      case 'ArrowDown':
        newIndex = Math.min(index + cols, products.length - 1);
        break;
      case 'ArrowUp':
        newIndex = Math.max(index - cols, 0);
        break;
      case 'Home':
        newIndex = 0;
        break;
      case 'End':
        newIndex = products.length - 1;
        break;
    }
    
    focusProduct(newIndex);
  };
}
```

### 11.4 Testing

- Manual keyboard testing
- Screen reader testing (VoiceOver, NVDA)
- Automated testing with axe-core
- Color contrast analyzer
- Reduced motion preference testing

---

## 12. AI Integration

### 12.1 Provider Abstraction

```python
# ai/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class AIResponse:
    content: str
    model: str
    usage: dict  # tokens, cost estimate
    raw_response: dict

class AIProvider(ABC):
    """Base class for AI providers."""
    
    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> AIResponse:
        """Generate a completion."""
        pass
    
    @abstractmethod
    async def embed(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Generate embeddings for texts."""
        pass
    
    @abstractmethod
    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate cost in USD."""
        pass
    
    @abstractmethod
    async def test_connection(self) -> bool:
        """Verify provider is configured correctly."""
        pass
```

### 12.2 Supported Providers

```python
# ai/providers/openai.py
class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.embedding_model = "text-embedding-3-small"
    
    async def complete(self, prompt: str, **kwargs) -> AIResponse:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": kwargs.get("system", "")},
                {"role": "user", "content": prompt},
            ],
            max_tokens=kwargs.get("max_tokens", 1000),
            temperature=kwargs.get("temperature", 0.7),
        )
        return AIResponse(
            content=response.choices[0].message.content,
            model=self.model,
            usage={
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            },
            raw_response=response.model_dump(),
        )

# ai/providers/anthropic.py
class AnthropicProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "claude-3-haiku-20240307"):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

# ai/providers/ollama.py
class OllamaProvider(AIProvider):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self.base_url = base_url
        self.model = model
    
    # Embedding via ollama's embedding endpoint or nomic-embed-text

# ai/providers/google.py
class GoogleProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        # Google Generative AI SDK
        pass
```

### 12.3 Prompts Library

Store prompts as text files for easy editing and versioning:

```
prompts/
├── identification/
│   ├── product_identifier.txt
│   └── system_detector.txt
├── extraction/
│   ├── monster_extractor.txt
│   ├── spell_extractor.txt
│   ├── random_table_extractor.txt
│   └── npc_extractor.txt
├── tagging/
│   ├── theme_tagger.txt
│   └── content_classifier.txt
└── search/
    └── query_reformulator.txt
```

Example prompt:

```text
# prompts/identification/product_identifier.txt

You are an expert in tabletop role-playing game products. Given text extracted from the first few pages of an RPG PDF, identify the product.

Respond in JSON format:
{
  "title": "The exact product title",
  "publisher": "Publisher name",
  "game_system": "The game system (e.g., 'Dungeon Crawl Classics', 'D&D 5e', 'Shadowdark')",
  "product_type": "One of: adventure, sourcebook, supplement, bestiary, tools, magazine, core_rules",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of identification"
}

If you cannot confidently identify the product, set confidence below 0.5 and explain why.

---
EXTRACTED TEXT:
{extracted_text}
---
```

### 12.4 Cost Management

```python
# ai/cost.py

PRICING = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},  # per 1K tokens
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
    "ollama/*": {"input": 0, "output": 0},  # Local = free
}

def estimate_tokens(text: str) -> int:
    """Rough estimate: ~4 chars per token."""
    return len(text) // 4

def estimate_processing_cost(
    product: Product,
    tasks: list[str],
    provider: str,
    model: str,
) -> float:
    """Estimate cost before processing."""
    total = 0.0
    pricing = PRICING.get(model, PRICING.get(f"{provider}/*", {"input": 0, "output": 0}))
    
    if "identify" in tasks:
        # ~2000 tokens input (first pages), ~200 output
        total += (2000 * pricing["input"] + 200 * pricing["output"]) / 1000
    
    if "extract" in tasks:
        # ~500 tokens per page input, ~100 output
        pages = product.page_count or 50
        total += (pages * 500 * pricing["input"] + pages * 100 * pricing["output"]) / 1000
    
    return total
```

### 12.5 Graceful Degradation

```python
# Feature availability based on AI configuration

class FeatureFlags:
    def __init__(self, settings: Settings):
        self.ai_enabled = settings.has_ai_provider()
        self.embeddings_enabled = settings.has_embedding_provider()
    
    @property
    def can_identify(self) -> bool:
        return self.ai_enabled
    
    @property
    def can_semantic_search(self) -> bool:
        return self.embeddings_enabled
    
    @property
    def can_extract_entities(self) -> bool:
        return self.ai_enabled
```

Frontend should check feature flags and hide/disable unavailable features:

```typescript
function SearchBar({ features }: { features: FeatureFlags }) {
  return (
    <div>
      <input type="search" placeholder="Search library..." />
      {features.can_semantic_search && (
        <button>
          <SparklesIcon /> AI Search
        </button>
      )}
    </div>
  );
}
```

---

## 13. File Processing Pipeline

### 13.1 Pipeline Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                      PROCESSING PIPELINE                          │
└──────────────────────────────────────────────────────────────────┘

PDF Detected
     │
     ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   TIER 1    │     │   TIER 2    │     │   TIER 3    │
│  (Always)   │ ──▶ │ (On-Demand) │ ──▶ │  (Manual)   │
└─────────────┘     └─────────────┘     └─────────────┘
     │                    │                    │
     ▼                    ▼                    ▼
• File metadata      • Full text          • Structured
• Page count         • Table of             extraction
• Cover image          contents           • Schema-based
• Quick text         • Layout analysis      parsing
  (first 10 pages)   • Embeddings         • AI refinement
• AI identification  • Deep search
  (if enabled)         indexing
```

### 13.2 Core Extraction Layer

Grimoire's extraction is based on the [markdown-extractor](https://github.com/madmichael/markdown-extractor) 
project, which provides a multi-backend extraction pipeline with custom fixes for RPG PDF layouts.

#### Multi-Backend Fallback Strategy

The extractor tries multiple backends in order of quality, falling back gracefully:

```
┌─────────────────────────────────────────────────────────────────┐
│                    EXTRACTION BACKENDS                           │
│                    (in priority order)                           │
├─────────────────────────────────────────────────────────────────┤
│  1. MARKER (ML-based)                                           │
│     • Best layout detection using computer vision               │
│     • Handles complex multi-column layouts                      │
│     • Table and equation extraction                             │
│     • Requires GPU for best performance                         │
│     • Models loaded once at startup                             │
├─────────────────────────────────────────────────────────────────┤
│  2. PyMuPDF (fitz)                                              │
│     • Good column detection and reading order                   │
│     • Fast, no ML overhead                                      │
│     • Block-based extraction                                    │
├─────────────────────────────────────────────────────────────────┤
│  3. MarkItDown (Microsoft)                                      │
│     • Good general-purpose extraction                           │
│     • Multi-format support                                      │
├─────────────────────────────────────────────────────────────────┤
│  4. pdfplumber + Custom Column Detection                        │
│     • Final fallback with custom enhancements                   │
│     • Smart column boundary detection                           │
│     • Word-level position analysis                              │
│     • Always available                                          │
└─────────────────────────────────────────────────────────────────┘
```

#### Custom Column Detection Algorithm

When falling back to pdfplumber, a custom algorithm handles multi-column RPG layouts:

```python
def extract_text_with_layout(page):
    """
    Extract text with multi-column awareness.
    
    Algorithm:
    1. Extract all words with x,y positions
    2. Analyze x-coordinate distribution
    3. Find largest horizontal gap in middle 25%-75% of page
    4. Gap > 40px indicates column boundary
    5. Assign each word to left or right column
    6. Process each column top-to-bottom (sort by y, then x)
    7. Concatenate columns in reading order
    """
    words = page.extract_words(x_tolerance=3, y_tolerance=3)
    
    # Find column boundaries by analyzing x-position gaps
    all_x_positions = sorted(set([int(w['x0']) for w in words] + [int(w['x1']) for w in words]))
    
    gaps = []
    for i in range(len(all_x_positions) - 1):
        gap_size = all_x_positions[i + 1] - all_x_positions[i]
        if gap_size > 40:  # Significant gap threshold
            gap_center = (all_x_positions[i] + all_x_positions[i + 1]) / 2
            # Only consider gaps in middle region of page
            if page.width * 0.25 < gap_center < page.width * 0.75:
                gaps.append((gap_size, gap_center))
    
    # Largest gap = column boundary (or single column if no gaps)
    if gaps:
        gaps.sort(reverse=True)
        column_boundary = gaps[0][1]
        # Two columns: assign words, process each separately
    else:
        # Single column layout
    
    # Sort words within each column by (y, x) and reassemble
    # ...
```

#### Text Cleaning Pipeline

Post-extraction cleanup handles common PDF artifacts:

```python
def clean_text(text):
    """Clean extracted text for better markdown output."""
    
    # 1. Remove HTML artifacts from Marker
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<[^>]+>', '', text)
    
    # 2. Fix hyphenated word breaks
    # "Play-\ning" → "Playing"
    text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)
    # "Play- ing" → "Playing" (space variant)
    text = re.sub(r'(\w)-\s+(\w)', r'\1\2', text)
    
    # 3. Fix broken words across lines
    # "experi ence" → "experience"
    text = re.sub(r'([a-z])\s*\n\s*([a-z])', r'\1\2', text)
    
    # 4. Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\n+', '\n\n', text)
    
    return text.strip()
```

#### Header/Footer Detection

Repeated text across pages is automatically identified and filtered:

```python
def detect_headers_footers(pages):
    """
    Find repeated text that appears in the same position across multiple pages.
    
    Algorithm:
    1. Collect last 3 lines from each page
    2. Count occurrences of each line
    3. Lines appearing > 2 times with length < 100 = probable footer
    4. Also detect page number patterns: "Page \d+"
    """
    from collections import Counter
    
    page_last_lines = []
    for page in pages:
        text = page.extract_text()
        if text:
            lines = text.split('\n')
            page_last_lines.extend([l.strip() for l in lines[-3:] if l.strip()])
    
    line_counts = Counter(page_last_lines)
    common_footers = {
        line for line, count in line_counts.items() 
        if count > 2 and len(line) < 100
    }
    
    return common_footers
```

#### Structural Detection

The extractor identifies document structure for better markdown output:

```python
def detect_heading(line, next_line=None):
    """Detect if a line is likely a heading."""
    line = line.strip()
    
    if not line:
        return False
    
    # All caps lines (≥3 chars, no period) are likely headings
    if len(line) >= 3 and line.isupper() and not line.endswith('.'):
        return True
    
    # Short lines (<60 chars) followed by empty line, starting with capital
    if len(line) < 60 and next_line is not None and not next_line.strip():
        if line[0].isupper() and not line.endswith((',', ';', ':')):
            return True
    
    return False

def is_list_item(line):
    """Detect bullet points and numbered lists."""
    line = line.strip()
    
    # Bullet points: •, ●, -, *
    if re.match(r'^[•●\-\*]\s+', line):
        return True
    
    # Numbered lists: 1. or 1)
    if re.match(r'^\d+[\.\)]\s+', line):
        return True
    
    return False
```

#### Marker Configuration

Marker is configured for optimal RPG PDF extraction:

```python
# Load models once at startup (significant memory/time savings)
MARKER_MODELS = create_model_dict()

# Configuration for stability
config_dict = {
    "disable_multiprocessing": True,  # Required for Windows compatibility
    "page_range": f"{start_page}-{end_page}",  # Support page ranges
}

config_parser = ConfigParser(config_dict)
converter = PdfConverter(
    artifact_dict=MARKER_MODELS,
    config=config_parser.generate_config_dict()
)
```

### 13.3 Tier 1: Quick Index (Automatic)

Runs automatically when new PDFs are detected.

```python
# processors/tier1.py

async def quick_index(product_id: int) -> None:
    """Fast indexing for immediate usability."""
    product = await get_product(product_id)
    pdf_path = product.file_path
    
    # 1. Extract basic metadata using pdfplumber (fast, no ML)
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        metadata = pdf.metadata
    
    await update_product(product_id, {
        "page_count": page_count,
        "embedded_title": metadata.get("Title"),
        "embedded_author": metadata.get("Author"),
    })
    
    # 2. Extract cover image
    cover_path = await extract_cover(pdf_path, product_id)
    await update_product(product_id, {"cover_image_path": cover_path})
    
    # 3. Quick text extraction (first 10 pages) using extraction layer
    from processors.extraction import extract_text_to_markdown
    quick_text = await extract_text_to_markdown(
        pdf_path, 
        start_page=1, 
        end_page=min(10, page_count),
        options={"use_marker": False}  # Fast mode: skip ML for quick index
    )
    
    # 4. AI identification (if enabled)
    if await ai_enabled():
        identification = await identify_product(quick_text)
        await update_product(product_id, {
            "title": identification.title,
            "publisher": identification.publisher,
            "game_system": identification.game_system,
            "product_type": identification.product_type,
            "ai_identified": True,
            "identification_confidence": identification.confidence,
        })
    
    # 5. Update processing status
    await update_product(product_id, {"cover_extracted": True})
```

### 13.4 Tier 2: Deep Analysis (On-Demand)

Triggered by user action or batch processing. Uses full extraction pipeline.

```python
# processors/tier2.py

async def deep_index(product_id: int) -> None:
    """Full content extraction and indexing using ML-powered extraction."""
    product = await get_product(product_id)
    pdf_path = product.file_path
    
    # 1. Full text extraction using extraction layer (with Marker if available)
    from processors.extraction import extract_text_to_markdown
    
    markdown_text = await extract_text_to_markdown(
        pdf_path,
        start_page=1,
        end_page=product.page_count,
        options={
            "use_marker": True,          # Use ML-based extraction
            "use_pymupdf": True,         # Fallback enabled
            "filter_headers_footers": True,
            "preserve_formatting": True,
        }
    )
    
    # 2. Chunk the markdown for indexing
    chunks = chunk_markdown(markdown_text, product_id)
    
    for chunk in chunks:
        await create_chunk(product_id, {
            "chunk_type": chunk.type,
            "content": chunk.content,
            "content_markdown": chunk.markdown,
            "page_number": chunk.page,
            "metadata": chunk.metadata,
        })
    
    # 3. Generate embeddings (if enabled)
    if await embeddings_enabled():
        texts = [c.content for c in chunks]
        embeddings = await generate_embeddings(texts)
        
        for chunk, embedding in zip(chunks, embeddings):
            await update_chunk(chunk.id, {"embedding": embedding})
    
    # 4. Extract table of contents from headings
    toc = extract_toc_from_markdown(markdown_text)
    await update_product(product_id, {"table_of_contents": toc})
    
    # 5. Detect special content (stat blocks, tables)
    await detect_special_content(product_id, chunks)
    
    # 6. Update status
    await update_product(product_id, {
        "text_extracted": True,
        "deep_indexed": True,
    })
```

### 13.4 Tier 3: Structured Extraction (Manual)

User-initiated extraction with specific schemas.

```python
# processors/tier3.py

async def extract_entities(
    product_id: int,
    entity_type: str,
    schema: dict,
) -> list[dict]:
    """Extract structured entities using AI and schema."""
    product = await get_product(product_id)
    chunks = await get_chunks(product_id)
    
    # Filter to relevant chunks (stat blocks, tables)
    relevant_chunks = filter_chunks_for_entity(chunks, entity_type)
    
    # Load extraction prompt
    prompt_template = load_prompt(f"extraction/{entity_type}_extractor.txt")
    
    entities = []
    for chunk in relevant_chunks:
        prompt = prompt_template.format(
            content=chunk.content,
            schema=json.dumps(schema),
        )
        
        response = await ai_provider.complete(prompt)
        extracted = parse_json_response(response.content)
        
        if extracted:
            entity = await create_entity(product_id, {
                "entity_type": entity_type,
                "entity_name": extracted.get("name"),
                "entity_data": extracted,
                "page_number": chunk.page_number,
                "source_text": chunk.content[:500],
                "extraction_method": "ai",
                "confidence": extracted.get("confidence", 0.8),
            })
            entities.append(entity)
    
    return entities
```

### 13.5 Special Content Detectors

```python
# processors/detectors.py

# Regex patterns for common stat block formats
STAT_BLOCK_PATTERNS = {
    "dcc": r"(?P<name>[A-Z][^:]+):\s*Init\s*(?P<init>[+-]?\d+)",
    "osr": r"(?P<name>[A-Z][^:]+)\s*(?:HD|Hit Dice)[:\s]*(?P<hd>\d+)",
    "5e": r"(?P<name>[A-Z][^\n]+)\n.*?(?:Armor Class|AC)\s*(?P<ac>\d+)",
}

async def detect_stat_blocks(
    product_id: int,
    chunks: list[Chunk],
    game_system: str | None = None,
) -> list[dict]:
    """Detect stat blocks using regex patterns."""
    detected = []
    
    patterns = (
        [STAT_BLOCK_PATTERNS[game_system]]
        if game_system in STAT_BLOCK_PATTERNS
        else STAT_BLOCK_PATTERNS.values()
    )
    
    for chunk in chunks:
        for pattern in patterns:
            matches = re.finditer(pattern, chunk.content, re.MULTILINE | re.DOTALL)
            for match in matches:
                detected.append({
                    "chunk_id": chunk.id,
                    "type": "stat_block",
                    "name": match.group("name"),
                    "match": match.group(0),
                    "page": chunk.page_number,
                })
    
    return detected

# Table detection patterns
TABLE_INDICATORS = [
    r"\b[dD]\d+\b.*?\n.*?\d+[-–]\d+",  # d6, d20 tables
    r"\bRoll\b.*?\bResult\b",
    r"^\s*\d+\.\s+.+$",  # Numbered lists
]

async def detect_random_tables(
    product_id: int,
    chunks: list[Chunk],
) -> list[dict]:
    """Detect random tables in content."""
    # Implementation
    pass
```

---

## 14. Project Structure

### 14.1 Repository Layout

```
grimoire/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml              # Run tests, linting
│   │   ├── release.yml         # Build and publish
│   │   └── security.yml        # Dependency scanning
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── PULL_REQUEST_TEMPLATE.md
├── backend/
│   ├── grimoire/
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI app entry
│   │   ├── config.py           # Settings/configuration
│   │   ├── database.py         # DB connection/session
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── deps.py         # Dependency injection
│   │   │   ├── routes/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── products.py
│   │   │   │   ├── collections.py
│   │   │   │   ├── search.py
│   │   │   │   ├── entities.py
│   │   │   │   ├── queue.py
│   │   │   │   └── settings.py
│   │   │   └── websocket.py
│   │   ├── models/             # SQLAlchemy models
│   │   │   ├── __init__.py
│   │   │   ├── product.py
│   │   │   ├── collection.py
│   │   │   ├── chunk.py
│   │   │   ├── entity.py
│   │   │   └── settings.py
│   │   ├── schemas/            # Pydantic schemas
│   │   │   ├── __init__.py
│   │   │   ├── product.py
│   │   │   ├── collection.py
│   │   │   └── common.py
│   │   ├── services/           # Business logic
│   │   │   ├── __init__.py
│   │   │   ├── library.py
│   │   │   ├── scanner.py
│   │   │   ├── search.py
│   │   │   └── processor.py
│   │   ├── processors/         # PDF processing
│   │   │   ├── __init__.py
│   │   │   ├── extraction/     # Core extraction (based on markdown-extractor)
│   │   │   │   ├── __init__.py
│   │   │   │   ├── extractor.py      # Main orchestrator with fallback logic
│   │   │   │   ├── backends/
│   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── marker.py     # ML-based (primary)
│   │   │   │   │   ├── pymupdf.py    # Block extraction (fallback 1)
│   │   │   │   │   ├── markitdown.py # Microsoft converter (fallback 2)
│   │   │   │   │   └── pdfplumber.py # Custom column detection (fallback 3)
│   │   │   │   ├── cleaners.py       # Text cleaning (hyphenation, breaks)
│   │   │   │   └── structure.py      # Headers, footers, headings, lists
│   │   │   ├── tier1.py        # Quick indexing (cover, metadata, ID)
│   │   │   ├── tier2.py        # Deep analysis (full text, embeddings)
│   │   │   ├── tier3.py        # Structured extraction (entities)
│   │   │   ├── cover.py        # Cover image extraction
│   │   │   └── entities.py     # Monster, table, spell detection
│   │   ├── ai/                 # AI integration
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── providers/
│   │   │   │   ├── openai.py
│   │   │   │   ├── anthropic.py
│   │   │   │   ├── google.py
│   │   │   │   └── ollama.py
│   │   │   ├── prompts.py
│   │   │   └── cost.py
│   │   ├── worker/             # Background tasks
│   │   │   ├── __init__.py
│   │   │   ├── queue.py
│   │   │   └── tasks.py
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── files.py
│   │       ├── security.py
│   │       └── hashing.py
│   ├── alembic/                # Database migrations
│   │   ├── versions/
│   │   ├── env.py
│   │   └── alembic.ini
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_api/
│   │   ├── test_services/
│   │   └── test_processors/
│   ├── pyproject.toml
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── src/
│   │   └── (see section 7.1)
│   ├── public/
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── package.json
├── prompts/                    # AI prompt templates
│   ├── identification/
│   ├── extraction/
│   ├── tagging/
│   └── README.md
├── schemas/                    # Game system schemas
│   ├── systems/
│   │   ├── dcc/
│   │   ├── shadowdark/
│   │   ├── 5e/
│   │   └── osr-generic/
│   └── README.md
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── nginx.conf
├── scripts/
│   ├── setup.sh
│   └── dev.sh
├── docs/
│   ├── installation.md
│   ├── configuration.md
│   ├── api.md
│   ├── contributing.md
│   └── schemas.md
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
└── CHANGELOG.md
```

### 14.2 Configuration Files

#### docker-compose.yml

```yaml
version: '3.8'

services:
  grimoire:
    build:
      context: .
      dockerfile: docker/Dockerfile.backend
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data              # Database and extracted content
      - ${PDF_LIBRARY_PATH}:/library:ro  # User's PDF folder (read-only)
    environment:
      - DATABASE_URL=sqlite:///app/data/grimoire.db
      - LIBRARY_PATH=/library
      - LOG_LEVEL=INFO
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  frontend:
    build:
      context: .
      dockerfile: docker/Dockerfile.frontend
    ports:
      - "3000:80"
    depends_on:
      - grimoire
    restart: unless-stopped

# Optional: GPU support for Marker
#  grimoire-gpu:
#    extends:
#      service: grimoire
#    deploy:
#      resources:
#        reservations:
#          devices:
#            - driver: nvidia
#              count: 1
#              capabilities: [gpu]
```

#### .env.example

```bash
# Library Configuration
PDF_LIBRARY_PATH=/path/to/your/rpg/pdfs

# Server Configuration
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO

# Database
DATABASE_URL=sqlite:///./data/grimoire.db

# AI Providers (optional - leave empty to disable)
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
OLLAMA_BASE_URL=http://localhost:11434

# Processing
MAX_CONCURRENT_PROCESSING=3
COVER_THUMBNAIL_SIZE=300

# Security
SECRET_KEY=change-this-in-production
```

---

## 15. Development Standards

### 15.1 Code Style

#### Python

- Follow PEP 8 with Black formatting (line length 100)
- Use type hints for all function signatures
- Docstrings for public functions (Google style)
- Use `ruff` for linting

```python
# Example function with proper style
async def get_product_by_id(
    product_id: int,
    db: AsyncSession,
    include_tags: bool = False,
) -> Product | None:
    """Retrieve a product by its ID.
    
    Args:
        product_id: The unique identifier of the product.
        db: Database session.
        include_tags: Whether to eagerly load associated tags.
    
    Returns:
        The product if found, None otherwise.
    
    Raises:
        DatabaseError: If the database query fails.
    """
    query = select(Product).where(Product.id == product_id)
    
    if include_tags:
        query = query.options(selectinload(Product.tags))
    
    result = await db.execute(query)
    return result.scalar_one_or_none()
```

#### TypeScript/React

- ESLint with Prettier
- Functional components with hooks
- Named exports (no default exports)
- Props interfaces defined explicitly

```typescript
// Example component with proper style
interface ProductCardProps {
  product: Product;
  onSelect?: (id: number) => void;
  isSelected?: boolean;
}

export function ProductCard({
  product,
  onSelect,
  isSelected = false,
}: ProductCardProps) {
  const handleClick = useCallback(() => {
    onSelect?.(product.id);
  }, [product.id, onSelect]);

  return (
    <article
      className={cn(
        "rounded-lg border p-4 transition-colors",
        isSelected && "border-primary-500 bg-primary-50"
      )}
      onClick={handleClick}
      role="button"
      tabIndex={0}
      aria-selected={isSelected}
    >
      {/* ... */}
    </article>
  );
}
```

### 15.2 Git Workflow

#### Branch Naming

- `main` - Production-ready code
- `develop` - Integration branch
- `feature/xxx` - New features
- `fix/xxx` - Bug fixes
- `docs/xxx` - Documentation updates
- `refactor/xxx` - Code refactoring

#### Commit Messages

Follow Conventional Commits:

```
type(scope): description

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

Examples:
```
feat(search): add semantic search with embeddings
fix(cover): handle PDFs with no embedded images
docs(api): add OpenAPI examples for product endpoints
refactor(processors): split tier2 into separate modules
```

### 15.3 Code Review Checklist

- [ ] Code follows style guidelines
- [ ] Tests added/updated for changes
- [ ] Documentation updated if needed
- [ ] No security vulnerabilities introduced
- [ ] Performance impact considered
- [ ] Accessibility maintained
- [ ] Mobile responsiveness verified
- [ ] Error handling is appropriate

---

## 16. Testing Strategy

### 16.1 Backend Testing

#### Unit Tests

```python
# tests/test_services/test_scanner.py
import pytest
from grimoire.services.scanner import calculate_file_hash, is_pdf_file

def test_is_pdf_file_with_pdf():
    assert is_pdf_file("document.pdf") is True
    assert is_pdf_file("document.PDF") is True

def test_is_pdf_file_with_non_pdf():
    assert is_pdf_file("document.txt") is False
    assert is_pdf_file("document.pdf.txt") is False

@pytest.mark.asyncio
async def test_calculate_file_hash(tmp_path):
    test_file = tmp_path / "test.pdf"
    test_file.write_bytes(b"test content")
    
    hash1 = await calculate_file_hash(test_file)
    hash2 = await calculate_file_hash(test_file)
    
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex length
```

#### Integration Tests

```python
# tests/test_api/test_products.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_list_products(client: AsyncClient, sample_products):
    response = await client.get("/api/v1/products")
    
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == len(sample_products)

@pytest.mark.asyncio
async def test_filter_products_by_system(client: AsyncClient, sample_products):
    response = await client.get("/api/v1/products?game_system=DCC")
    
    assert response.status_code == 200
    data = response.json()
    assert all(p["game_system"] == "DCC" for p in data["items"])
```

#### Test Fixtures

```python
# tests/conftest.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with AsyncSession(engine) as session:
        yield session

@pytest.fixture
def sample_products(db_session):
    products = [
        Product(title="Sailors on the Starless Sea", game_system="DCC"),
        Product(title="Cursed Scroll Zine #1", game_system="Shadowdark"),
    ]
    # ... insert and return
```

### 16.2 Frontend Testing

#### Component Tests

```typescript
// src/components/library/__tests__/ProductCard.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { ProductCard } from '../ProductCard';

const mockProduct = {
  id: 1,
  title: 'Test Adventure',
  game_system: 'DCC',
  cover_url: '/covers/1.jpg',
};

describe('ProductCard', () => {
  it('renders product title', () => {
    render(<ProductCard product={mockProduct} />);
    expect(screen.getByText('Test Adventure')).toBeInTheDocument();
  });

  it('calls onSelect when clicked', () => {
    const onSelect = vi.fn();
    render(<ProductCard product={mockProduct} onSelect={onSelect} />);
    
    fireEvent.click(screen.getByRole('button'));
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it('shows selected state', () => {
    render(<ProductCard product={mockProduct} isSelected />);
    expect(screen.getByRole('button')).toHaveAttribute('aria-selected', 'true');
  });
});
```

#### E2E Tests

```typescript
// e2e/library.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Library', () => {
  test('displays products after scan', async ({ page }) => {
    await page.goto('/');
    
    // Wait for library to load
    await page.waitForSelector('[data-testid="product-grid"]');
    
    // Check that products are displayed
    const products = page.locator('[data-testid="product-card"]');
    await expect(products).toHaveCountGreaterThan(0);
  });

  test('filters by game system', async ({ page }) => {
    await page.goto('/');
    
    // Open filter panel
    await page.click('[data-testid="filter-button"]');
    
    // Select DCC system
    await page.selectOption('[data-testid="system-filter"]', 'DCC');
    
    // Verify filtered results
    const systemBadges = page.locator('[data-testid="system-badge"]');
    await expect(systemBadges).toHaveText(['DCC']);
  });
});
```

### 16.3 Coverage Requirements

- Backend: Minimum 80% line coverage
- Frontend: Minimum 70% line coverage
- Critical paths (authentication, file processing): 95%+

---

## 17. Deployment

### 17.1 Docker Deployment

#### Quick Start

```bash
# Clone repository
git clone https://github.com/Live-to-Role/grimoire.git
cd grimoire

# Configure environment
cp .env.example .env
# Edit .env to set PDF_LIBRARY_PATH

# Start services
docker-compose up -d

# Access at http://localhost:3000
```

#### Production Deployment

```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  grimoire:
    image: ghcr.io/live-to-role/grimoire:latest
    volumes:
      - grimoire_data:/app/data
      - /path/to/pdfs:/library:ro
    environment:
      - LOG_LEVEL=WARNING
      - SECRET_KEY=${SECRET_KEY}
    restart: always
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
    depends_on:
      - grimoire

volumes:
  grimoire_data:
  caddy_data:
```

### 17.2 Health Checks

```python
# grimoire/api/routes/health.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Basic health check."""
    # Check database connectivity
    try:
        await db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception:
        db_healthy = False
    
    return {
        "status": "healthy" if db_healthy else "degraded",
        "database": "connected" if db_healthy else "disconnected",
        "version": __version__,
    }

@router.get("/health/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness check for load balancers."""
    # More comprehensive checks
    checks = {
        "database": await check_database(db),
        "storage": await check_storage(),
        "worker": await check_worker(),
    }
    
    all_ready = all(checks.values())
    return {
        "ready": all_ready,
        "checks": checks,
    }
```

### 17.3 Backup and Restore

```bash
# Backup script
#!/bin/bash
BACKUP_DIR=/backups
DATE=$(date +%Y%m%d_%H%M%S)

# Stop services
docker-compose stop

# Backup database and extracted content
tar -czf "$BACKUP_DIR/grimoire_$DATE.tar.gz" ./data

# Start services
docker-compose start

# Restore script
#!/bin/bash
BACKUP_FILE=$1

# Stop services
docker-compose stop

# Restore
tar -xzf "$BACKUP_FILE" -C .

# Start services
docker-compose start
```

---

## 18. Contributing Guidelines

### 18.1 Ways to Contribute

1. **Code Contributions**
   - Bug fixes
   - New features
   - Performance improvements

2. **Non-Code Contributions**
   - Documentation improvements
   - Game system schemas
   - AI prompt improvements
   - Bug reports
   - Feature suggestions

3. **Community Metadata**
   - Product identifications
   - Publisher patterns
   - Extraction templates

### 18.2 Getting Started

```bash
# Fork and clone
git clone https://github.com/YOUR_USERNAME/grimoire.git
cd grimoire

# Set up development environment
./scripts/setup-dev.sh

# Create feature branch
git checkout -b feature/your-feature

# Make changes and test
./scripts/test.sh

# Submit PR
```

### 18.3 Adding a Game System Schema

1. Create directory: `schemas/systems/your-system/`
2. Add schema files:
   - `monster.json` - Monster/creature schema
   - `spell.json` - Spell schema (if applicable)
   - `item.json` - Magic item schema
   - `README.md` - Documentation

Example schema:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DCC Monster",
  "type": "object",
  "required": ["name", "hit_dice", "armor_class"],
  "properties": {
    "name": {"type": "string"},
    "hit_dice": {"type": "string", "pattern": "^\\d+d\\d+"},
    "armor_class": {"type": "integer"},
    "movement": {"type": "string"},
    "attacks": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "bonus": {"type": "string"},
          "damage": {"type": "string"}
        }
      }
    },
    "special_abilities": {"type": "array", "items": {"type": "string"}},
    "alignment": {"type": "string"},
    "xp_value": {"type": "integer"}
  }
}
```

### 18.4 Adding AI Prompts

1. Create prompt file in appropriate directory
2. Follow the template format:
   - Clear instructions
   - Expected output format
   - Placeholder variables in `{brackets}`
3. Test with multiple PDFs
4. Submit PR with example outputs

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **Product** | A single PDF file in the library |
| **Chunk** | A segment of extracted text for indexing |
| **Entity** | Structured data extracted from content (monster, spell, etc.) |
| **Collection** | User-created grouping of products |
| **Campaign** | User's active game with linked products |
| **Tier 1/2/3** | Processing depth levels |
| **BYOK** | Bring Your Own Key (for AI services) |

## Appendix B: Game System Codes

| Code | System |
|------|--------|
| `dcc` | Dungeon Crawl Classics |
| `shadowdark` | Shadowdark RPG |
| `5e` | D&D 5th Edition |
| `pf2e` | Pathfinder 2nd Edition |
| `osr` | Generic OSR/Old School |
| `bx` | B/X D&D / Old School Essentials |
| `mork-borg` | Mörk Borg |
| `coc` | Call of Cthulhu |
| `other` | Other/Unknown |

## Appendix C: Product Type Codes

| Code | Type |
|------|------|
| `adventure` | Adventure module |
| `sourcebook` | Setting/sourcebook |
| `supplement` | Rules supplement |
| `bestiary` | Monster collection |
| `tools` | GM tools, generators |
| `magazine` | Zine, magazine issue |
| `core_rules` | Core rulebook |
| `screen` | GM screen |
| `other` | Other/Unknown |

## Appendix D: Live to Role Ecosystem URLs

| Service | URL | Purpose |
|---------|-----|---------|
| **Live to Role** | livetorole.com | Main site, adventures, about |
| **Codex Web** | codex.livetorole.com | Browse, edit, contribute metadata |
| **Codex API** | api.codex.livetorole.com | Programmatic access for Grimoire and developers |
| **Grimoire Repo** | github.com/Live-to-Role/grimoire | Source code, releases, issues |
| **Grimoire Docs** | grimoire.livetorole.com *(future)* | Documentation, installation guides |

---

*Document Version: 1.1*  
*Last Updated: 2024*  
*Maintainer: Live to Role LLC*

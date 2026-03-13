# Folio: Private PDF Knowledge Base Platform

**Date:** 2026-03-13
**Status:** Design approved, not yet implemented
**License:** MIT
**Origin:** Evolved from [Grimoire](https://github.com/mkemi/grimoire) RPG library manager

## Vision

Folio is a local-first, open-source platform for building private, searchable knowledge bases from PDFs you already own. Users organize PDFs into topic instances — isolated libraries with their own search, metadata, and domain-specific intelligence via plugins.

The core insight: people accumulate PDF collections around specific interests (TTRPG sourcebooks, design books, legal references, technical manuals) but have no good tool that combines proper library management with AI-powered search and Q&A — all running locally with no cloud dependency.

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Open source vs. commercial | Open source (MIT) | Local-first tools are hard to monetize; value is higher as a portfolio/community project |
| Architecture | Monolith with plugin registry | Simple deployment, plugins as pip packages via entry points |
| Topic isolation | Hybrid — separate SQLite per topic + cross-topic index | Clean isolation with optional cross-topic discovery |
| Plugin depth | Metadata schemas + custom extractors | Low contributor bar; no plugin UI needed |
| Tech stack | FastAPI + SQLAlchemy + SQLite / React + TypeScript | Proven in Grimoire, single `pip install`, runs on Pi |
| Distribution | pip/pipx install, frontend bundled | No Docker, no Node, no DB server required |

## Architecture

### Data Layout

```
~/.folio/
  config.yaml              # global settings (embedding provider, API keys)
  index.db                 # cross-topic discovery index
  topics/
    ttrpg-collection/
      library.db           # full schema: documents, tags, collections, embeddings
      covers/              # extracted cover images
      text/                # extracted text files
      images/              # extracted images
    visual-design/
      library.db
      covers/
      text/
      images/
```

Each topic instance is fully self-contained. Deleting a topic directory removes all its data (the app also cleans up corresponding rows in `index.db`). Backing up a topic is copying its directory — note that the actual PDF files live outside this directory, so a full backup must include the source PDF paths as well.

**Topic directory naming:** Topic names are slugified for filesystem use (lowercase, spaces to hyphens, special characters stripped). A UUID suffix is appended if a slug collision occurs.

### Core Document Model

Universal fields only — no domain-specific metadata in core:

| Field | Type | Purpose |
|---|---|---|
| id | int | Primary key |
| title | str | Document title |
| author | str | Author(s) |
| publisher | str | Publisher |
| description | text | Free-text description |
| publication_year | int | Year published |
| isbn | str | ISBN if available |
| page_count | int | Number of pages |
| file_size | int | File size in bytes |
| path | str | Absolute path to PDF |
| hash | str | SHA-256 for dedup |
| cover_extracted | bool | Processing flag |
| text_extracted | bool | Processing flag |
| images_extracted | bool | Processing flag |
| image_count | int | Number of extracted images |
| ai_identified | bool | Processing flag |
| extracted_text_path | str | Path to extracted text file |
| plugin_metadata | JSON | Extended fields from domain plugin |
| created_at | datetime | Record creation |
| updated_at | datetime | Last modification |

### Cross-Topic Index (index.db)

Lightweight pointers enabling cross-topic search without coupling databases:

| Field | Type | Purpose |
|---|---|---|
| topic_id | str | Topic instance identifier |
| document_id | int | ID within topic's library.db |
| title | str | Denormalized for fast display |
| author | str | Denormalized for fast display |
| averaged_embedding | blob | Mean of all chunk embeddings for this document |
| plugin_type | str | Which plugin manages this topic |

## Plugin System

### Extractor Interface

```python
class Extractor:
    """Base class for domain-specific extractors."""
    name: str                          # e.g., "statblock"

    async def extract(self, text: str, pdf_path: str, metadata: dict) -> dict:
        """Run extraction on a document's text.

        Args:
            text: Full extracted text of the document.
            pdf_path: Path to the source PDF (for page-level access if needed).
            metadata: Current document metadata (core + plugin_metadata).

        Returns:
            Dict of extracted data to merge into plugin_metadata.
            e.g., {"stat_blocks": [...], "encounter_count": 5}
        """
```

### FilterDef

```python
@dataclass
class FilterDef:
    """Defines a filterable field for the UI."""
    field: str          # key in plugin_metadata, e.g., "game_system"
    type: str           # "select" | "multiselect" | "range" | "boolean" | "text"
    label: str          # display label, e.g., "Game System"
    options: list | None = None   # for select/multiselect types
    min: int | None = None        # for range type
    max: int | None = None        # for range type
```

### Plugin Interface

```python
from folio.plugins import FolioPlugin, Extractor, FilterDef

class TopicShelfPlugin(FolioPlugin):
    name = "ttrpg"
    display_name = "Tabletop RPG"
    version = "1.0.0"

    def metadata_schema(self) -> dict:
        """Extended metadata field definitions.

        Returns a dict of field_name -> {type, label, description, options?}
        Stored in the document's plugin_metadata JSON column.
        """
        return {
            "game_system": {
                "type": "select",
                "label": "Game System",
                "options": ["D&D 5E", "Pathfinder 2E", "OSR", "Other"]
            },
            "product_type": {
                "type": "select",
                "label": "Product Type",
                "options": ["Adventure", "Sourcebook", "Bestiary", "Module"]
            },
            "level_range": {
                "type": "range",
                "label": "Level Range",
                "min": 1, "max": 20
            },
            "themes": {
                "type": "tags",
                "label": "Themes"
            }
        }

    def extractors(self) -> list[Extractor]:
        """Domain-specific extractors run after text extraction."""
        return [StatBlockExtractor(), EncounterExtractor()]

    def enrich_search_text(self, doc: "Document", metadata: dict) -> str:
        """Prepend domain context to text before embedding."""
        parts = []
        if metadata.get("game_system"):
            parts.append(f"System: {metadata['game_system']}")
        if metadata.get("product_type"):
            parts.append(f"Type: {metadata['product_type']}")
        if metadata.get("level_range"):
            lr = metadata["level_range"]
            parts.append(f"Levels: {lr['min']}-{lr['max']}")
        return " | ".join(parts)

    def filter_definitions(self) -> list[FilterDef]:
        """Filterable fields for the UI FilterDrawer."""
        return [
            FilterDef("game_system", type="select", label="Game System"),
            FilterDef("product_type", type="select", label="Product Type"),
            FilterDef("level_range", type="range", label="Level Range"),
        ]
```

### Plugin Discovery

Standard Python entry points in `pyproject.toml`:

```toml
[project.entry-points."folio.plugins"]
ttrpg = "folio_ttrpg:TTRPGPlugin"
```

Discovered at startup via `importlib.metadata.entry_points(group="folio.plugins")`.

### Base Plugin

A `base` plugin ships with the core. It provides generic metadata fields (subject, category, keywords) and uses AI-prompted extraction to fill them. Users who install no domain plugins still get a working system.

### Installing Plugins

```bash
pipx inject folio folio-ttrpg     # add TTRPG plugin
pipx inject folio folio-legal     # add Legal plugin
folio plugins                      # list installed plugins
```

## Multi-Database Session Management

Each topic has its own SQLite file, so the app manages multiple async engines dynamically:

- **Engine cache:** A `TopicEngineManager` maintains a `dict[str, AsyncEngine]` keyed by topic slug. Engines are created lazily on first access and cached for the process lifetime.
- **Session factory:** `get_topic_db(topic_id)` returns an `AsyncSession` for that topic's `library.db`. Route handlers receive the topic ID from the URL path and request the appropriate session.
- **Index DB:** `index.db` has its own dedicated engine, created at startup.
- **WAL mode:** Each SQLite database is configured with WAL mode, 30s busy timeout, and appropriate cache size (matching Grimoire's proven configuration).
- **Cleanup:** When a topic is deleted, its engine is disposed and removed from the cache.

```python
# Dependency injection in route handlers
@router.get("/api/topics/{topic_id}/documents")
async def list_documents(topic_id: str, db: AsyncSession = Depends(get_topic_db)):
    ...
```

## API Routes

| Verb | Path | Purpose |
|---|---|---|
| **Topics** | | |
| GET | /api/topics | List all topic instances |
| POST | /api/topics | Create a new topic |
| GET | /api/topics/{id} | Get topic details |
| PATCH | /api/topics/{id} | Update topic (name, icon, color) |
| DELETE | /api/topics/{id} | Delete topic and all its data |
| **Documents** | | |
| GET | /api/topics/{id}/documents | List documents (paginated, filtered, sorted) |
| POST | /api/topics/{id}/documents | Add documents (file paths or upload) |
| GET | /api/topics/{id}/documents/{doc_id} | Document detail with plugin metadata |
| PATCH | /api/topics/{id}/documents/{doc_id} | Update document metadata |
| DELETE | /api/topics/{id}/documents/{doc_id} | Remove document |
| GET | /api/topics/{id}/documents/{doc_id}/cover | Serve cover image |
| GET | /api/topics/{id}/documents/{doc_id}/text | Serve extracted text |
| **Search** | | |
| GET | /api/topics/{id}/search | Basic + FTS search within a topic |
| POST | /api/topics/{id}/semantic | Semantic search within a topic |
| POST | /api/topics/{id}/ask | RAG Q&A within a topic |
| POST | /api/search/all | Cross-topic search via index.db |
| **Organization** | | |
| GET/POST | /api/topics/{id}/tags | Tag CRUD within a topic |
| GET/POST | /api/topics/{id}/collections | Collection CRUD within a topic |
| **Processing** | | |
| GET | /api/topics/{id}/queue | Queue status for a topic |
| POST | /api/topics/{id}/embed-all | Queue all documents for embedding |
| **Filters** | | |
| GET | /api/topics/{id}/filters | Core + plugin filter definitions |
| **System** | | |
| GET/PATCH | /api/settings | Global settings (providers, API keys) |
| GET | /api/plugins | List installed plugins |

## Search

### Three Tiers

1. **Basic search** — SQLite LIKE on title, author, filename. Always available.

2. **Full-text search** — FTS5 virtual table per topic database. Created when the topic's `library.db` is initialized. Indexes title, author, description, extracted text. Kept in sync via SQLite triggers on INSERT/UPDATE/DELETE (same pattern as Grimoire's `fts_service.py`). Works offline, no models.

3. **Semantic search** — Embeddings with provider hierarchy:
   - Local: sentence-transformers (all-MiniLM-L6-v2) — works offline, runs on Pi
   - Local: Ollama (nomic-embed-text) — better quality, still local
   - Cloud: OpenAI (text-embedding-3-small) — best quality, requires API key

### Domain-Aware Embeddings

Before text is chunked and embedded, the plugin's `enrich_search_text()` prepends domain context. The embedding system is domain-agnostic; the plugin makes embeddings domain-aware.

### Cross-Topic Search

Uses averaged vectors in `index.db`. The "All Topics" view loads index vectors and runs cosine similarity across all topics. Drill-down queries the individual topic's database.

### Q&A (RAG)

`POST /api/topics/{id}/ask` endpoint:
1. Embeds the question
2. Retrieves top-k relevant chunks from the topic
3. Sends chunks + question to LLM (Ollama local or OpenAI cloud)
4. Returns answer with source citations (document title + page number)

## Processing Pipeline

Queue-based, same architecture as Grimoire, generalized:

```
PDF added → cover extraction        (priority 1)
         → text extraction          (priority 2)
         → plugin extractors        (priority 3, requires text)
         → AI identification        (priority 3, requires text)
         → embedding generation     (priority 4, requires text)
         → cross-topic index update (priority 5, requires embedding)
```

- Queue processor is plugin-aware: runs the active plugin's extractors for each topic
- Watched folders per topic — point a topic at a directory for auto-ingestion
- Queue stores `topic_id` to route work to the correct SQLite database

## Frontend

### Layout

```
┌──────────┬──────────────────────────────────┐
│ Topics   │  Visual Design (32 books)        │
│          │                                  │
│ 📚 TTRPG │  [Search...] [🔍 Semantic ▾]    │
│ 🎨 Design│                                  │
│ 📷 Photo │  ┌─────┐ ┌─────┐ ┌─────┐        │
│          │  │cover│ │cover│ │cover│        │
│ + New    │  │     │ │     │ │     │        │
│          │  └─────┘ └─────┘ └─────┘        │
│──────────│  Brand Identity    Color Theory  │
│ 🔎 All   │  by Acme Press    by J. Smith   │
│ ⚙ Settings                                  │
└──────────┴──────────────────────────────────┘
```

### Key UI Elements

- **Topic sidebar** — list of topic instances with icons and document counts
- **"All Topics" view** — cross-topic search via the index
- **Grid/list view** — cover images, virtual scrolling (from Grimoire)
- **Filter drawer** — dynamically rendered from core + plugin filter definitions
- **Ask panel** — slide-out RAG Q&A panel per topic
- **Document detail** — metadata + plugin fields rendered generically from schema
- **Settings** — embedding provider, LLM provider, API keys, plugin management

### What Carries Over from Grimoire

- ProductGrid / virtual scrolling
- Cover image display
- Filter drawer pattern
- Search mode toggle (basic/FTS/semantic)
- Settings page for provider configuration
- Image gallery

### What's New

- Topic sidebar and instance management
- Cross-topic search view
- Ask/Q&A panel
- Dynamic field rendering from plugin schemas

### What Moves to TTRPG Plugin

- Campaign/session tracking
- Stat block display
- Game system filters
- Level range filters
- All RPG-specific metadata fields

## Distribution

### Installation

```bash
pipx install folio                    # core + base plugin
folio start                           # opens browser at localhost:8000
```

### Adding Domain Plugins

```bash
pipx inject folio folio-ttrpg         # TTRPG domain intelligence
```

### Minimum System Requirements

- Python 3.11+
- 1GB RAM recommended (sentence-transformers needs ~300MB during model loading; works on Pi 4+ but not Pi Zero/3). Sentence-transformers is optional — the app falls back gracefully to FTS-only search when unavailable.
- No Docker, no database server, no Node runtime

### For Contributors

Frontend development requires Node 18+ for the React dev server. The built frontend is bundled into the Python package as static assets.

## CLI

```bash
folio start                           # start web server
folio start --port 9000               # custom port
folio create "Topic Name"             # create topic instance
folio create "TTRPG" --plugin ttrpg   # create with domain plugin
folio add ~/pdfs/*.pdf --topic "Name" # ingest PDFs
folio topics                          # list topic instances
folio plugins                         # list installed plugins
folio search "query" --topic "Name"   # CLI search
folio ask "question" --topic "Name"   # CLI Q&A
folio export --topic "Name"           # backup a topic
folio import ./backup/                # restore a topic
```

## Migration from Grimoire

For existing Grimoire users, a migration path:

1. `folio migrate-grimoire /path/to/grimoire.db` creates a new TTRPG topic instance
2. Core fields map directly: title, author, publisher, description, publication_year, isbn, page_count, file_size, path, hash, processing flags, extracted_text_path, image_count, created_at, updated_at
3. RPG-specific fields move to `plugin_metadata` JSON: game_system, genre, product_type, setting, level_range_min/max, party_size_min/max, estimated_runtime, series, series_order, themes, content_warnings, dtrpg_url, itch_url, msrp, format, run_status, run_rating, run_difficulty, run_completed_at
4. Tags, collections carry over (core features in both systems)
5. Embeddings re-generated (schema differs)
6. Watched folders re-registered under the new topic
7. Campaign/session data migrates only if the TTRPG plugin is installed

## Competitive Positioning

| Tool | What it does | What Folio adds |
|---|---|---|
| Paperless-ngx | Digitize & file documents | AI search, Q&A, domain plugins, topic organization |
| AnythingLLM | Chat with documents | Library management, visual browsing, domain awareness |
| NotebookLM | Cloud doc analysis | Local/private, plugin extensibility, no source limits |
| Calibre | E-book management | AI search, Q&A, PDF-specific extraction, domain plugins |
| ChatPDF | Chat with single PDFs | Cross-document search, library management, offline |

Folio's niche: **the intersection of library management and AI search, running locally, with domain-specific intelligence via plugins.**

## Open Questions

- **Name validation:** Verify "Folio" availability on PyPI, GitHub, npm (for the frontend package name)
- **Plugin marketplace:** Should there be a registry of community plugins? Or just a list in the README?
- **Mobile/tablet:** Responsive web UI sufficient, or consider a PWA?
- **Collaboration:** Multi-user support (like Paperless-ngx) or single-user only for v1?
- **Updates:** How should the app handle PDF content updates (new editions)?
- **Plugin removal:** When a plugin is uninstalled, topics using it should fall back to the base plugin. Plugin metadata is preserved in JSON but domain-specific filters/extractors become unavailable until the plugin is reinstalled.
- **Index consistency:** The cross-topic index can be rebuilt from topic databases via `folio reindex`. Needed if the app crashes between embedding generation and index update (separate SQLite files have no cross-DB transactions).
- **`pipx inject` limitations:** Injected plugin packages share a virtualenv with the core app; dependency conflicts between plugins are possible. Acceptable for v1 given a small plugin ecosystem.

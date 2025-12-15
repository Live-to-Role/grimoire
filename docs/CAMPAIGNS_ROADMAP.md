# Campaigns & Community Sharing Roadmap

> **Vision**: Transform Grimoire's Campaigns feature into a powerful GM prep tool, then connect it to Codex for community-driven adventure wisdom sharing.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Moderation | Community flagging + admin review | Scalable, community-driven |
| Spoilers | Required spoiler tagging (none/minor/major/endgame) | Protects GMs who want tips without plot reveals |
| Monetization | None | Gift to the TTRPG community |
| Privacy | Private / Anonymous / Public options | Respect user preferences |

---

## Security Considerations

### Grimoire (Local App)
- **Local-only by default**: All campaign/session/note data stays local until explicitly shared
- **Input validation**: Max lengths on all text fields, enum validation for status fields
- **Content sanitization**: Strip HTML/scripts from user input before storage and display

### Codex Sync
- **Authentication**: Reuse existing Codex auth token from contribution system
- **Authorization**: Users can only modify their own runs/notes
- **Rate limiting**: 
  - Voting: Max 100 votes/hour per user
  - Flagging: Max 20 flags/hour per user
  - Note creation: Max 10 notes/hour per user
- **Content moderation**: Auto-flag notes with suspicious patterns, require admin approval

### Data Validation Rules
| Field | Max Length | Allowed Values |
|-------|------------|----------------|
| Campaign name | 255 chars | - |
| Campaign description | 5000 chars | - |
| Session title | 255 chars | - |
| Session notes/summary | 10000 chars | - |
| Run note title | 255 chars | - |
| Run note content | 20000 chars | Markdown allowed |
| run_status | - | want_to_run, running, completed |
| run_difficulty | - | easier, as_written, harder |
| spoiler_level | - | none, minor, major, endgame |
| visibility | - | private, anonymous, public |

---

## Current State (Dec 2024)

### What Exists
- **Campaign model**: name, description, game_system, status, dates, player_count, notes
- **Session model**: session_number, title, scheduled/actual dates, duration, summary, notes, status
- **campaign_products table**: Many-to-many linking products to campaigns
- **Backend API**: Full CRUD for campaigns and sessions

### What's Broken
- Sessions display but **aren't clickable/editable** in the UI
- Products section **not shown** in campaign detail view
- No UI to **add products** to campaigns
- No way to **create campaign from product view**

---

## Phase 1: Fix Current Campaigns (Local)

**Goal**: Make the existing feature actually functional.

### Tasks

| Task | Component | Status |
|------|-----------|--------|
| Session edit modal | Frontend | DONE |
| - Title, scheduled date, actual date | | |
| - Duration, status (planned/completed/cancelled) | | |
| - Summary, notes fields | | |
| Display linked products in campaign view | Frontend | DONE |
| Add/remove products from campaign UI | Frontend | DONE |
| "Add to Campaign" button on product detail | Frontend | DONE |
| "Create Campaign" from product view | Frontend | DONE |

### Files to Modify
- `frontend/src/pages/Campaigns.tsx` - Session modal, products section
- `frontend/src/pages/ProductDetail.tsx` (or equivalent) - Campaign actions

### Frontend Components Needed

**Session Edit Modal**
- Title input (text)
- Scheduled date picker
- Actual date picker  
- Duration input (minutes, number)
- Status dropdown (planned/completed/cancelled)
- Summary textarea
- Notes textarea (markdown support)
- Save/Cancel buttons
- Delete session button (with confirmation)

**Product Picker Modal**
- Search input with debounce
- Filter by game system (match campaign)
- Product list with checkboxes
- Show already-linked products as checked
- Add/Remove selected products
- Loading and empty states

**Campaign Actions on Product Detail**
- "Add to Campaign" dropdown (list existing campaigns)
- "Create Campaign with this Product" button
- Visual indicator if product is in campaigns

### UI/UX Requirements
- **Mobile responsive**: All modals must work on 320px+ screens
- **Loading states**: Skeleton loaders for async operations
- **Error handling**: Toast notifications for failures
- **Optimistic updates**: Update UI before server confirms
- **Keyboard navigation**: Esc to close modals, Tab through fields

---

## Phase 2: Enhanced Session Planning (Local)

**Goal**: Make campaigns useful for actual GM prep workflow.

### Tasks

| Task | Description | Status |
|------|-------------|--------|
| Session prep notes | Dedicated field for upcoming session prep | DONE (uses notes field) |
| Previous session display | Auto-show last session's summary when prepping next | DONE |
| Quick-open campaign PDFs | One-click to open all linked products | DONE |
| Campaign dashboard | At-a-glance: next session, active threads, party status | TODO |

### Data Model Changes
None required - existing Session model has `notes` and `summary` fields.

---

## Phase 3: Run Tracking (Local → Codex)

**Goal**: Track what adventures you've run and share that with the community.

### Tasks

| Task | Description | Status |
|------|-------------|--------|
| Add run status to products | want_to_run, running, completed | DONE |
| Run rating | 1-5 stars "would run again" | DONE |
| Run difficulty | easier/as_written/harder than expected | DONE |
| Run status UI on product cards/detail | Visual indicator + edit control | DONE |
| Auto-set run status from campaigns | When campaign uses product, update status | DONE |
| Sync run status to Codex | New contribution type | DONE |

### Data Model Changes (Grimoire)

```python
# In models/product.py
class Product(Base):
    # ... existing fields ...
    run_status = Column(String(20), nullable=True)  # want_to_run, running, completed
    run_rating = Column(Integer, nullable=True)  # 1-5
    run_difficulty = Column(String(20), nullable=True)  # easier, as_written, harder
    run_completed_at = Column(DateTime, nullable=True)
```

### Migration Required
```sql
-- Migration: 002_add_run_tracking.sql
ALTER TABLE products ADD COLUMN run_status VARCHAR(20);
ALTER TABLE products ADD COLUMN run_rating INTEGER CHECK (run_rating >= 1 AND run_rating <= 5);
ALTER TABLE products ADD COLUMN run_difficulty VARCHAR(20);
ALTER TABLE products ADD COLUMN run_completed_at TIMESTAMP;

CREATE INDEX idx_products_run_status ON products(run_status);
```

### API Endpoints (Grimoire)
```
PUT  /products/{id}/run-status    - Update run status/rating/difficulty
GET  /products?run_status=running - Filter by run status
```

### Frontend Components
- **Run Status Badge**: Visual indicator on product cards (color-coded)
- **Run Status Editor**: Dropdown + star rating + difficulty selector
- **Filter UI**: Add run status filter to product list sidebar

---

## Phase 4: Run Notes (Local → Codex)

**Goal**: Let GMs share their hard-won wisdom about running adventures.

### Tasks

| Task | Description | Status |
|------|-------------|--------|
| RunNote model | Store GM notes about running products | DONE |
| Note types | prep_tip, modification, warning, review | DONE |
| Spoiler tagging | none, minor, major, endgame | DONE |
| Run notes UI in Grimoire | Add/edit notes on products | DONE |
| Share to Codex | Contribute notes to community | TODO (Codex-side) |
| Privacy controls | Private / Anonymous / Public | DONE |

### Data Model (Grimoire)

```python
class RunNote(Base):
    __tablename__ = "run_notes"
    
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"))
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    
    note_type = Column(String(20))  # prep_tip, modification, warning, review
    title = Column(String(255))
    content = Column(Text)
    spoiler_level = Column(String(20), default="none")  # none, minor, major, endgame
    
    shared_to_codex = Column(Boolean, default=False)
    codex_note_id = Column(String(50), nullable=True)  # ID from Codex if shared
    visibility = Column(String(20), default="private")  # private, anonymous, public
    
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now(UTC))
```

### API Endpoints (Grimoire)

```
GET    /products/{id}/run-notes       - List notes for a product
POST   /products/{id}/run-notes       - Create a note
PUT    /run-notes/{id}                - Update a note
DELETE /run-notes/{id}                - Delete a note
POST   /run-notes/{id}/share          - Share to Codex
```

### Migration Required
```sql
-- Migration: 003_add_run_notes.sql
CREATE TABLE run_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    note_type VARCHAR(20) NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    spoiler_level VARCHAR(20) DEFAULT 'none',
    shared_to_codex BOOLEAN DEFAULT FALSE,
    codex_note_id VARCHAR(50),
    visibility VARCHAR(20) DEFAULT 'private',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_run_notes_product ON run_notes(product_id);
CREATE INDEX idx_run_notes_campaign ON run_notes(campaign_id);
```

### Frontend Components
- **Notes List**: Expandable cards showing note preview
- **Note Editor**: Markdown textarea with preview toggle
- **Spoiler Tag Selector**: Radio buttons or dropdown
- **Share Button**: Confirm dialog with privacy options
- **Shared Badge**: Visual indicator for notes already on Codex

---

## Phase 5: Community Notes (Codex)

**Goal**: Display and curate community GM notes on Codex product pages.

### Tasks

| Task | Description | Status |
|------|-------------|--------|
| AdventureRun model (Codex) | Track who ran what | TODO |
| CommunityNote model (Codex) | Store shared notes | TODO |
| GM Notes tab on product pages | Display community notes | TODO |
| Voting system | Upvote-only for logged-in users | TODO |
| Vote tracking | Track which users voted on which notes | TODO |
| Sort options | Most votes, Least votes, Newest, Oldest | TODO |
| Spoiler filtering | Hide notes above chosen level | TODO |
| Flagging system | Report inappropriate content | TODO |
| Pull notes into Grimoire | See community notes for owned products | TODO |

### Data Model (Codex)

```python
class AdventureRun(Base):
    __tablename__ = "adventure_runs"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    
    status = Column(String(20))  # want_to_run, running, completed
    rating = Column(Integer, nullable=True)  # 1-5
    difficulty = Column(String(20), nullable=True)
    
    session_count = Column(Integer, nullable=True)
    player_count = Column(Integer, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

class CommunityNote(Base):
    __tablename__ = "community_notes"
    
    id = Column(Integer, primary_key=True)
    adventure_run_id = Column(Integer, ForeignKey("adventure_runs.id"))
    grimoire_note_id = Column(String(50), nullable=True)  # Reference back to source
    
    note_type = Column(String(20))
    title = Column(String(255))
    content = Column(Text)
    spoiler_level = Column(String(20))
    
    visibility = Column(String(20))  # anonymous, public
    
    upvotes = Column(Integer, default=0)
    
    flagged = Column(Boolean, default=False)
    flag_count = Column(Integer, default=0)
    flag_reasons = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now(UTC))

class NoteVote(Base):
    """Track which users upvoted which notes (prevents duplicate votes)."""
    __tablename__ = "note_votes"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    note_id = Column(Integer, ForeignKey("community_notes.id", ondelete="CASCADE"))
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    
    # Unique constraint: one vote per user per note
    __table_args__ = (UniqueConstraint('user_id', 'note_id', name='unique_user_note_vote'),)
```

### API Endpoints (Codex)

```
GET    /products/{id}/community-notes     - List community notes
POST   /products/{id}/adventure-runs      - Record that user ran this
POST   /adventure-runs/{id}/notes         - Add a note to a run
POST   /community-notes/{id}/vote         - Upvote (logged-in users only)
DELETE /community-notes/{id}/vote         - Remove upvote
GET    /products/{id}/community-notes     - Supports ?sort=most_votes|least_votes|newest|oldest
POST   /community-notes/{id}/flag         - Flag for review
GET    /users/{id}/adventure-runs         - User's run history
```

### Pagination
All list endpoints support:
```
?page=1&per_page=20&sort=most_votes|newest
```

---

## Integration Points

### Grimoire → Codex Sync

Extend existing contribution system:

```python
# New contribution types
CONTRIBUTION_TYPES = [
    "product_metadata",  # existing
    "adventure_run",     # new: run status
    "run_note",          # new: GM notes
]
```

### Codex → Grimoire Pull

New API for Grimoire to fetch community notes:

```
GET /api/v1/products/{codex_id}/community-notes
    ?spoiler_max=minor
    &sort=most_votes|least_votes|newest|oldest
    &limit=10
```

---

## UI Mockups (Conceptual)

### Campaign Detail View
```
┌─────────────────────────────────────────────────┐
│ Curse of Strahd Campaign                    ✏️ 🗑️│
│ D&D 5e • Active • 4 players                     │
├─────────────────────────────────────────────────┤
│ [Status: Active] [Sessions: 12] [Players: 4]    │
├─────────────────────────────────────────────────┤
│ 📚 Products (3)                        [+ Add]  │
│ ├─ Curse of Strahd (Adventure)                  │
│ ├─ Monster Manual (Core Rules)                  │
│ └─ Van Richten's Guide (Supplement)             │
├─────────────────────────────────────────────────┤
│ 📅 Sessions                          [+ Add]    │
│ ├─ Session 12: Death House Finale    [Planned]  │
│ ├─ Session 11: Into the Mists        [Done]     │
│ └─ ...                                          │
└─────────────────────────────────────────────────┘
```

### Product Detail - Run Status
```
┌─────────────────────────────────────────────────┐
│ Curse of Strahd                                 │
│ ⭐⭐⭐⭐⭐ (4.8) • Adventure • D&D 5e              │
├─────────────────────────────────────────────────┤
│ 🎲 Run Status: [Completed ✓]                    │
│    Rating: ⭐⭐⭐⭐⭐ (Would definitely run again) │
│    Difficulty: As Written                       │
│    [View My Notes] [Share to Codex]             │
├─────────────────────────────────────────────────┤
│ 💬 Community Notes (23)              [Add Note] │
│ ├─ "Prep tip: Map out Barovia early" ⬆️42      │
│ ├─ "Warning: Chapter 4 pacing issues" ⬆️38     │
│ └─ [Show more...]                               │
└─────────────────────────────────────────────────┘
```

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Campaigns created per user | > 1 |
| Products linked per campaign | > 2 |
| Sessions with notes | > 50% |
| Run status set on adventures | > 30% of owned adventures |
| Notes shared to Codex | > 10% of completed runs |
| Community notes per popular adventure | > 5 |

---

## Open Questions

1. **Session-level product links?** Should specific products be linkable to specific sessions (e.g., "Session 5 uses pages 45-60 of the adventure")?

2. **Party tracking?** Should campaigns track party members, levels, inventory?

3. **Cross-campaign notes?** If a GM runs the same adventure twice, should notes be shared across campaigns?

4. **Publisher integration?** Could publishers see aggregate data (X users ran this, average rating Y)?

---

## Changelog

| Date | Change |
|------|--------|
| 2024-12-15 | Initial roadmap created |
| 2024-12-15 | Added upvote system details: logged-in users only, sort by votes/date |
| 2024-12-15 | Note: Codex-side implementation will be developed separately in Codex repo |
| 2024-12-15 | Added: Security section, frontend component specs, UI/UX requirements, migrations, pagination |
| 2024-12-15 | Phase 1 COMPLETE: Session edit modal, products section, product picker, add-to-campaign from product detail |
| 2024-12-15 | Phase 2 COMPLETE: Previous session summary display, quick-open PDFs (individual + all), wider modal |
| 2024-12-15 | Phase 3 COMPLETE: Run tracking - database migration, API endpoints, product schema, frontend UI with status/rating/difficulty |
| 2024-12-15 | Phase 4 COMPLETE: Run notes - RunNote model, API endpoints, GM Notes tab with CRUD, spoiler levels, visibility controls |

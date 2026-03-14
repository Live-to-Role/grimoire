# Backup System Design

## Problem

Processing a large RPG PDF library is a significant time investment. The grimoire backend stores ~14 GB of database data plus ~3 GB of derived files (covers, extracted text, images). There is currently no backup mechanism — data loss from corruption, accidental deletion, or disk failure would require re-processing the entire library, including costly AI identification and embedding generation.

## Goals

- Protect against data loss for the irreplaceable database (metadata, tags, collections, campaign notes, AI identifications, embeddings)
- Provide recovery for derived files (covers, extracted text, images) that are expensive to regenerate
- Let the user control backup destination, storage budget, and retention policy with smart defaults
- Trigger backups automatically after significant processing operations
- Keep backups in standard formats (plain SQLite files, zip archives) so they can be restored manually if needed

## Non-Goals

- Backing up the original PDF files (those live in watched folders managed by the user)
- Cloud backup integration (the user can point the backup destination at a synced folder)
- Real-time replication or continuous data protection
- Backing up application configuration (environment variables, config.py)

## Design

### Backup Types

| Type | Contents | Trigger | Typical Size |
|------|----------|---------|-------------|
| DB snapshot | Consistent copy of `grimoire.db` via SQLite backup API | After major operations + manual | ~14 GB |
| Full backup | DB snapshot + covers/ + text/ + images/ as zip | Manual only | ~17 GB |

DB snapshots are the primary protection mechanism. They capture all irreplaceable user data (metadata, tags, collections, campaign notes, run notes, AI identifications, embeddings) in a consistent state using SQLite's built-in `backup()` API — no risk of WAL corruption or partial writes.

Full backups additionally capture derived files. These are manual-only since derived files can be regenerated from PDFs, and the size makes frequent full backups impractical.

### Storage Layout

The user configures a backup destination directory. Within it:

```
<backup_dir>/
├── db/
│   ├── grimoire-2026-03-14T10-30-00.db
│   ├── grimoire-2026-03-13T18-45-00.db
│   └── ...
├── full/
│   ├── grimoire-full-2026-03-14T10-30-00.zip
│   └── ...
└── backup-manifest.json
```

`backup-manifest.json` indexes all backups with metadata: timestamp, type, size in bytes, product count, SHA-256 integrity hash, and a label (e.g., "pre-restore", "auto: post-scan").

Backups use standard formats — plain `.db` files and `.zip` archives — so they can be restored manually without the application if necessary.

### BackupService

A new service at `grimoire/services/backup.py` with these methods:

#### Core Operations

- **`snapshot_db(label: str | None)`** — Uses `sqlite3.backup()` to create a consistent DB copy. Writes to `<backup_dir>/db/grimoire-{timestamp}.db`. Computes SHA-256 hash. Updates manifest. Calls `rotate()`.
- **`full_backup()`** — Calls `snapshot_db()`, then creates a zip archive of `data/covers/`, `data/text/`, and `data/images/` alongside the DB copy. Writes to `<backup_dir>/full/grimoire-full-{timestamp}.zip`. Updates manifest. Calls `rotate()`.
- **`restore_from_snapshot(backup_id: str)`** — Pre-restore safety snapshot, then copies backup DB over current `grimoire.db`, removes WAL/SHM files, reconnects. Returns summary.
- **`restore_from_full(backup_id: str)`** — Calls DB restore, then unpacks derived files from zip overwriting current data directories. Returns summary.
- **`list_backups()`** — Returns all manifest entries with type, timestamp, size, label.
- **`delete_backup(backup_id: str)`** — Removes backup file and manifest entry.

#### Retention & Recommendations

- **`rotate()`** — Enforces retention limits. Deletes oldest backups (by type) that exceed either the retention count or the storage budget, whichever is hit first.
- **`get_storage_recommendations(max_budget_gb: float)`** — Measures current DB and derived file sizes. Allocates 70% of budget to DB snapshots, 30% to full backups. Divides each allocation by the respective backup size to compute recommended retention counts. Returns recommendations with explanation.

#### Status & Health

- **`get_status()`** — Returns destination info, last backup timestamps, counts, budget usage, and warnings.

### API Routes

New route module at `grimoire/api/routes/backups.py` mounted at `/api/v1/backups/`:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/` | List all backups |
| GET | `/status` | Backup health status and warnings |
| GET | `/recommendations` | Storage recommendations for a given budget |
| POST | `/snapshot` | Trigger manual DB snapshot |
| POST | `/full` | Trigger manual full backup |
| POST | `/{id}/restore` | Restore from a specific backup |
| DELETE | `/{id}` | Delete a specific backup |

#### Status Response

```json
{
  "destination_configured": true,
  "destination_path": "D:/Backups/grimoire",
  "destination_available_gb": 120.5,
  "last_db_snapshot": "2026-03-14T10:30:00",
  "last_full_backup": "2026-03-10T08:00:00",
  "total_backup_size_gb": 45.2,
  "budget_gb": 100,
  "budget_used_pct": 45.2,
  "db_snapshot_count": 3,
  "full_backup_count": 1,
  "warnings": []
}
```

#### Warnings

The status endpoint surfaces warnings when:
- No backup in over 7 days
- Budget nearly full (>90%)
- Destination drive low on space (<10% or <5 GB free)
- Last backup failed

### Event-Driven Triggers

After these operations complete, automatically call `snapshot_db()` if auto-backups are enabled:

1. **Folder scan completes** — hook in `scanner.py` after scan finishes
2. **Bulk AI identification finishes** — hook in `ai_identifier.py`
3. **Bulk embedding generation finishes** — hook in `embeddings.py`
4. **Bulk text extraction finishes** — hook in `text_extractor.py`

Each auto-triggered snapshot is labeled with the event (e.g., "auto: post-scan", "auto: post-identification") for easy identification in the backup list.

### Settings

Backup configuration stored in the existing `settings` table:

| Key | Default | Description |
|-----|---------|-------------|
| `backup_destination` | `null` | Path to backup directory (must be set by user) |
| `backup_max_budget_gb` | `100` | Max total disk space for all backups |
| `backup_db_retention_count` | `null` | Max DB snapshots to keep (null = use recommendation) |
| `backup_full_retention_count` | `null` | Max full backups to keep (null = use recommendation) |
| `backup_auto_enabled` | `false` | Enable event-driven auto-backups |

When retention counts are `null`, the system uses `get_storage_recommendations()` with the configured budget to determine how many to keep.

### First-Run Flow

When backup endpoints are accessed with no destination configured, the API returns a setup-needed status. The frontend prompts for:

1. Backup destination path
2. Storage budget (with sensible default of 100 GB)
3. Smart recommendations displayed based on current data size and chosen budget
4. User adjusts retention counts if desired
5. Whether to enable auto-backups

### Restore Safety

#### Pre-Restore Checks

- Verify backup file exists at the expected path
- Re-compute SHA-256 hash and compare against manifest (integrity check)
- Check available disk space for the restore operation
- Return clear error with details if any check fails

#### Restore Process

1. **Auto-protect current state** — create a snapshot labeled `pre-restore-{timestamp}` so the user can undo a bad restore
2. **DB restore** — shut down DB connection pool, copy backup DB over `grimoire.db`, delete WAL and SHM files, re-initialize connection pool
3. **Full restore only** — additionally unpack derived files (covers/, text/, images/) overwriting current contents
4. **Post-restore verification** — open DB, run a basic query (product count), confirm success
5. **Return summary** — product count, backup timestamp, pre-restore snapshot ID for rollback

#### What Restore Does NOT Touch

- Original PDF files in watched folders
- Backup files themselves
- Application configuration (environment variables, config.py)

### Integrity

- Every backup gets a SHA-256 hash stored in `backup-manifest.json`
- Hashes are verified before restore
- If the manifest is lost or corrupted, backups remain usable — they are standard SQLite and zip files that can be restored manually
- No proprietary formats

### File Structure

```
grimoire/
├── services/
│   └── backup.py           # BackupService
├── api/routes/
│   └── backups.py           # Backup API routes
└── schemas/
    └── backup.py            # Pydantic models for backup requests/responses
```

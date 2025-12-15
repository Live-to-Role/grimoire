-- Migration: Add deleted_duplicates table for tracking deleted duplicate file paths
-- This prevents re-importing files that were intentionally deleted as duplicates

CREATE TABLE IF NOT EXISTS deleted_duplicates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    file_hash TEXT NOT NULL,
    original_product_id INTEGER,
    deleted_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_deleted_duplicates_path ON deleted_duplicates(file_path);
CREATE INDEX IF NOT EXISTS idx_deleted_duplicates_hash ON deleted_duplicates(file_hash);

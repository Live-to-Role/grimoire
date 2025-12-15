-- Migration: Add run_notes table for GM notes about running products
-- Run this if you have an existing database

CREATE TABLE IF NOT EXISTS run_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    
    note_type VARCHAR(20) NOT NULL,  -- prep_tip, modification, warning, review
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    spoiler_level VARCHAR(20) DEFAULT 'none',  -- none, minor, major, endgame
    
    shared_to_codex BOOLEAN DEFAULT FALSE,
    codex_note_id VARCHAR(50),  -- ID from Codex if shared
    visibility VARCHAR(20) DEFAULT 'private',  -- private, anonymous, public
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_run_notes_product ON run_notes(product_id);
CREATE INDEX IF NOT EXISTS ix_run_notes_campaign ON run_notes(campaign_id);
CREATE INDEX IF NOT EXISTS ix_run_notes_note_type ON run_notes(note_type);

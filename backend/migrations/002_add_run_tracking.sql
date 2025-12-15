-- Migration: Add run tracking fields to products table
-- Run this if you have an existing database

-- Add run status column (want_to_run, running, completed)
ALTER TABLE products ADD COLUMN run_status VARCHAR(20);

-- Add run rating (1-5 stars, "would run again")
ALTER TABLE products ADD COLUMN run_rating INTEGER CHECK (run_rating IS NULL OR (run_rating >= 1 AND run_rating <= 5));

-- Add run difficulty (easier, as_written, harder than expected)
ALTER TABLE products ADD COLUMN run_difficulty VARCHAR(20);

-- Add run completed timestamp
ALTER TABLE products ADD COLUMN run_completed_at TIMESTAMP;

-- Create index for filtering by run status
CREATE INDEX IF NOT EXISTS ix_products_run_status ON products(run_status);

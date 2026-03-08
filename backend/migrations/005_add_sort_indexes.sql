-- Add indexes for sortable columns that were missing
-- These improve performance when sorting by updated_at or last_opened_at

CREATE INDEX IF NOT EXISTS ix_products_updated_at ON products(updated_at);
CREATE INDEX IF NOT EXISTS ix_products_last_opened_at ON products(last_opened_at);

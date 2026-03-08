-- Add index on is_missing for filtered product listing
CREATE INDEX IF NOT EXISTS ix_products_is_missing ON products(is_missing);

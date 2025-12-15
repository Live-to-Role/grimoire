-- Migration: Add author and genre fields to products table
-- Run this if you have an existing database

-- Add author column
ALTER TABLE products ADD COLUMN author VARCHAR(500);

-- Add genre column  
ALTER TABLE products ADD COLUMN genre VARCHAR(50);

-- Create indexes
CREATE INDEX IF NOT EXISTS ix_products_author ON products(author);
CREATE INDEX IF NOT EXISTS ix_products_genre ON products(genre);

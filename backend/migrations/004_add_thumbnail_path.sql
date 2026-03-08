-- Add thumbnail_path column to products table
-- Migration: 004_add_thumbnail_path
-- Date: 2026-01-04

ALTER TABLE products ADD COLUMN thumbnail_path TEXT;

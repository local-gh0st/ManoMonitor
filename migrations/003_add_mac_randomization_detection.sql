-- Migration: Add MAC randomization detection and device grouping
-- Date: 2026-01-21
-- Description: Adds support for detecting and grouping randomized MAC addresses

-- Create device_groups table
CREATE TABLE IF NOT EXISTS device_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100),
    primary_mac VARCHAR(17),
    confidence_score FLOAT DEFAULT 0.0,
    fingerprint_data TEXT,
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    times_seen INTEGER DEFAULT 1
);

-- Add MAC randomization fields to assets table
ALTER TABLE assets ADD COLUMN is_randomized_mac BOOLEAN DEFAULT 0;
ALTER TABLE assets ADD COLUMN device_group_id INTEGER REFERENCES device_groups(id);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_assets_device_group ON assets(device_group_id);
CREATE INDEX IF NOT EXISTS idx_assets_randomized_mac ON assets(is_randomized_mac);

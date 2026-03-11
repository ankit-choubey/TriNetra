-- ╔══════════════════════════════════════════════════════╗
-- ║  TRINETRA — Supabase Postgres Setup                 ║
-- ║  Run this in Supabase SQL Editor (Dashboard)        ║
-- ╚══════════════════════════════════════════════════════╝

-- ── Applications Table (UCSO stored as JSONB) ──
CREATE TABLE IF NOT EXISTS applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name TEXT DEFAULT '',
    pan TEXT DEFAULT '',
    gstin TEXT DEFAULT '',
    cin TEXT DEFAULT '',
    ucso_data JSONB DEFAULT '{}',
    status TEXT DEFAULT 'CREATED',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Indexes for fast lookups ──
CREATE INDEX IF NOT EXISTS idx_app_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_app_created ON applications(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_pan ON applications(pan);

-- ── Enable Row Level Security (disabled for now — open endpoints) ──
-- ALTER TABLE applications ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "Allow all" ON applications FOR ALL USING (true);

-- ═══════════════════════════════════════════════════════
-- STORAGE: Create bucket via Supabase Dashboard
-- Bucket Name: trinetra-files
-- Public: YES (for signed URL access)
-- ═══════════════════════════════════════════════════════

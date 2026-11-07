-- 009_qr_sessions.sql — pre-Bot QR onboarding sessions
--
-- A QR session owns a temporary AstrBot platform (``temp_platform_id``) but does
-- NOT create a row in ``bots`` until the scan is confirmed and finalize runs.
-- Keeping the machine-readable status here lets a restarted console treat
-- orphaned sessions as expired instead of leaking temporary platforms.

CREATE TABLE IF NOT EXISTS qr_sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  name TEXT NOT NULL,
  template_id TEXT NOT NULL,
  temp_platform_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qr_sessions_user
  ON qr_sessions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qr_sessions_status
  ON qr_sessions(status, expires_at);

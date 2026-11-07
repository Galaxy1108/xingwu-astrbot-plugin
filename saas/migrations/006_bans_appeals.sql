-- 006_bans_appeals.sql — account bans, admin bot disable and appeals (M6)
--
-- Banning a user records which bots were *enabled* (status='ready') at ban
-- time in ``users.banned_restore_bots`` so unban only restores those bots;
-- bots the user had already disabled manually stay disabled.

ALTER TABLE users ADD COLUMN status_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN status_changed_at INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN banned_restore_bots TEXT NOT NULL DEFAULT '[]';

ALTER TABLE bots ADD COLUMN admin_disabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bots ADD COLUMN disabled_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE bots ADD COLUMN disabled_at INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS appeals (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  target_type TEXT NOT NULL CHECK (target_type IN ('user', 'bot')),
  target_id TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'approved', 'rejected')),
  admin_id TEXT NOT NULL DEFAULT '',
  admin_note TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  resolved_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_appeals_user ON appeals(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_appeals_status ON appeals(status, created_at DESC);

-- One pending appeal per user per target (user id for target_type='user',
-- bot id for target_type='bot').
CREATE UNIQUE INDEX IF NOT EXISTS uniq_appeals_pending
  ON appeals(user_id, target_type, target_id) WHERE status = 'pending';

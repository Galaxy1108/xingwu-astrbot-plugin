-- 005_redemption_codes.sql — no-payment model: admin-issued redemption codes
--
-- Every top-up happens through a redemption code (orders / manual ledger adjust
-- remain available for legacy admin flows).  ``redemption_codes.code`` is the
-- bearer secret shown to the user; ``redemption_uses`` records who already
-- redeemed a code so a single user cannot redeem the same code twice even when
-- ``max_uses > 1``.

CREATE TABLE IF NOT EXISTS redemption_codes (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  points INTEGER NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  max_uses INTEGER NOT NULL DEFAULT 1,
  used_count INTEGER NOT NULL DEFAULT 0,
  expires_at INTEGER NOT NULL DEFAULT 0,
  disabled INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_redemption_codes_created
  ON redemption_codes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_redemption_codes_code ON redemption_codes(code);

CREATE TABLE IF NOT EXISTS redemption_uses (
  code_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (code_id, user_id)
);

-- 001_init.sql — plugin database schema (M1)
-- See handoff doc §5. Additions documented in docs/ARCHITECTURE.md:
--   * otp_codes        (needed by FR-A, not in the §5 sketch)
--   * sessions.absolute_expires_at, sessions.csrf_token_hash
--   * bots.snapshot    (template snapshot: "创建后不随模板变化")
--   * invites.code_hash TEXT (hex) instead of BLOB for simpler indexing

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'disabled', 'deleted')),
  created_at INTEGER NOT NULL,
  disabled_at INTEGER NOT NULL DEFAULT 0,
  invite_code TEXT NOT NULL DEFAULT '',
  encryption_enabled INTEGER NOT NULL DEFAULT 1,
  encryption_state TEXT NOT NULL DEFAULT 'encrypted',
  encryption_changed_at INTEGER NOT NULL DEFAULT 0,
  encryption_changed_by TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,                 -- sha256 hex of the cookie token
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  absolute_expires_at INTEGER NOT NULL,
  last_seen_at INTEGER NOT NULL,
  csrf_token_hash TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT '',
  user_agent TEXT NOT NULL DEFAULT '',
  revoked_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, revoked_at);

CREATE TABLE IF NOT EXISTS invites (
  code_hash TEXT PRIMARY KEY,
  code_hint TEXT NOT NULL DEFAULT '',   -- INV-XXXX, shown in admin list
  created_by TEXT NOT NULL,
  max_uses INTEGER NOT NULL DEFAULT 1,
  used_count INTEGER NOT NULL DEFAULT 0,
  expires_at INTEGER NOT NULL,
  revoked_at INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_invites_created ON invites(created_at DESC);

CREATE TABLE IF NOT EXISTS otp_codes (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  purpose TEXT NOT NULL DEFAULT 'login',
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  consumed_at INTEGER NOT NULL DEFAULT 0,
  ip TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_otp_email ON otp_codes(email, created_at DESC);

CREATE TABLE IF NOT EXISTS templates (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  persona_prompt TEXT NOT NULL DEFAULT '',
  begin_dialogs TEXT NOT NULL DEFAULT '[]',
  config_patch TEXT NOT NULL DEFAULT '{}',
  memory_defaults TEXT NOT NULL DEFAULT '{}',
  privacy_defaults TEXT NOT NULL DEFAULT '{}',
  quota TEXT NOT NULL DEFAULT '{}',
  user_overridable TEXT NOT NULL DEFAULT '[]',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_templates_enabled ON templates(enabled, updated_at DESC);

CREATE TABLE IF NOT EXISTS bots (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  template_id TEXT NOT NULL DEFAULT '',
  platform TEXT NOT NULL CHECK (platform IN ('weixin_oc', 'qq_official')),
  persona_name TEXT NOT NULL DEFAULT '',
  conf_id TEXT NOT NULL DEFAULT '',
  memory_db TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'creating'
    CHECK (status IN ('creating', 'pending_qr', 'ready', 'disabled', 'deleting', 'deleted')),
  snapshot TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  last_active_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_bots_user ON bots(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bots_status ON bots(status);

CREATE TABLE IF NOT EXISTS bot_bindings (
  bot_id TEXT PRIMARY KEY REFERENCES bots(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  credential_cipher BLOB,
  bound_at INTEGER NOT NULL DEFAULT 0,
  last_ok_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tenant_keys (
  tenant_id TEXT PRIMARY KEY,
  key_version INTEGER NOT NULL DEFAULT 1,
  wrapped_key BLOB NOT NULL,
  created_at INTEGER NOT NULL,
  rotated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS crypto_jobs (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('decrypt', 'encrypt')),
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'paused', 'done', 'failed')),
  total INTEGER NOT NULL DEFAULT 0,
  done INTEGER NOT NULL DEFAULT 0,
  cursor TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  started_at INTEGER NOT NULL DEFAULT 0,
  finished_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_crypto_jobs_user ON crypto_jobs(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_id TEXT NOT NULL DEFAULT '',
  actor_role TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL,
  target_type TEXT NOT NULL DEFAULT '',
  target_id TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor_id, created_at DESC);

CREATE TABLE IF NOT EXISTS content_access_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  admin_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  bot_id TEXT NOT NULL,
  resource TEXT NOT NULL,
  resource_id TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_access_bot ON content_access_logs(bot_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_access_user ON content_access_logs(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS quotas (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  max_bots INTEGER NOT NULL DEFAULT 3,
  monthly_tokens INTEGER NOT NULL DEFAULT 1000000,
  max_memories INTEGER NOT NULL DEFAULT 2000,
  used_tokens INTEGER NOT NULL DEFAULT 0,
  used_memories INTEGER NOT NULL DEFAULT 0,
  period_start INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS wallets (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  balance INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  delta INTEGER NOT NULL,
  type TEXT NOT NULL,
  ref TEXT NOT NULL DEFAULT '',
  idem_key TEXT UNIQUE,
  note TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  amount_cny REAL NOT NULL DEFAULT 0,
  credits INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'manual',
  external_ref TEXT UNIQUE,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at INTEGER NOT NULL,
  paid_at INTEGER NOT NULL DEFAULT 0,
  operator TEXT NOT NULL DEFAULT ''
);

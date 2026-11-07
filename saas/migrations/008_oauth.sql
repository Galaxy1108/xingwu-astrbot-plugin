-- 008_oauth.sql — third-party identities (GitHub) and one-time OAuth states
--
-- ``oauth_states`` is the server-side half of the OAuth handshake: the random
-- state is single-use, expires after 10 minutes and carries the requested mode
-- (login / register / bind), the pending user (bind only), the invite code and
-- the post-login redirect.

CREATE TABLE IF NOT EXISTS oauth_identities (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  subject TEXT NOT NULL,
  email TEXT NOT NULL DEFAULT '',
  login TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  UNIQUE(provider, subject)
);
CREATE INDEX IF NOT EXISTS idx_oauth_identities_user
  ON oauth_identities(user_id, provider);

CREATE TABLE IF NOT EXISTS oauth_states (
  state TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('login', 'register', 'bind')),
  user_id TEXT NOT NULL DEFAULT '',
  invite TEXT NOT NULL DEFAULT '',
  redirect TEXT NOT NULL DEFAULT '',
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oauth_states_expires ON oauth_states(expires_at);

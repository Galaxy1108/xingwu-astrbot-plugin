-- 010_conversation_shares.sql — read-only public links to one conversation
--
-- ``expires_at = 0`` means the share never expires. The token is the primary
-- key and is generated with ``secrets.token_urlsafe``; revoking deletes rows.

CREATE TABLE IF NOT EXISTS conversation_shares (
  token TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  bot_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  expires_at INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversation_shares_owner
  ON conversation_shares(user_id, bot_id, conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversation_shares_expiry
  ON conversation_shares(expires_at);

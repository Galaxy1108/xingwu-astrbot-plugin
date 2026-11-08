CREATE TABLE IF NOT EXISTS message_stats (
  user_id TEXT NOT NULL,
  bot_id TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT '',
  day TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, bot_id, day)
);
CREATE INDEX IF NOT EXISTS idx_message_stats_user_day ON message_stats(user_id, day DESC);

-- 001_init.sql — per-bot memory library (handoff §4.5.3)

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL DEFAULT 'fact',
  content TEXT NOT NULL,
  reasoning TEXT NOT NULL DEFAULT '',
  importance INTEGER NOT NULL DEFAULT 3,
  pinned INTEGER NOT NULL DEFAULT 0,
  source_conversation_id TEXT NOT NULL DEFAULT '',
  source_message_id TEXT NOT NULL DEFAULT '',
  metadata TEXT NOT NULL DEFAULT '{}',
  embedding BLOB,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  last_recalled_at INTEGER NOT NULL DEFAULT 0,
  recall_count INTEGER NOT NULL DEFAULT 0,
  deleted_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind, deleted_at);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_pinned ON memories(pinned, importance);

CREATE TABLE IF NOT EXISTS memory_tags (
  memory_id INTEGER NOT NULL,
  tag TEXT NOT NULL,
  PRIMARY KEY (memory_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_memory_tags_tag ON memory_tags(tag);

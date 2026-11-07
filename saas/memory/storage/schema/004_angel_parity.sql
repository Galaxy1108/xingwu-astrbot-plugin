-- 004_angel_parity.sql — note library + vector index + memory strength metadata

CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  short_id TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  deleted_at INTEGER NOT NULL DEFAULT 0
);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
  title, content, tags, tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS memory_vectors (
  memory_id INTEGER PRIMARY KEY,
  model TEXT NOT NULL DEFAULT '',
  dim INTEGER NOT NULL DEFAULT 0,
  vector BLOB NOT NULL,
  updated_at INTEGER NOT NULL
);

ALTER TABLE memories ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'knowledge';
ALTER TABLE memories ADD COLUMN strength INTEGER NOT NULL DEFAULT 50;
ALTER TABLE memories ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memories ADD COLUMN last_decay_at INTEGER NOT NULL DEFAULT 0;

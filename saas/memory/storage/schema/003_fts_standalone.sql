-- 003_fts_standalone.sql — migrate legacy external-content FTS to standalone
--
-- Drops the old triggers/table (created by the first M1 draft) and rebuilds a
-- standalone index from the base table. Idempotent: safe on fresh databases.

DROP TRIGGER IF EXISTS memories_ai;
DROP TRIGGER IF EXISTS memories_ad;
DROP TRIGGER IF EXISTS memories_au;
DROP TABLE IF EXISTS memories_fts;

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
  content, reasoning, tags,
  tokenize='unicode61'
);

INSERT INTO memories_fts(rowid, content, reasoning, tags)
SELECT id, content, reasoning,
       COALESCE((SELECT group_concat(tag, ' ') FROM memory_tags WHERE memory_id = memories.id), '')
FROM memories
WHERE deleted_at = 0;

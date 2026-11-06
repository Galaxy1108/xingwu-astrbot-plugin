-- 002_fts.sql — FTS5 index + triggers (handoff §4.5.3)

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
  content, reasoning, tags,
  content='memories', content_rowid='id',
  tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, content, reasoning, tags)
  VALUES (
    new.id,
    new.content,
    new.reasoning,
    COALESCE((SELECT group_concat(tag, ' ') FROM memory_tags WHERE memory_id = new.id), '')
  );
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content, reasoning, tags)
  VALUES (
    'delete',
    old.id,
    old.content,
    old.reasoning,
    COALESCE((SELECT group_concat(tag, ' ') FROM memory_tags WHERE memory_id = old.id), '')
  );
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content, reasoning, tags)
  VALUES (
    'delete',
    old.id,
    old.content,
    old.reasoning,
    COALESCE((SELECT group_concat(tag, ' ') FROM memory_tags WHERE memory_id = old.id), '')
  );
  INSERT INTO memories_fts(rowid, content, reasoning, tags)
  VALUES (
    new.id,
    new.content,
    new.reasoning,
    COALESCE((SELECT group_concat(tag, ' ') FROM memory_tags WHERE memory_id = new.id), '')
  );
END;

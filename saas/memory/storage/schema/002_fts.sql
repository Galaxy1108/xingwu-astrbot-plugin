-- 002_fts.sql — standalone FTS5 index (managed explicitly by the repository)
--
-- NOTE: an *external content* FTS table (content='memories') cannot be kept
-- consistent when tags live in another table: the insert trigger indexes tags
-- before they exist, while the delete leg of the update trigger sees the new
-- tags and corrupts the index ("database disk image is malformed").
-- Therefore the index is standalone and SqlCipherRepository maintains it.

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
  content, reasoning, tags,
  tokenize='unicode61'
);

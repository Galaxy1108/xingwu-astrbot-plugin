-- 007_password_auth.sql — password login, username and verified-email marker
--
-- Existing accounts keep e-mail login (they proved e-mail ownership through
-- OTP before this migration), hence ``email_verified = 1`` for every legacy row.
-- Accounts created without an e-mail use the placeholder
-- ``u_<id>@no-email.local`` (``email`` stays NOT NULL/UNIQUE) and are left
-- unverified so password reset is unavailable.
--
-- The partial unique index allows many rows with ``username = ''`` while
-- enforcing uniqueness once a username is chosen.

ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN username TEXT NOT NULL DEFAULT '';

UPDATE users SET email_verified = 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username
  ON users(username) WHERE username != '';

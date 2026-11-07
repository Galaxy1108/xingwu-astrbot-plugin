-- 004_user_profile.sql — display name for users

ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT '';

UPDATE users
SET display_name = CASE
  WHEN instr(email, '@') > 1 THEN substr(email, 1, instr(email, '@') - 1)
  ELSE email
END
WHERE display_name = '';

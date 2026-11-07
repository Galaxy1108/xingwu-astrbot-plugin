-- 002_template_conf.sql — templates reference an AstrBot config profile

ALTER TABLE templates ADD COLUMN base_conf_id TEXT NOT NULL DEFAULT 'default';

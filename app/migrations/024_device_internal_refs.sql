-- Introduce opaque server-generated relational references for devices.
-- Database.migrate() performs an idempotent backfill while preserving legacy
-- columns and all historical rows. Column removal is deferred until all app
-- and firmware paths use device_ref exclusively.
INSERT OR IGNORE INTO system_meta(key,value) VALUES('device_internal_ref_schema_version','001');
INSERT OR REPLACE INTO system_meta(key,value) VALUES('schema_version','024');

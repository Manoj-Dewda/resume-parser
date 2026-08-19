-- Adds the Supabase Storage object path alongside the existing file_data
-- column. Both coexist during the migration: new uploads write to both,
-- the worker reads from storage_path when present and falls back to
-- file_data otherwise. file_data is dropped in a later migration once
-- every row has a storage_path and the new path is verified live.
ALTER TABLE resumes ADD COLUMN storage_path TEXT;

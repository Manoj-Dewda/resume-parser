-- Step 1 of the file_data cutover (see docs/STATUS.md): new uploads stop
-- writing the raw binary into Postgres and rely on storage_path (Supabase
-- Storage) alone. Existing rows are untouched; this only lets new inserts
-- omit the column instead of violating NOT NULL.
ALTER TABLE resumes ALTER COLUMN file_data DROP NOT NULL;

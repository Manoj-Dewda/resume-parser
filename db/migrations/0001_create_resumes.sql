CREATE TABLE resumes (
    id BIGSERIAL PRIMARY KEY,
    original_filename TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'docx')),
    file_data BYTEA NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    parsed_result JSONB,
    error TEXT,
    attempts INT NOT NULL DEFAULT 0,
    locked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Partial index: the queue only ever scans for pending work, and a full-table
-- index would also cover 'done'/'failed' rows that SELECT ... FOR UPDATE
-- SKIP LOCKED never needs to touch.
CREATE INDEX resumes_pending_idx ON resumes (created_at) WHERE status = 'pending';

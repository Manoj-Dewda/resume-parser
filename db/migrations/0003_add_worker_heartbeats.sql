-- Tracks worker liveness independently of the resumes queue: each worker
-- thread upserts its own row every poll loop iteration, so a crashed or
-- hung thread's row simply stops advancing rather than disappearing.
CREATE TABLE worker_heartbeats (
    worker_id INT PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

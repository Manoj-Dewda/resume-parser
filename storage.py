"""Resume file storage on Supabase Storage.

The raw resume bytes live here, not in Postgres — Postgres only holds
job metadata (status, storage_path, parsed_result), so the database
isn't also doing double duty as a blob store.
"""

import os
from uuid import uuid4

from supabase import create_client

BUCKET = "resumes"


def _client():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def upload_resume(file_data: bytes, filename: str) -> str:
    storage_path = f"{uuid4()}/{filename}"
    _client().storage.from_(BUCKET).upload(storage_path, file_data)
    return storage_path


def download_resume(storage_path: str) -> bytes:
    return _client().storage.from_(BUCKET).download(storage_path)

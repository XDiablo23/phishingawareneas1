"""Shared helper: read an upload with a hard size cap so a large file can't
exhaust memory in the parsing path."""
from __future__ import annotations

from fastapi import HTTPException, UploadFile

from app.config import settings


async def read_upload_capped(file: UploadFile) -> bytes:
    max_bytes = max(1, settings.MAX_UPLOAD_MB) * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            413, f"file too large (max {settings.MAX_UPLOAD_MB} MB)")
    return data

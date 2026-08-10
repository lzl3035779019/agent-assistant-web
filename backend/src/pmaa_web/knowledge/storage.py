from __future__ import annotations

import asyncio
from io import BytesIO

from minio import Minio

from pmaa_web.config import get_settings


def _client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def _ensure_bucket(client: Minio) -> None:
    bucket = get_settings().minio_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


async def upload_object(storage_key: str, data: bytes, content_type: str) -> None:
    def upload() -> None:
        client = _client()
        _ensure_bucket(client)
        client.put_object(
            get_settings().minio_bucket,
            storage_key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    await asyncio.to_thread(upload)


async def download_object(storage_key: str) -> bytes:
    def download() -> bytes:
        response = _client().get_object(get_settings().minio_bucket, storage_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    return await asyncio.to_thread(download)


async def delete_object(storage_key: str) -> None:
    await asyncio.to_thread(
        _client().remove_object,
        get_settings().minio_bucket,
        storage_key,
    )

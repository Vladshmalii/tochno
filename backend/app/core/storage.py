"""Сховище файлів: локальний диск (за замовчуванням) або S3-сумісне (MinIO/AWS) через STORAGE_BACKEND=s3."""

import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from ..config import get_settings


class Storage(Protocol):
    def save(self, tenant_id: int, ext: str, data: bytes) -> str: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def save(self, tenant_id: int, ext: str, data: bytes) -> str:
        d = self.root / str(tenant_id)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{uuid.uuid4().hex}{ext}"
        path.write_bytes(data)
        return str(path)

    def read(self, key: str) -> bytes:
        return Path(key).read_bytes()

    def delete(self, key: str) -> None:
        Path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return Path(key).exists()


class S3Storage:
    def __init__(self) -> None:
        import boto3  # опційна залежність: pip install boto3

        s = get_settings()
        self.bucket = s.s3_bucket
        self.client = boto3.client("s3", endpoint_url=s.s3_endpoint or None, region_name=s.s3_region or None,
                                   aws_access_key_id=s.s3_access_key or None, aws_secret_access_key=s.s3_secret_key or None)

    def save(self, tenant_id: int, ext: str, data: bytes) -> str:
        key = f"{tenant_id}/{uuid.uuid4().hex}{ext}"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return key

    def read(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001
            return False


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    s = get_settings()
    return S3Storage() if s.storage_backend == "s3" else LocalStorage(s.storage_dir)

#!/usr/bin/env python3
"""
memShare Storage Backend Abstraction

Provides a unified interface for different storage backends:
- LocalStorage: File system storage
- COSStorage: Tencent Cloud COS
- S3Storage: AWS S3 / S3-compatible

Usage:
    backend = create_backend()  # Auto-detect from env
    backend.push("path/to/local", "remote/prefix")
    backend.pull("remote/prefix", "path/to/local")
"""

import os
import sys
import shutil
import hashlib
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("memshare.storage")


class StorageBackend(ABC):
    """Abstract storage backend interface."""

    @staticmethod
    def _md5(filepath: Path) -> str:
        """Calculate MD5 hash of a file."""
        h = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @abstractmethod
    def push(self, local_dir: str, remote_prefix: str, exclude: list = None) -> dict:
        """
        Push local files to remote storage.

        Args:
            local_dir: Local directory path
            remote_prefix: Remote path prefix
            exclude: List of glob patterns to exclude

        Returns:
            dict with keys: uploaded (int), skipped (int), errors (list)
        """
        pass

    @abstractmethod
    def pull(self, remote_prefix: str, local_dir: str, exclude: list = None) -> dict:
        """
        Pull remote files to local storage.

        Args:
            remote_prefix: Remote path prefix
            local_dir: Local directory path
            exclude: List of glob patterns to exclude

        Returns:
            dict with keys: downloaded (int), skipped (int), errors (list)
        """
        pass

    @abstractmethod
    def list_files(self, remote_prefix: str) -> list:
        """List files under a remote prefix."""
        pass

    @abstractmethod
    def delete(self, remote_path: str) -> bool:
        """Delete a remote file."""
        pass


class LocalStorage(StorageBackend):
    """
    Local file system storage backend.
    Used for single-device setups or when no cloud sync is needed.
    The 'remote' is just another local directory.
    """

    def __init__(self, base_dir: str = None):
        self.base_dir = Path(base_dir or os.path.expanduser("~/memshare-data"))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"LocalStorage initialized: {self.base_dir}")

    def push(self, local_dir: str, remote_prefix: str, exclude: list = None) -> dict:
        result = {"uploaded": 0, "skipped": 0, "errors": []}
        local_path = Path(local_dir)
        remote_path = self.base_dir / remote_prefix

        if not local_path.exists():
            result["errors"].append(f"Local directory not found: {local_dir}")
            return result

        for file in local_path.rglob("*"):
            if file.is_dir():
                continue
            if exclude and any(file.match(pat) for pat in exclude):
                result["skipped"] += 1
                continue

            rel = file.relative_to(local_path)
            dest = remote_path / rel
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Skip if content is identical
            if dest.exists() and self._md5(file) == self._md5(dest):
                result["skipped"] += 1
                continue

            try:
                shutil.copy2(file, dest)
                result["uploaded"] += 1
            except Exception as e:
                result["errors"].append(f"{file}: {e}")

        return result

    def pull(self, remote_prefix: str, local_dir: str, exclude: list = None) -> dict:
        result = {"downloaded": 0, "skipped": 0, "errors": []}
        remote_path = self.base_dir / remote_prefix
        local_path = Path(local_dir)

        if not remote_path.exists():
            result["errors"].append(f"Remote prefix not found: {remote_prefix}")
            return result

        for file in remote_path.rglob("*"):
            if file.is_dir():
                continue
            if exclude and any(file.match(pat) for pat in exclude):
                result["skipped"] += 1
                continue

            rel = file.relative_to(remote_path)
            dest = local_path / rel
            dest.parent.mkdir(parents=True, exist_ok=True)

            if dest.exists() and self._md5(file) == self._md5(dest):
                result["skipped"] += 1
                continue

            try:
                shutil.copy2(file, dest)
                result["downloaded"] += 1
            except Exception as e:
                result["errors"].append(f"{file}: {e}")

        return result

    def list_files(self, remote_prefix: str) -> list:
        remote_path = self.base_dir / remote_prefix
        if not remote_path.exists():
            return []
        return [str(f.relative_to(remote_path)) for f in remote_path.rglob("*") if f.is_file()]

    def delete(self, remote_path: str) -> bool:
        target = self.base_dir / remote_path
        if target.exists():
            target.unlink()
            return True
        return False


class COSStorage(StorageBackend):
    """
    Tencent Cloud COS storage backend.
    Requires: pip install cos-python-sdk-v5
    """

    def __init__(self, secret_id: str = None, secret_key: str = None,
                 bucket: str = None, region: str = None):
        try:
            from qcloud_cos import CosConfig, CosS3Client
        except ImportError:
            raise ImportError(
                "cos-python-sdk-v5 is required for COS backend.\n"
                "Install it: pip install cos-python-sdk-v5"
            )

        self.secret_id = secret_id or os.environ.get("COS_SECRET_ID", "")
        self.secret_key = secret_key or os.environ.get("COS_SECRET_KEY", "")
        self.bucket = bucket or os.environ.get("COS_BUCKET", "")
        self.region = region or os.environ.get("COS_REGION", "ap-guangzhou")

        if not all([self.secret_id, self.secret_key, self.bucket]):
            raise ValueError(
                "COS credentials required. Set COS_SECRET_ID, COS_SECRET_KEY, "
                "COS_BUCKET in environment or .env file."
            )

        config = CosConfig(
            Region=self.region,
            SecretId=self.secret_id,
            SecretKey=self.secret_key,
        )
        self.client = CosS3Client(config)
        logger.info(f"COSStorage initialized: {self.bucket} @ {self.region}")

    def push(self, local_dir: str, remote_prefix: str, exclude: list = None) -> dict:
        result = {"uploaded": 0, "skipped": 0, "errors": []}
        local_path = Path(local_dir)

        if not local_path.exists():
            result["errors"].append(f"Local directory not found: {local_dir}")
            return result

        for file in local_path.rglob("*"):
            if file.is_dir():
                continue
            if exclude and any(file.match(pat) for pat in exclude):
                result["skipped"] += 1
                continue

            rel = file.relative_to(local_path)
            key = f"{remote_prefix}/{rel}" if remote_prefix else str(rel)

            try:
                # Check if remote file exists and has same md5
                try:
                    resp = self.client.head_object(Bucket=self.bucket, Key=key)
                    remote_etag = resp.get("ETag", "").strip('"')
                    local_md5 = self._md5(file)
                    if remote_etag == local_md5:
                        result["skipped"] += 1
                        continue
                except Exception:
                    pass  # File doesn't exist remotely, upload it

                self.client.upload_file(
                    Bucket=self.bucket,
                    Key=key,
                    LocalFilePath=str(file),
                )
                result["uploaded"] += 1
            except Exception as e:
                result["errors"].append(f"{file}: {e}")

        return result

    def pull(self, remote_prefix: str, local_dir: str, exclude: list = None) -> dict:
        result = {"downloaded": 0, "skipped": 0, "errors": []}
        local_path = Path(local_dir)

        files = self.list_files(remote_prefix)
        for rel_path in files:
            if exclude and any(Path(rel_path).match(pat) for pat in exclude):
                result["skipped"] += 1
                continue

            key = f"{remote_prefix}/{rel_path}" if remote_prefix else rel_path
            dest = local_path / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)

            try:
                self.client.download_file(
                    Bucket=self.bucket,
                    Key=key,
                    DestFilePath=str(dest),
                )
                result["downloaded"] += 1
            except Exception as e:
                result["errors"].append(f"{key}: {e}")

        return result

    def list_files(self, remote_prefix: str) -> list:
        files = []
        marker = ""
        while True:
            resp = self.client.list_objects(
                Bucket=self.bucket,
                Prefix=remote_prefix,
                Marker=marker,
                MaxKeys=1000,
            )
            contents = resp.get("Contents", [])
            for item in contents:
                key = item["Key"]
                if key.endswith("/"):
                    continue
                rel = key[len(remote_prefix):].lstrip("/") if remote_prefix else key
                if rel:
                    files.append(rel)

            if resp.get("IsTruncated") == "true":
                marker = resp.get("NextMarker", contents[-1]["Key"])
            else:
                break
        return files

    def delete(self, remote_path: str) -> bool:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=remote_path)
            return True
        except Exception:
            return False


class S3Storage(StorageBackend):
    """
    AWS S3 / S3-compatible storage backend.
    Requires: pip install boto3
    """

    def __init__(self, access_key: str = None, secret_key: str = None,
                 bucket: str = None, region: str = None, endpoint_url: str = None):
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for S3 backend.\n"
                "Install it: pip install boto3"
            )

        self.access_key = access_key or os.environ.get("AWS_ACCESS_KEY_ID", "")
        self.secret_key = secret_key or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        self.bucket = bucket or os.environ.get("S3_BUCKET", "")
        self.region = region or os.environ.get("S3_REGION", "us-east-1")
        self.endpoint_url = endpoint_url or os.environ.get("S3_ENDPOINT_URL")

        if not all([self.access_key, self.secret_key, self.bucket]):
            raise ValueError(
                "S3 credentials required. Set AWS_ACCESS_KEY_ID, "
                "AWS_SECRET_ACCESS_KEY, S3_BUCKET in environment or .env file."
            )

        kwargs = {
            "aws_access_key_id": self.access_key,
            "aws_secret_access_key": self.secret_key,
            "region_name": self.region,
        }
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url

        self.s3 = boto3.client("s3", **kwargs)
        logger.info(f"S3Storage initialized: {self.bucket} @ {self.region}")

    def push(self, local_dir: str, remote_prefix: str, exclude: list = None) -> dict:
        result = {"uploaded": 0, "skipped": 0, "errors": []}
        local_path = Path(local_dir)

        if not local_path.exists():
            result["errors"].append(f"Local directory not found: {local_dir}")
            return result

        for file in local_path.rglob("*"):
            if file.is_dir():
                continue
            if exclude and any(file.match(pat) for pat in exclude):
                result["skipped"] += 1
                continue

            rel = file.relative_to(local_path)
            key = f"{remote_prefix}/{rel}" if remote_prefix else str(rel)

            try:
                # Check ETag for skip
                try:
                    resp = self.s3.head_object(Bucket=self.bucket, Key=key)
                    remote_etag = resp.get("ETag", "").strip('"')
                    local_md5 = self._md5(file)
                    if remote_etag == local_md5:
                        result["skipped"] += 1
                        continue
                except Exception:
                    pass

                self.s3.upload_file(str(file), self.bucket, key)
                result["uploaded"] += 1
            except Exception as e:
                result["errors"].append(f"{file}: {e}")

        return result

    def pull(self, remote_prefix: str, local_dir: str, exclude: list = None) -> dict:
        result = {"downloaded": 0, "skipped": 0, "errors": []}
        local_path = Path(local_dir)

        files = self.list_files(remote_prefix)
        for rel_path in files:
            if exclude and any(Path(rel_path).match(pat) for pat in exclude):
                result["skipped"] += 1
                continue

            key = f"{remote_prefix}/{rel_path}" if remote_prefix else rel_path
            dest = local_path / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)

            try:
                self.s3.download_file(self.bucket, key, str(dest))
                result["downloaded"] += 1
            except Exception as e:
                result["errors"].append(f"{key}: {e}")

        return result

    def list_files(self, remote_prefix: str) -> list:
        files = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=remote_prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                rel = key[len(remote_prefix):].lstrip("/") if remote_prefix else key
                if rel:
                    files.append(rel)
        return files

    def delete(self, remote_path: str) -> bool:
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=remote_path)
            return True
        except Exception:
            return False


def create_backend(backend_type: str = None, **kwargs) -> StorageBackend:
    """
    Factory function to create a storage backend.

    Args:
        backend_type: "local", "cos", or "s3". Auto-detected from
                      MEMSHARE_STORAGE env var if not specified.
        **kwargs: Backend-specific configuration

    Returns:
        StorageBackend instance
    """
    # Load .env if python-dotenv is available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    backend_type = backend_type or os.environ.get("MEMSHARE_STORAGE", "local")
    backend_type = backend_type.lower().strip()

    if backend_type == "local":
        return LocalStorage(**kwargs)
    elif backend_type == "cos":
        return COSStorage(**kwargs)
    elif backend_type == "s3":
        return S3Storage(**kwargs)
    else:
        raise ValueError(
            f"Unknown storage backend: {backend_type}. "
            f"Supported: local, cos, s3"
        )


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    backend = create_backend()
    print(f"Backend type: {type(backend).__name__}")
    print("Storage backend initialized successfully!")

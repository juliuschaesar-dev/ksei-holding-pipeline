"""Thin S3 (SeaweedFS) wrapper. Bronze raw objects are write-once."""

import hashlib
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ksei.config import Settings


class ImmutableObjectError(Exception):
    """Attempt to overwrite a bronze raw object."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def s3_client(endpoint_url: str, access_key: str, secret_key: str) -> Any:
    """The one way this project talks to S3 (SeaweedFS): path-style addressing, fixed region."""
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )


def ensure_buckets(settings: Settings) -> None:
    """Create the lake and Airflow-log buckets if they do not exist yet. Safe to run repeatedly."""
    client = s3_client(settings.s3_endpoint_url, settings.s3_access_key, settings.s3_secret_key)
    for name in (settings.s3_bucket, settings.s3_logs_bucket):
        try:
            client.create_bucket(Bucket=name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {
                "BucketAlreadyOwnedByYou",
                "BucketAlreadyExists",
            }:
                raise


class Storage:
    def __init__(self, client: Any, bucket: str) -> None:
        self._s3 = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> Storage:
        client = s3_client(settings.s3_endpoint_url, settings.s3_access_key, settings.s3_secret_key)
        return cls(client, settings.s3_bucket)

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    def put(self, key: str, data: bytes) -> None:
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data)

    def put_raw(self, key: str, data: bytes, metadata: dict[str, str]) -> None:
        if self.exists(key):
            raise ImmutableObjectError(f"bronze raw object already exists: {key}")
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, Metadata=metadata)

    def get(self, key: str) -> bytes:
        return self._s3.get_object(Bucket=self._bucket, Key=key)["Body"].read()

    def metadata(self, key: str) -> dict[str, str]:
        return self._s3.head_object(Bucket=self._bucket, Key=key)["Metadata"]

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        for page in self._s3.get_paginator("list_objects_v2").paginate(
            Bucket=self._bucket, Prefix=prefix
        ):
            keys += [obj["Key"] for obj in page.get("Contents", [])]
        return keys

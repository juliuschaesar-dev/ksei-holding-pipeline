"""Create the S3 buckets used by the stack. Idempotent; run by airflow-init."""

from ksei.config import Settings
from ksei.storage import ensure_buckets

if __name__ == "__main__":
    ensure_buckets(Settings.from_env())

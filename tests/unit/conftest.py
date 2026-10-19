"""Fixtures shared by the unit tests."""

import boto3
import pytest
from moto import mock_aws

from ksei.storage import Storage
from ksei.warehouse import ClickHouse
from tests.unit.support import CLICKHOUSE_URL

BUCKET = "lake"


@pytest.fixture
def storage():
    """Storage over a moto S3 with the one bucket."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        yield Storage(s3, BUCKET)


@pytest.fixture
def ch() -> ClickHouse:
    return ClickHouse(CLICKHOUSE_URL, "pipeline", "pw")

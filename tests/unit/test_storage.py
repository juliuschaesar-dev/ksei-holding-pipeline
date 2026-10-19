import pytest
from moto import mock_aws

from ksei.config import Settings
from ksei.storage import ImmutableObjectError, Storage, ensure_buckets, s3_client, sha256_hex
from tests.unit.test_config import ENV

pytestmark = pytest.mark.unit

BUCKET = "lake"


def test_sha256_hex_matches_known_digest() -> None:
    assert sha256_hex(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_put_raw_then_get_roundtrips_bytes_and_metadata(storage: Storage) -> None:
    storage.put_raw("bronze/x/raw/a.zip", b"data", {"sha256": "abc", "source-url": "http://u"})

    assert storage.get("bronze/x/raw/a.zip") == b"data"
    assert storage.metadata("bronze/x/raw/a.zip") == {"sha256": "abc", "source-url": "http://u"}


def test_put_raw_refuses_to_overwrite_an_existing_key(storage: Storage) -> None:
    storage.put_raw("bronze/x/raw/a.zip", b"first", {})

    with pytest.raises(ImmutableObjectError, match=r"bronze/x/raw/a\.zip"):
        storage.put_raw("bronze/x/raw/a.zip", b"second", {})

    assert storage.get("bronze/x/raw/a.zip") == b"first"


def test_put_overwrites_so_parsed_output_can_be_rebuilt(storage: Storage) -> None:
    storage.put("bronze/x/parsed/data.parquet", b"v1")
    storage.put("bronze/x/parsed/data.parquet", b"v2")

    assert storage.get("bronze/x/parsed/data.parquet") == b"v2"


def test_exists_reports_presence(storage: Storage) -> None:
    assert not storage.exists("missing")
    storage.put("present", b"1")
    assert storage.exists("present")


def test_list_keys_returns_only_keys_under_the_prefix(storage: Storage) -> None:
    storage.put("bronze/a/raw/1.zip", b"1")
    storage.put("bronze/a/raw/2.zip", b"2")
    storage.put("bronze/b/raw/3.zip", b"3")

    assert storage.list_keys("bronze/a/") == ["bronze/a/raw/1.zip", "bronze/a/raw/2.zip"]


def test_s3_client_uses_the_given_endpoint_with_path_style_addressing() -> None:
    client = s3_client("http://s3.local:8333", "access", "secret")

    assert client.meta.endpoint_url == "http://s3.local:8333"
    assert client.meta.config.s3["addressing_style"] == "path"


def test_ensure_buckets_creates_the_lake_and_log_buckets_and_can_run_twice() -> None:
    # moto only intercepts AWS addresses, so the endpoint is an AWS one in this test
    settings = Settings.from_env({**ENV, "S3_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com"})
    with mock_aws():
        ensure_buckets(settings)
        ensure_buckets(settings)  # idempotent: the second run must not fail

        client = s3_client(settings.s3_endpoint_url, "k", "s")
        names = {b["Name"] for b in client.list_buckets()["Buckets"]}

    assert names == {"lake", "logs"}

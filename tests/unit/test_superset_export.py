from pathlib import Path

import pytest
from superset import export_assets

pytestmark = pytest.mark.unit


def test_a_database_export_keeps_no_user_or_host_in_the_connection_uri() -> None:
    exported = (
        b"database_name: KSEI ClickHouse\n"
        b"sqlalchemy_uri: clickhousedb://someuser:XXXXXXXXXX@somehost:8123/gold\n"
        b"expose_in_sqllab: true\n"
    )

    result = export_assets._portable(Path("databases/KSEI_ClickHouse.yaml"), exported).decode()

    assert "someuser" not in result and "somehost" not in result
    assert "sqlalchemy_uri: clickhousedb://" in result  # still a URI the importer can parse
    assert "expose_in_sqllab: true" in result  # the rest is untouched


def test_a_chart_export_still_drops_the_instance_specific_query_context() -> None:
    exported = b'slice_name: Q1\nquery_context: \'{"datasource": {"id": 5}}\'\nviz_type: table\n'

    result = export_assets._portable(Path("charts/Q1_1.yaml"), exported).decode()

    assert "query_context: null" in result and '"id": 5' not in result
    assert "viz_type: table" in result

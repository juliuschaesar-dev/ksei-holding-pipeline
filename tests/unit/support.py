"""What several unit-test files share: the ClickHouse address and the SQL a stub received."""

import respx

CLICKHOUSE_URL = "http://ch.local:8123"  # the address ENV in test_config points at


def sent_sql(route: respx.Route) -> list[str]:
    """The statements a mocked ClickHouse route received, in order."""
    return [call.request.content.decode() for call in route.calls]

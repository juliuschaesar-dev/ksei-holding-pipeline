"""The provisioned dashboard: imported on startup, built on gold only, every chart returns rows.

Needs the full profile (`make up PROFILE=full`). The chart queries need gold data (a DAG run or
`make dbt-build`): on a fresh stack, such as CI, there are no gold tables and that test is skipped.
"""

import json

import httpx
import pytest

from tests.smoke.conftest import CLICKHOUSE_URL, SUPERSET_URL, compose_ps

pytestmark = pytest.mark.smoke

SLUG = "ksei-ownership"
DATABASE_NAME = "KSEI ClickHouse"
# The cards, the three dashboard questions (see docs/dashboard-questions.md) and the data freshness.
EXPECTED_CHARTS = {
    "Latest period",
    "Foreign share of value",
    "Total value held",
    "Change since peak",
    "Largest holder group",
    "Q1 Foreign share of ownership over time",
    "Local vs foreign split",
    "Q2 Ownership by investor type",
    "Q3 Biggest moves in foreign share",
}
EXPECTED_FILTERS = {"Date range", "Security type"}


@pytest.fixture(scope="module")
def api(env: dict[str, str]) -> httpx.Client:
    if compose_ps().get("superset", {}).get("State") != "running":
        pytest.skip("superset runs only under `make up PROFILE=full`")
    client = httpx.Client(base_url=SUPERSET_URL, timeout=120)
    token = client.post(
        "/api/v1/security/login",
        json={
            "username": env["SUPERSET_ADMIN_USER"],
            "password": env["SUPERSET_ADMIN_PASSWORD"],
            "provider": "db",
            "refresh": True,
        },
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def test_dashboard_is_imported_and_published(api: httpx.Client) -> None:
    response = api.get(f"/api/v1/dashboard/{SLUG}")

    assert response.status_code == 200
    assert response.json()["result"]["published"] is True


def test_every_dataset_is_a_gold_table_on_the_clickhouse_connection(api: httpx.Client) -> None:
    datasets = api.get("/api/v1/dataset/", params={"q": "(page_size:100)"}).json()["result"]

    assert datasets, "no datasets were imported"
    assert {d["schema"] for d in datasets} == {"gold"}
    assert {d["database"]["database_name"] for d in datasets} == {DATABASE_NAME}


def test_the_dashboard_has_the_cards_the_three_questions_and_freshness(
    api: httpx.Client,
) -> None:
    charts = api.get(f"/api/v1/dashboard/{SLUG}/charts").json()["result"]

    assert {c["slice_name"] for c in charts} == EXPECTED_CHARTS


def test_the_dashboard_keeps_its_native_filters(api: httpx.Client) -> None:
    result = api.get(f"/api/v1/dashboard/{SLUG}").json()["result"]
    filters = json.loads(result["json_metadata"])["native_filter_configuration"]

    assert {f["name"] for f in filters} == EXPECTED_FILTERS


def test_no_chart_writes_a_value_with_an_si_prefix(api: httpx.Client) -> None:
    """An SI format shows 8,009 trillion rupiah as 8.0P; the dashboard counts in T (trillion)."""
    charts = api.get(f"/api/v1/dashboard/{SLUG}/charts").json()["result"]
    si_formats = []
    for chart in charts:
        params = json.loads(api.get(f"/api/v1/chart/{chart['id']}").json()["result"]["params"])
        si_formats += [
            (chart["slice_name"], key, params[key])
            for key in ("y_axis_format", "number_format")
            if key in params and params[key].endswith("s")
        ]
        si_formats += [
            (chart["slice_name"], name, column["d3NumberFormat"])
            for name, column in params.get("column_config", {}).items()
            if column.get("d3NumberFormat", "").endswith("s")
        ]

    assert not si_formats


def chart_params(api: httpx.Client, name: str) -> tuple[str, dict]:
    charts = api.get(f"/api/v1/dashboard/{SLUG}/charts").json()["result"]
    chart = next(c for c in charts if c["slice_name"] == name)
    detail = api.get(f"/api/v1/chart/{chart['id']}").json()["result"]
    return detail["viz_type"], json.loads(detail["params"])


def test_the_text_cards_are_not_plain_tables(api: httpx.Client) -> None:
    for name in ("Latest period", "Largest holder group"):
        viz_type, _ = chart_params(api, name)

        assert viz_type != "table", name


def test_the_policy_lets_handlebars_charts_run_and_is_otherwise_unchanged() -> None:
    """A Handlebars chart compiles its template in the browser, which needs `unsafe-eval`."""
    policy = httpx.get(f"{SUPERSET_URL}/login/", timeout=30).headers["content-security-policy"]
    directives = {d.split()[0]: d.split()[1:] for d in policy.split(";") if d.strip()}

    assert "'unsafe-eval'" in directives["script-src"]
    assert "'strict-dynamic'" in directives["script-src"]  # still the nonce-based script policy
    assert directives["default-src"] == ["'self'"]
    assert directives["object-src"] == ["'none'"]


def test_largest_holder_group_is_a_card_with_the_name_the_value_and_the_foreign_share(
    api: httpx.Client,
) -> None:
    viz_type, params = chart_params(api, "Largest holder group")

    assert viz_type == "handlebars"
    for field in ("holder_group", "held", "foreign_pct"):
        assert "{{" + field + "}}" in params["handlebarsTemplate"]


def test_the_charts_of_one_period_filter_on_the_flag_not_on_a_copied_subquery(
    api: httpx.Client,
) -> None:
    """is_latest_period is the one home of "the newest period"; no chart works it out for itself."""
    charts = api.get(f"/api/v1/dashboard/{SLUG}/charts").json()["result"]
    copies = []
    for chart in charts:
        params = json.loads(api.get(f"/api/v1/chart/{chart['id']}").json()["result"]["params"])
        copies += [
            chart["slice_name"]
            for adhoc in params.get("adhoc_filters", [])
            if "max(period)" in (adhoc.get("sqlExpression") or "")
        ]

    assert not copies


def test_the_investor_type_names_are_not_written_out_in_superset(api: httpx.Client) -> None:
    """The names are the investor_types var of dbt (a gold column), not a CASE in a dataset."""
    datasets = api.get("/api/v1/dataset/", params={"q": "(page_size:100)"}).json()["result"]
    ids = [d["id"] for d in datasets]
    calculated = []
    for dataset_id in ids:
        columns = api.get(f"/api/v1/dataset/{dataset_id}").json()["result"]["columns"]
        calculated += [c["column_name"] for c in columns if c.get("expression")]

    assert not calculated


def test_change_since_peak_is_red_below_zero_and_green_from_zero(api: httpx.Client) -> None:
    _, params = chart_params(api, "Change since peak")

    rules = {
        (r["operator"], r["targetValue"]): r["colorScheme"]
        for r in params["conditional_formatting"]
    }
    assert set(rules) == {("<", 0), (">=", 0)}
    assert rules[("<", 0)] != rules[(">=", 0)]


def chart_query(params: dict) -> dict:
    """The query a chart sends to its dataset, rebuilt from the chart's saved form data."""
    columns = [
        c for c in [params.get("x_axis"), params.get("series"), *params.get("groupby", [])] if c
    ]
    where = [f["sqlExpression"] for f in params.get("adhoc_filters", []) if f.get("sqlExpression")]
    return {
        "columns": columns,
        # a big number and a pie chart have one `metric`; the other charts have a list
        "metrics": params.get("metrics") or [m for m in [params.get("metric")] if m],
        "filters": [],
        "extras": {"where": " AND ".join(f"({w})" for w in where), "having": ""},
        "row_limit": params.get("row_limit", 1000),
    }


def test_every_chart_query_returns_rows(api: httpx.Client, env: dict[str, str]) -> None:
    tables = httpx.post(
        CLICKHOUSE_URL,
        auth=(env["CLICKHOUSE_PIPELINE_USER"], env["CLICKHOUSE_PIPELINE_PASSWORD"]),
        content="SELECT count() FROM system.tables WHERE database = 'gold'",
        timeout=30,
    ).text.strip()
    if tables == "0":
        pytest.skip("no gold tables yet: run the DAG or `make dbt-build` first")

    charts = api.get(f"/api/v1/dashboard/{SLUG}/charts").json()["result"]

    for chart in charts:
        detail = api.get(f"/api/v1/chart/{chart['id']}").json()["result"]
        body = {
            "datasource": {"id": detail["datasource_id"], "type": detail["datasource_type"]},
            "queries": [chart_query(json.loads(detail["params"]))],
            "result_format": "json",
            "result_type": "full",
        }
        response = api.post("/api/v1/chart/data", json=body)
        assert response.status_code == 200, (chart["slice_name"], response.text[:300])
        assert response.json()["result"][0]["rowcount"] > 0, chart["slice_name"]

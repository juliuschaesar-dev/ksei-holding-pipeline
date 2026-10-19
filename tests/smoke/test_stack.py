import httpx
import pytest

from ksei.storage import s3_client
from tests.smoke.conftest import (
    AIRFLOW_URL,
    CLICKHOUSE_URL,
    CORE_SERVICES,
    S3_URL,
    SUPERSET_URL,
    compose_ps,
    wait_until,
)

pytestmark = pytest.mark.smoke

HELLO_DAG = "hello_world"


def test_every_core_service_is_healthy() -> None:
    def all_healthy() -> dict[str, str] | None:
        rows = compose_ps()
        states = {s: rows.get(s, {}).get("Health", "missing") for s in CORE_SERVICES}
        return states if all(v == "healthy" for v in states.values()) else None

    wait_until(all_healthy, timeout=300)


def test_airflow_init_exits_successfully() -> None:
    row = compose_ps()["airflow-init"]
    assert row["State"] == "exited"
    assert row["ExitCode"] == 0


def test_period_init_exits_successfully() -> None:
    row = compose_ps()["period-init"]
    assert row["State"] == "exited"
    assert row["ExitCode"] == 0


def test_airflow_api_server_reports_healthy() -> None:
    response = httpx.get(f"{AIRFLOW_URL}/api/v2/monitor/health", timeout=10)
    assert response.status_code == 200
    assert response.json()["metadatabase"]["status"] == "healthy"


def airflow_headers(env: dict[str, str]) -> dict[str, str]:
    token = httpx.post(
        f"{AIRFLOW_URL}/auth/token",
        json={"username": env["AIRFLOW_ADMIN_USER"], "password": env["AIRFLOW_ADMIN_PASSWORD"]},
        timeout=10,
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_ksei_http_pool_has_a_single_slot(env: dict[str, str]) -> None:
    response = httpx.get(
        f"{AIRFLOW_URL}/api/v2/pools/ksei_http", headers=airflow_headers(env), timeout=10
    )
    assert response.status_code == 200
    assert response.json()["slots"] == 1


def test_ksei_monthly_dag_is_registered_without_import_errors(env: dict[str, str]) -> None:
    headers = airflow_headers(env)

    def parsed() -> bool | None:
        r = httpx.get(f"{AIRFLOW_URL}/api/v2/dags/ksei_monthly", headers=headers, timeout=10)
        return True if r.status_code == 200 else None

    wait_until(parsed, timeout=120)
    errors = httpx.get(f"{AIRFLOW_URL}/api/v2/importErrors", headers=headers, timeout=10).json()
    assert errors["total_entries"] == 0


def test_hello_world_dag_completes_on_celery_worker(env: dict[str, str]) -> None:
    token = httpx.post(
        f"{AIRFLOW_URL}/auth/token",
        json={"username": env["AIRFLOW_ADMIN_USER"], "password": env["AIRFLOW_ADMIN_PASSWORD"]},
        timeout=10,
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    def dag_is_parsed() -> bool | None:
        r = httpx.patch(
            f"{AIRFLOW_URL}/api/v2/dags/{HELLO_DAG}",
            json={"is_paused": False},
            headers=headers,
            timeout=10,
        )
        return True if r.status_code == 200 else None

    wait_until(dag_is_parsed, timeout=120)

    run = httpx.post(
        f"{AIRFLOW_URL}/api/v2/dags/{HELLO_DAG}/dagRuns",
        json={"logical_date": None},
        headers=headers,
        timeout=10,
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["dag_run_id"]

    def finished() -> str | None:
        state = httpx.get(
            f"{AIRFLOW_URL}/api/v2/dags/{HELLO_DAG}/dagRuns/{run_id}",
            headers=headers,
            timeout=10,
        ).json()["state"]
        return state if state in {"success", "failed"} else None

    assert wait_until(finished, timeout=180) == "success"


def test_clickhouse_accepts_query_and_has_medallion_databases(env: dict[str, str]) -> None:
    response = httpx.post(
        CLICKHOUSE_URL,
        content="SELECT name FROM system.databases ORDER BY name FORMAT JSONCompact",
        auth=(env["CLICKHOUSE_PIPELINE_USER"], env["CLICKHOUSE_PIPELINE_PASSWORD"]),
        timeout=10,
    )
    assert response.status_code == 200, response.text
    names = {row[0] for row in response.json()["data"]}
    assert {"bronze", "silver", "gold"} <= names


def test_seaweedfs_s3_has_buckets_and_roundtrips_an_object(env: dict[str, str]) -> None:
    s3 = s3_client(S3_URL, env["S3_ACCESS_KEY"], env["S3_SECRET_KEY"])
    buckets = {b["Name"] for b in s3.list_buckets()["Buckets"]}
    assert {env["S3_BUCKET"], env["S3_LOGS_BUCKET"]} <= buckets

    key = "smoke/ping.txt"
    s3.put_object(Bucket=env["S3_BUCKET"], Key=key, Body=b"pong")
    assert s3.get_object(Bucket=env["S3_BUCKET"], Key=key)["Body"].read() == b"pong"
    s3.delete_object(Bucket=env["S3_BUCKET"], Key=key)


def test_superset_login_page_responds() -> None:
    if compose_ps().get("superset", {}).get("State") != "running":
        pytest.skip("superset runs only under `make up PROFILE=full`")
    assert httpx.get(f"{SUPERSET_URL}/login/", timeout=10).status_code == 200

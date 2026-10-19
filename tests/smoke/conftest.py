"""Shared helpers for smoke tests: read .env, wait for conditions, query Compose."""

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

AIRFLOW_URL = "http://localhost:8080"
CLICKHOUSE_URL = "http://localhost:8123"
S3_URL = "http://localhost:8333"
SUPERSET_URL = "http://localhost:8088"

CORE_SERVICES = (
    "postgres",
    "redis",
    "seaweedfs",
    "clickhouse",
    "airflow-apiserver",
    "airflow-scheduler",
    "airflow-dag-processor",
    "airflow-worker",
    "airflow-triggerer",
)


def read_env_file() -> dict[str, str]:
    env_file = ROOT / ".env"
    if not env_file.exists():
        pytest.fail(".env not found; run `cp .env.example .env` and fill in values")
    values: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


@pytest.fixture(scope="session")
def env() -> dict[str, str]:
    return read_env_file()


def compose_ps() -> dict[str, dict[str, str]]:
    """Map service name to its `docker compose ps -a` row (all profiles)."""
    out = subprocess.run(
        ["docker", "compose", "--profile", "full", "ps", "-a", "--format", "json"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
    return {row["Service"]: row for row in rows}


def wait_until[T](probe: Callable[[], T | None], timeout: float, interval: float = 3.0) -> T:
    """Call `probe` until it returns a non-None value; fail the test on timeout."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = probe()
            if result is not None:
                return result
        except Exception as exc:
            last_error = exc
        time.sleep(interval)
    pytest.fail(f"condition not met within {timeout}s (last error: {last_error!r})")

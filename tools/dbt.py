"""Run dbt the one way this project does: in the Airflow image's own virtualenv.

`make dbt-build`, `make dbt-test` and the integration tests all go through here, so the command
lives in one place. ./dbt is mounted, so edits apply without rebuilding the image.

    uv run python tools/dbt.py build --exclude "test_type:unit"
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = "/opt/airflow/dbt"


def command(dbt_args: list[str]) -> list[str]:
    return [
        "docker",
        "compose",
        "run",
        "--rm",
        "--no-deps",
        "-v",
        f"{ROOT / 'dbt'}:{PROJECT_DIR}",
        "--entrypoint",
        "/opt/dbt-venv/bin/dbt",
        "airflow-worker",
        *dbt_args,
        "--project-dir",
        PROJECT_DIR,
        "--profiles-dir",
        PROJECT_DIR,
    ]


def run(dbt_args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command(dbt_args), cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S603


if __name__ == "__main__":
    sys.exit(subprocess.run(command(sys.argv[1:]), cwd=ROOT, check=False).returncode)  # noqa: S603

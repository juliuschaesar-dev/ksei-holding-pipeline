from pathlib import Path

import pytest
from tools.dbt import ROOT, command

pytestmark = pytest.mark.unit


def test_the_command_runs_dbt_in_the_airflow_image_with_the_working_tree_mounted() -> None:
    argv = command(["build"])

    assert argv[:5] == ["docker", "compose", "run", "--rm", "--no-deps"]
    assert f"{ROOT / 'dbt'}:/opt/airflow/dbt" in argv
    assert argv[argv.index("--entrypoint") + 1] == "/opt/dbt-venv/bin/dbt"
    assert "airflow-worker" in argv


def test_the_dbt_arguments_come_before_the_project_and_profile_directories() -> None:
    argv = command(["build", "--exclude", "test_type:unit"])

    tail = argv[argv.index("airflow-worker") + 1 :]
    assert tail == [
        "build",
        "--exclude",
        "test_type:unit",
        "--project-dir",
        "/opt/airflow/dbt",
        "--profiles-dir",
        "/opt/airflow/dbt",
    ]


def test_the_root_is_the_repository_root() -> None:
    assert (Path(ROOT) / "dbt" / "dbt_project.yml").exists()


def test_on_linux_the_container_runs_as_the_owner_of_the_mounted_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tools.dbt.os.getuid", lambda: 1001, raising=False)

    argv = command(["build"])

    assert argv[argv.index("--user") + 1] == "1001:0"
    assert argv.index("--user") < argv.index("airflow-worker")

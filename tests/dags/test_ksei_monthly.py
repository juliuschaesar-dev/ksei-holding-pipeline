"""DAG structure tests; they need Airflow, so `make test-dags` runs them in the Airflow image."""

import itertools
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("airflow.models")

from airflow.models import DagBag

from ksei.config import DATASETS

DAGS = Path(__file__).resolve().parents[2] / "airflow" / "dags"
STEPS = ("detect_new_periods", "download_to_bronze", "parse_to_parquet", "load_bronze")


@pytest.fixture(scope="module")
def bag() -> DagBag:
    return DagBag(dag_folder=str(DAGS), bundle_path=DAGS, bundle_name="test")


@pytest.fixture(scope="module")
def dag(bag: DagBag):
    return bag.dags.get("ksei_monthly")


def test_dag_files_import_without_errors(bag: DagBag) -> None:
    assert bag.import_errors == {}


def test_ksei_monthly_dag_exists(dag) -> None:
    assert dag is not None


def test_one_task_group_per_registry_dataset_with_the_four_steps_plus_dbt_build(dag) -> None:
    expected = {f"{name}.{step}" for name in DATASETS for step in STEPS} | {"dbt_build"}
    assert set(dag.task_ids) == expected


@pytest.mark.parametrize("name", list(DATASETS))
def test_steps_run_in_order_within_a_dataset(dag, name: str) -> None:
    for earlier, later in itertools.pairwise(STEPS):
        task = dag.get_task(f"{name}.{later}")
        assert task.upstream_task_ids == {f"{name}.{earlier}"}


def test_datasets_do_not_depend_on_each_other(dag) -> None:
    for name in DATASETS:
        for step in STEPS:
            task = dag.get_task(f"{name}.{step}")
            assert all(t.startswith(f"{name}.") for t in task.upstream_task_ids)


@pytest.mark.parametrize("name", list(DATASETS))
def test_every_step_that_calls_ksei_uses_the_single_slot_http_pool(dag, name: str) -> None:
    for step in ("detect_new_periods", "download_to_bronze"):
        task = dag.get_task(f"{name}.{step}")
        assert task.pool == "ksei_http"
        assert task.pool_slots == 1


def test_only_ksei_steps_use_the_http_pool(dag) -> None:
    for name in DATASETS:
        for step in ("parse_to_parquet", "load_bronze"):
            assert dag.get_task(f"{name}.{step}").pool != "ksei_http"


def test_every_task_has_retries_and_a_retry_delay(dag) -> None:
    for task in dag.tasks:
        assert task.retries >= 2
        assert task.retry_delay >= timedelta(minutes=1)


def test_schedule_is_monthly_in_jakarta_time(dag) -> None:
    serialized = dag.timetable.serialize()
    fields = serialized["expression"].split()
    assert fields[2] != "*" and fields[3] == "*" and fields[4] == "*"  # day-of-month, any month
    assert int(fields[2]) <= 5  # right after the month-end release
    assert serialized["timezone"] == "Asia/Jakarta"


def test_catchup_is_off_and_one_run_at_a_time(dag) -> None:
    assert dag.catchup is False
    assert dag.max_active_runs == 1


@pytest.mark.parametrize("name", list(DATASETS))
def test_download_and_later_steps_are_mapped_over_periods(dag, name: str) -> None:
    for step in STEPS[1:]:
        assert dag.get_task(f"{name}.{step}").is_mapped


def test_xcom_carries_only_small_values(dag) -> None:
    allowed = {"str", "list[dict[str, str]]", "dict[str, str]"}
    for task in dag.tasks:
        func = getattr(task, "python_callable", None) or task.partial_kwargs["python_callable"]
        annotation = func.__annotations__["return"]
        assert (annotation is str) or str(annotation) in allowed


def test_dbt_build_waits_for_every_dataset_to_be_loaded(dag) -> None:
    upstream = dag.get_task("dbt_build").upstream_task_ids
    assert upstream == {f"{name}.load_bronze" for name in DATASETS}


def test_dbt_build_runs_when_something_loaded_and_nothing_failed(dag) -> None:
    # a dataset with no new period skips its mapped tasks; that must not block dbt
    assert dag.get_task("dbt_build").trigger_rule == "none_failed_min_one_success"


def test_dbt_build_runs_the_real_data_models_without_unit_tests(dag) -> None:
    command = dag.get_task("dbt_build").python_callable()
    assert "/opt/dbt-venv/bin/dbt build" in command
    assert "--exclude" in command and "test_type:unit" in command  # unit tests use seeds

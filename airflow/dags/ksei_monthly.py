"""Monthly KSEI ingestion: one task group per dataset in the DATASETS registry.

Wiring only; the logic lives in `ksei.tasks`. XCom carries small strings (periods, URLs).
"""

from datetime import timedelta
from typing import Any

import pendulum
from airflow.sdk import TaskGroup, dag, task
from airflow.timetables.trigger import CronTriggerTimetable

from ksei import tasks
from ksei.config import DATASETS, Dataset, Settings

HTTP_POOL = "ksei_http"  # 1 slot: never more than one request to KSEI at a time
TIMEZONE = "Asia/Jakarta"


def build_dataset_group(dataset: Dataset) -> Any:
    @task(task_id="detect_new_periods", pool=HTTP_POOL)
    def detect_new_periods() -> list[dict[str, str]]:
        return tasks.run_detect(Settings.from_env(), dataset)

    @task(task_id="download_to_bronze", pool=HTTP_POOL)
    def download_to_bronze(link: dict[str, str]) -> str:
        return tasks.run_download(Settings.from_env(), dataset, link)

    @task(task_id="parse_to_parquet")
    def parse_to_parquet(period: str) -> str:
        return tasks.run_parse(Settings.from_env(), dataset, period)

    @task(task_id="load_bronze")
    def load_period(period: str) -> str:
        return tasks.run_load(Settings.from_env(), dataset, period)

    with TaskGroup(group_id=dataset.name):
        new_links = detect_new_periods()
        downloaded = download_to_bronze.expand(link=new_links)
        parsed = parse_to_parquet.expand(period=downloaded)
        return load_period.expand(period=parsed)


@dag(
    dag_id="ksei_monthly",
    schedule=CronTriggerTimetable("0 6 2 * *", timezone=TIMEZONE),
    start_date=pendulum.datetime(2023, 10, 1, tz=TIMEZONE),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 3, "retry_delay": timedelta(minutes=10)},
    tags=["ksei"],
)
def ksei_monthly() -> None:
    @task.bash(task_id="dbt_build", trigger_rule="none_failed_min_one_success")
    def dbt_build() -> str:
        # real-data models only: the unit tests run on seeds in CI (`make dbt-test`)
        return (
            "/opt/dbt-venv/bin/dbt build --exclude 'test_type:unit' "
            "--project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt"
        )

    loaded = [build_dataset_group(dataset) for dataset in DATASETS.values()]
    loaded >> dbt_build()


ksei_monthly()

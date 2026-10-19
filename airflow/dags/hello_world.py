"""Smoke-test DAG: proves the scheduler, Celery worker and API server are wired together."""

import logging

import pendulum
from airflow.sdk import dag, task

log = logging.getLogger(__name__)


@dag(
    dag_id="hello_world",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="Asia/Jakarta"),
    catchup=False,
    tags=["smoke"],
)
def hello_world() -> None:
    @task(retries=1)
    def say_hello() -> str:
        log.info("hello from a Celery worker")
        return "hello"

    say_hello()


hello_world()

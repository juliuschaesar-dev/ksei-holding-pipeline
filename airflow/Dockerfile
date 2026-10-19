# Build context is the repository root: docker build -f airflow/Dockerfile .
FROM apache/airflow:3.3.2-python3.14

ARG AIRFLOW_VERSION=3.3.2
ARG PYTHON_VERSION=3.14
ARG DBT_CORE_VERSION=1.12.5
ARG DBT_CLICKHOUSE_VERSION=1.10.3
ARG DBT_PYTHON=3.14
ARG CONSTRAINTS=https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt

# dbt lives in its own virtualenv so it cannot conflict with Airflow's dependency set.
USER root
RUN mkdir -p /opt/dbt-venv /opt/airflow/config && chown airflow:0 /opt/dbt-venv /opt/airflow/config
USER airflow
RUN uv venv --python ${DBT_PYTHON} /opt/dbt-venv \
 && uv pip install --python /opt/dbt-venv/bin/python \
      dbt-core==${DBT_CORE_VERSION} dbt-clickhouse==${DBT_CLICKHOUSE_VERSION}

COPY --chown=airflow:0 airflow/requirements.txt /tmp/requirements.txt
RUN uv pip install --constraint ${CONSTRAINTS} -r /tmp/requirements.txt

COPY --chown=airflow:0 pyproject.toml /opt/ksei/pyproject.toml
COPY --chown=airflow:0 src /opt/ksei/src
RUN uv pip install --constraint ${CONSTRAINTS} /opt/ksei

COPY --chown=airflow:0 airflow/dags /opt/airflow/dags
COPY --chown=airflow:0 dbt /opt/airflow/dbt
COPY --chown=airflow:0 infra/create_buckets.py /opt/airflow/infra/create_buckets.py
COPY --chown=airflow:0 infra/init_period.py /opt/airflow/infra/init_period.py

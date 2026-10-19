# Versions

Single source of truth for pinned versions. Verified 2026-10-07.

## Runtime

| Component | Version | Notes |
|---|---|---|
| Python | 3.14 | Project package, tests, Airflow image |
| Apache Airflow | 3.3.2 | `apache/airflow:3.3.2-python3.14`, CeleryExecutor |
| apache-airflow-providers-celery | 3.24.0 | Matches the 3.3.2 constraints file |
| apache-airflow-providers-amazon | 9.36.0 | S3 remote logging |
| redis (Python client) | 6.4.0 | Matches the 3.3.2 constraints file |
| Redis | 8.10 | Celery broker (`redis:8.10`) |
| PostgreSQL | 18 | `postgres:18`; data path is `/var/lib/postgresql` |
| SeaweedFS | 4.48 | `chrislusf/seaweedfs:4.48`, S3 gateway |
| ClickHouse | 26.8 LTS | `clickhouse/clickhouse-server:26.8` |
| dbt-core | 1.12.5 | Own virtualenv at `/opt/dbt-venv` |
| dbt-clickhouse | 1.10.3 | |
| Apache Superset | 6.1.0 | `apache/superset:6.1.0`, own image |
| clickhouse-connect (Superset) | 1.9.0 | |
| psycopg2-binary (Superset) | 2.9.13 | |
| polars | 1.44.2 | Parser; matches the Airflow 3.3.2 constraints |
| httpx | 0.28.1 | The only HTTP library |
| boto3 | 1.43.75 | S3 / SeaweedFS |

## Dev tooling

Pinned in `pyproject.toml` / `uv.lock`: pytest 9.1.1, pytest-cov 7.1.0, respx 0.23.1,
moto 5.2.3, ruff 0.16.10, sqlfluff 4.4.0, pre-commit 4.6.2, httpx 0.28.1, boto3 1.43.75.
Pre-commit hook revisions are pinned in `.pre-commit-config.yaml`.

## CI (GitHub Actions)

Pinned in `.github/workflows/ci.yml` and in the `Makefile`; a test checks that every action in the
workflow is listed here.

| Component | Version | Notes |
|---|---|---|
| `actions/checkout@v7.0.1` | v7.0.1 | |
| `astral-sh/setup-uv@v10.3.0` | v10.3.0 | caches uv between runs |
| `docker/setup-buildx-action@v4.4.1` | v4.4.1 | the builder that keeps the layer cache |
| `docker/bake-action@v7.5.0` | v7.5.0 | builds the Compose images with the GitHub cache |
| `actions/upload-artifact@v7.0.2` | v7.0.2 | the logs of a failed integration run |
| gitleaks | v8.30.1 | `zricethezav/gitleaks:v8.30.1`; also the pre-commit hook |
| trivy | 0.76.0 | `aquasec/trivy:0.76.0` |
| actionlint | 1.7.12 | `rhysd/actionlint:1.7.12`, run by hand to check the workflow (not part of CI) |

## Decisions and checks

- **dbt-clickhouse on Python 3.14 (open check 1): resolved.** dbt-core 1.12.5 and
  dbt-clickhouse 1.10.3 install and run in a Python 3.14 virtualenv in the Airflow image;
  no 3.13 fallback needed.
- **Dataframe library: polars 1.44.2** (decided in Phase 3). The files are small pipe-delimited
  text read as all-strings, and polars writes Parquet without pyarrow. pandas is not used.
- Not used: dbt Core 2.0, ClickHouse 26.9, PostgreSQL 19.

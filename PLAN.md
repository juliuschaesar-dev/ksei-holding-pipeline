# PLAN.md — KSEI Holding Composition Data Pipeline

Production-style portfolio project: a monthly batch pipeline that ingests two
KSEI datasets, the securities master file and the securities holding
composition (local vs foreign ownership), stores them in a medallion
architecture, transforms them with dbt, and serves dashboards in Superset, all
delivered with CI. Source details: `docs/data-source.md`.

Status legend: `[ ]` todo, `[~]` in progress, `[x]` done.

---

## 1. Goals and non-goals

**Goals**
- End-to-end, reproducible pipeline that runs with one command (`make up`).
- Production practices: idempotency, data quality tests, observability,
  secrets management, CI, documentation.
- Respectful data collection: low frequency, rate limited, public pages only.

**Non-goals**
- Real-time or streaming ingestion.
- Big-data tooling for its own sake (no Spark).
- Redistributing raw KSEI files or exposing bulk downloads publicly.

## 2. Engineering principles: TDD, DRY, YAGNI

These govern every phase below. `AGENTS.md` turns them into rules for coding
agents.

### 2.1 TDD (test-driven development)

Every task follows red → green → refactor:

1. **Red:** write one failing test that states the behavior. Run it and
   confirm it fails for the right reason (not an import error or typo).
2. **Green:** write the smallest code that makes it pass.
3. **Refactor:** clean up (remove duplication, improve names) with all tests
   green. Run the full suite.
4. Commit test and implementation together (or the test first), never
   implementation without a test.

In each phase below, the test tasks come first and are listed first on purpose.

| Layer | What is tested | Tooling | Written before |
|---|---|---|---|
| Unit (Python) | URL/link parsing, rate limiting, retries, checksum, unzip and parse, S3 wrapper, config | `pytest`, `respx` (HTTP), `moto` (S3), fixture files | the module |
| Contract (parser) | Parser output schema against small fixture files shaped like the real files | `pytest`, fixtures in `tests/fixtures/` | `parser.py` |
| DAG | Imports cleanly, task ids, dependencies, pool, schedule, retries | `pytest` (+ `dag.test()` where useful) | the DAG file |
| dbt | Column tests, singular business-rule tests, **dbt unit tests** (given/expect, inline fixtures) | dbt tests, dbt unit tests, seeds | the model SQL |
| Integration / e2e | Compose stack up, fixture HTTP server standing in for KSEI → bronze → silver → gold, idempotent rerun | `pytest` + Docker Compose | wiring of the DAG into the stack |
| Smoke (infra) | Every service healthy; hello-world DAG runs on a Celery worker | script / `pytest` | `docker-compose.yml` |

Rules:
- Tests never call the real KSEI site; a small fixture HTTP server serves
  synthetic pages and zips for integration tests.
- Coverage gate: ≥90% on `src/ksei`. Every dbt model has at least one test;
  every primary key has `not_null` + `unique`.
- A bug fix starts with a failing regression test.
- Tests must be deterministic: no wall-clock dependence (inject the clock),
  no network, no shared mutable state.

### 2.2 DRY (don't repeat yourself)

DRY is about duplicated *knowledge*, not code that merely looks alike.
Apply the rule of three: tolerate a second copy, abstract on the third, and
only when the abstraction is obvious.

Single sources of truth:
- **Datasets:** one registry (`DATASETS` in `src/ksei/config.py`) holds, per
  dataset, the archive URL, file-name pattern, bronze path, parser spec, and
  raw table name. The client, storage paths, DAG task groups, and loader all
  read from it. Adding a dataset means adding one entry, not copying code.
- **Configuration:** `.env.example` is the only list of environment
  variables; Compose, Airflow, dbt `profiles.yml`, and the Python package read
  the same names. Shared Airflow settings use one Compose YAML anchor.
- **Commands:** CI calls the same `Makefile` targets developers run
  (`make lint`, `make test`, `make dbt-test`); no logic is duplicated in
  workflow YAML.
- **SQL:** repeated casting/cleaning logic goes into dbt macros; the bronze
  load uses one parameterized SQL template for both datasets.
- **Docs:** versions live only in `docs/versions.md`; model docs live in dbt
  YAML and are published via `dbt docs`, not retyped in the README.

### 2.3 YAGNI (you aren't gonna need it)

Build only what the current phase's tests and the dashboard require.
- No abstraction, option, config knob, or extension point without a failing
  test or a concrete current use that needs it.
- Gold models exist only if a dashboard chart or a documented question needs
  them.
- Choose one tool where two would do the same job (one HTTP library, one
  dataframe library).
- Prefer the boring solution (synchronous code, plain functions, a dataclass
  for config).

**Deferred until a concrete need appears (do not build now):**
Spark, Flower, notification task (Slack/email), separate Celery queues (the
`ksei_http` pool already enforces the rate limit), SCD2 history for
security attributes, a security dimension (no credible second source), marts not backed by a dashboard chart, abstract base classes
or plugin systems for parsers, async HTTP client, generic multi-source
ingestion framework, extra data-quality frameworks (dbt tests are enough),
lineage tooling, Kubernetes, additional storage backends.

CeleryExecutor stays because it was chosen explicitly for this project, not
because the workload needs it; the README states this honestly.

## 3. Tech stack

Versions verified on 2026-10-07. Full table, rationale, and open compatibility
checks: `docs/versions.md`.

| Area | Tool | Version |
|---|---|---|
| Language | Python | 3.14 |
| Orchestration | Apache Airflow, CeleryExecutor | 3.3.2 (`apache/airflow:3.3.2-python3.14`) |
| Broker | Redis | 8.10.x |
| Object storage (bronze, Airflow logs) | SeaweedFS with S3 gateway | 4.48 |
| Warehouse (bronze tables, silver, gold) | ClickHouse | 26.8 LTS (26.9 is newest stable) |
| Metadata DB | PostgreSQL (Airflow, Celery result backend, Superset) | 18.x (19 not GA yet) |
| Transformation | dbt-core + `dbt-clickhouse` | dbt-core 1.12.x + dbt-clickhouse 1.10.3 |
| dbt orchestration | Airflow `@task.bash` | `dbt_build` runs `dbt build` in the dbt virtualenv (Cosmos removed) |
| Ingestion | `httpx`, `boto3`, and `polars` (chosen in Phase 3; pandas is not used) | pinned |
| BI | Apache Superset + `clickhouse-connect` | Superset 6.1.0, clickhouse-connect 1.9.0 |
| Infra | Docker, Docker Compose, Makefile | n/a |
| CI | GitHub Actions | n/a |

Dev tooling: `pytest`, `respx`, `moto`, `ruff`, `sqlfluff`, `pre-commit`, `gitleaks`, `trivy`.

Rules: pin exact versions (no `latest`), keep `docs/versions.md` in sync, and
install Python dependencies with the Airflow 3.3.2 constraints file for
Python 3.14. dbt runs in its own virtualenv so it cannot conflict with
Airflow's dependency set. dbt Core 2.0 is out of scope (see `docs/versions.md`).

## 4. Data flow (medallion)

Two datasets, same flow. `<dataset>` is `master_securities` or
`holding_composition`.

```
KSEI archive pages (list links; never guess URLs)
   │  (Airflow: download_to_bronze, pool ksei_http size 1, rate limited)
   ▼
SeaweedFS  s3://ksei-lake/bronze/<dataset>/raw/year=YYYY/month=MM/<original .zip>
   │  (Airflow: parse_to_parquet — unzip, schema-on-read, no business cleaning)
   ▼
SeaweedFS  s3://ksei-lake/bronze/<dataset>/parsed/year=YYYY/month=MM/data.parquet
   │  (Airflow: load_bronze — INSERT INTO bronze.* SELECT FROM s3(...), per period)
   ▼
ClickHouse bronze.stg_master_securities, bronze.stg_holding_composition
   (the period calendar takes a shorter way: period-init -> bronze/period -> bronze.stg_period
    -> gold.dim_period, once, without silver)
   │  (dbt: silver — raw Data Vault 2.0: hubs, links, satellites with is_active / is_deleted flags)
   ▼
ClickHouse silver.* (hub_*, link_*, satellite_*)
   │  (dbt: gold — fact_security_monthly from master file, facts from holding composition)
   ▼
ClickHouse gold.*  ──►  Superset dashboards
```

---

## Phase 0 — Discovery and legal check

- [x] Confirm the archive pages are server-rendered HTML with plain download
      links and no auth (both datasets).
- [x] Confirm file name patterns and release cadence (monthly, last trading
      day of month).
- [x] Find how previous years are loaded (year tabs); `/<dataset>/<year>`
      currently returns HTTP 500. (Resolved: the path form works; the `?Year=`
      query form is the one that fails. See `docs/data-source.md`.)
- [x] Download 2–3 samples of each dataset manually; document the files
      inside each zip, delimiter, encoding, header, columns, and units.
- [~] Check `robots.txt` and the "Ketentuan dan Kebijakan" page. Done: `robots.txt`
      does not exist on either host; disclaimer page checked (liability only, no
      automation clause). Still open: the terms page itself.
- [ ] (Recommended) Email helpdesk@ksei.co.id asking whether automated
      monthly retrieval for a non-commercial portfolio project is acceptable.
- [~] Write `docs/data-source.md`: URL patterns, format, column dictionary,
      cadence, legal notes, rate-limit policy.

**Exit criteria:** file format and schema documented; no blocker found in
terms of use.

## Phase 1 — Repository scaffolding

- [x] Create folder structure (see `AGENTS.md`).
- [x] `pyproject.toml` (Python 3.14), `ruff` config, `pytest` config with
      markers (`unit`, `integration`, `smoke`) and a coverage gate (≥90% on
      `src/ksei`).
- [x] A first trivial failing-then-passing test proves the TDD loop works in
      `make test` and in CI.
- [x] `pre-commit` with ruff, sqlfluff, gitleaks, end-of-file/trailing
      whitespace hooks.
- [x] `.gitignore` (including `data/`, `.env`, dbt `target/` and `logs/`).
- [x] `.env.example` with every required variable and placeholder values.
- [x] `Makefile` targets: `up`, `down`, `logs`, `lint`, `test` (unit),
      `test-integration`, `test-smoke`, `dbt-test`, `dbt-build`, `dbt-docs`,
      `clean`. CI will call these same targets.
- [x] README skeleton and `docs/` folder. (No LICENSE file: not needed for this portfolio project.)

**Exit criteria:** `make lint` and `make test` run (even with no real tests yet).

## Phase 2 — Local infrastructure

Test first: write `tests/smoke/` before the Compose file.

- [x] (Red) Smoke tests: every service reports healthy within a timeout;
      Airflow API server responds; a hello-world DAG completes on a Celery
      worker; ClickHouse accepts a query; SeaweedFS S3 accepts a put/get;
      Superset login page responds. They fail until the stack exists.
- [x] `airflow/Dockerfile` on `apache/airflow:3.3.2-python3.14` with
      `apache-airflow-providers-celery` and the project
      package, installed with the Airflow 3.3.2 constraints for Python 3.14.
      Install `dbt-core` 1.12.x + `dbt-clickhouse` 1.10.3 in a dedicated
      virtualenv inside the image; never in the Airflow environment.
- [x] Verify `dbt-clickhouse` 1.10.3 on Python 3.14 (see `docs/versions.md`,
      open check 1). If it fails, build the dbt virtualenv on Python 3.13.
- [x] `docker-compose.yml` services: postgres, redis, airflow-init,
      airflow-apiserver, airflow-scheduler, airflow-dag-processor,
      airflow-worker, airflow-triggerer, seaweedfs, clickhouse, superset.
      Shared Airflow settings in one YAML anchor.
- [x] Healthchecks for every service; `depends_on` with `service_healthy`.
- [x] Shared `AIRFLOW__API_AUTH__JWT_SECRET`, Fernet key, execution API URL.
- [x] Init: create SeaweedFS buckets (`ksei-lake`, `airflow-logs`), ClickHouse
      databases (`bronze`, `silver`, `gold`) and users, Postgres databases for
      Airflow and Superset.
- [x] Airflow remote logging to SeaweedFS.
- [x] Compose profiles: default (core), `full` (adds superset).

**Exit criteria:** smoke tests green (`make test-smoke`) after `make up`.

## Phase 3 — Ingestion package (`src/ksei/`)

Work module by module in this order. For each: write failing tests, make them
pass, refactor. Fixtures are small synthetic files that mirror the real
structure documented in `docs/data-source.md`.

- [x] `config.py`: frozen dataclass reading env vars, plus the `DATASETS`
      registry (archive URL, file-name pattern, bronze path template, parser
      spec, raw table). Tests: missing env var raises a clear error; registry
      entries are complete; paths render correctly for a period.
- [x] `client.py` (one generic client driven by `DATASETS`). Tests first:
      lists (dataset, period, URL) from a fixture archive page; ignores
      unrelated links; downloads with a descriptive User-Agent; enforces the
      minimum delay (inject a fake clock/sleep); retries with backoff on 5xx
      and timeouts; does not retry on 4xx; gives up after N attempts.
- [x] `storage.py` (S3 wrapper, includes SHA-256 checksum and metadata
      helpers; no separate `metadata.py` until it grows). Tests with `moto`:
      put with metadata, exists, get, list by prefix; writing an existing raw
      key is refused (bronze is immutable).
- [x] `parser.py` (one generic unzip-and-parse function driven by each
      dataset's parser spec). Tests first: unzips the fixture; parses
      delimiter/encoding/header per spec; all columns kept as strings; adds
      `_period`, `_source_file`, `_ingested_at` (clock injected); fails
      loudly with a clear message on unexpected columns or empty files;
      output Parquet round-trips.
- [x] Choose the dataframe library (`polars` or `pandas`) based on the real
      file format; record the decision in `docs/versions.md`.
- [x] Refactor pass: remove duplication between datasets; confirm adding a
      dataset requires only a registry entry plus a parser spec.

**Exit criteria:** `make test` green with ≥90% coverage on `src/ksei`;
re-running a download for an existing period is a no-op (tested).

## Phase 4 — Airflow DAG

Tests first, in `tests/dags/`.

- [x] (Red) DAG tests: file imports without errors; one task group per
      `DATASETS` entry, generated from the registry (no per-dataset
      copy-paste); expected task ids and dependencies; download task uses
      pool `ksei_http`; `retries` and `retry_delay` set; schedule is monthly
      in `Asia/Jakarta`; no DataFrames in XCom (only paths and periods).
- [x] (Green) `ksei_monthly` DAG using `airflow.sdk` decorators,
      `catchup=False`, backfill supported via dynamic task mapping over the
      periods returned by `detect_new_periods` (needed for the 2023–2026
      historical load).
- [x] Tasks: `detect_new_periods` → `download_to_bronze` (pool `ksei_http`,
      1 slot) → `parse_to_parquet` → `load_bronze` (delete + insert per
      period, one parameterized SQL template) → `dbt_build`.

- [x] Task logic lives in `src/ksei/`; DAG file stays thin (wiring only).
- [x] Integration test: with Compose up and a fixture HTTP server standing in
      for KSEI, one run lands the expected rows in `bronze.*`; a second run
      for the same period leaves row counts unchanged.

**Exit criteria:** DAG and integration tests green; one historical backfill
and one scheduled run succeed; rerun is idempotent.

## Phase 5 — dbt models (ClickHouse)

Specification first: write the dashboard questions, then tests, then models.

- [x] Dashboard questions (the spec; only models needed to answer these are
      built):
      Q1 How has foreign vs local ownership changed over time?
      Q2 How is ownership composed by investor type, and by security type?
      Q3 What changed month over month?
- [x] `profiles.yml` from env vars only; sources declared once in
      `models/sources.yml`, with freshness checks.
- [x] No seeds: unit tests carry small inline fixtures, and the integration test loads
      synthetic periods into bronze through the pipeline itself.
- [x] (Red) Tests before each model: dbt **unit tests** (given/expect) for the
      transformation logic, generic tests (`not_null`, `unique`,
      `accepted_values`, `relationships`), and singular tests (e.g. local +
      foreign = total per period; every security in the fact exists in the
      security fact; no duplicate keys after a rerun).
- [x] (Green) Silver as a raw **Data Vault 2.0** (reference: the `datavault-dbt` repo):
      `hub_security`, `hub_isin`, `hub_currency`, `link_master_securities`,
      `satellite_master_securities` and `satellite_holding_composition` (multi-active on `period`,
      which is a satellite child key, not a hub), each one call to a
      `dv_*` macro. Keys are MD5 hashes; satellite rows are append-only, with
      `meta_is_active` and `is_deleted` flags kept by post-hooks.
- [x] (Green) Gold, projected from the vault only: `fact_security_monthly` (one row per
      period and security, with description, type and issuer; no security dimension, no SCD2), `fact_holding_monthly`, and only those marts that Q1–Q3 require
      (month-over-month change can be a window function in a mart or a
      Superset metric; build a separate model only if it is reused).
      `dim_investor_type` was not needed: investor types are shown by code (their
      names are unconfirmed).
- [x] Silver is incremental (`append`; satellites also flip their two flags); gold is rebuilt as tables.
      `MergeTree` with sensible `ORDER BY`. Tests that a rerun, and a full
      rebuild, yield identical results.
- [x] Column descriptions in YAML; `dbt docs generate` works.
- [x] `gold.dim_period`, the calendar of the facts' `period` (`date_actual`) (added on request, outside the
      original Q1-Q3 scope): `src/ksei/period.py` and the `period-init` Compose service load a
      static CSV (`PERIOD_SOURCE_URL`) once into SeaweedFS `bronze/period/` and typed
      `bronze.stg_period`; dbt reads it straight into gold, skipping silver by decision.

**Exit criteria:** `make dbt-test` green; every model has at
least one test; every primary key has `not_null` + `unique`.

## Phase 6 — Superset

Test first: assert the dashboard export imports and each chart's dataset
query returns rows against the gold data.

- [x] ClickHouse database connection provisioned via env/init script.
- [x] Datasets on `gold` models only.
- [x] Dashboard charts and cards each answer Q1–Q3 or show one KPI of them (the latest period, the
      foreign share, the total value, the change since the peak, the largest holder group, the
      local/foreign split); no chart without a question or a KPI. Listed in
      `docs/dashboard-questions.md`.
- [x] Dashboard redesigned to the supplied design (added on request): values in IDR trillion
      (`T`, via `D3_FORMAT`), a colour rule on the change since the peak, native filters (Date
      range for the chart over time, Security type for the mart charts), and card heights that
      stay equal in "Download as Image" (CSS).
- [x] Gold carries what the dashboard needs, so Superset repeats nothing: `investor_types` var (codes and
      names) and `investor_type_name`, the `is_latest_period` flag on the facts and marts, and
      `mart_investor_type_monthly` (one row per period and investor type, ranked) behind the
      largest-holder card.
- [x] The largest-holder card is a Handlebars chart, which needs two loosened Superset security
      settings (`unsafe-eval` in `script-src`, the `style` attribute in chart HTML); both are set
      in `superset_config.py`, tested by a smoke test and described in `docs/runbook.md`.
- [x] Export assets to `superset/assets/` and import on startup.

**Exit criteria:** fresh `make up` + one DAG run renders the dashboard with no
manual clicks.

## Phase 7 — CI (GitHub Actions)

- [x] `ci.yml` on PR and push, calling the same Makefile targets as local
      development (DRY): `make lint`, `make test` (coverage gate; it also checks
      that the generated dbt fixtures are current), `make test-dags` (inside the
      Airflow image), Docker image builds, gitleaks (`make scan-secrets`), trivy
      (`make scan-images`). dbt runs in the integration job: the integration tests build the models on
      synthetic periods and check a rerun and a full rebuild, then `make dbt-test`; a separate
      `make dbt-build` on an empty warehouse would add nothing. Tests check the workflow (only `make` calls,
      pinned actions, the jobs above) and actionlint accepts it; it has not run on GitHub yet.
- [x] Integration job: `make env`, `make up PROFILE=full`, `make test-smoke`, `make test-integration`,
      `make dbt-test` (the same tests as Phases 2 and 4, not new ones); the logs of a failed run are kept.
- [x] Cache uv (setup-uv) and Docker layers (buildx and bake with the GitHub cache); the effect
      shows only on the second run.
- [ ] Branch protection: CI must pass before merge. A GitHub setting, not a file; the steps are in
      `docs/runbook.md`.

**Exit criteria:** CI green on `main`; badge in README. The badge is in the README; the first green run on
`main` is still to come.

## Phase 8 — Documentation and polish

- [x] README: overview, architecture diagram, stack, quickstart, screenshots,
      design decisions and trade-offs (why ClickHouse, why Celery, why no
      Spark), data source disclaimer.
- [x] `docs/architecture.md`, `docs/data-source.md`, `docs/runbook.md`
      (common failures and fixes), `docs/versions.md`.
- [x] Final review against the Definition of Done in `AGENTS.md`.

---

## Milestones

| Milestone | Phases | Outcome |
|---|---|---|
| M1 Foundation | 0–2 | Stack runs locally, data source understood |
| M2 Data in | 3–4 | Raw data lands in bronze automatically |
| M3 Data modeled | 5–6 | Gold models and dashboard |
| M4 Production-ready | 7–8 | CI, docs, polished repo |

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Legacy site `web.ksei.co.id` retired in favor of `www.ksei.co.id` | Base URLs in config; scraping logic isolated per dataset; alert on 404 |
| KSEI page structure or URL changes | Isolate scraping logic in `client.py`; alert on parse failure; schema check task |
| File format changes between periods | Parser versioning per period range; schema validation in `parse_to_parquet` |
| Terms of use prohibit automation | Phase 0 check; fall back to manual download + same pipeline from bronze |
| `dbt-clickhouse` not officially verified on Python 3.14 | Resolved: dbt-core 1.12.5 and dbt-clickhouse 1.10.3 run on Python 3.14 in their own virtualenv; no fallback needed. Airflow runs dbt with one `@task.bash` |
| Superset 6.1.0 declares Python 3.10–3.12 only | Superset runs from its own official image; never share the Python 3.14 environment |
| Newest releases (dbt Core 2.0, ClickHouse 26.9, PostgreSQL 19) are very recent | Use dbt 1.12, ClickHouse LTS, PostgreSQL 18; upgrade deliberately after the first release is stable |
| Heavy local resource usage | Compose profiles; document 8 GB RAM minimum |
| Over-engineering creeps in | YAGNI list in section 2.3; every addition needs a failing test or a dashboard question |
| Tests slow down or become flaky | Pyramid: many fast unit tests, few integration tests; injected clock; fixture HTTP server; no real network |
| Secrets leaking | `.env` ignored, gitleaks in pre-commit and CI |

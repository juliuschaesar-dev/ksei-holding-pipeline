# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.
Read this file fully before making changes. The roadmap lives in `PLAN.md`;
pick tasks from the current phase and tick checkboxes as you finish them.

## Project summary

A production-style, portfolio data pipeline that collects two KSEI (Kustodian
Sentral Efek Indonesia) datasets monthly, the securities master file and the
securities holding composition (local vs foreign ownership), stores it with a medallion architecture, models it with dbt, and
serves dashboards in Superset. Everything runs in Docker Compose and ships via
GitHub Actions CI.

## Hard rules (never break these)

1. **Never commit data.** No raw or parsed KSEI files, no database dumps. Only
   small synthetic fixtures under `tests/fixtures/`.
2. **Never commit secrets.** All credentials come from environment variables.
   Update `.env.example` (placeholders only) whenever you add a variable.
3. **Respect the data source.**
   - Only access public, unauthenticated KSEI pages. Never touch login areas
     (e.g. AKSes) and never bypass CAPTCHAs, tokens, or other protections.
   - All HTTP calls to KSEI go through `src/ksei/client.py`, which enforces a
     minimum delay between requests, retries with backoff, timeouts, and a
     descriptive User-Agent. Do not add other code paths that call KSEI.
   - The download task runs in Airflow pool `ksei_http` with 1 slot.
   - Never schedule more often than the source's release cadence (monthly).
   - Never construct download URLs from dates. Release dates are the last
     trading day of the month, so always take URLs from the archive pages.
   - Tests must never hit the real KSEI site; mock HTTP.
4. **Idempotency.** Every task and model must produce the same result when
   re-run for the same period. Bronze raw files are immutable (write once).
5. **Do not change the stack** (add Spark, swap ClickHouse, replace Celery,
   etc.) without an explicit instruction. Propose changes in a PR description
   instead.
6. **Pin versions.** No `latest` tags in Dockerfiles or Compose; no unpinned
   dependencies. Record versions in `docs/versions.md`.
7. Follow the development methodology below (TDD, DRY, YAGNI). Code
   without a prior failing test, or features not backed by `PLAN.md`, are
   rejected in review.
8. Keep the data-source disclaimer in the README: not affiliated with KSEI,
   data belongs to KSEI, educational/portfolio use only.

## Tech stack

Versions verified on 2026-10-07; details and rationale in `docs/versions.md`.

| Area | Tool | Notes |
|---|---|---|
| Language | Python **3.14** | Project package, tests, CI, Airflow image |
| Orchestration | Apache Airflow **3.3.2**, CeleryExecutor | Image `apache/airflow:3.3.2-python3.14` |
| Broker | Redis **8.10.x** | Celery broker |
| Metadata DB | PostgreSQL **18.x** | Airflow, Celery result backend, Superset only; **not** the warehouse. PG 18 images use data path `/var/lib/postgresql` |
| Object storage | SeaweedFS **4.48** (S3 gateway) | Bronze files, Airflow remote logs |
| Warehouse | ClickHouse **26.8 LTS** | Databases `bronze`, `silver`, `gold` |
| Transformation | dbt-core **1.12.x** + `dbt-clickhouse` **1.10.3** | Runs in a dedicated virtualenv, not in the Airflow environment |
| dbt orchestration | Airflow `@task.bash` | `dbt_build` runs `dbt build` in the dbt virtualenv; no Cosmos |
| Ingestion | `httpx`, `boto3`, `polars` | Pinned. polars was chosen in Phase 3 (all-strings text in, Parquet out, no pyarrow); pandas is not used |
| BI | Apache Superset **6.1.0** | `clickhouse-connect` 1.9.0; runs from its own image (Superset declares Python 3.10–3.12) |
| CI | GitHub Actions | lint, tests, image build and scans, full-stack tests |

Do not upgrade to dbt Core 2.0, ClickHouse 26.9, or PostgreSQL 19 without an
explicit instruction.

## Development methodology (TDD, DRY, YAGNI)

### The task loop (mandatory)

1. Pick one unchecked task from the current `PLAN.md` phase. Do not start a
   later phase early.
2. **Red:** write a failing test describing one behavior. Run it. Confirm it
   fails for the expected reason, not because of an import error or typo.
3. **Green:** write the smallest code that passes. No extra behavior.
4. **Refactor:** remove duplication, improve names, keep every test green.
   Run `make lint test` (plus `make dbt-test` for dbt work).
5. Repeat with the next behavior. Commit when green.
6. In the PR description, state which tests were written first and what they
   covered.

### TDD rules

- No production code without a failing test first. This applies to Python,
  DAGs, and dbt models (write schema/singular/unit tests before the
  model SQL).
- Bug fix = failing regression test first, then the fix.
- Tests are deterministic and offline: inject clocks, mock HTTP (`respx`),
  mock S3 (`moto`), use small synthetic fixtures. Integration tests use a
  local fixture HTTP server, never the real KSEI site.
- Test names state behavior (`test_client_retries_on_5xx_then_succeeds`).
  One behavior per test; assert outcomes, not implementation details.
- Do not weaken, skip, or delete a test to make it pass. If a test is wrong,
  fix the test and say why.
- Coverage gate: ≥90% on `src/ksei`. Every dbt model has at least one test;
  every primary key has `not_null` + `unique`.
- Test pyramid: many fast unit tests, a few integration tests, a small smoke
  suite. Markers: `unit`, `integration`, `smoke`. DAG tests need Airflow, so they run
  inside the Airflow image (`make test-dags`) instead of `make test`.

### DRY rules

- Duplicated knowledge has one home:
  - dataset definitions: `DATASETS` registry in `src/ksei/config.py`;
  - environment variables: `.env.example`;
  - shared Airflow settings: one Compose YAML anchor;
  - commands: `Makefile`, which CI also calls (no logic copied into workflow
    YAML);
  - repeated SQL casting/cleaning: dbt macros;
  - versions: `docs/versions.md` only;
  - model documentation: dbt YAML, published with `dbt docs`.
- Adding a dataset must require only a registry entry and a parser spec. If
  it requires copying a module, refactor first.
- Rule of three: tolerate a second similar copy; abstract on the third and
  only when the shared concept is clear. Do not merge code that merely looks
  alike but changes for different reasons.

### YAGNI rules

- Build only what the current task's failing test or a dashboard question
  (Q1–Q3 in `PLAN.md`) requires. No speculative parameters, hooks, base
  classes, or config options.
- Do not add dependencies, services, models, DAG tasks, or abstractions that
  are not in `PLAN.md` without an explicit instruction. Propose them in the PR
  description instead.
- One tool per job (one HTTP library: `httpx`; one dataframe library: `polars`;
  never both).
- Prefer plain functions, dataclasses, and synchronous code.
- Deferred list (do not build): Spark, Flower, notification tasks, separate
  Celery queues, SCD2, marts without a dashboard chart, parser base classes or
  plugin systems, async HTTP, generic multi-source framework, extra data
  quality frameworks, lineage tooling, Kubernetes, alternative storage.
- Delete dead code and unused config as soon as it appears.

## Architecture

```
KSEI archive ─► SeaweedFS bronze/raw ─► SeaweedFS bronze/parsed (Parquet)
            ─► ClickHouse bronze ─► dbt silver (Data Vault 2.0) ─► dbt gold (facts and marts) ─► Superset
```

- **Bronze**: raw files as downloaded (`raw/`), plus a schema-on-read Parquet
  copy (`parsed/`, all strings + `_period`, `_source_file`, `_ingested_at`).
  The ClickHouse tables `bronze.stg_<dataset>` are **typed**: `load_bronze` casts each
  column to the type declared in the `DATASETS` registry (only `String`, `Int64`,
  `Float64`, `Date`, `DateTime`; never `Nullable`). An empty cell in an optional
  column is stored as the type default (`''`, `0`, `1970-01-01`), because plain types
  cannot hold NULL; gold restores NULL where the distinction matters. An empty
  required value, or one that cannot be converted, fails the load. Files in S3 stay
  all strings so a period can always be reloaded.
- **Silver**: the raw **Data Vault 2.0** (dbt), loaded from the bronze tables with no business
  rules: hubs (business keys), links (relationships) and satellites (descriptive history),
  all keyed by MD5 hashes. Hubs and links are insert-only. A changed attribute is a new
  satellite row, and two flags on each satellite row (`meta_is_active`, `is_deleted`) say which
  version is in force and whether the grain vanished from the source. Reference implementation:
  the `datavault-dbt` repo.
- **Gold**: facts and marts projected from the vault (dbt) for the dashboards. There is no
  security dimension: the master file is the only source of security attributes and KSEI
  reformats them over time, so each period keeps what it was published with. This is where values are cleaned (casing, spelling variants, NULL restored,
  standard types).

S3 layout: `s3://ksei-lake/bronze/<dataset>/{raw|parsed}/year=YYYY/month=MM/`,
where `<dataset>` is `master_securities` or `holding_composition`. The period calendar, a static
reference file that is not a KSEI release, lives at `s3://ksei-lake/bronze/period/{raw|parsed}/`.
Source pages, URL patterns, and file details: `docs/data-source.md`.

## Repository layout

```
.
├── AGENTS.md
├── PLAN.md
├── README.md
├── Makefile
├── docker-compose.yml
├── .env.example
├── pyproject.toml
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml
├── airflow/
│   ├── Dockerfile
│   └── dags/{ksei_monthly.py,hello_world.py}   # hello_world is the smoke-test DAG
├── src/ksei/
│   ├── config.py           # settings and the DATASETS registry
│   ├── client.py           # the only code that talks to KSEI
│   ├── storage.py          # S3 client, buckets, checksum/metadata helpers
│   ├── parser.py
│   ├── warehouse.py        # ClickHouse over HTTP, typed bronze load
│   ├── period.py           # one-time load of the period calendar (not a KSEI file)
│   └── tasks.py            # what the DAG tasks call
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml
│   ├── models/{sources.yml,silver/,gold/}
│   ├── macros/
│   └── tests/
├── superset/{Dockerfile,superset_config.py,assets/,init/,export_assets.py}
├── tools/                      # dbt.py (the one dbt command), generate_dbt_unit_tests.py, make_env.py
├── infra/                      # init scripts: buckets, period calendar, ClickHouse DBs/users, Postgres DBs
├── tests/{unit,dags,integration,smoke,fixtures}/
└── docs/{architecture.md,data-source.md,runbook.md,versions.md}
```

## Commands

```bash
make env                    # .env with random secrets (or cp .env.example .env and fill it in)
make up                     # core services
make up PROFILE=full        # + superset
make down
make logs SERVICE=airflow-worker
make lint                   # ruff + sqlfluff
make test                   # unit tests with coverage gate (fast, offline)
make test-dags              # DAG structure tests, run inside the Airflow image
make test-integration       # needs `make up`; uses fixture HTTP server
make test-smoke             # needs `make up`; service health + hello DAG
make dbt-test               # dbt unit tests and data tests on the built models
make dbt-build              # dbt build inside the Airflow image
make dbt-docs
make dbt-fixtures           # regenerate the dbt unit-test files that hold MD5 hashes
make images                 # build the images (PROFILE=full: Superset too)
make scan-secrets           # gitleaks over the git history (pinned image)
make scan-images            # trivy over the built ksei-* images (pinned image)
make logs-dump              # every service's log in compose.log (CI keeps it on failure)
make superset-export        # re-export the dashboard after editing it in the UI
```

`.github/workflows/ci.yml` only calls these targets (a test enforces it); never put logic in the workflow.
Run `make lint test` before every commit. Run `make dbt-build` when touching
anything under `dbt/`.

## Conventions

### Python
- Python 3.14, type hints everywhere, `ruff` for lint and format. Target
  `py314` in tool configs; avoid deprecated or removed stdlib APIs.
- Small pure functions; side effects (HTTP, S3, DB) isolated behind thin
  wrappers so they can be mocked.
- Config via `src/ksei/config.py` reading env vars; no hard-coded hosts,
  buckets, or credentials, and no default values for settings: every variable is required and
  listed in `.env.example`. `tests/unit/test_no_hardcoded_config.py` fails when a password, key,
  user or bucket from `.env` is written literally anywhere in the repository.
- Logging with the standard `logging` module; no `print`.
- Tests: `pytest`, HTTP mocked with `respx`, S3 mocked with `moto`, clock
  injected. Coverage gate ≥90% on `src/ksei`. See the methodology section.

### Airflow 3
- Use the Task SDK: `from airflow.sdk import dag, task`. Do not import from
  `airflow.decorators` or use removed 2.x APIs (`schedule_interval`,
  `provide_session` in tasks, direct metadata DB access).
- `schedule` monthly, timezone `Asia/Jakarta`, explicit `catchup`.
- XCom carries only small values (periods, S3 keys). Never DataFrames.
- Rate limiting is enforced by the `ksei_http` pool; do not add queues or
  extra executors without a measured need.
- Every task must be retry-safe; set `retries` and `retry_delay`.
- Keep DAG files thin: business logic belongs in `src/ksei/`.
- The DAG must import cleanly (`airflow dags list-import-errors` is empty).

### dbt (ClickHouse)
- Model naming: `hub_*`, `link_*`, `satellite_*` (silver, the vault) and `fact_*`,
  `mart_*` (gold). Hash keys are `hmd5_<hub>` and `lmd5_<link>`. Schemas map to ClickHouse
  databases `silver` and `gold`.
- Every hub, link and satellite is one call to a macro in `macros/datavault/` (`dv_hub`,
  `dv_link`, `dv_satellite`); do not hand-write vault SQL. Keys are `lower(hex(MD5(...)))` over
  the trimmed business key(s), so loads need no ordering. A business key is a real entity
  (security code, ISIN, currency); a date such as the reporting period is not, so it is a
  satellite child key, never a hub.
- Silver models are `incremental` with `incremental_strategy='append'`. Hubs and links are
  insert-only. Satellite data is append-only too (a changed attribute is a new row, and an A -> B
  -> A change is recorded), and only the two bookkeeping flags are ever changed: post-hooks
  `dv_track_deletions` (inserts an `is_deleted = 1` marker row when a grain leaves the source) and
  `dv_deactivate_superseded` (sets `meta_is_active = 0` on superseded rows). Read the version in
  force with `dv_satellite_current` (active and not deleted).
- Gold models are tables rebuilt on every run; they read only the vault, never bronze. The one
  exception is `dim_period`: the calendar is reference data, so it reads `bronze.stg_period`.
- Knowledge a dashboard needs lives in dbt, not in Superset: the names of the investor types are the
  `investor_types` var (codes and names together), and "the newest period" is the `is_latest_period` column
  (macro `is_latest_period()`). A chart filters on the column; it does not repeat a subquery or a `CASE`.
- Engines: `MergeTree`, `ORDER BY` starting with low-cardinality filter columns; large gold
  facts are `PARTITION BY toYYYYMM(period)`.
- Types: plain, standard types everywhere: `String`, `Int64`, `Float64`, `Date`, `DateTime`.
  No `LowCardinality`, `Decimal` or unsigned types (the `assert_only_standard_column_types` test
  enforces it). Business keys in the vault are text, and gold converts the period back to a `Date`.
  A column is `Nullable` only where gold needs a real NULL.
- Every model has a description and column docs in YAML; primary keys get
  `not_null` + `unique`; categories get `accepted_values`.
- SQL style enforced by `sqlfluff` (ClickHouse dialect, lowercase keywords,
  CTEs over subqueries).
- `profiles.yml` uses `env_var()` only.

### ClickHouse
- Never use `ALTER TABLE ... UPDATE/DELETE` mutations in the hot path; prefer
  partition-level delete + insert. The one exception is the satellite flag update, which uses the
  ClickHouse lightweight `UPDATE` statement (satellite tables are created with
  `enable_block_number_column` and `enable_block_offset_column`) and touches only superseded rows.
- Loading from SeaweedFS uses the `s3()` table function with credentials from
  env/named collections, not literals in SQL files.

### Docker / Compose
- One Airflow image for all Airflow services.
- Every service has a healthcheck; dependencies use `service_healthy`. The one-shot init services
  (`airflow-init`, `period-init`) have none: they run to completion and exit, and `service_completed_successfully`
  is the dependency on them.
- Shared Airflow settings (JWT secret, Fernet key, execution API URL,
  executor, broker, result backend) live in a single YAML anchor.

### Superset
- Datasets only on `gold` tables.
- Dashboards are exported to `superset/assets/` and imported on startup;
  do not rely on manual UI configuration.
  After editing a dashboard in the UI, run `make superset-export` and commit the diff.
- The ClickHouse SQLAlchemy dialect is `clickhousedb://`; every dashboard chart needs a smoke-test
  query that returns rows.
- The Superset image copies `superset/assets/` when it is built: after `make superset-export`, rebuild it
  (`docker compose --profile full up -d --build superset`), or the old assets are imported again.
- Values are rupiah and the dashboard counts them in trillions: divide by `1e12` and format with `$,.0f`
  (`D3_FORMAT` in `superset_config.py` gives `$` the suffix ` T`). No SI formats: they write 8,009 trillion as `8.0P`.
- `superset_config.py` loosens two security settings, only for the Handlebars card of the largest holder:
  `unsafe-eval` in `script-src` and the `style` attribute in chart HTML. Do not loosen anything else, and see
  `docs/runbook.md` before touching them.
- "Download as Image" draws each card at the height of its content: the heights in the dashboard CSS and in
  the layout must be changed together (`docs/runbook.md`).

## Git workflow

- Branches: `feat/*`, `fix/*`, `chore/*`, `docs/*`.
- Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `ci:`).
- Small, focused PRs, each linked to a `PLAN.md` task. Describe what changed,
  why, and how it was tested.
- CI must be green before merge.

## Definition of done

A task is done when:
- [ ] A failing test existed before the implementation (TDD), and the PR
      description says which.
- [ ] Code follows the conventions above and passes `make lint test`.
- [ ] dbt changes pass `make dbt-test`; every model has tests.
- [ ] No duplicated knowledge introduced (DRY) and nothing built beyond the
      task (YAGNI); dead code removed.
- [ ] No data or secrets added; `.env.example` updated if needed.
- [ ] Docs updated (README, `docs/`, model YAML) where behavior changed.
- [ ] Re-running the affected task/model is idempotent.
- [ ] The corresponding checkbox in `PLAN.md` is ticked.

## When unsure

- If the KSEI file format, columns, or URL patterns are unknown, check
  `docs/data-source.md`. If it is missing or incomplete, stop and ask; do not
  guess column names or scrape speculatively.
- If a library version conflicts with Airflow 3.3.2 constraints, isolate it
  (e.g. separate virtualenv for dbt) rather than loosening constraints.
- If a dependency does not support Python 3.14 yet, check
  `docs/versions.md` for the documented fallback before changing the Python
  version of the main project.
- Prefer the simplest solution that meets production practices; explain any
  added complexity in the PR.

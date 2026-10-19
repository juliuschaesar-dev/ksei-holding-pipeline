# Runbook

## SeaweedFS: `InternalError` on PutObject

`No writable volumes and no free volumes left`: the volume server hit its slot
limit. `infra/seaweedfs/entrypoint.sh` sets `-volume.max=100`; raise it if you
add many buckets.

## A service is unhealthy

`make logs SERVICE=<name>`; `docker compose ps` shows the health state.

## Tests

- `make test`: unit tests (offline). `make test-dags`: DAG structure tests, run inside the
  Airflow image because Airflow does not install on Windows. `make test-integration`: needs
  `make up`; a local fixture server stands in for KSEI and fictional 2001 periods are used
  and cleaned up. `make test-smoke`: service health, pool, DAG registration, hello DAG.

## First run after unpausing `ksei_monthly`

Unpausing creates one run for the latest missed schedule even with `catchup=False`. That
run backfills every period not yet in `bronze.*` (detect compares the archive with the
`_period` values in ClickHouse), one request at a time. A manual trigger queues behind it
(`max_active_runs=1`) and will find nothing new.

## The period calendar

`period-init` loads it on every start of the stack and does nothing once it is in place.
If it exits with an error, read `docker compose logs period-init`: a refused download shows
the HTTP status; a share link that answers with a sign-in page fails on the header check and
stores nothing. Re-run it with `docker compose up -d --force-recreate period-init`.
To load a corrected file, delete `bronze/period/` in the `ksei-lake` bucket and truncate
`bronze.stg_period`, then re-run the service and `dbt build --select dim_period`.

## Reload a period

Delete nothing by hand: re-run `load_bronze` for the period; it drops the partition
`_period = 'YYYY-MM-DD'` and re-inserts from `bronze/<dataset>/parsed/`. Raw zips are
immutable; to re-parse, re-run `parse_to_parquet` first.

## ClickHouse admin user and S3 access

The admin user's name comes from `CLICKHOUSE_ADMIN_USER`: Compose renders the config that gives it
`named_collection_control` (the `configs:` block in `docker-compose.yml`), so it is not a fixed
name in the repository. Changing it needs a recreated container (`docker compose up -d --force-recreate clickhouse`).

`s3()` uses the named collection `ksei_s3`, defined in
`infra/clickhouse/config.d/named_collections.xml` from environment variables. After
changing S3 credentials, recreate the clickhouse container.

## CI

`.github/workflows/ci.yml` runs on every pull request and on every push to `main`. Each step is a Makefile
target (a test checks that nothing else is in the workflow), so any failure is reproduced locally by the same
command. Versions of the actions and of the scanners: [versions.md](versions.md).

| Job | What it runs | Locally |
|---|---|---|
| `lint` | ruff and sqlfluff | `make lint` |
| `test` | unit tests, coverage gate of 90%, and a check that the generated dbt fixtures are current | `make test` |
| `test-dags` | the DAG tests, inside the Airflow image | `make test-dags` |
| `images` | builds the Airflow and Superset images, then trivy over them (reports fixable HIGH and CRITICAL; `TRIVY_EXIT_CODE=1` makes them fail) | `make images PROFILE=full`, `make scan-images` |
| `secrets` | gitleaks over the whole git history | `make scan-secrets` |
| `integration` | `make env`, `make up PROFILE=full`, smoke tests, integration tests, dbt unit tests; the logs of a failed run are kept as an artifact | the same commands |

- **dbt in CI.** The integration tests build the dbt models on synthetic periods and check that a rerun and
  a full rebuild leave every table identical, so a separate `make dbt-build` on an empty warehouse adds nothing
  and is not run; `make dbt-test` (the dbt unit tests) runs after them.
- **The `.env`** of a run is made by `make env` (random secrets from `.env.example`); no secret is stored in GitHub.
- **Resources.** The stack with Superset needs about 8 GB of RAM. A public repository's runner has 16 GB, a
  private one 7 GB, which is not enough: leave out `PROFILE=full` in the `integration` job then.
- **The period calendar** is downloaded by `period-init` from `PERIOD_SOURCE_URL` every time the stack starts
  in CI, so the `integration` job needs that file to be reachable.
- **Branch protection** is a GitHub setting, not a file. Settings, Branches, a rule for `main`: require a pull
  request, and require the status checks `lint`, `test`, `test-dags`, `images`, `secrets` and `integration`
  to pass before merging.
- **Check the workflow itself** (not part of CI):
  `docker run --rm -v "$PWD:/repo:ro" -w /repo rhysd/actionlint:1.7.12 .github/workflows/ci.yml`.
- The badge in the README points to `https://github.com/juliuschaesar-dev/ksei-holding-pipeline/actions/workflows/ci.yml`.

## Superset

- The dashboard, its two gold datasets and the ClickHouse connection are imported from
  `superset/assets/` every time the container starts; nothing is configured by hand. The
  connection password comes from `.env` (`provision_connection.py`), never from the repository.
- To change the dashboard: edit it in the UI, run `make superset-export`, commit the diff.
- To start Superset from scratch, stop it and recreate its metadata database
  (`DROP DATABASE superset; CREATE DATABASE superset;` in Postgres), then `make up PROFILE=full`.
- The ClickHouse dialect is named `clickhousedb` (not `clickhouse+connect`).
- The charts that show a single period filter on the gold column `is_latest_period = 1`. Only the
  "Change since peak" card still has a subquery (the highest share of the whole market), which Superset
  allows only with the `ALLOW_ADHOC_SUBQUERY` feature flag (set in `superset_config.py`).
- Two security settings are loosened in `superset_config.py` for the "Largest holder group" card, a
  Handlebars chart: the content security policy allows `unsafe-eval` in `script-src` (the chart compiles its
  template in the browser; scripts still need the page's nonce), and HTML in charts may carry a `style`
  attribute (no `<style>` tags, no scripts). The smoke test `test_the_policy_lets_handlebars_charts_run...`
  checks the first. Remove both, and turn the card into a Big Number, to go back to the default policy.
- "Download as Image" lays each card out at the height of its content, not the height of the layout, so
  cards of one row came out uneven. The dashboard CSS therefore gives the small rows a shared minimum height
  (chart cards 224px = 28 grid units, as in the layout; the title card 234px, because the export draws a chart
  card 10px taller than its minimum and a Markdown card exactly at it). If you change those heights in the
  layout, change the CSS with them. On screen the title card is therefore 10px taller than its slot, so its
  bottom corners are cut square.
- The Superset image copies `superset/assets/` when it is built: after `make superset-export`, rebuild it
  (`docker compose --profile full up -d --build superset`) or the old assets are imported again.
- Exports do not keep a chart's saved `query_context`: it embeds the numeric dataset id of the
  instance it came from and would point at the wrong dataset after an import.

## dbt

- `make dbt-test`: unit tests (small inline fixtures) and data tests, on the models already built.
- `make dbt-build`: builds silver and gold from the real bronze tables (what the DAG does).
- Hubs and links are insert-only; satellites only append rows and flip their two flags. A new payload column is appended (`on_schema_change:
  append_new_columns`), but renaming or dropping one needs `--full-refresh` on that model,
  which also reloads its history from bronze with fresh load timestamps.
- `assert_every_held_security_exists_in_the_master_file` warns by design: about 280 codes appear
  only in the holding file.
- KSEI sometimes uses one code for two ISINs (two SRBI). The master satellite keeps both
  (multi-active on `isin_code`); `fact_security_monthly` keeps the lowest ISIN because the holding file
  has no ISIN.

## Generated dbt fixtures

`dbt/models/silver/_silver_unit_tests.yml` and `dbt/models/gold/_gold_unit_tests.yml` hold MD5
hashes and are generated by `tools/generate_dbt_unit_tests.py`; do not edit them by hand. After
changing a vault model, its payload or the hash rules, run `make dbt-fixtures` and commit the
result. `tests/unit/test_generated_fixtures.py` fails when they are out of date.


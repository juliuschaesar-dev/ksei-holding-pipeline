SHELL := /bin/bash
PROFILE ?=
SERVICE ?=
COMPOSE := docker compose $(if $(PROFILE),--profile $(PROFILE),)
# dbt runs in the Airflow image's own virtualenv; tools/dbt.py is the one place that builds the command
DBT := uv run python tools/dbt.py

# dbt unit-test files that hold MD5 hashes are generated; run this after changing a vault model.
.PHONY: env up down logs logs-dump images scan-secrets scan-images lint test test-dags test-integration test-smoke dbt-test dbt-build dbt-docs superset-export dbt-fixtures clean

# A .env with random secrets, made from .env.example; it never overwrites an existing .env.
env:
	uv run python tools/make_env.py

up:
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f $(SERVICE)

# Every service's log in one file, for the CI artifact of a failed run.
logs-dump:
	$(COMPOSE) logs --no-color --timestamps > compose.log 2>&1

# Build the images of the stack (the Superset image too with PROFILE=full).
images:
	$(COMPOSE) build

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run sqlfluff lint dbt

test:
	uv run pytest -m "not integration and not smoke" --cov

# DAG tests need Airflow, so they run inside the Airflow image against the working tree.
test-dags:
	$(COMPOSE) build airflow-init
	docker run --rm -v "$(CURDIR):/workspace" -w /workspace -e PYTHONPATH=/workspace/src \
		-e AIRFLOW__CORE__LOAD_EXAMPLES=false --entrypoint bash ksei-airflow:local -c \
		"uv pip install -q pytest==9.1.1 && python -m pytest tests/dags -q -p no:cacheprovider"

test-integration:
	uv run pytest -m integration

test-smoke:
	uv run pytest -m smoke

# Unit tests (small inline fixtures) and data tests, on the models already built from bronze.
dbt-test:
	$(DBT) test

# Silver and gold from the real bronze tables, with their data tests (what the DAG runs).
dbt-build:
	$(DBT) build --exclude "test_type:unit"

dbt-fixtures:
	uv run python tools/generate_dbt_unit_tests.py

dbt-docs:
	$(DBT) docs generate

# Re-export the dashboard after editing it in the Superset UI (needs `make up PROFILE=full`).
superset-export:
	uv run python superset/export_assets.py

# Scanners run from pinned images (their versions are in docs/versions.md). Gitleaks reads the whole git
# history; it runs as the owner of the checkout, or git refuses the directory. Trivy reads an image
# saved to a file, so no container gets the Docker socket. Only images built here (ksei-*) are scanned.
GITLEAKS := zricethezav/gitleaks:v8.30.1
TRIVY := aquasec/trivy:0.76.0
# Report only by default: the upstream Superset image carries many fixable findings we cannot patch.
# Make them fail the run with `make scan-images TRIVY_EXIT_CODE=1`.
TRIVY_EXIT_CODE ?= 0

scan-secrets:
	docker run --rm --user "$$(id -u):$$(id -g)" -v "$(CURDIR):/repo" $(GITLEAKS) git /repo --redact

scan-images:
	mkdir -p .trivy
	for image in $$(docker compose --profile full config --images | grep '^ksei-' | sort -u); do 		docker save "$$image" -o .trivy/image.tar || exit 1; 		docker run --rm -v "$(CURDIR)/.trivy:/scan:ro" $(TRIVY) image --input /scan/image.tar 			--timeout 20m --severity HIGH,CRITICAL --ignore-unfixed --exit-code $(TRIVY_EXIT_CODE) || exit 1; 	done

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov dbt/target dbt/logs .trivy compose.log

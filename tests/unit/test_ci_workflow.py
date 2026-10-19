"""The CI workflow only calls Makefile targets, pins what it uses and covers what Phase 7 lists."""

import re

import pytest

from tests.unit.workflows import (
    ROOT,
    actions_used,
    header,
    jobs,
    make_targets,
    run_lines,
    text,
)

pytestmark = pytest.mark.unit

CI = "ci.yml"
REPOSITORY = "juliuschaesar-dev/ksei-holding-pipeline"


def test_the_workflow_runs_on_pull_requests_and_on_pushes_to_main() -> None:
    triggers = header(CI)

    assert re.search(r"(?m)^  pull_request:", triggers)
    assert re.search(r"(?m)^  push:", triggers)
    assert re.search(r"branches:\s*\[main\]", triggers)


def test_every_run_step_is_a_make_call_so_no_logic_is_copied_into_the_workflow() -> None:
    commands = run_lines(text(CI))

    assert commands, "the workflow has no run steps"
    assert [c for c in commands if not c.startswith("make ")] == []


def test_every_make_target_the_workflow_calls_exists_in_the_makefile() -> None:
    called = {c.split()[1] for c in run_lines(text(CI))}

    assert called <= make_targets(), called - make_targets()


def test_every_action_is_pinned_to_a_full_version() -> None:
    used = actions_used(CI)

    assert used
    assert [u for u in used if not re.search(r"@v\d+\.\d+\.\d+$", u)] == []


def test_the_pinned_actions_are_recorded_in_docs_versions() -> None:
    versions = (ROOT / "docs" / "versions.md").read_text(encoding="utf-8")

    assert [u for u in sorted(actions_used(CI)) if u not in versions] == []


def test_the_workflow_has_a_job_for_every_check_the_plan_lists() -> None:
    assert {"lint", "test", "test-dags", "images", "secrets", "integration"} <= set(jobs(CI))


@pytest.mark.parametrize(
    ("job", "target"),
    [
        ("lint", "make lint"),
        ("test", "make test"),
        ("test-dags", "make test-dags"),
        ("images", "make scan-images"),
        ("secrets", "make scan-secrets"),
    ],
)
def test_each_check_job_runs_its_make_target(job: str, target: str) -> None:
    assert target in run_lines(jobs(CI)[job])


def test_the_images_are_built_before_they_are_scanned() -> None:
    commands = run_lines(jobs(CI)["images"])

    assert commands.index("make images PROFILE=full") < commands.index("make scan-images")


def test_the_integration_job_brings_the_stack_up_then_runs_smoke_integration_and_dbt_tests() -> (
    None
):
    commands = run_lines(jobs(CI)["integration"])
    expected = [
        "make env",
        "make up PROFILE=full",
        "make test-smoke",
        "make test-integration",
        "make dbt-test",
    ]

    assert [c for c in commands if c in expected] == expected


def test_the_integration_job_keeps_the_logs_of_a_failed_run() -> None:
    block = jobs(CI)["integration"]

    assert "make logs-dump" in run_lines(block)
    assert re.search(r"if:\s*failure\(\)", block)


def test_secrets_are_scanned_over_the_whole_history() -> None:
    assert re.search(r"fetch-depth:\s*0", jobs(CI)["secrets"])


def test_the_workflow_asks_for_read_access_only() -> None:
    assert re.search(r"(?m)^permissions:\n  contents: read$", text(CI))


def test_a_new_push_cancels_the_run_it_replaces() -> None:
    assert "cancel-in-progress: true" in text(CI)


def test_the_readme_badge_shows_this_workflow_of_this_repository() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"https://github.com/{REPOSITORY}/actions/workflows/ci.yml/badge.svg" in readme
    assert f"https://github.com/{REPOSITORY}/actions/workflows/ci.yml" in readme


def test_no_compose_file_or_dockerfile_uses_a_latest_tag() -> None:
    files = [ROOT / "docker-compose.yml", *ROOT.glob("**/Dockerfile")]
    skipped = {".venv", "target", "node_modules"}
    files = [f for f in files if not skipped & set(f.relative_to(ROOT).parts)]

    offenders = [
        f.name
        for f in files
        if re.search(r"(?m)^\s*(image:|FROM)\s+\S+:latest\b", f.read_text("utf-8"))
    ]

    assert offenders == []


def test_the_image_scan_only_reports_unless_asked_to_fail() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "TRIVY_EXIT_CODE ?= 0" in makefile
    assert "--exit-code $(TRIVY_EXIT_CODE)" in makefile

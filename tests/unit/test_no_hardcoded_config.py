"""Values that live in .env must come from variables, never from literals in the repository."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
# Variables whose values identify a credential or an account: passwords, keys, users, buckets.
SECRET = re.compile(r"(PASSWORD|SECRET|KEY|FERNET)")
USER = re.compile(r"(_USER$|_USERNAME$)")
BUCKET = re.compile(r"BUCKET")
SENSITIVE = re.compile(f"{SECRET.pattern}|{USER.pattern}|{BUCKET.pattern}")
SKIPPED_DIRS = {".venv", ".git", "target", "logs", "__pycache__", ".pytest_cache", ".ruff_cache"}
SCANNED_SUFFIXES = {".py", ".sql", ".yml", ".yaml", ".sh", ".xml", ".toml", ".json", ".cfg"}
SCANNED_NAMES = {"Makefile", "Dockerfile"}
# Files that are the home of configuration or that only describe it.
# make_env.py only describes configuration: it has to know the marker (`change-me`) that
# .env.example puts in front of every value to be replaced, and it writes no value of its own.
SKIPPED_FILES = {
    ".env",
    ".env.example",
    "uv.lock",
    "test_no_hardcoded_config.py",
    "make_env.py",
}


def configured_values() -> dict[str, str]:
    """Sensitive values from .env.example and, when present, from the local .env."""
    values: dict[str, str] = {}
    for name in (".env.example", ".env"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and not line.startswith("#") and SENSITIVE.search(key) and len(value) >= 5:
                values[key] = value
    return values


def repository_files() -> list[Path]:
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or SKIPPED_DIRS & set(path.relative_to(ROOT).parts):
            continue
        if path.name in SKIPPED_FILES:
            continue
        if path.suffix in SCANNED_SUFFIXES or path.name in SCANNED_NAMES:
            files.append(path)
    return files


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def literal_hits(variable: str, value: str, text: str) -> list[str]:
    """Lines where the value is written out as a credential, account or bucket."""
    v = re.escape(value)
    if SECRET.search(variable):
        patterns = [v]  # a secret must not appear anywhere
    elif USER.search(variable):
        patterns = [
            rf"://{v}[:@]",  # user in a connection URI
            rf"<{v}>",  # an XML element named after the user
            rf"(?i)(user|username|login)['\"]?\s*[:=]\s*['\"]?{v}",
            rf"--username\s+{v}",
            rf"-U\s+{v}",
            rf"(?i)(user|login).*['\"]{v}['\"]",  # a quoted literal on a line about users
        ]
    else:
        patterns = [rf"['\"]{v}['\"]", rf"s3://{v}"]
    return [
        line.strip()
        for line in text.splitlines()
        if any(re.search(pattern, line) for pattern in patterns)
    ]


def test_the_env_files_define_sensitive_values_to_check() -> None:
    assert len(configured_values()) >= 8


@pytest.mark.parametrize("variable", sorted(configured_values()))
def test_a_configured_value_is_not_hard_coded_anywhere(variable: str) -> None:
    value = configured_values()[variable]
    hits = {
        str(path.relative_to(ROOT)): found
        for path in repository_files()
        if (found := literal_hits(variable, value, read(path)))
    }

    assert hits == {}, f"{variable}={value!r} is written literally: {hits}"


def test_compose_names_the_clickhouse_admin_user_from_the_variable() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "<${CLICKHOUSE_ADMIN_USER}>" in compose
    assert not (ROOT / "infra" / "clickhouse" / "users.d").exists()

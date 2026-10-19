"""Write a .env from .env.example with random secrets: `make env`, for local runs and for CI.

Every `change-me...` value of the example becomes its own random value. A value that is not a
placeholder (a host, a bucket, a user agent, a URL) is copied as it is. An existing .env is never
overwritten.

    uv run python tools/make_env.py
"""

import base64
import secrets
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = "change-me"
FERNET = "AIRFLOW_FERNET_KEY"


def new_secret() -> str:
    """Letters and digits only, so the value fits in the connection URIs the Compose file builds."""
    return secrets.token_hex(16)


def new_fernet_key() -> str:
    """What Airflow's Fernet key must be: 32 random bytes, URL-safe base64."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def generate(example: str, secret: Callable[[], str], fernet_key: Callable[[], str]) -> str:
    lines = []
    for line in example.splitlines():
        key, separator, value = line.partition("=")
        if separator and not line.startswith("#") and value.startswith(PLACEHOLDER):
            line = f"{key}={fernet_key() if key == FERNET else secret()}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def write_env(root: Path) -> Path:
    target = root / ".env"
    if target.exists():
        raise FileExistsError(f"{target} exists; delete it first if you want a new one")
    example = (root / ".env.example").read_text(encoding="utf-8")
    target.write_text(generate(example, new_secret, new_fernet_key), encoding="utf-8")
    return target


def main(argv: list[str]) -> int:
    try:
        sys.stdout.write(f"wrote {write_env(ROOT)}\n")
    except FileExistsError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

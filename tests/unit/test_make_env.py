"""`make env`: a .env with random secrets from .env.example, for local runs and for CI."""

import base64
from collections.abc import Callable
from itertools import count
from pathlib import Path

import pytest
from tools.make_env import PLACEHOLDER, generate, write_env

pytestmark = pytest.mark.unit

EXAMPLE = f"""# a comment stays

POSTGRES_PASSWORD={PLACEHOLDER}
REDIS_PASSWORD={PLACEHOLDER}
AIRFLOW_FERNET_KEY={PLACEHOLDER}-generate-with-cryptography-fernet
S3_BUCKET=ksei-lake
KSEI_USER_AGENT=ksei/0.1 (portfolio project; contact: you@example.com)
"""


def numbered() -> Callable[[], str]:
    numbers = count(1)
    return lambda: f"secret{next(numbers)}"


def values(text: str) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in text.splitlines() if "=" in line)
    return {key: value for key, value in pairs if not key.startswith("#")}


def test_every_placeholder_becomes_its_own_secret() -> None:
    result = values(generate(EXAMPLE, numbered(), lambda: "fernet-key"))

    assert result["POSTGRES_PASSWORD"] == "secret1"  # noqa: S105 (a test value, not a credential)
    assert result["REDIS_PASSWORD"] == "secret2"  # noqa: S105


def test_the_fernet_key_comes_from_its_own_generator() -> None:
    result = values(generate(EXAMPLE, numbered(), lambda: "fernet-key"))

    assert result["AIRFLOW_FERNET_KEY"] == "fernet-key"


def test_values_that_are_not_placeholders_and_comments_stay_as_they_are() -> None:
    text = generate(EXAMPLE, numbered(), lambda: "fernet-key")

    assert "# a comment stays" in text
    assert "S3_BUCKET=ksei-lake" in text
    assert "KSEI_USER_AGENT=ksei/0.1 (portfolio project; contact: you@example.com)" in text


def test_the_variables_are_the_ones_of_the_example_in_the_same_order() -> None:
    text = generate(EXAMPLE, numbered(), lambda: "fernet-key")

    assert list(values(text)) == list(values(EXAMPLE))


def test_the_real_example_leaves_no_placeholder_behind() -> None:
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")

    text = generate(example, numbered(), lambda: "fernet-key")

    assert PLACEHOLDER not in text


def test_a_generated_fernet_key_is_32_bytes_of_url_safe_base64() -> None:
    from tools.make_env import new_fernet_key

    assert len(base64.urlsafe_b64decode(new_fernet_key())) == 32


def test_generated_secrets_are_letters_and_digits_only_so_they_fit_in_a_connection_uri() -> None:
    from tools.make_env import new_secret

    assert new_secret().isalnum()
    assert new_secret() != new_secret()


def test_write_env_creates_the_file_from_the_example(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(EXAMPLE, encoding="utf-8")

    path = write_env(tmp_path)

    assert path == tmp_path / ".env"
    assert PLACEHOLDER not in path.read_text(encoding="utf-8")


def test_write_env_never_overwrites_an_existing_env(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(EXAMPLE, encoding="utf-8")
    (tmp_path / ".env").write_text("MINE=1\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_env(tmp_path)

    assert (tmp_path / ".env").read_text(encoding="utf-8") == "MINE=1\n"

"""Every environment variable the package reads has one home (.env.example) and reaches Airflow."""

from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from ksei.config import Settings

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


class RecordingEnv(Mapping[str, str]):
    """Answers any variable and remembers which ones were asked for."""

    def __init__(self) -> None:
        self.asked: set[str] = set()

    def __getitem__(self, key: str) -> str:
        self.asked.add(key)
        return "1"

    def __iter__(self) -> Iterator[str]:
        return iter(self.asked)

    def __len__(self) -> int:
        return len(self.asked)


def settings_variables() -> set[str]:
    env = RecordingEnv()
    Settings.from_env(env)
    return env.asked


def test_settings_read_a_known_set_of_variables() -> None:
    assert {"KSEI_BASE_URL", "KSEI_USER_AGENT", "S3_BUCKET"} <= settings_variables()


@pytest.mark.parametrize("name", sorted(settings_variables()))
def test_env_example_lists_every_setting(name: str) -> None:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()

    assert any(line.startswith(f"{name}=") for line in lines)


@pytest.mark.parametrize("name", sorted(settings_variables()))
def test_compose_passes_every_setting_to_airflow(name: str) -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert f"    {name}: ${{{name}}}" in compose

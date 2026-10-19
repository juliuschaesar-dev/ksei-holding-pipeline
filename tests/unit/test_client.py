from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from ksei.client import DownloadError, KseiClient, Link
from ksei.config import DATASETS, Settings
from tests.unit.test_config import ENV

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HOLDING = DATASETS["holding_composition"]
BASE = "https://web.ksei.co.id"
ZIP_URL = f"{BASE}/Download/x.zip"
ARCHIVE = f"{BASE}{HOLDING.archive_path}"
MASTER_ARCHIVE = f"{BASE}{DATASETS['master_securities'].archive_path}"


class FakeTime:
    """Injected clock and sleep: sleeping advances the clock."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


@pytest.fixture
def client(fake_time: FakeTime) -> KseiClient:
    return KseiClient(
        user_agent="test-agent/1.0",
        min_delay_seconds=5.0,
        base_url=BASE,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        max_attempts=3,
        backoff_seconds=2.0,
    )


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def mock_holding_pages() -> None:
    respx.get(ARCHIVE).respond(200, text=fixture_text("archive_holding_2026.html"))
    respx.get(f"{ARCHIVE}/2025").respond(200, text=fixture_text("archive_holding_2025.html"))


@respx.mock
def test_list_links_returns_period_and_absolute_url_for_every_year(client: KseiClient) -> None:
    mock_holding_pages()

    assert client.list_links(HOLDING) == [
        Link(HOLDING.name, date(2025, 12, 30), f"{BASE}/Download/BalanceposEfek20251230.zip"),
        Link(HOLDING.name, date(2026, 8, 31), f"{BASE}/Download/BalanceposEfek20260831.zip"),
        Link(HOLDING.name, date(2026, 9, 30), f"{BASE}/Download/BalanceposEfek20260930.zip"),
    ]


@respx.mock
def test_list_links_ignores_unrelated_links_and_duplicates(client: KseiClient) -> None:
    mock_holding_pages()

    urls = [link.url for link in client.list_links(HOLDING)]

    assert len(urls) == len(set(urls)) == 3
    assert all("Panduan" not in u and "master_securities" not in u for u in urls)


@respx.mock
def test_master_links_match_the_txt_zip_pattern(client: KseiClient) -> None:
    master = DATASETS["master_securities"]
    respx.get(MASTER_ARCHIVE).respond(200, text=fixture_text("archive_master_2026.html"))

    assert [link.url for link in client.list_links(master)] == [
        f"{BASE}/Download/StatisEfek20260930.txt.zip"
    ]


@respx.mock
def test_requests_send_the_descriptive_user_agent(client: KseiClient) -> None:
    route = respx.get(ZIP_URL).respond(200, content=b"zip")

    client.download(ZIP_URL)

    assert route.calls.last.request.headers["user-agent"] == "test-agent/1.0"


@respx.mock
def test_download_returns_the_response_bytes(client: KseiClient) -> None:
    respx.get(ZIP_URL).respond(200, content=b"PK-bytes")

    assert client.download(ZIP_URL) == b"PK-bytes"


@respx.mock
def test_consecutive_requests_are_spaced_by_the_minimum_delay(
    client: KseiClient, fake_time: FakeTime
) -> None:
    respx.get(ZIP_URL).respond(200, content=b"a")

    client.download(ZIP_URL)
    fake_time.now += 1.0
    client.download(ZIP_URL)

    # the first request also waits (the client may be a fresh process after another task)
    assert fake_time.sleeps == [pytest.approx(5.0), pytest.approx(4.0)]


@respx.mock
def test_no_wait_when_the_minimum_delay_has_already_passed(
    client: KseiClient, fake_time: FakeTime
) -> None:
    respx.get(ZIP_URL).respond(200, content=b"a")

    client.download(ZIP_URL)
    fake_time.now += 60.0
    client.download(ZIP_URL)

    assert fake_time.sleeps == [pytest.approx(5.0)]  # only the initial wait


@respx.mock
def test_client_retries_on_5xx_then_succeeds(client: KseiClient) -> None:
    route = respx.get(ZIP_URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(500), httpx.Response(200, content=b"ok")]
    )

    assert client.download(ZIP_URL) == b"ok"
    assert route.call_count == 3


@respx.mock
def test_client_retries_on_timeout_then_succeeds(client: KseiClient) -> None:
    route = respx.get(ZIP_URL).mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, content=b"ok")]
    )

    assert client.download(ZIP_URL) == b"ok"
    assert route.call_count == 2


@respx.mock
def test_retries_wait_at_least_the_minimum_delay_between_attempts(
    client: KseiClient, fake_time: FakeTime
) -> None:
    respx.get(ZIP_URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(503), httpx.Response(200, content=b"ok")]
    )

    client.download(ZIP_URL)

    # backoff is 2s then 4s; both are topped up to the 5s minimum spacing
    assert fake_time.sleeps == [pytest.approx(5.0)] * 3


@respx.mock
def test_backoff_exceeds_the_minimum_delay_when_it_grows_large(
    fake_time: FakeTime,
) -> None:
    client = KseiClient(
        user_agent="t",
        min_delay_seconds=1.0,
        base_url=BASE,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        max_attempts=3,
        backoff_seconds=4.0,
    )
    respx.get(ZIP_URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(503), httpx.Response(200, content=b"ok")]
    )

    client.download(ZIP_URL)

    assert fake_time.sleeps == [pytest.approx(1.0), pytest.approx(4.0), pytest.approx(8.0)]


@respx.mock
def test_client_does_not_retry_on_4xx(client: KseiClient) -> None:
    route = respx.get(ZIP_URL).respond(404)

    with pytest.raises(DownloadError, match="404"):
        client.download(ZIP_URL)

    assert route.call_count == 1


@respx.mock
def test_client_gives_up_after_max_attempts(client: KseiClient) -> None:
    route = respx.get(ZIP_URL).respond(503)

    with pytest.raises(DownloadError, match="3 attempts"):
        client.download(ZIP_URL)

    assert route.call_count == 3


@respx.mock
def test_listing_with_no_matching_links_fails_loudly(client: KseiClient) -> None:
    respx.get(ARCHIVE).respond(200, text="<html><body>nothing here</body></html>")

    with pytest.raises(DownloadError, match="no download links"):
        client.list_links(HOLDING)


@respx.mock
def test_default_settings_survive_four_consecutive_500s(fake_time: FakeTime) -> None:
    # Regression: KSEI's year pages intermittently return 500 several times in a row.
    client = KseiClient("t", 5.0, base_url=BASE, clock=fake_time.clock, sleep=fake_time.sleep)
    respx.get(ZIP_URL).mock(
        side_effect=[httpx.Response(500)] * 4 + [httpx.Response(200, content=b"ok")]
    )

    assert client.download(ZIP_URL) == b"ok"


@respx.mock
def test_client_uses_the_configured_base_url(fake_time: FakeTime) -> None:
    master = DATASETS["master_securities"]
    client = KseiClient(
        "t", 0.0, base_url="http://fixture.local", clock=fake_time.clock, sleep=fake_time.sleep
    )
    respx.get(f"http://fixture.local{master.archive_path}").respond(
        200, text=fixture_text("archive_master_2026.html")
    )

    links = client.list_links(master)

    assert [link.url for link in links] == [
        "http://fixture.local/Download/StatisEfek20260930.txt.zip"
    ]


@respx.mock
def test_client_from_settings_uses_its_user_agent_and_base_url() -> None:
    settings = Settings.from_env(
        {**ENV, "KSEI_USER_AGENT": "from-settings/1", "KSEI_BASE_URL": "http://fixture.local"}
    )
    route = respx.get("http://fixture.local/Download/x.zip").respond(200, content=b"ok")

    KseiClient.from_settings(settings).download("http://fixture.local/Download/x.zip")

    assert route.calls.last.request.headers["user-agent"] == "from-settings/1"

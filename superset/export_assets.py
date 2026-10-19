"""Export the KSEI dashboard from a running Superset into superset/assets/.

Edit the dashboard in the Superset UI, then run `make superset-export` and commit the diff. The
assets are imported again whenever the container starts, so nothing is configured by hand.
"""

import io
import logging
import shutil
import zipfile
from pathlib import Path

import httpx

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "superset" / "assets"
SLUG = "ksei-ownership"


def read_env() -> dict[str, str]:
    lines = (ROOT / ".env").read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))


# Not a real address: the container writes the real URI, from .env, when it starts.
URI_PLACEHOLDER = "clickhousedb://user:XXXXXXXXXX@host/gold"


def _portable(relative: Path, content: bytes) -> bytes:
    """Drop what is tied to one instance or one environment.

    A chart's saved query_context holds the numeric dataset id of the instance it came from, which
    differs after an import; Superset rebuilds it from the chart's params (whose dataset reference
    the import does remap). A database's connection URI holds the account and host from .env, so
    it is replaced by a placeholder and written again from the environment at container start.
    """
    if relative.parts[0] == "databases":
        text = content.decode("utf-8")
        kept = [
            f"sqlalchemy_uri: {URI_PLACEHOLDER}" if line.startswith("sqlalchemy_uri:") else line
            for line in text.splitlines()
        ]
        return ("\n".join(kept) + "\n").encode("utf-8")
    if relative.parts[0] != "charts":
        return content
    kept = []
    skipping = False
    for line in content.decode("utf-8").splitlines():
        if line.startswith("query_context:"):
            kept.append("query_context: null")
            skipping = True  # a long value is folded onto indented continuation lines
        elif skipping and line[:1].isspace():
            continue
        else:
            skipping = False
            kept.append(line)
    return ("\n".join(kept) + "\n").encode("utf-8")


def main() -> None:
    env = read_env()
    client = httpx.Client(base_url="http://localhost:8088", timeout=120)
    token = client.post(
        "/api/v1/security/login",
        json={
            "username": env["SUPERSET_ADMIN_USER"],
            "password": env["SUPERSET_ADMIN_PASSWORD"],
            "provider": "db",
            "refresh": True,
        },
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    dashboard_id = client.get(f"/api/v1/dashboard/{SLUG}").json()["result"]["id"]
    response = client.get("/api/v1/dashboard/export/", params={"q": f"!({dashboard_id})"})
    response.raise_for_status()

    shutil.rmtree(ASSETS, ignore_errors=True)
    ASSETS.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        for name in archive.namelist():
            relative = Path(*Path(name).parts[1:])  # drop the timestamped top folder
            if name.endswith("/") or not relative.parts:
                continue
            target = ASSETS / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_portable(relative, archive.read(name)))
    log.info("exported %s to %s", SLUG, ASSETS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()

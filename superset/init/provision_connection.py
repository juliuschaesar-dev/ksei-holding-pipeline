"""Put the real ClickHouse URI (from the environment) into exported database definitions.

An export masks the connection password, which the import refuses. This runs on a scratch copy of
the assets at container start, so the password never lands in the repository or the image.
"""

import os
import sys
from pathlib import Path


def main(directory: str) -> None:
    uri = (
        f"clickhousedb://{os.environ['CLICKHOUSE_SUPERSET_USER']}"
        f":{os.environ['CLICKHOUSE_SUPERSET_PASSWORD']}"
        f"@{os.environ['CLICKHOUSE_HOST']}:{os.environ['CLICKHOUSE_HTTP_PORT']}/gold"
    )
    for path in Path(directory).glob("*.yaml"):
        lines = path.read_text(encoding="utf-8").splitlines()
        patched = [
            f"sqlalchemy_uri: {uri}" if x.startswith("sqlalchemy_uri:") else x for x in lines
        ]
        path.write_text("\n".join(patched) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])

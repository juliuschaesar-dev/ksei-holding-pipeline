"""Load the period calendar into SeaweedFS and ClickHouse bronze. Idempotent; run by period-init."""

import logging

from ksei.config import Settings
from ksei.period import run_init_period

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_init_period(Settings.from_env())

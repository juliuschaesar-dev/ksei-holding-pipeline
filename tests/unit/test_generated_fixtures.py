"""The dbt unit-test files with MD5 hashes are generated and must not drift from the generator."""

import pytest
from tools.generate_dbt_unit_tests import GENERATED, md5

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("path", list(GENERATED), ids=lambda p: p.name)
def test_a_committed_fixture_file_is_what_the_generator_produces(path) -> None:
    committed = path.read_text(encoding="utf-8")

    assert committed == GENERATED[path](), "run `make dbt-fixtures` and commit the result"


def test_hash_keys_follow_the_vault_rules() -> None:
    # delimiter between parts, so ('AB', 'C') and ('A', 'BC') differ; empty parts become '^^'
    assert md5("AB", "C") != md5("A", "BC")
    assert md5("A", "") == md5("A", "^^")
    assert md5(" A ") == md5("A")  # parts are trimmed

import pytest

import ksei

pytestmark = pytest.mark.unit


def test_package_exposes_version_string() -> None:
    assert isinstance(ksei.__version__, str)
    assert ksei.__version__.count(".") == 2

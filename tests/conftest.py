import pytest

from builders import synthetic_log
from parser import parse_bin


@pytest.fixture(scope="session")
def normal_log_bytes() -> bytes:
    """2 s de log com os 4 grupos, sem rollover."""
    return synthetic_log(2000)


@pytest.fixture
def normal_log(normal_log_bytes):
    return parse_bin(normal_log_bytes)

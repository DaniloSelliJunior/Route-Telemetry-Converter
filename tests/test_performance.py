"""Regressão leve de desempenho com o log sintético do bench_enduro.py (30 min, ~15 MB).

Fora da execução padrão: rode com  pytest -m slow
"""

import time

import pytest

from bench_enduro import gerar_bin
from exporter import write_ld
from ldparser.ldparser import read_ldfile
from parser import parse_file

pytestmark = pytest.mark.slow

MINUTES = 30
# ~2 s numa máquina comum; o add_channel original do upstream levava ~115 s
BUDGET_S = 15.0


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    d = tmp_path_factory.mktemp("bench")
    src, dst = str(d / "bench.bin"), str(d / "bench.ld")
    gerar_bin(src, MINUTES)
    t = time.perf_counter()
    result = parse_file(src)
    write_ld(result, dst)
    return result, time.perf_counter() - t, read_ldfile(dst)[1]


def test_enduro_conversion_stays_within_time_budget(converted):
    _, elapsed, _ = converted
    assert elapsed < BUDGET_S


def test_enduro_log_decodes_every_packet_without_warnings(converted):
    result, _, _ = converted
    assert (result.total_packets, result.warnings) == (558_000, [])


def test_enduro_ld_has_full_length_channels_at_each_rate(converted):
    _, _, chans = converted
    lengths = {c.freq: len(c.data) for c in chans}
    assert (len(chans), lengths) == (23, {200: 360_000, 50: 90_000, 10: 18_000})

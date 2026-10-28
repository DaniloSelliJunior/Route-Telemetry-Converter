"""write_csv: um canal por linha -> nome, unidade, "<freq>Hz", v0, v1, ... (sem linha de cabeçalho)."""

import csv

import pytest

from builders import PERIOD_MS, packet, payload
from exporter import write_csv
from packets import PACKETS
from parser import parse_bin

ALL_CHANNELS = [(pid, k, ch) for pid, d in PACKETS.items() for k, ch in enumerate(d.channels)]


@pytest.fixture
def rows(tmp_path, normal_log):
    path = tmp_path / "log.csv"
    write_csv(normal_log, path)
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def test_one_row_per_channel_in_packet_definition_order(rows):
    assert [r[0] for r in rows] == [ch.name for _, _, ch in ALL_CHANNELS]


def test_row_metadata_has_unit_and_group_rate(rows):
    expected = [[ch.name, ch.unit, f"{PACKETS[pid].freq_hz:g}Hz"] for pid, _, ch in ALL_CHANNELS]
    assert [r[:3] for r in rows] == expected


def test_sample_count_per_row_matches_group_rate_over_log_duration(rows):
    # 2 s de log: última amostra em 1995 / 1980 / 1900 ms
    expected = {200: 400, 50: 100, 10: 20}
    assert [len(r) - 3 for r in rows] == \
           [expected[PACKETS[pid].freq_hz] for pid, _, _ in ALL_CHANNELS]


@pytest.mark.parametrize("pid, k, ch", ALL_CHANNELS, ids=[c.name for _, _, c in ALL_CHANNELS])
def test_values_match_logged_samples_on_regular_log(rows, pid, k, ch):
    row = next(r for r in rows if r[0] == ch.name)
    logged = [payload(pid, t)[k] for t in range(0, 2000, PERIOD_MS[pid])]
    assert [float(v) for v in row[3:]] == logged


def test_values_are_written_with_six_significant_digits(tmp_path):
    path = tmp_path / "x.csv"
    write_csv(parse_bin(packet(0x04, 0, 1234.5678, 1 / 3, 0, 0, 0, 0, 0)), path)
    temp_motor, temp_iat = list(csv.reader(path.open()))[:2]
    assert (temp_motor[3], temp_iat[3]) == ("1234.57", "0.333333")

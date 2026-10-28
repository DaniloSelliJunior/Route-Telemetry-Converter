"""NaN / inf vindos do sensor, grupos sem pacotes e logs com uma única amostra.

O conversor não filtra NaN/inf (limitação documentada); estes testes garantem
que a conversão não quebra e que o valor ruim não "vaza" para longe da amostra.
"""

import csv
import math

import numpy as np
import pytest

from builders import packet, zeros
from exporter import write_csv, write_ld
from parser import parse_bin, resample_uniform

BAD = pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf],
                              ids=["nan", "inf", "-inf"])


@BAD
def test_bad_sample_only_affects_neighbouring_intervals_when_interpolating(bad):
    out = resample_uniform([0, 10, 20, 30, 40], [0.0, bad, 2.0, 3.0, 4.0], 200, 0)
    # grade 0..40 ms de 5 em 5: só 5, 10 e 15 ms dependem da amostra ruim
    assert (~np.isfinite(out)).tolist() == [False, True, True, True] + [False] * 5


@BAD
def test_bad_sample_is_held_only_until_next_sample(bad):
    out = resample_uniform([0, 10, 20], [1.0, bad, 2.0], 200, 0, hold=True)
    assert (~np.isfinite(out)).tolist() == [False, False, True, True, False]


def test_nan_between_two_infinities_does_not_crash():
    out = resample_uniform([0, 10], [-math.inf, math.inf], 200, 0)
    assert math.isnan(out[1])


@BAD
def test_parser_decodes_non_finite_floats_without_warning(bad):
    r = parse_bin(packet(0x01, 0, bad, 0, 0, 0, 0, 0))
    assert (r.warnings, np.isfinite(r.groups[0x01].columns[0][0])) == ([], False)


@pytest.mark.parametrize("bad, text", [(math.nan, "nan"), (math.inf, "inf"),
                                       (-math.inf, "-inf")])
def test_csv_writes_non_finite_values_as_text(tmp_path, bad, text):
    data = packet(0x01, 0, bad, 0, 0, 0, 0, 0) + packet(0x01, 5, 1.0, 0, 0, 0, 0, 0)
    path = tmp_path / "x.csv"
    write_csv(parse_bin(data), path)
    assert next(csv.reader(path.open()))[3] == text


def test_ld_stores_nan_sample(tmp_path):
    from ldparser.ldparser import read_ldfile           # disponível após importar exporter
    data = packet(0x01, 0, math.nan, 0, 0, 0, 0, 0) + packet(0x01, 5, 1.0, 0, 0, 0, 0, 0)
    path = tmp_path / "x.ld"
    write_ld(parse_bin(data), str(path))
    _, chans = read_ldfile(str(path))
    assert math.isnan(chans[0].data[0])


# --- grupos sem pacotes / uma amostra ---------------------------------------

def test_groups_absent_from_log_are_left_out_of_export(tmp_path):
    data = b"".join(packet(0x01, t, *zeros(0x01)) for t in range(0, 100, 5))
    path = tmp_path / "x.csv"
    write_csv(parse_bin(data), path)
    names = [r[0] for r in csv.reader(path.open())]
    assert names == ["Acel_X", "Acel_Y", "Acel_Z", "Gyro_X", "Gyro_Y", "Gyro_Z"]


def test_log_with_single_packet_exports_one_value_per_channel(tmp_path):
    path = tmp_path / "x.csv"
    write_csv(parse_bin(packet(0x04, 123, *zeros(0x04))), path)
    assert [len(r) - 3 for r in csv.reader(path.open())] == [1] * 7


def test_log_with_single_packet_writes_valid_ld(tmp_path):
    from ldparser.ldparser import read_ldfile
    path = tmp_path / "x.ld"
    write_ld(parse_bin(packet(0x04, 123, *zeros(0x04))), str(path))
    _, chans = read_ldfile(str(path))
    assert [len(c.data) for c in chans] == [1] * 7

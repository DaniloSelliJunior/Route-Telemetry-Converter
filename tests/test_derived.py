"""signals e derived: suavização, eventos e canais derivados (Balanço, G combinado...)."""

import math

import numpy as np
import pytest

from builders import packet, synthetic_log, zeros
from derived import DERIVED, brake_balance, compute_derived, throttle_rate
from exporter import resampled_channels, write_ld
from parser import parse_bin
from signals import (cumulative_distance_m, events, fill_nan, interp_to, percentile, rate_of,
                     runs, smooth)


# --- signals -------------------------------------------------------------------

def test_smooth_moving_average_keeps_length_and_constant():
    v = np.array([0, 0, 3, 0, 0], float)
    assert smooth(v, 10, 0.3).tolist() == [0, 1, 1, 1, 0]
    assert smooth(np.full(7, 2.0), 10, 0.5).tolist() == [2.0] * 7
    assert smooth(v, 10, 0.0).tolist() == v.tolist()


def test_runs_and_events_merge_and_min_duration():
    m = np.array([0, 1, 1, 0, 1, 0, 0, 0, 1, 1, 1, 1], bool)
    assert runs(m) == [(1, 3), (4, 5), (8, 12)]
    assert events(m, 10, min_duration_s=0.3, merge_gap_s=0.1) == [(1, 5), (8, 12)]
    assert events(m, 10, min_duration_s=0.4) == [(8, 12)]
    assert runs(np.zeros(3, bool)) == []


def test_interp_fill_percentile_rate_distance():
    assert interp_to([0, 1], [0, 10], [0.5]).tolist() == [5]
    assert interp_to([0, 1], [0, 10], [0.5], hold=True).tolist() == [0]
    assert np.isnan(interp_to([], [], [1.0])).all()
    assert fill_nan([0, 1, 2], [0, math.nan, 4]).tolist() == [0, 2, 4]
    assert percentile([1, 2, math.nan, 3], 50) == 2 and percentile([math.nan], 50) is None
    assert rate_of([0, 0.02, 0.04]) == pytest.approx(50) and math.isnan(rate_of([0]))
    # 36 km/h = 10 m/s por 2 s
    assert cumulative_distance_m([0, 1, 2], [36, 36, 36]).tolist() == [0, 10, 20]


# --- derivados -------------------------------------------------------------------

def test_brake_balance_and_division_by_zero():
    out = brake_balance([60, 0, 3, 10], [40, 0, 1, -10], min_total=5)
    assert out[0] == 60 and np.isnan(out[1:]).all()


def test_throttle_rate_of_ramp():
    thr = np.linspace(0, 100, 51)              # 0 -> 100% em 1 s a 50 Hz
    assert throttle_rate(thr, 50, 0.1)[10:40] == pytest.approx(np.full(30, 100.0))


def _channels(**cols):
    data, units, freqs = {}, {}, {}
    for name, (freq, v, unit) in cols.items():
        v = np.asarray(v, float)
        data[name] = (np.arange(v.size) / freq, v)
        units[name], freqs[name] = unit, freq
    return data, units, freqs


def test_compute_derived_from_available_inputs_only():
    data, units, freqs = _channels(Acel_X=(200, [3, 0], "g"), Acel_Y=(200, [4, 1], "g"))
    ch, u, f = compute_derived(data, units, freqs)
    assert list(ch) == ["G_Combinado"]
    assert ch["G_Combinado"][1].tolist() == [5, 1] and u["G_Combinado"] == "g"
    assert f["G_Combinado"] == 200


def test_compute_derived_subset_and_speed_channels():
    data, units, freqs = _channels(Velocidade=(50, np.full(51, 36.0), "km/h"))
    ch, u, _ = compute_derived(data, units, freqs, names=["Distancia", "Acel_Long_Velocidade"])
    assert ch["Distancia"][1][-1] == pytest.approx(10.0)       # 1 s a 10 m/s
    assert np.allclose(ch["Acel_Long_Velocidade"][1], 0) and u["Acel_Long_Velocidade"] == "g"


def test_derived_names_are_unique_and_do_not_clash_with_log_channels():
    from packets import PACKETS
    names = [d.name for d in DERIVED]
    logged = {c.name for d in PACKETS.values() for c in d.channels}
    assert len(names) == len(set(names)) and not set(names) & logged


def test_full_log_gives_all_derived_and_ld_keeps_23_originals_first(tmp_path):
    from ldparser.ldparser import read_ldfile
    r = parse_bin(synthetic_log(2000))
    data, units, freqs = resampled_channels(r)
    ch, u, f = compute_derived(data, units, freqs)
    assert set(ch) == {d.name for d in DERIVED}
    extra = [(n, u[n], f[n], ch[n][1]) for n in ch]
    path = str(tmp_path / "x.ld")
    write_ld(r, path, extra_channels=extra)
    names = [c.name for c in read_ldfile(path)[1]]
    assert names[:23] == list(data) and names[23:] == list(ch)


def test_resampled_channels_time_axis_matches_rate():
    data, _, freqs = resampled_channels(parse_bin(synthetic_log(1000)))
    t, v = data["Acel_X"]
    assert (freqs["Acel_X"], t[1], len(t)) == (200.0, 0.005, len(v))

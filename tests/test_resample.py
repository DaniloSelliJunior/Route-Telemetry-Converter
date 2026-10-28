"""resample_uniform: grade fixa por grupo, interpolação linear ou hold (canais discretos)."""

import csv

import numpy as np
import pytest

from builders import packet, zeros
from exporter import write_csv
from parser import parse_bin, resample_uniform

BOTH_MODES = pytest.mark.parametrize("hold", [False, True], ids=["linear", "hold"])


# --- grade --------------------------------------------------------------------

@pytest.mark.parametrize("freq, n", [(200, 201), (50, 51), (10, 11)])
def test_grid_has_one_sample_per_period_including_both_ends(freq, n):
    out = resample_uniform([0, 1000], [0.0, 1.0], freq, 0)
    assert len(out) == n


def test_last_partial_period_is_not_extrapolated():
    # último pacote em 1003 ms a 10 Hz: a grade para em 1000 ms
    assert len(resample_uniform([0, 1003], [0.0, 1.0], 10, 0)) == 11


def test_grid_starts_at_given_origin_not_at_first_sample():
    # dado começa em 100 ms, origem comum em 0: 20 pontos antes do primeiro pacote
    assert len(resample_uniform([100, 200], [1.0, 2.0], 200, 0)) == 41


def test_output_is_float64():
    assert resample_uniform([0, 10], [1, 2], 200, 0).dtype == np.float64


# --- interpolação linear (canais contínuos) -----------------------------------

def test_linear_interpolates_between_samples():
    out = resample_uniform([0, 10, 20], [0.0, 1.0, 2.0], 200, 0)
    assert out.tolist() == [0.0, 0.5, 1.0, 1.5, 2.0]


def test_linear_upsampling_from_irregular_event_times():
    out = resample_uniform([0, 3, 20], [0.0, 30.0, 200.0], 200, 0)
    assert out[1:3].tolist() == pytest.approx([50.0, 100.0])   # t=5 e t=10 ms


def test_linear_returns_exact_sample_values_on_grid_points():
    vals = [1.5, -2.25, 7.0]
    assert resample_uniform([0, 5, 10], vals, 200, 0).tolist() == vals


@BOTH_MODES
def test_value_before_first_sample_repeats_first_value(hold):
    out = resample_uniform([20, 30], [7.0, 9.0], 200, 0, hold=hold)
    assert out[:4].tolist() == [7.0] * 4


# --- hold (marcha) ------------------------------------------------------------

@pytest.mark.parametrize("freq", [200, 50, 10])
def test_gear_shift_never_produces_intermediate_value(freq):
    ts = list(range(0, 2000, 20))                       # marcha a 50 Hz
    gear = [2.0 if t < 1003 else 3.0 for t in ts]       # troca entre amostras
    out = resample_uniform(ts, gear, freq, 0, hold=True)
    assert set(out.tolist()) == {2.0, 3.0}


def test_hold_switches_exactly_at_the_new_sample_timestamp():
    out = resample_uniform([0, 20, 40], [2.0, 3.0, 4.0], 200, 0, hold=True)
    assert out.tolist() == [2.0, 2.0, 2.0, 2.0, 3.0, 3.0, 3.0, 3.0, 4.0]


def test_gear_channel_is_held_in_full_export(tmp_path):
    data = b"".join(packet(0x03, t, 8000, 2 if t < 1000 else 3, 0, 0, 0, 0)
                    for t in range(0, 2000, 40))         # 25 Hz: precisa reamostrar
    path = tmp_path / "x.csv"
    write_csv(parse_bin(data), path)
    gear = next(r for r in csv.reader(path.open()) if r[0] == "Marcha")
    assert set(gear[3:]) == {"2", "3"}


# --- timestamps repetidos -----------------------------------------------------

@BOTH_MODES
def test_repeated_timestamp_keeps_last_sample(hold):
    out = resample_uniform([0, 10, 10, 20], [0.0, 1.0, 5.0, 2.0], 100, 0, hold=hold)
    assert out[1] == 5.0


# --- poucas amostras ----------------------------------------------------------

def test_empty_channel_returns_empty_array():
    assert resample_uniform([], [], 200, 0).size == 0


@BOTH_MODES
def test_single_sample_at_origin_gives_single_value(hold):
    assert resample_uniform([0], [4.5], 200, 0, hold=hold).tolist() == [4.5]


@BOTH_MODES
def test_single_sample_after_origin_is_held_from_origin(hold):
    assert resample_uniform([20], [4.5], 200, 0, hold=hold).tolist() == [4.5] * 5


# --- origem de tempo comum ----------------------------------------------------

def test_groups_share_time_origin_of_earliest_packet(tmp_path):
    # IMU (200 Hz) começa em 1000 ms; Motor_Lento (10 Hz) só em 1500 ms
    data = b"".join(packet(0x01, t, *zeros(0x01)) for t in range(1000, 3000, 5))
    data += b"".join(packet(0x04, t, *zeros(0x04)) for t in range(1500, 3000, 100))
    path = tmp_path / "x.csv"
    write_csv(parse_bin(data), path)
    lengths = {r[0]: len(r) - 3 for r in csv.reader(path.open())}
    # t = 0 é 1000 ms para os dois grupos: 0..1995 ms a 200 Hz, 0..1900 ms a 10 Hz
    assert (lengths["Acel_X"], lengths["Temp_Motor"]) == (400, 20)


# --- timestamps fora de ordem (Bug B) ---------------------------------------
# np.interp e np.searchsorted exigem tempo crescente; sem ordenar, o resultado era
# silenciosamente errado (o pico em t=20 ms sumia).

@BOTH_MODES
def test_out_of_order_samples_are_placed_at_their_timestamps(hold):
    out = resample_uniform([0, 20, 10, 30], [0.0, 100.0, 0.0, 0.0], 100, 0, hold=hold)
    assert out.tolist() == [0.0, 0.0, 100.0, 0.0]


@BOTH_MODES
def test_non_adjacent_repeated_timestamp_keeps_last_sample_in_file_order(hold):
    out = resample_uniform([0, 10, 0, 20], [0.0, 1.0, 99.0, 2.0], 100, 0, hold=hold)
    assert out.tolist() == [99.0, 1.0, 2.0]

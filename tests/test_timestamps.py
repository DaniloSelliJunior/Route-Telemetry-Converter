"""unwrap_timestamps: rollover do contador uint32 de ms do ESP32 (~49,7 dias)."""

import numpy as np
import pytest

from builders import U32, synthetic_log
from exporter import write_csv
from parser import parse_bin, unwrap_timestamps


@pytest.mark.parametrize("ts, expected", [
    ([U32 - 10, U32 - 5, 0, 5], [U32 - 10, U32 - 5, U32, U32 + 5]),
    ([U32 - 1, 0], [U32 - 1, U32]),
    ([U32 - 5, 3, 8], [U32 - 5, U32 + 3, U32 + 8]),
], ids=["mid-stream", "adjacent", "lands-off-zero"])
def test_single_rollover_continues_time_past_2_32(ts, expected):
    assert unwrap_timestamps(ts).tolist() == expected


def test_two_rollovers_add_2_32_each_time():
    ts = [U32 - 1, 0, U32 - 1, 0]          # dois estouros (log hipotético > 99 dias)
    assert unwrap_timestamps(ts).tolist() == [U32 - 1, U32, 2 * U32 - 1, 2 * U32]


def test_monotonic_timestamps_are_unchanged():
    ts = [0, 5, 10, 1_000_000, U32 - 1]
    assert unwrap_timestamps(ts).tolist() == ts


@pytest.mark.parametrize("ts", [[100, 95, 110], [5000, 0, 6000]])
def test_small_backward_step_is_not_treated_as_rollover(ts):
    assert unwrap_timestamps(ts).tolist() == ts


def test_counter_reset_is_not_mistaken_for_rollover():
    # reboot do ESP32 (contador volta para ~0 longe do fim da faixa): não é estouro,
    # e o conversor não tenta corrigir (limitação documentada no README)
    assert unwrap_timestamps([1000, 2000, 10, 20]).tolist() == [1000, 2000, 10, 20]


@pytest.mark.parametrize("ts", [[], [U32 - 1]])
def test_zero_or_one_sample_is_returned_as_is(ts):
    assert unwrap_timestamps(ts).tolist() == ts


def test_unwrapped_values_are_int64_to_hold_more_than_32_bits():
    assert unwrap_timestamps([U32 - 1, 0]).dtype == np.int64


def test_log_crossing_rollover_exports_same_csv_as_log_without_it(tmp_path):
    # mesmo conteúdo, só deslocado para atravessar 2**32 no meio do log
    normal, wrapped = tmp_path / "normal.csv", tmp_path / "wrapped.csv"
    write_csv(parse_bin(synthetic_log(2000, start_ms=0)), normal)
    write_csv(parse_bin(synthetic_log(2000, start_ms=U32 - 1000)), wrapped)
    assert wrapped.read_text() == normal.read_text()

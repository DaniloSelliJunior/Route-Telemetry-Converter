"""Funções puras do app.py (resumo exibido na GUI). A interface Flet em si não é testada."""

import pytest

pytest.importorskip("flet")                       # app.py importa flet no topo

from app import fmt_duration, fmt_size, log_duration_s, quality_lines, rates_summary  # noqa: E402
from builders import U32, packet, synthetic_log, zeros   # noqa: E402
from parser import parse_bin                              # noqa: E402


@pytest.mark.parametrize("n, text", [
    (0, "0 B"), (1023, "1023 B"), (1024, "1.0 KB"), (1536, "1.5 KB"),
    (15 * 1024**2, "15.0 MB"), (3 * 1024**3, "3.0 GB"), (5000 * 1024**3, "5000.0 GB"),
])
def test_fmt_size_picks_unit_by_powers_of_1024(n, text):
    assert fmt_size(n) == text


@pytest.mark.parametrize("seconds, text", [
    (0, "0:00 min"), (5, "0:05 min"), (59.4, "0:59 min"), (125, "2:05 min"),
    (1800, "30:00 min"), (3725, "62:05 min"),
])
def test_fmt_duration_formats_minutes_and_zero_padded_seconds(seconds, text):
    assert fmt_duration(seconds) == text


def test_log_duration_is_longest_group_span():
    # synthetic_log(2000): IMU vai até 1995 ms, os outros grupos terminam antes
    assert log_duration_s(parse_bin(synthetic_log(2000))) == 1.995


def test_log_duration_ignores_groups_with_single_packet():
    data = packet(0x01, 0, *zeros(0x01)) + packet(0x04, 0, *zeros(0x04)) \
         + packet(0x04, 500, *zeros(0x04))
    assert log_duration_s(parse_bin(data)) == 0.5


def test_log_duration_of_empty_log_is_zero():
    assert log_duration_s(parse_bin(b"")) == 0.0


def test_log_duration_across_rollover_counts_time_past_2_32():
    # 2 s de log começando 1 s antes do estouro do contador
    assert log_duration_s(parse_bin(synthetic_log(2000, start_ms=U32 - 1000))) == 1.995


def test_quality_lines_are_capped_with_remaining_count():
    rep = {"avisos": [f"a{i}" for i in range(5)]}
    assert quality_lines(rep, limit=3) == ["a0", "a1", "a2", "... e mais 2 aviso(s)."]
    assert quality_lines({"avisos": []}) == []


def test_rates_summary_shows_real_and_nominal_rate_per_group():
    from quality import build_quality_report
    rep = build_quality_report(parse_bin(synthetic_log(2000)))
    assert rates_summary(rep) == ("Chassi_IMU: 200 / 200 Hz  ·  Pedais_Freios: 50 / 50 Hz  ·  "
                                  "Motor_Rapido: 50 / 50 Hz  ·  Motor_Lento: 10 / 10 Hz")


def test_rates_summary_with_single_packet_group():
    from quality import build_quality_report
    rep = build_quality_report(parse_bin(packet(0x04, 0, *zeros(0x04))))
    assert rates_summary(rep) == "Motor_Lento: - / 10 Hz"

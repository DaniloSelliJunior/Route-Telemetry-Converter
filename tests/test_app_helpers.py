"""Funções puras do app.py (resumo exibido na GUI). A interface Flet em si não é testada."""

import pytest

pytest.importorskip("flet")                       # app.py importa flet no topo

from app import (batch_lines, chart_series, fmt_duration, fmt_kpi, fmt_size,  # noqa: E402
                 kpi_table_rows,
                 log_duration_s, quality_lines, rates_summary)
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


def test_batch_lines_one_line_per_file_with_status():
    from pipeline import BatchItem
    items = [BatchItem("/x/a.bin", "ok", ["a.ld", "a_50Hz.csv"], "", 2),
             BatchItem("/x/b.bin", "ok", ["b_seg1.ld", "b_seg2.ld"], "2 segmentos"),
             BatchItem("/x/c.bin", "pulado", [], "já existe: c.ld"),
             BatchItem("/x/d.bin", "erro", [], "Nenhum dado válido")]
    assert batch_lines(items) == ["[OK] a.bin: 2 arquivo(s), 2 aviso(s)",
                                  "[OK] b.bin: 2 arquivo(s) (2 segmentos)",
                                  "[PULADO] c.bin: já existe: c.ld",
                                  "[ERRO] d.bin: Nenhum dado válido"]


@pytest.mark.parametrize("v, text", [(None, "–"), (0.0, "0"), (1 / 3, "0.3333"), (12.345, "12.35"),
                                     (8123.6, "8124"), (-1500.2, "-1500")])
def test_fmt_kpi(v, text):
    assert fmt_kpi(v) == text


def test_kpi_table_rows_with_and_without_comparison():
    from kpi import KPI, KpiResult
    a = [("a", KpiResult([KPI("V", 100.0, "km/h", "sessao"), KPI("V", 90.0, "km/h", "L1")]))]
    b = [("b", KpiResult([KPI("V", 110.0, "km/h", "sessao")]))]
    assert kpi_table_rows(a) == [("V", "100", "km/h")]
    assert kpi_table_rows(a, segment="L1") == [("V", "90", "km/h")]
    assert kpi_table_rows(a, b) == [("V", "100", "km/h", "110", "10", "+10.0%")]
    assert kpi_table_rows(a, b, "L1") == [("V", "90", "km/h", "–", "–", "–")]
    assert kpi_table_rows([]) == []


def test_chart_series_for_native_bar_charts():
    from kpi import KpiResult
    ev = {"sessao": {"tempo_marcha": {"1": 2.0, "2": 3.0},
                     "frenagens": [{"pico_psi": 400.0}, {"pico_psi": 600.0}]}}
    a = KpiResult([], [], ev)
    b = KpiResult([], [], {"sessao": {"tempo_marcha": {"2": 1.0, "3": 4.0}}})
    assert chart_series("tempo_marcha", a) == (["1", "2"], [2.0, 3.0], None)
    assert chart_series("tempo_marcha", a, b) == (["1", "2", "3"], [2.0, 3.0, 0.0], [0.0, 1.0, 4.0])
    assert chart_series("frenagens", a) == (["1", "2"], [400.0, 600.0], None)
    assert chart_series("hist_rpm", a) is None and chart_series("frenagens", b) is None

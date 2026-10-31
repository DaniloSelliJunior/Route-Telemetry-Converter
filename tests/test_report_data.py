"""report_data: dados dos gráficos e tabelas do relatório (sem matplotlib)."""

import report_data as rd
from kpi import KPI, SESSION, KpiResult
from pipeline import SessionMeta, load_log

EV = {SESSION: {
    "hist_rpm": {"bordas": [4000.0, 5000.0, 6000.0], "pct": [25.0, 75.0]},
    "hist_acelerador": {"bordas": [0.0, 10.0, 20.0], "pct": [60.0, 40.0]},
    "tempo_marcha": {"0": 1.0, "2": 5.0, "1": 2.0},
    "frenagens": [{"inicio_s": 1.0, "fim_s": 2.0, "duracao_s": 1.0, "pico_psi": 400.0,
                   "balanco_medio_pct": 60.0}],
    "gg": {"longitudinal": [0.1, -0.5], "lateral": [1.0, 0.2], "unidade": "g", "referencia": 1.2},
    "oleo_rpm": {"rpm": [3000.0, 5000.0], "pressao": [2.0, 3.5], "unidade": "bar",
                 "faixas": [{"rpm_de": 2000.0, "rpm_ate": 4000.0, "min": 2.0}]},
}}
RES = KpiResult([KPI("Velocidade_Max", 100.0, "km/h", SESSION), KPI("Velocidade_Max", 90.0, "km/h", "V1"),
                 KPI("Frenagem_Pico_Max", 400.0, "PSI", SESSION)], ["aviso <x>"], EV)


# --- report_data (sem matplotlib) -------------------------------------------------

def test_fmt_value():
    assert [rd.fmt_value(v) for v in (None, 0.5, 8123.4)] == ["–", "0.5", "8123"]


def test_hist_and_gear_bars():
    assert rd.hist_bars(RES, "hist_rpm") == (["4-5k", "5-6k"], [25.0, 75.0])
    assert rd.hist_bars(RES, "hist_acelerador") == (["0-10", "10-20"], [60.0, 40.0])
    assert rd.gear_bars(RES) == (["N", "1", "2"], [1.0, 2.0, 5.0])
    assert rd.hist_bars(RES, "hist_rpm", "V1") is None and rd.gear_bars(None) is None


def test_align_bars_fills_missing_labels_with_zero():
    assert rd.align_bars((["1", "2"], [1, 2]), (["2", "3"], [5, 6])) == \
           (["1", "2", "3"], [1, 2, 0.0], [0.0, 5, 6])
    assert rd.align_bars(None, None) is None


def test_kpi_pivot_and_segment_names():
    segs, rows = rd.kpi_pivot(RES)
    assert segs == [SESSION, "V1"]
    assert rows[0] == ("Velocidade_Max", "km/h", [100.0, 90.0])
    assert rows[1] == ("Frenagem_Pico_Max", "PSI", [400.0, None])
    assert rd.segment_names([("a", RES)]) == [SESSION, "V1"]


def test_events_accessors():
    assert rd.braking(RES)[0]["pico_psi"] == 400 and rd.braking(RES, "V1") == []
    assert rd.gg_points(RES)["referencia"] == 1.2 and rd.oil_points(RES)["unidade"] == "bar"


def test_session_summary(tmp_path):
    from builders import synthetic_log
    p = tmp_path / "s.bin"
    p.write_bytes(synthetic_log(2000))
    summary = dict(rd.session_summary(load_log(str(p)), SessionMeta(piloto="Ana")))
    assert (summary["Arquivo"], summary["Piloto"], summary["Duração"], summary["Pacotes"]) == \
           ("s.bin", "Ana", "0:02 min", "620")

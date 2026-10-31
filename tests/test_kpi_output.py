"""Saídas dos KPIs: CSV longo, JSON com metadados/limiares/qualidade e comparação (deltas)."""

import csv
import json

import pytest

from builders import synthetic_log
from kpi import KPI, KpiResult, merge_config
from kpi.output import (COMPARE_COLUMNS, CSV_COLUMNS, compare, kpi_rows, kpis_document,
                        write_comparison_csv, write_kpis_csv)
from pipeline import (SessionMeta, comparison_path, compute_log_kpis, kpi_paths, load_log,
                      session_names, write_comparison, write_kpi_outputs, write_ld_outputs)


def res(*kpis, avisos=(), eventos=None):
    return KpiResult([KPI(*k) for k in kpis], list(avisos), eventos or {})


A = [("log", res(("Velocidade_Max", 100.0, "km/h", "sessao"), ("Frenagens_Numero", 4.0, "", "sessao"),
                 ("Velocidade_Max", 90.0, "km/h", "Volta 1")))]
B = [("log2", res(("Velocidade_Max", 110.0, "km/h", "sessao"), ("Frenagens_Numero", 0.0, "", "sessao"),
                  ("Tempo_0_75m_Melhor", 4.5, "s", "sessao")))]


def test_long_csv_columns_and_rows(tmp_path):
    p = tmp_path / "k.csv"
    write_kpis_csv(p, A)
    rows = list(csv.reader(p.open(encoding="utf-8")))
    assert rows[0] == CSV_COLUMNS == ["sessao", "segmento", "kpi", "valor", "unidade"]
    assert rows[1:] == [["log", "sessao", "Velocidade_Max", "100", "km/h"],
                        ["log", "sessao", "Frenagens_Numero", "4", ""],
                        ["log", "Volta 1", "Velocidade_Max", "90", "km/h"]]


def test_long_csv_excel_br_profile(tmp_path):
    p = tmp_path / "k.csv"
    write_kpis_csv(p, [("s", res(("X", 1.25, "s", "sessao")))], "excel_br")
    assert p.read_bytes().decode("utf-8-sig").splitlines()[1] == "s;sessao;X;1,25;s"


def test_json_document_has_values_metadata_thresholds_quality_and_version():
    cfg = merge_config()
    ev = {"sessao": {"frenagens": [{"inicio_s": 1.0}], "gg": {"longitudinal": [0.1]}}}
    doc = kpis_document([("log", res(("X", 1.0, "s", "sessao"), avisos=["a"], eventos=ev))],
                        {"piloto": "Ana"}, cfg, {"ok": True})
    json.dumps(doc)
    assert doc["metadados"] == {"piloto": "Ana"} and doc["limiares"] == cfg
    assert doc["limiares_provisorios"] is True and doc["qualidade"] == {"ok": True}
    assert "versao" in doc and doc["sessoes"][0]["kpis"] == [
        {"segmento": "sessao", "kpi": "X", "valor": 1.0, "unidade": "s"}]
    assert doc["sessoes"][0]["avisos"] == ["a"]
    assert doc["sessoes"][0]["eventos"] == {"sessao": {"frenagens": [{"inicio_s": 1.0}]}}


def test_compare_deltas_and_unmatched_kpis():
    rows = compare(A, B)
    by = {(r["segmento"], r["kpi"]): r for r in rows}
    v = by[("sessao", "Velocidade_Max")]
    assert (v["valor_a"], v["valor_b"], v["delta"], v["delta_pct"]) == (100, 110, 10, 10)
    f = by[("sessao", "Frenagens_Numero")]
    assert (f["delta"], f["delta_pct"]) == (-4, -100)
    assert by[("Volta 1", "Velocidade_Max")]["valor_b"] is None
    assert by[("sessao", "Tempo_0_75m_Melhor")]["valor_a"] is None


def test_compare_delta_pct_undefined_when_a_is_zero(tmp_path):
    rows = compare([("a", res(("N", 0.0, "", "sessao")))], [("b", res(("N", 3.0, "", "sessao")))])
    assert (rows[0]["delta"], rows[0]["delta_pct"]) == (3, None)
    p = tmp_path / "c.csv"
    write_comparison_csv(p, rows)
    lines = list(csv.reader(p.open(encoding="utf-8")))
    assert lines == [COMPARE_COLUMNS, ["sessao", "N", "", "0", "3", "3", ""]]


def test_kpi_rows_flatten_sessions():
    assert [r["sessao"] for r in kpi_rows(A + B)] == ["log"] * 3 + ["log2"] * 3


# --- pipeline -------------------------------------------------------------------

@pytest.fixture
def two_logs(tmp_path):
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(synthetic_log(3000))
    b.write_bytes(synthetic_log(2000))
    return load_log(str(a)), load_log(str(b))


def test_pipeline_kpi_files_and_comparison(two_logs, tmp_path):
    la, lb = two_logs
    sa, sb = compute_log_kpis(la), compute_log_kpis(lb)
    assert [n for n, _ in sa] == ["a"]
    out = write_kpi_outputs(la, SessionMeta(piloto="Ana"), sa)
    assert out == kpi_paths(la) == [str(tmp_path / "a_kpis.csv"), str(tmp_path / "a_kpis.json")]
    doc = json.loads(open(out[1], encoding="utf-8").read())
    assert doc["metadados"]["piloto"] == "Ana" and doc["metadados"]["arquivo_origem"] == "a.bin"
    assert doc["qualidade"]["ok"] is True
    cmp_path = write_comparison(la, sa, lb, sb)
    assert cmp_path == comparison_path(la, lb) == str(tmp_path / "a_vs_b_comparacao.csv")
    assert len(list(csv.reader(open(cmp_path, encoding="utf-8")))) > 10


def test_segmented_log_gives_one_kpi_session_per_segment(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(synthetic_log(2000, start_ms=500_000) + synthetic_log(2000))
    log = load_log(str(p))
    assert session_names(log) == ["x_seg1", "x_seg2"]
    assert [n for n, _ in compute_log_kpis(log)] == ["x_seg1", "x_seg2"]


def test_ld_with_and_without_derived_channels(two_logs):
    from ldparser.ldparser import read_ldfile
    la, _ = two_logs
    out = write_ld_outputs(la, SessionMeta())
    assert len(read_ldfile(out[0])[1]) == 23
    out = write_ld_outputs(la, SessionMeta(), include_derived=True)
    names = [c.name for c in read_ldfile(out[0])[1]]
    assert len(names) == 28 and names[23] == "Balanco_Freio_Pct"

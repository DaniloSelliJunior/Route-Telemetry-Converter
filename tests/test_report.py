"""Relatório HTML/PDF e figuras (pulado se o matplotlib não estiver instalado)."""

import re

import numpy as np
import pytest

from builders import packet
from kpi import KpiResult
from pipeline import SessionMeta, compute_log_kpis, load_log, report_paths
from test_report_data import RES

mpl = pytest.importorskip("matplotlib")
import report  # noqa: E402


def inp(b=False):
    return report.ReportInput(summary=[("Arquivo", "a.bin"), ("Piloto", "<Ana>")],
                              quality=None, sessions_a=[("a", RES)], label_a="a",
                              sessions_b=[("b", RES)] if b else None, label_b="b")


def test_charts_built_only_when_data_exists():
    keys = [c.key for c in report.build_charts(RES)]
    assert keys == ["hist_rpm", "hist_acelerador", "tempo_marcha", "frenagens", "gg", "oleo"]
    assert report.build_charts(RES, segment="V1") == []
    assert [c.key for c in report.build_charts(RES, only=("gg",))] == ["gg"]


def test_comparison_charts_have_both_series_in_table():
    c = next(c for c in report.build_charts(RES, RES, "a", "b") if c.key == "tempo_marcha")
    assert c.table[0] == ["Marcha", "a", "b"] and c.table[1][0] == ["N", "1", "1"]


def test_html_is_self_contained_and_escaped(tmp_path):
    path = tmp_path / "r.html"
    report.write_html(path, inp())
    h = path.read_text(encoding="utf-8")
    assert h.startswith("<!doctype html>") and "<script" not in h
    assert not re.search(r'(?:src|href)="(?:https?:)?//', h)
    assert h.count("<svg") == 6 and "&lt;Ana&gt;" in h and "aviso &lt;x&gt;" in h
    for title in ("Resumo da sessão", "Qualidade do log", "KPIs", "Gráficos"):
        assert f"<h2>{title}" in h
    assert "Comparação entre sessões" not in h


def test_html_with_comparison_section(tmp_path):
    path = tmp_path / "r.html"
    report.write_html(path, inp(b=True))
    h = path.read_text(encoding="utf-8")
    assert "<h2>Comparação entre sessões</h2>" in h and "A x B" in h


def test_pdf_is_written(tmp_path):
    path = tmp_path / "r.pdf"
    report.write_pdf(path, inp(b=True))
    data = path.read_bytes()
    # resumo + KPIs + comparação + 6 gráficos
    assert data.startswith(b"%PDF") and data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") >= 9


def test_report_with_no_events_still_renders(tmp_path):
    empty = report.ReportInput([("Arquivo", "x")], None, [("x", KpiResult())], "x")
    report.write_html(tmp_path / "e.html", empty)
    report.write_pdf(tmp_path / "e.pdf", empty)
    assert "Sem dados para gráficos" in (tmp_path / "e.html").read_text(encoding="utf-8")


def test_pipeline_report_from_bin_with_comparison(tmp_path):
    from pipeline import write_report
    t = np.arange(0, 20_000, 20)
    buf = bytearray()
    for ms in t:                                          # 20 s com frenagem e trocas
        v = min(100.0, ms / 100)
        buf += packet(0x02, int(ms), 100.0 if ms < 12_000 else 0.0, 0, 500.0 if ms >= 12_000 else 0.0, 250.0)
        buf += packet(0x03, int(ms), 6000, 1 + int(v // 30), 50.0, 60.0, 10.0, v)
    for ms in range(0, 20_000, 5):
        buf += packet(0x01, ms, 0.3, 0.8, 1.0, 0, 0, 10.0)
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(bytes(buf))
    b.write_bytes(bytes(buf))
    la, lb = load_log(str(a)), load_log(str(b))
    out = write_report(la, SessionMeta(), compute_log_kpis(la), lb, compute_log_kpis(lb))
    assert out == report_paths(la) == [str(tmp_path / "a_relatorio.html"), str(tmp_path / "a_relatorio.pdf")]
    h = open(out[0], encoding="utf-8").read()
    assert "Frenagens" in h and "Comparação entre sessões" in h


def test_invalid_report_format(tmp_path):
    from builders import synthetic_log
    from pipeline import write_report
    p = tmp_path / "s.bin"
    p.write_bytes(synthetic_log(1000))
    log = load_log(str(p))
    with pytest.raises(ValueError, match="Formato de relatório inválido"):
        write_report(log, SessionMeta(), compute_log_kpis(log), formats=("docx",))


def test_dark_style_png_for_gui():
    c = report.build_charts(RES, style="dark", only=("gg",))[0]
    import base64
    assert base64.b64decode(report.figure_png_b64(c.figure))[:8] == b"\x89PNG\r\n\x1a\n"

"""Relatório da sessão em HTML autocontido (e PDF), com gráficos matplotlib.

matplotlib é dependência só do relatório (requirements-report.txt): o núcleo
(parser, CSV, KPIs) continua só com NumPy, e este módulo só importa o
matplotlib quando um gráfico é pedido. Usa matplotlib.figure.Figure direto
(sem pyplot): não abre janela e pode rodar na thread da GUI.

Conteúdo: resumo, qualidade do log, tabela de KPIs, g-g, histogramas (RPM,
acelerador, tempo por marcha), frenagens (pico e balanço), pressão de óleo x
RPM e comparação entre duas sessões. Sem séries temporais (o i2 faz melhor).
"""

import base64
import datetime
import html
import io
import textwrap
from dataclasses import dataclass, field

import numpy as np

import report_data as rd
from exporter import atomic_path
from kpi import SESSION
from kpi.output import compare
from version import __version__

# cores por papel (paleta de referência validada para daltonismo: azul = série A,
# laranja = série B). O vermelho da equipe fica na interface, não nos dados.
STYLES = {
    "light": {"bg": "#fcfcfb", "text": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df",
              "a": "#2a78d6", "b": "#eb6834"},
    "dark": {"bg": "#151920", "text": "#F2F4F7", "muted": "#8B95A5", "grid": "#272D38",
             "a": "#3987e5", "b": "#d95926"},
}


def _style(style) -> dict:
    """Nome em STYLES ou um dict com as mesmas chaves (a GUI passa a paleta ativa)."""
    return STYLES[style] if isinstance(style, str) else style


def matplotlib_available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


def _figure(st, w=6.4, h=3.0, rows=1):
    try:
        from matplotlib.figure import Figure
    except ImportError:
        raise RuntimeError("matplotlib não instalado: pip install -r requirements-report.txt") from None
    fig = Figure(figsize=(w, h), dpi=100, facecolor=st["bg"])
    axes = fig.subplots(rows, 1, squeeze=False)[:, 0]
    for ax in axes:
        ax.set_facecolor(st["bg"])
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(st["grid"])
        ax.tick_params(colors=st["muted"], labelsize=8, length=0)
        ax.grid(axis="y", color=st["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
        ax.yaxis.label.set_color(st["muted"])
        ax.xaxis.label.set_color(st["muted"])
    return fig, axes


def _title(ax, st, text):
    ax.set_title(text, loc="left", fontsize=10, color=st["text"], fontweight="bold")


def _legend(ax, st, markerscale=1.0):
    leg = ax.legend(frameon=False, fontsize=8, loc="upper right", markerscale=markerscale)
    for t in leg.get_texts():
        t.set_color(st["text"])
    for h in leg.legend_handles:
        h.set_alpha(1.0)


def _bar_width(n: int, series: int = 1) -> float:
    """Largura (unidades de dado) que limita cada barra a ~24 px numa figura de 6,4 pol."""
    return min(0.7 / series, 24.0 / (560.0 / max(n, 1)))


def fig_bars(title, ylabel, labels, a, b=None, label_a="A", label_b="B", style="light"):
    """Barras de uma série (sem legenda) ou duas lado a lado (com legenda)."""
    st = _style(style)
    fig, (ax,) = _figure(st)
    x = np.arange(len(labels))
    if b is None:
        ax.bar(x, a, width=_bar_width(len(labels)), color=st["a"])
    else:
        w = _bar_width(len(labels), 2)
        ax.bar(x - w / 2 - 0.01, a, width=w, color=st["a"], label=label_a)
        ax.bar(x + w / 2 + 0.01, b, width=w, color=st["b"], label=label_b)
        _legend(ax, st)
    ax.set_xticks(x, labels, fontsize=8, rotation=45 if len(labels) > 8 else 0,
                  ha="right" if len(labels) > 8 else "center")
    ax.set_ylabel(ylabel, fontsize=8)
    _title(ax, st, title)
    fig.tight_layout()
    return fig


def fig_braking(events: list, unit: str, style="light"):
    """Pico de pressão dianteira (barras) e balanço médio (pontos) por frenagem.

    Dois painéis com eixo próprio, um embaixo do outro (nunca eixo duplo).
    """
    st = _style(style)
    fig, (ax1, ax2) = _figure(st, h=4.6, rows=2)
    x = np.arange(1, len(events) + 1)
    ax1.bar(x, [e["pico_psi"] for e in events], width=_bar_width(len(events)), color=st["a"])
    ax1.set_ylabel(f"Pico [{unit}]", fontsize=8)
    _title(ax1, st, "Frenagens: pico de pressão dianteira")
    bal = [np.nan if e["balanco_medio_pct"] is None else e["balanco_medio_pct"] for e in events]
    ax2.scatter(x, bal, s=36, color=st["a"], edgecolors=st["bg"], linewidths=1.5, zorder=3)
    ax2.axhline(50, color=st["muted"], linewidth=0.8, linestyle="--")
    ax2.set_ylabel("Balanço [%]", fontsize=8)
    ax2.set_xlabel("Frenagem nº", fontsize=8)
    _title(ax2, st, "Balanço médio (pressão dianteira / total; indicativo)")
    for ax in (ax1, ax2):
        ax.set_xticks(x if len(x) <= 30 else x[::max(1, len(x) // 15)])
    fig.tight_layout()
    return fig


def fig_gg(a: dict, b: dict = None, label_a="A", label_b="B", style="light"):
    """Dispersão g-g (lateral x longitudinal) com o círculo de referência."""
    st = _style(style)
    fig, (ax,) = _figure(st, w=4.8, h=4.6)
    ax.grid(axis="x", color=st["grid"], linewidth=0.8)
    for pts, color, label in ((a, st["a"], label_a), (b, st["b"], label_b)):
        if pts:
            ax.scatter(pts["lateral"], pts["longitudinal"], s=4, alpha=0.35, color=color,
                       linewidths=0, rasterized=True, label=label if b else None)
    ref = (a or b).get("referencia")
    if ref:
        th = np.linspace(0, 2 * np.pi, 181)
        ax.plot(ref * np.cos(th), ref * np.sin(th), color=st["muted"], linewidth=0.8,
                linestyle="--")
    unit = (a or b).get("unidade") or ""
    ax.set_xlabel(f"Lateral [{unit}]", fontsize=8)
    ax.set_ylabel(f"Longitudinal [{unit}]", fontsize=8)
    ax.set_aspect("equal", adjustable="datalim")
    if b:
        _legend(ax, st, markerscale=3.0)
    _title(ax, st, "Diagrama g-g (tracejado: referência)")
    fig.tight_layout()
    return fig


def fig_oil(pts: dict, style="light"):
    """Pressão de óleo x RPM (acima da marcha lenta) com o mínimo de cada faixa."""
    st = _style(style)
    fig, (ax,) = _figure(st)
    ax.scatter(pts["rpm"], pts["pressao"], s=6, alpha=0.4, color=st["a"], linewidths=0,
               rasterized=True)
    for f in pts["faixas"]:
        ax.plot([f["rpm_de"], f["rpm_ate"]], [f["min"], f["min"]], color=st["text"], linewidth=2)
    ax.set_xlabel("RPM", fontsize=8)
    ax.set_ylabel(f"Pressão de óleo [{pts['unidade']}]", fontsize=8)
    _title(ax, st, "Pressão de óleo x RPM (traço: mínimo por faixa)")
    fig.tight_layout()
    return fig


def figure_svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", facecolor=fig.get_facecolor())
    text = buf.getvalue()
    return text[text.index("<svg"):]


def figure_png_b64(fig, dpi=110) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=fig.get_facecolor())
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ---- conjunto de gráficos ------------------------------------------------------

@dataclass
class Chart:
    key: str
    figure: object
    caption: str
    table: tuple          # (cabeçalho, linhas) para a visão em tabela


def build_charts(res_a, res_b=None, label_a="A", label_b="B", segment=SESSION,
                 style="light", only=None) -> list:
    """Gráficos disponíveis para o segmento (os sem dados ficam de fora)."""
    out = []
    want = (lambda k: only is None or k in only)
    fmt = rd.fmt_value
    for key, kind, title, ylabel in (("hist_rpm", "hist_rpm", "Tempo por faixa de RPM", "% do tempo (motor ligado)"),
                                     ("hist_acelerador", "hist_acelerador", "Tempo por faixa de acelerador", "% do tempo")):
        if not want(key):
            continue
        a = rd.hist_bars(res_a, kind, segment)
        b = rd.hist_bars(res_b, kind, segment) if res_b else None
        if a is None and b is None:
            continue
        labels, va, vb = rd.align_bars(a, b)
        fig = fig_bars(title, ylabel, labels, va, vb if res_b else None, label_a, label_b, style)
        head = ["Faixa", label_a] + ([label_b] if res_b else [])
        rows = [[lab, fmt(x)] + ([fmt(y)] if res_b else []) for lab, x, y in zip(labels, va, vb)]
        out.append(Chart(key, fig, title + " (%)", (head, rows)))
    if want("tempo_marcha"):
        a, b = rd.gear_bars(res_a, segment), (rd.gear_bars(res_b, segment) if res_b else None)
        if a or b:
            labels, va, vb = rd.align_bars(a, b)
            fig = fig_bars("Tempo por marcha", "s", labels, va, vb if res_b else None,
                           label_a, label_b, style)
            head = ["Marcha", label_a] + ([label_b] if res_b else [])
            rows = [[lab, fmt(x)] + ([fmt(y)] if res_b else []) for lab, x, y in zip(labels, va, vb)]
            out.append(Chart("tempo_marcha", fig, "Tempo por marcha (s; N = neutro)", (head, rows)))
    if want("frenagens"):
        evs = rd.braking(res_a, segment)
        if evs:
            unit = next((k.unidade for k in res_a.kpis if k.nome == "Frenagem_Pico_Max"), "")
            fig = fig_braking(evs, unit, style)
            rows = [[str(i), fmt(e["inicio_s"]), fmt(e["duracao_s"]), fmt(e["pico_psi"]),
                     fmt(e["balanco_medio_pct"])] for i, e in enumerate(evs, 1)]
            out.append(Chart("frenagens", fig, f"Frenagens de {label_a}",
                             (["Nº", "Início [s]", "Duração [s]", f"Pico [{unit}]", "Balanço [%]"], rows)))
    if want("gg"):
        a = rd.gg_points(res_a, segment)
        b = rd.gg_points(res_b, segment) if res_b else None
        if a or b:
            fig = fig_gg(a, b, label_a, label_b, style)
            rows = []
            for lab, res in ((label_a, res_a), (label_b, res_b)):
                if res is None:
                    continue
                for name in ("G_Lateral_P99", "G_Longitudinal_Pos_P99", "G_Longitudinal_Neg_P99",
                             "G_Combinado_P99", "Uso_Circulo_GG_Medio_Pct"):
                    rows.append([lab, name, fmt(res.get(name, segment))])
            out.append(Chart("gg", fig, "Diagrama g-g (pontos amostrados)",
                             (["Sessão", "KPI", "Valor"], rows)))
    if want("oleo"):
        pts = rd.oil_points(res_a, segment)
        if pts:
            fig = fig_oil(pts, style)
            rows = [[f"{f['rpm_de']:.0f}-{f['rpm_ate']:.0f}", fmt(f["min"])] for f in pts["faixas"]]
            out.append(Chart("oleo", fig, f"Pressão de óleo x RPM de {label_a}",
                             (["Faixa de RPM", f"Mínimo [{pts['unidade']}]"], rows)))
    return out


# ---- HTML -----------------------------------------------------------------------

@dataclass
class ReportInput:
    summary: list                       # [(rótulo, valor)]
    quality: dict
    sessions_a: list                    # [(nome, KpiResult)]
    label_a: str
    sessions_b: list = None
    label_b: str = "B"
    notes: list = field(default_factory=list)


CSS = """
:root { --bg:#fcfcfb; --surface:#ffffff; --text:#0b0b0b; --muted:#52514e; --line:#e4e3df;
        --accent:#E4002B; --warn:#8a5a00; --ok:#0a7a0a; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
main { max-width:980px; margin:0 auto; padding:24px 16px 48px; }
header { border-bottom:3px solid var(--accent); padding-bottom:12px; margin-bottom:8px; }
h1 { font-size:22px; margin:0; } h2 { font-size:17px; margin:28px 0 10px; }
h3 { font-size:14px; margin:18px 0 6px; }
.sub { color:var(--muted); font-size:12px; margin:4px 0 0; }
dl { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:8px; margin:0; }
dl div { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:8px 10px; }
dt { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.03em; }
dd { margin:0; font-weight:600; overflow-wrap:anywhere; }
.status { font-weight:600; } .status.ok { color:var(--ok); } .status.warn { color:var(--warn); }
ul { margin:6px 0; padding-left:20px; }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:12.5px; background:var(--surface); }
th, td { border-bottom:1px solid var(--line); padding:4px 8px; text-align:left; white-space:nowrap; }
th { color:var(--muted); font-weight:600; }
td.n { text-align:right; font-variant-numeric:tabular-nums; }
figure { margin:16px 0; background:var(--surface); border:1px solid var(--line);
         border-radius:8px; padding:10px; }
figure svg { width:100%; height:auto; display:block; }
figcaption { color:var(--muted); font-size:12px; margin-top:4px; }
details { margin-top:6px; } summary { cursor:pointer; color:var(--muted); font-size:12px; }
footer { color:var(--muted); font-size:12px; margin-top:32px; border-top:1px solid var(--line);
         padding-top:10px; }
@media print { figure, table { break-inside:avoid; } details { display:none; } }
"""


def _e(x) -> str:
    return html.escape(str(x))


def _table(head, rows, numeric_from=1) -> str:
    th = "".join(f"<th>{_e(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(
        f'<td class="n">{_e(c)}</td>' if i >= numeric_from else f"<td>{_e(c)}</td>"
        for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def _quality_html(q: dict) -> str:
    if not q:
        return "<p>Sem relatório de qualidade.</p>"
    cls, text = ("ok", "Nenhum problema encontrado.") if q["ok"] else \
                ("warn", f"{len(q['avisos'])} aviso(s).")
    parts = [f'<p class="status {cls}">{_e(text)}</p>']
    if q["avisos"]:
        parts.append("<ul>" + "".join(f"<li>{_e(a)}</li>" for a in q["avisos"][:60]) + "</ul>")
    rows = [[name, g["id"], g["pacotes"], f"{g['taxa_nominal_hz']:g}",
             "–" if g["taxa_mediana_hz"] is None else f"{g['taxa_mediana_hz']:g}",
             "–" if g["taxa_media_hz"] is None else f"{g['taxa_media_hz']:g}", g["lacunas"]]
            for name, g in q["grupos"].items()]
    parts.append(_table(["Grupo", "ID", "Pacotes", "Nominal [Hz]", "Mediana [Hz]",
                         "Média [Hz]", "Lacunas"], rows, numeric_from=2))
    d = q["descartes"]
    parts.append(f"<p class=\"sub\">Descartes: {d['bytes']} bytes, {d['pacotes_corrompidos']} "
                 f"pacote(s) vizinhos de dados corrompidos, {d['pacotes_timestamp_isolado']} "
                 f"pacote(s) com timestamp isolado. Segmentos de log: "
                 f"{q['timestamps']['segmentos']}. {_e(q['imu_unidade']['mensagem'])}</p>")
    return "".join(parts)


def _kpi_html(sessions: list) -> str:
    parts = []
    for name, res in sessions:
        segs, rows = rd.kpi_pivot(res)
        if len(sessions) > 1:
            parts.append(f"<h3>{_e(name)}</h3>")
        head = ["KPI", "Unidade"] + ["Sessão inteira" if s == SESSION else s for s in segs]
        parts.append(_table(head, [[k, u] + [rd.fmt_value(v) for v in vals]
                                   for k, u, vals in rows], numeric_from=2))
        if res.avisos:
            parts.append(f"<details><summary>{len(res.avisos)} aviso(s) do cálculo</summary><ul>"
                         + "".join(f"<li>{_e(a)}</li>" for a in res.avisos) + "</ul></details>")
    return "".join(parts)


def _compare_html(inp: ReportInput) -> str:
    rows = compare(inp.sessions_a[:1], inp.sessions_b[:1])
    fmt = rd.fmt_value
    body = [[r["segmento"] if r["segmento"] != SESSION else "Sessão inteira", r["kpi"], r["unidade"],
             fmt(r["valor_a"]), fmt(r["valor_b"]), fmt(r["delta"]),
             "–" if r["delta_pct"] is None else f"{r['delta_pct']:+.1f}%"] for r in rows]
    return (f"<p class=\"sub\">A = {_e(inp.label_a)}, B = {_e(inp.label_b)}; delta = B − A.</p>"
            + _table(["Segmento", "KPI", "Unidade", "A", "B", "Δ", "Δ %"], body, numeric_from=3))


def build_html(inp: ReportInput) -> str:
    res_a = inp.sessions_a[0][1] if inp.sessions_a else None
    res_b = inp.sessions_b[0][1] if inp.sessions_b else None
    charts = build_charts(res_a, res_b, inp.label_a, inp.label_b) if res_a else []
    figs = "".join(
        f"<figure>{figure_svg(c.figure)}<figcaption>{_e(c.caption)}</figcaption>"
        f"<details><summary>Ver dados</summary>{_table(*c.table)}</details></figure>"
        for c in charts) or "<p>Sem dados para gráficos.</p>"
    now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    notes = "".join(f"<p>{_e(n)}</p>" for n in inp.notes)
    summary = "".join(f"<div><dt>{_e(k)}</dt><dd>{_e(v)}</dd></div>" for k, v in inp.summary)
    cmp = f"<section><h2>Comparação entre sessões</h2>{_compare_html(inp)}</section>" if res_b else ""
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relatório de telemetria – {_e(inp.label_a)}</title>
<style>{CSS}</style></head>
<body><main>
<header><h1>Relatório de telemetria</h1>
<p class="sub">Formula Route UFSCar · Route Telemetry Converter {_e(__version__)} · gerado em {now}</p></header>
<section><h2>Resumo da sessão</h2><dl>{summary}</dl></section>
<section><h2>Qualidade do log</h2>{_quality_html(inp.quality)}</section>
<section><h2>KPIs</h2>{_kpi_html(inp.sessions_a)}</section>
<section><h2>Gráficos (sessão inteira{', A x B' if res_b else ''})</h2>{figs}</section>
{cmp}
<footer>Limiares dos KPIs provisórios (ainda não calibrados com logs reais). KPIs de volta,
setor e slip dependem de GPS e sensores que o log atual não tem; voltas e trechos vêm das
marcações manuais. {notes}</footer>
</main></body></html>
"""


def write_html(path, inp: ReportInput):
    text = build_html(inp)
    with atomic_path(path) as tmp:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)


# ---- PDF ------------------------------------------------------------------------

A4 = (8.27, 11.69)


def _text_page(lines: list, title: str):
    from matplotlib.figure import Figure
    fig = Figure(figsize=A4, facecolor="white")
    fig.text(0.07, 0.95, title, fontsize=15, fontweight="bold")
    y = 0.91
    for ln in lines:
        for part in (textwrap.wrap(ln, 105) or [""]):
            fig.text(0.07, y, part, fontsize=8.5, family="DejaVu Sans")
            y -= 0.016
            if y < 0.05:
                return fig
    return fig


def _table_pages(head, rows, title, per_page=48):
    from matplotlib.figure import Figure
    pages = []
    for i in range(0, max(len(rows), 1), per_page):
        chunk = rows[i:i + per_page] or [["–"] * len(head)]
        fig = Figure(figsize=A4, facecolor="white")
        fig.text(0.07, 0.95, title + (f" ({i // per_page + 1})" if len(rows) > per_page else ""),
                 fontsize=13, fontweight="bold")
        ax = fig.add_axes([0.05, 0.04, 0.9, 0.88])
        ax.axis("off")
        rest = (1.0 - 0.34 - 0.08) / max(len(head) - 2, 1)
        widths = ([0.34, 0.08] + [rest] * (len(head) - 2)) if head[1] == "Unidade" else None
        tab = ax.table(cellText=chunk, colLabels=head, loc="upper left", cellLoc="left",
                       colWidths=widths)
        tab.auto_set_font_size(False)
        tab.set_fontsize(7.5)
        tab.scale(1, 1.25)
        for (r, _), cell in tab.get_celld().items():
            cell.set_edgecolor("#e4e3df")
            if r == 0:
                cell.set_text_props(fontweight="bold", color="#52514e")
        pages.append(fig)
    return pages


def write_pdf(path, inp: ReportInput):
    try:
        from matplotlib.backends.backend_pdf import PdfPages
    except ImportError:
        raise RuntimeError("matplotlib não instalado: pip install -r requirements-report.txt") from None
    q = inp.quality or {}
    lines = [f"{k}: {v}" for k, v in inp.summary] + ["", "Qualidade do log:"]
    lines += ([f"  • {a}" for a in q.get("avisos", [])] or ["  Nenhum problema encontrado."])
    if q.get("imu_unidade"):
        lines += ["", q["imu_unidade"]["mensagem"]]
    lines += ["", "Limiares dos KPIs provisórios (ainda não calibrados com logs reais)."] + inp.notes
    pages = [_text_page(lines, "Relatório de telemetria – " + inp.label_a)]
    for name, res in inp.sessions_a:
        segs, rows = rd.kpi_pivot(res)
        segs = segs[:6]
        head = ["KPI", "Unidade"] + ["Sessão" if s == SESSION else s for s in segs]
        body = [[k, u] + [rd.fmt_value(v) for v in vals[:6]] for k, u, vals in rows]
        pages += _table_pages(head, body, f"KPIs – {name}")
    res_a = inp.sessions_a[0][1] if inp.sessions_a else None
    res_b = inp.sessions_b[0][1] if inp.sessions_b else None
    if res_b:
        rows = compare(inp.sessions_a[:1], inp.sessions_b[:1])
        body = [[r["segmento"], r["kpi"], r["unidade"], rd.fmt_value(r["valor_a"]),
                 rd.fmt_value(r["valor_b"]), rd.fmt_value(r["delta"])] for r in rows]
        pages += _table_pages(["Segmento", "KPI", "Unidade", "A", "B", "Δ"], body,
                              f"Comparação: A = {inp.label_a}, B = {inp.label_b}")
    if res_a:
        pages += [c.figure for c in build_charts(res_a, res_b, inp.label_a, inp.label_b)]
    with atomic_path(path) as tmp:
        with PdfPages(tmp) as pdf:
            for fig in pages:
                pdf.savefig(fig)

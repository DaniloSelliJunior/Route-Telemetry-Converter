"""Dados prontos para gráficos e tabelas (sem matplotlib): usados pela GUI e pelo relatório.

Tudo sai dos KpiResult (KPIs + eventos de cada segmento). Nenhuma série
temporal: o i2 faz isso melhor; aqui só distribuições, eventos e dispersões.
"""

import datetime
import os

from kpi import SESSION
from parser import aligned_timestamps


def fmt_value(v) -> str:
    """Valor de KPI para tabelas: inteiro a partir de 1000, senão 4 algarismos; None = "–"."""
    if v is None:
        return "–"
    return f"{v:.0f}" if abs(v) >= 1000 else f"{v:.4g}"


def _events(res, segment):
    return res.eventos.get(segment, {}) if res else {}


def hist_bars(res, kind: str, segment: str = SESSION):
    """("hist_rpm" | "hist_acelerador") -> ([rótulo da faixa], [%]) ou None."""
    h = _events(res, segment).get(kind)
    if not h or not h["pct"]:
        return None
    e = h["bordas"]
    fmt = (lambda a, b: f"{a / 1000:g}-{b / 1000:g}k") if kind == "hist_rpm" else \
          (lambda a, b: f"{a:g}-{b:g}")
    return [fmt(a, b) for a, b in zip(e[:-1], e[1:])], list(h["pct"])


def gear_bars(res, segment: str = SESSION):
    """([marcha, "N" para 0], [s]) ou None."""
    g = _events(res, segment).get("tempo_marcha")
    if not g:
        return None
    keys = sorted(g, key=int)
    return [("N" if k == "0" else k) for k in keys], [g[k] for k in keys]


def braking(res, segment: str = SESSION) -> list:
    return list(_events(res, segment).get("frenagens", []))


def gg_points(res, segment: str = SESSION):
    """dict(longitudinal, lateral, unidade, referencia) ou None."""
    return _events(res, segment).get("gg")


def oil_points(res, segment: str = SESSION):
    """dict(rpm, pressao, faixas, unidade) ou None."""
    return _events(res, segment).get("oleo_rpm")


def align_bars(a, b):
    """Une duas séries de barras (rótulos, valores) pelos rótulos; faltante vira 0."""
    if a is None and b is None:
        return None
    labels = list(a[0]) if a else []
    for lab in (b[0] if b else []):
        if lab not in labels:
            labels.append(lab)
    def pick(s):
        d = dict(zip(*s)) if s else {}
        return [d.get(lab, 0.0) for lab in labels]
    return labels, pick(a), pick(b)


def segment_names(sessions: list) -> list:
    """Segmentos na ordem em que aparecem (sessão inteira primeiro)."""
    out = []
    for _, res in sessions:
        for k in res.kpis:
            if k.segmento not in out:
                out.append(k.segmento)
    return out


def kpi_pivot(res) -> tuple:
    """(segmentos, [(kpi, unidade, [valor por segmento ou None])]) de um KpiResult."""
    segs, rows, index = [], [], {}
    for k in res.kpis:
        if k.segmento not in segs:
            segs.append(k.segmento)
    for k in res.kpis:
        key = k.nome
        if key not in index:
            index[key] = len(rows)
            rows.append((k.nome, k.unidade, [None] * len(segs)))
        rows[index[key]][2][segs.index(k.segmento)] = k.valor
    return segs, rows


def session_summary(log, meta) -> list:
    """[(rótulo, valor)] do resumo da sessão para o relatório."""
    r = log.result
    when = (datetime.datetime.fromtimestamp(r.source_mtime).strftime("%d/%m/%Y %H:%M")
            if r.source_mtime else "–")
    spans = []
    for seg in log.segments:
        all_ts, t0 = aligned_timestamps(seg)
        spans.append(max(int(ts.max()) - t0 for ts in all_ts.values()) / 1000.0)
    return [
        ("Arquivo", os.path.basename(log.path)),
        ("Data do log", when),
        ("Piloto", meta.piloto), ("Veículo", meta.veiculo), ("Local", meta.local),
        ("Evento", meta.evento or "–"), ("Sessão", meta.sessao or "–"),
        ("Duração", f"{int(round(sum(spans))) // 60}:{int(round(sum(spans))) % 60:02d} min"),
        ("Pacotes", f"{r.total_packets:,}".replace(",", ".")),
        ("Segmentos de log", str(len(log.segments))),
    ]

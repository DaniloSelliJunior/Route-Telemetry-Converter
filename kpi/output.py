"""Saídas dos KPIs: kpis.csv (formato longo), kpis.json e comparação entre sessões."""

import csv
import datetime

from csv_export import PROFILES, format_column, write_json
from exporter import atomic_path
from version import __version__

CSV_COLUMNS = ["sessao", "segmento", "kpi", "valor", "unidade"]
COMPARE_COLUMNS = ["segmento", "kpi", "unidade", "valor_a", "valor_b", "delta", "delta_pct"]
# eventos leves que vão no JSON (pontos de g-g/óleo ficam só para os gráficos)
JSON_EVENTS = ("frenagens", "trocas", "arrancadas", "tempo_marcha", "hist_rpm")


def kpi_rows(sessions: list) -> list:
    """sessions: [(nome da sessão, KpiResult)] -> linhas do formato longo."""
    return [{"sessao": name, "segmento": k.segmento, "kpi": k.nome, "valor": k.valor,
             "unidade": k.unidade} for name, res in sessions for k in res.kpis]


def _write_rows(path, header, rows, profile, numeric):
    prof = PROFILES[profile]
    with atomic_path(path) as tmp:
        with open(tmp, "w", newline="", encoding="utf-8-sig" if prof.bom else "utf-8") as f:
            w = csv.writer(f, delimiter=prof.delimiter)
            w.writerow(header)
            for r in rows:
                w.writerow([("" if r[c] is None else format_column([r[c]], prof.decimal)[0])
                            if c in numeric else r[c] for c in header])


def write_kpis_csv(path, sessions: list, profile: str = "padrao"):
    _write_rows(path, CSV_COLUMNS, kpi_rows(sessions), profile, {"valor"})


def kpis_document(sessions: list, metadata: dict = None, config: dict = None,
                  quality: dict = None) -> dict:
    return {
        "versao": __version__,
        "gerado_em": datetime.datetime.now().isoformat(timespec="seconds"),
        "metadados": dict(metadata or {}),
        "limiares": config,
        "limiares_provisorios": True,
        "qualidade": quality,
        "sessoes": [{
            "sessao": name,
            "kpis": [{"segmento": k.segmento, "kpi": k.nome, "valor": k.valor,
                      "unidade": k.unidade} for k in res.kpis],
            "avisos": list(res.avisos),
            "eventos": {seg: {k: v for k, v in ev.items() if k in JSON_EVENTS}
                        for seg, ev in res.eventos.items()},
        } for name, res in sessions],
    }


def write_kpis_json(path, sessions: list, metadata=None, config=None, quality=None):
    write_json(path, kpis_document(sessions, metadata, config, quality))


def compare(sessions_a: list, sessions_b: list) -> list:
    """Deltas B - A por (segmento, kpi), pareando as sessões pela posição (seg1 com seg1).

    KPIs presentes só de um lado aparecem com o outro valor vazio.
    """
    rows = []
    for (_, ra), (_, rb) in zip(sessions_a, sessions_b):
        a = {(k.segmento, k.nome): k for k in ra.kpis}
        b = {(k.segmento, k.nome): k for k in rb.kpis}
        keys = list(a) + [k for k in b if k not in a]
        for key in keys:
            ka, kb = a.get(key), b.get(key)
            va = ka.valor if ka else None
            vb = kb.valor if kb else None
            delta = vb - va if va is not None and vb is not None else None
            rows.append({"segmento": key[0], "kpi": key[1], "unidade": (ka or kb).unidade,
                         "valor_a": va, "valor_b": vb, "delta": delta,
                         "delta_pct": 100.0 * delta / abs(va) if delta is not None and va else None})
    return rows


def write_comparison_csv(path, rows: list, profile: str = "padrao"):
    _write_rows(path, COMPARE_COLUMNS, rows, profile, {"valor_a", "valor_b", "delta", "delta_pct"})

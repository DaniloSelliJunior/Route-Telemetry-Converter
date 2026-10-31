"""compute_kpis: aplica todos os módulos de KPI a cada segmento."""

import math

import numpy as np

from kpi import driver, dynamics, engine, fuel, launch, reliability
from kpi.config import merge_config
from kpi.model import SESSION, Ctx, KpiResult, Segment
from kpi.segments import check_segments

MODULES = (driver, engine, dynamics, reliability, fuel, launch)


def slice_channels(channels: dict, seg: Segment) -> dict:
    """Só as amostras com inicio_s <= t <= fim_s (canais vazios saem)."""
    out = {}
    for name, (t, v) in channels.items():
        t = np.asarray(t, dtype=np.float64)
        m = (t >= seg.inicio_s) & (t <= seg.fim_s)
        if m.any():
            out[name] = (t[m], np.asarray(v, dtype=np.float64)[m])
    return out


def duration_s(channels: dict) -> float:
    ends = [float(np.asarray(t)[-1]) for t, _ in channels.values() if len(t)]
    return max(ends) if ends else 0.0


def compute_kpis(channels: dict, segments: list = None, config: dict = None,
                 units: dict = None) -> KpiResult:
    """KPIs da sessão inteira e de cada segmento marcado.

    channels: {nome: (t_s, valores)} reamostrado (grade do .ld, mais derivados);
    segments: marcações (o log inteiro, "sessao", sempre entra primeiro);
    config: configuração completa (merge_config) ou None para os padrões.
    """
    cfg = config if config is not None else merge_config()
    units = units or {}
    result = KpiResult()
    dur = duration_s(channels)
    marks = list(segments or [])
    result.avisos.extend(check_segments(marks, dur))
    for seg in [Segment(SESSION, 0.0, math.inf)] + marks:
        if seg.inicio_s >= dur and seg.nome != SESSION:
            continue
        sliced = slice_channels(channels, seg)
        if not sliced:
            result.avisos.append(f"[{seg.nome}] sem amostras no trecho.")
            continue
        ctx = Ctx(seg, cfg, units, result.avisos, {})
        for mod in MODULES:
            try:
                mod.compute(sliced, ctx)
            except Exception as ex:        # um KPI com problema não derruba os outros
                ctx.warn(f"falha em {mod.__name__}: {ex}")
        result.kpis.extend(ctx.kpis)
        result.eventos[seg.nome] = ctx.eventos
    return result

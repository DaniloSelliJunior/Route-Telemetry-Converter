"""Consumo de combustível por regressão linear do Nivel_Combustivel.

Nunca pela diferença entre dois pontos: o sinal de nível balança com o carro
(curvas, frenagens) e dois pontos isolados podem errar por muito. O R² e o
desvio dos resíduos indicam se a reta explica o sinal.
"""

import numpy as np


def fit_consumption(t, level):
    """(inclinação L/s, intercepto, R², desvio dos resíduos) dos pontos finitos; None se < 3."""
    t = np.asarray(t, dtype=np.float64)
    level = np.asarray(level, dtype=np.float64)
    fin = np.isfinite(t) & np.isfinite(level)
    t, level = t[fin], level[fin]
    if t.size < 3 or np.ptp(t) == 0:
        return None
    slope, intercept = np.polyfit(t, level, 1)
    resid = level - (slope * t + intercept)
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((level - level.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else (1.0 if ss_res == 0 else 0.0)
    return float(slope), float(intercept), r2, float(np.std(resid))


def compute(ch: dict, ctx) -> None:
    c = ctx.cfg["consumo"]
    if "Nivel_Combustivel" not in ch:
        ctx.missing("Consumo", ["Nivel_Combustivel"])
        return
    t, level = ch["Nivel_Combustivel"]
    dur = float(t[-1] - t[0]) if t.size else 0.0
    if dur < c["duracao_min_s"]:
        ctx.warn(f"Consumo: trecho de {dur:.0f} s, menor que o mínimo de "
                 f"{c['duracao_min_s']:g} s; não calculado.")
        return
    fit = fit_consumption(t, level)
    if fit is None:
        ctx.warn("Consumo: amostras insuficientes de Nivel_Combustivel.")
        return
    slope, _, r2, sd = fit
    unit = ctx.units.get("Nivel_Combustivel", "L")
    ctx.add("Consumo_Combustivel", -slope * 60.0, f"{unit}/min")
    ctx.add("Consumo_Total_Estimado", -slope * dur, unit)
    ctx.add("Consumo_R2", r2, "")
    ctx.add("Consumo_Desvio_Residuos", sd, unit)
    if r2 < c["r2_min"]:
        ctx.warn(f"Consumo: sinal de Nivel_Combustivel muito ruidoso (R² = {r2:.2f} < "
                 f"{c['r2_min']:g}) ou consumo desprezível; use o valor com cautela.")
    if slope > 0:
        ctx.warn("Consumo: o nível subiu no trecho (reabastecimento ou sensor?).")

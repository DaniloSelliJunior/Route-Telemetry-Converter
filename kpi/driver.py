"""KPIs de piloto: acelerador, frenagens e sobreposição freio + acelerador."""

import numpy as np

from derived import brake_balance, throttle_rate
from signals import events, interp_to, percentile, rate_of


def braking_events(t, front, rear, cfg: dict, min_total: float) -> list:
    """Frenagens: Pressao_Freio_Diant acima do limiar por pelo menos a duração mínima.

    Cada evento: início/fim (s), duração (s), pico de pressão dianteira e
    balanço médio (%) durante o evento (None sem pressão traseira).
    """
    f = rate_of(t)
    if not np.isfinite(f):
        return []
    mask = np.nan_to_num(front, nan=-np.inf) > cfg["freio_limiar_psi"]
    bal = brake_balance(front, rear, min_total) if rear is not None else None
    out = []
    for s, e in events(mask, f, cfg["freio_duracao_min_s"], cfg["freio_intervalo_uniao_s"]):
        b = None
        if bal is not None:
            seg = bal[s:e]
            seg = seg[np.isfinite(seg)]
            b = float(seg.mean()) if seg.size else None
        out.append({"inicio_s": float(t[s]), "fim_s": float(t[e - 1]) + 1.0 / f,
                    "duracao_s": (e - s) / f, "pico_psi": float(np.nanmax(front[s:e])),
                    "balanco_medio_pct": b})
    return out


def compute(ch: dict, ctx) -> None:
    c = ctx.cfg["piloto"]
    dcfg = ctx.cfg["derivados"]

    if "Hall_Acelerador" in ch:
        t, thr = ch["Hall_Acelerador"]
        fin = thr[np.isfinite(thr)]
        if fin.size:
            full = 100.0 * np.mean(fin > c["acelerador_pleno_pct"])
            zero = 100.0 * np.mean(fin < c["acelerador_zero_pct"])
            ctx.add("Acelerador_Pleno_Pct", full, "%")
            ctx.add("Acelerador_Zero_Pct", zero, "%")
            ctx.add("Acelerador_Parcial_Pct", 100.0 - full - zero, "%")
        f = rate_of(t)
        if np.isfinite(f):
            rate = throttle_rate(thr, f, dcfg["suavizacao_acelerador_s"])
            app = rate[rate > c["taxa_acelerador_min_pct_s"]]
            ctx.add("Taxa_Aplicacao_Acelerador_Mediana", percentile(app, 50), "%/s")
            ctx.add("Taxa_Aplicacao_Acelerador_P90", percentile(app, 90), "%/s")
    else:
        ctx.missing("Acelerador", ["Hall_Acelerador"])

    if "Pressao_Freio_Diant" in ch:
        t, front = ch["Pressao_Freio_Diant"]
        rear = None
        if "Pressao_Freio_Tras" in ch:
            tr, r = ch["Pressao_Freio_Tras"]
            rear = interp_to(tr, r, t)
        unit = ctx.units.get("Pressao_Freio_Diant", "")
        evs = braking_events(t, front, rear, c, dcfg["balanco_pressao_min_psi"])
        ctx.eventos["frenagens"] = evs
        ctx.add("Frenagens_Numero", len(evs), "")
        if evs:
            peaks = [e["pico_psi"] for e in evs]
            ctx.add("Frenagem_Pico_Medio", np.mean(peaks), unit)
            ctx.add("Frenagem_Pico_Max", np.max(peaks), unit)
            ctx.add("Frenagem_Duracao_Media", np.mean([e["duracao_s"] for e in evs]), "s")
            bals = [e["balanco_medio_pct"] for e in evs if e["balanco_medio_pct"] is not None]
            if bals:
                ctx.add("Frenagem_Balanco_Medio_Pct", np.mean(bals), "%")
        if "Hall_Acelerador" in ch:
            ta, thr = ch["Hall_Acelerador"]
            fr = interp_to(t, front, ta)
            both = (np.nan_to_num(thr, nan=-np.inf) > c["sobreposicao_acelerador_pct"]) & \
                   (np.nan_to_num(fr, nan=-np.inf) > c["freio_limiar_psi"])
            if ta.size:
                ctx.add("Sobreposicao_Freio_Acelerador_Pct", 100.0 * both.mean(), "%")
    else:
        ctx.missing("Frenagens", ["Pressao_Freio_Diant"])

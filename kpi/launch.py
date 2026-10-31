"""Provas curtas: 0-100 km/h e 0-75 m a partir do repouso, integrando a Velocidade.

Arrancada = carro parado (Velocidade < repouso_kmh) por pelo menos
repouso_min_s, seguido de movimento que passa de arrancada_min_kmh antes de
parar de novo. O instante de largada é a última amostra parada. A Velocidade
vem da ECU (provavelmente roda motriz): patinagem infla a distância.
"""

import numpy as np

from signals import fill_nan, rate_of, runs


def _crossing(t, y, i, target):
    """Instante (interpolado) em que y cruza target entre as amostras i-1 e i."""
    if i == 0 or y[i] == y[i - 1]:
        return float(t[i])
    return float(t[i - 1] + (target - y[i - 1]) / (y[i] - y[i - 1]) * (t[i] - t[i - 1]))


def launches(t, speed, cfg: dict) -> list:
    t = np.asarray(t, dtype=np.float64)
    v = fill_nan(t, speed)
    f = rate_of(t)
    if not np.isfinite(f) or not np.isfinite(v).any():
        return []
    rest = v < cfg["repouso_kmh"]
    min_rest = max(1, int(round(cfg["repouso_min_s"] * f)))
    out = []
    for s, e in runs(rest):
        if e - s < min_rest or e >= v.size:
            continue
        start = e - 1                                   # última amostra parada
        stop = np.flatnonzero(rest[e:])
        end = e + int(stop[0]) if stop.size else v.size
        vv, tt = v[start:end], t[start:end]
        if vv.max() < cfg["arrancada_min_kmh"]:
            continue
        dist = np.concatenate(([0.0], np.cumsum((vv[1:] + vv[:-1]) / 2 / 3.6 * np.diff(tt))))
        ev = {"inicio_s": float(t[start]), "vel_max_kmh": float(vv.max()),
              "tempo_0_100_s": None, "tempo_0_75m_s": None, "vel_75m_kmh": None}
        hit = np.flatnonzero(vv >= cfg["alvo_kmh"])
        if hit.size:
            ev["tempo_0_100_s"] = _crossing(tt, vv, int(hit[0]), cfg["alvo_kmh"]) - tt[0]
        hit = np.flatnonzero(dist >= cfg["alvo_distancia_m"])
        if hit.size:
            i = int(hit[0])
            tc = _crossing(tt, dist, i, cfg["alvo_distancia_m"])
            ev["tempo_0_75m_s"] = tc - tt[0]
            ev["vel_75m_kmh"] = float(np.interp(tc, tt, vv))
        out.append(ev)
    return out


def compute(ch: dict, ctx) -> None:
    c = ctx.cfg["arrancada"]
    if "Velocidade" not in ch:
        ctx.missing("Arrancadas", ["Velocidade"])
        return
    t, v = ch["Velocidade"]
    evs = launches(t, v, c)
    ctx.eventos["arrancadas"] = evs
    ctx.add("Arrancadas_Numero", len(evs), "")
    t100 = [e["tempo_0_100_s"] for e in evs if e["tempo_0_100_s"] is not None]
    t75 = [e for e in evs if e["tempo_0_75m_s"] is not None]
    alvo, dist = c["alvo_kmh"], c["alvo_distancia_m"]
    if t100:
        ctx.add(f"Tempo_0_{alvo:g}kmh_Melhor", min(t100), "s")
    if t75:
        best = min(t75, key=lambda e: e["tempo_0_75m_s"])
        ctx.add(f"Tempo_0_{dist:g}m_Melhor", best["tempo_0_75m_s"], "s")
        ctx.add(f"Velocidade_{dist:g}m_Melhor", best["vel_75m_kmh"], ctx.units.get("Velocidade", "km/h"))

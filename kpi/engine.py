"""KPIs de câmbio e motor: tempo por marcha, trocas, RPM nas trocas, histograma de RPM, velocidade."""

import numpy as np

from signals import interp_to, rate_of


def gear_runs(t, gear, min_s: float) -> list:
    """[(marcha, i_inicio, i_fim)] sem as "piscadas": trechos mais curtos que min_s
    são absorvidos e trechos vizinhos de mesma marcha são unidos."""
    g = np.asarray(gear, dtype=np.float64)
    fin = np.isfinite(g)
    if not fin.any():
        return []
    idx = np.arange(g.size)
    g = np.round(np.interp(idx, idx[fin], g[fin])).astype(int)      # NaN: vizinhos finitos
    change = np.flatnonzero(np.diff(g)) + 1
    bounds = np.concatenate(([0], change, [g.size]))
    f = rate_of(t)
    min_n = max(1, int(round(min_s * f))) if np.isfinite(f) else 1
    raw = [(int(g[s]), int(s), int(e)) for s, e in zip(bounds[:-1], bounds[1:])]
    kept = []
    for gear_v, s, e in raw:
        if kept and (e - s < min_n or kept[-1][0] == gear_v):
            kept[-1] = (kept[-1][0], kept[-1][1], e)       # absorve no trecho anterior
        else:
            kept.append((gear_v, s, e))
    # o 1º trecho pode ser curto; une marchas iguais que ficaram vizinhas
    merged = []
    for r in kept:
        if merged and merged[-1][0] == r[0]:
            merged[-1] = (r[0], merged[-1][1], r[2])
        else:
            merged.append(r)
    return merged


def compute(ch: dict, ctx) -> None:
    c = ctx.cfg["motor"]

    if "Marcha" in ch:
        t, gear = ch["Marcha"]
        f = rate_of(t)
        runs = gear_runs(t, gear, c["troca_min_s"])
        times = {}
        for g, s, e in runs:
            times[g] = times.get(g, 0) + (e - s)
        total = sum(times.values())
        dt = 1.0 / f if np.isfinite(f) else 0.0
        ctx.eventos["tempo_marcha"] = {str(g): n * dt for g, n in sorted(times.items())}
        for g, n in sorted(times.items()):
            ctx.add(f"Tempo_Marcha_{g}", n * dt, "s")
            ctx.add(f"Tempo_Marcha_{g}_Pct", 100.0 * n / total, "%")
        shifts = []
        rpm = None
        if "RPM" in ch:
            tr, r = ch["RPM"]
            rpm = interp_to(tr, r, t)
        win = max(1, int(round(c["janela_rpm_troca_s"] * f))) if np.isfinite(f) else 1
        for (g0, _, _), (g1, s, _) in zip(runs[:-1], runs[1:]):
            up = g1 > g0
            ev = {"t_s": float(t[s]), "de": g0, "para": g1, "tipo": "subida" if up else "reducao",
                  "rpm": None}
            if rpm is not None:
                # subida: pico de RPM antes da troca; redução: pico depois (sobregiro)
                w = rpm[max(0, s - win):s] if up else rpm[s:s + win]
                w = w[np.isfinite(w)]
                ev["rpm"] = float(w.max()) if w.size else None
            shifts.append(ev)
        ctx.eventos["trocas"] = shifts
        ups = [e for e in shifts if e["tipo"] == "subida"]
        downs = [e for e in shifts if e["tipo"] == "reducao"]
        ctx.add("Trocas_Numero", len(shifts), "")
        ctx.add("Trocas_Subida", len(ups), "")
        ctx.add("Trocas_Reducao", len(downs), "")
        for name, lst in (("Subida", ups), ("Reducao", downs)):
            vals = [e["rpm"] for e in lst if e["rpm"] is not None]
            if vals:
                ctx.add(f"RPM_Troca_{name}_Media", np.mean(vals), "rpm")
                ctx.add(f"RPM_Troca_{name}_Max", np.max(vals), "rpm")
    else:
        ctx.missing("Câmbio", ["Marcha"])

    if "RPM" in ch:
        _, r = ch["RPM"]
        on = r[np.isfinite(r) & (r > c["rpm_motor_ligado"])]
        if on.size:
            w = c["rpm_hist_faixa"]
            lo = np.floor(on.min() / w) * w
            hi = max(np.ceil(on.max() / w) * w, lo + w)
            if on.max() == hi:
                hi += w
            edges = np.arange(lo, hi + w / 2, w)
            counts, _ = np.histogram(on, edges)
            pct = 100.0 * counts / on.size
            ctx.eventos["hist_rpm"] = {"bordas": edges.tolist(), "pct": pct.tolist()}
            for a, b, p in zip(edges[:-1], edges[1:], pct):
                ctx.add(f"RPM_Hist_{a:.0f}_{b:.0f}_Pct", p, "%")
    else:
        ctx.missing("Histograma de RPM", ["RPM"])

    if "Velocidade" in ch:
        _, v = ch["Velocidade"]
        v = v[np.isfinite(v)]
        if v.size:
            unit = ctx.units.get("Velocidade", "km/h")
            ctx.add("Velocidade_Max", v.max(), unit)
            ctx.add("Velocidade_Media", v.mean(), unit)
            moving = v[v > c["movimento_kmh"]]
            if moving.size:
                ctx.add("Velocidade_Media_Movimento", moving.mean(), unit)
    else:
        ctx.missing("Velocidade", ["Velocidade"])

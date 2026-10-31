"""KPIs de dinâmica: g lateral/longitudinal (percentil do sinal suavizado), círculo g-g, yaw.

Nunca o máximo bruto: um pico isolado da IMU (batida, vibração) não vira KPI.
Os eixos (qual canal é longitudinal/lateral) vêm da configuração, porque a
montagem da IMU no carro não está documentada. Valores na unidade da IMU.
"""

import numpy as np

from signals import decimate, interp_to, percentile, rate_of, smooth

GG_MAX_POINTS = 4000


def compute(ch: dict, ctx) -> None:
    c = ctx.cfg["dinamica"]
    lon_n, lat_n, yaw_n = c["canal_longitudinal"], c["canal_lateral"], c["canal_yaw"]
    p = c["percentil"]

    if lon_n in ch and lat_n in ch:
        t, lon = ch[lon_n]
        tl, lat = ch[lat_n]
        lat = interp_to(tl, lat, t)
        f = rate_of(t)
        if np.isfinite(f):
            lon = smooth(lon, f, c["suavizacao_s"])
            lat = smooth(lat, f, c["suavizacao_s"])
        unit = ctx.units.get(lon_n, "")
        ctx.add("G_Lateral_P99", percentile(np.abs(lat), p), unit)
        ctx.add("G_Longitudinal_Pos_P99", percentile(lon, p), unit)
        neg = percentile(lon, 100.0 - p)
        ctx.add("G_Longitudinal_Neg_P99", None if neg is None else -neg, unit)
        comb = np.hypot(lon, lat)
        comb_p = percentile(comb, p)
        ctx.add("G_Combinado_P99", comb_p, unit)

        moving = np.ones(t.size, dtype=bool)
        if "Velocidade" in ch:
            tv, v = ch["Velocidade"]
            moving = np.nan_to_num(interp_to(tv, v, t), nan=0.0) > c["movimento_kmh"]
        ref = c["g_max_referencia"] if c["g_max_referencia"] is not None else comb_p
        use = comb[moving & np.isfinite(comb)]
        if use.size and ref:
            ctx.add("Uso_Circulo_GG_Medio_Pct", 100.0 * use.mean() / ref, "%")
            ctx.add(f"Tempo_Acima_{c['gg_limiar_pct']:g}pct_GG_Pct",
                    100.0 * np.mean(use > c["gg_limiar_pct"] / 100.0 * ref), "%")
        idx = decimate(t.size, GG_MAX_POINTS)
        ctx.eventos["gg"] = {"longitudinal": lon[idx].tolist(), "lateral": lat[idx].tolist(),
                             "unidade": unit, "referencia": ref}
    else:
        ctx.missing("Dinâmica (g-g)", [n for n in (lon_n, lat_n) if n not in ch])

    if yaw_n in ch:
        t, yaw = ch[yaw_n]
        f = rate_of(t)
        if np.isfinite(f):
            yaw = smooth(yaw, f, c["suavizacao_s"])
        ctx.add("Yaw_Rate_P99", percentile(np.abs(yaw), p), ctx.units.get(yaw_n, ""))
    else:
        ctx.missing("Yaw", [yaw_n])

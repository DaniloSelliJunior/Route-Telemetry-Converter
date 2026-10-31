"""KPIs de confiabilidade: temperatura do motor, pressão de óleo x RPM, bateria, lambda em carga alta."""

import numpy as np

from signals import decimate, interp_to, percentile, rate_of

OIL_MAX_POINTS = 4000


def compute(ch: dict, ctx) -> None:
    c = ctx.cfg["confiabilidade"]

    if "Temp_Motor" in ch:
        t, temp = ch["Temp_Motor"]
        fin = np.isfinite(temp)
        if fin.any():
            unit = ctx.units.get("Temp_Motor", "C")
            f = rate_of(t)
            ctx.add("Temp_Motor_Pico", temp[fin].max(), unit)
            above = np.count_nonzero(temp[fin] > c["temp_motor_limite_c"])
            ctx.add("Temp_Motor_Tempo_Acima_Limite", above / f if np.isfinite(f) else 0.0, "s")
    else:
        ctx.missing("Temperatura do motor", ["Temp_Motor"])

    if "Pressao_Oleo" in ch and "RPM" in ch:
        t, oil = ch["Pressao_Oleo"]
        tr, r = ch["RPM"]
        rpm = interp_to(tr, r, t)
        sel = np.isfinite(oil) & np.isfinite(rpm) & (rpm > c["rpm_marcha_lenta"])
        unit = ctx.units.get("Pressao_Oleo", "bar")
        if sel.any():
            o, rr = oil[sel], rpm[sel]
            ctx.add("Pressao_Oleo_Min_Acima_Lenta", o.min(), unit)
            w = c["oleo_rpm_faixa"]
            lo = c["rpm_marcha_lenta"]
            bins = []
            while lo < rr.max():
                m = (rr > lo) & (rr <= lo + w)
                if m.any():
                    ctx.add(f"Pressao_Oleo_Min_RPM_{lo:.0f}_{lo + w:.0f}", o[m].min(), unit)
                    bins.append({"rpm_de": lo, "rpm_ate": lo + w, "min": float(o[m].min())})
                lo += w
            idx = decimate(o.size, OIL_MAX_POINTS)
            ctx.eventos["oleo_rpm"] = {"rpm": rr[idx].tolist(), "pressao": o[idx].tolist(),
                                       "faixas": bins, "unidade": unit}
        else:
            ctx.warn("Pressão de óleo: nenhuma amostra acima da marcha lenta.")
    else:
        ctx.missing("Pressão de óleo x RPM", [n for n in ("Pressao_Oleo", "RPM") if n not in ch])

    if "Tensao_Bateria" in ch:
        _, v = ch["Tensao_Bateria"]
        v = v[np.isfinite(v)]
        if v.size:
            unit = ctx.units.get("Tensao_Bateria", "V")
            med = float(np.median(v))
            ctx.add("Tensao_Bateria_Min", v.min(), unit)
            ctx.add("Tensao_Bateria_Mediana", med, unit)
            ctx.add("Tensao_Bateria_Queda_Max", med - v.min(), unit)
    else:
        ctx.missing("Bateria", ["Tensao_Bateria"])

    if "Lambda_1" in ch and "TPS" in ch:
        t, lam = ch["Lambda_1"]
        tt, tps = ch["TPS"]
        load = interp_to(tt, tps, t)
        sel = np.isfinite(lam) & (np.nan_to_num(load, nan=-np.inf) > c["carga_alta_tps_pct"])
        if sel.any():
            l = lam[sel]
            f = rate_of(t)
            ctx.add("Tempo_Carga_Alta", sel.sum() / f if np.isfinite(f) else 0.0, "s")
            for q in (10, 50, 90):
                ctx.add(f"Lambda_Carga_Alta_P{q}", percentile(l, q), "")
            ctx.add("Lambda_Carga_Alta_Pobre_Pct", 100.0 * np.mean(l > c["lambda_pobre_limite"]), "%")
            ctx.eventos["lambda_carga_alta"] = l[decimate(l.size, OIL_MAX_POINTS)].tolist()
        else:
            ctx.warn("Lambda: nenhuma amostra em carga alta.")
    else:
        ctx.missing("Lambda em carga alta", [n for n in ("Lambda_1", "TPS") if n not in ch])

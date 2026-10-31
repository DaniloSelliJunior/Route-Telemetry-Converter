"""Relatório de qualidade do log (funções puras sobre NumPy).

Entra o ParseResult (e, se houver, o TimeCheck de parser.check_timestamps);
sai um dict pronto para JSON com a lista de avisos em português. Nada aqui
altera os dados: a checagem de unidade da IMU, por exemplo, só avisa.

Os limiares ficam em QualityConfig e são provisórios (sem logs reais para
calibrar).
"""

from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np

from parser import ParseResult, TimeCheck, aligned_timestamps, unwrap_timestamps

G = 9.80665


@dataclass
class QualityConfig:
    rate_tolerance_pct: float = 5.0       # taxa real x nominal
    gap_factor: float = 5.0               # lacuna = intervalo > gap_factor x período nominal
    stationary_speed_kmh: float = 1.0     # "parado" para a checagem da IMU
    min_stationary_samples: int = 50
    g_tolerance: float = 0.25             # |a| parado a menos disso de 1 -> g
    ms2_tolerance: float = 2.0            # |a| parado a menos disso de 9,81 -> m/s²


def _rate_stats(ts, freq_hz: float, cfg: QualityConfig) -> dict:
    """Taxa real de um grupo pelos intervalos positivos entre pacotes (ordem do arquivo).

    A mediana segue o pedido do relatório, mas com timestamps em ms inteiros
    ela é grosseira a 200 Hz (intervalos de 5 ou 6 ms); por isso também vai a
    taxa média sem as lacunas, que capta pacotes perdidos.
    """
    ts = np.asarray(ts, dtype=np.int64)
    d = np.diff(unwrap_timestamps(ts)) if ts.size > 1 else np.empty(0, np.int64)
    period = 1000.0 / freq_hz
    gap_ms = cfg.gap_factor * period
    pos = d[d > 0]
    gaps = pos[pos > gap_ms]
    regular = pos[pos <= gap_ms]
    out = {"pacotes": int(ts.size), "taxa_nominal_hz": freq_hz,
           "taxa_mediana_hz": None, "taxa_media_hz": None, "desvio_pct": None,
           "lacunas": int(gaps.size),
           "maior_lacuna_s": float(gaps.max()) / 1000.0 if gaps.size else 0.0,
           "fora_de_ordem": int(np.count_nonzero(d < 0)),
           "repetidos": int(np.count_nonzero(d == 0))}
    if regular.size:
        med = 1000.0 / float(np.median(regular))
        mean = 1000.0 / float(np.mean(regular))
        dev = max(abs(med - freq_hz), abs(mean - freq_hz)) / freq_hz * 100.0
        out.update(taxa_mediana_hz=round(med, 3), taxa_media_hz=round(mean, 3),
                   desvio_pct=round(dev, 2))
    return out


def _find_channel(result: ParseResult, name: str):
    """(pid, índice) do canal pelo nome, ou None."""
    for pid, g in result.groups.items():
        for k, ch in enumerate(g.definition.channels):
            if ch.name == name:
                return pid, k
    return None


def imu_unit_check(segments, cfg: QualityConfig) -> dict:
    """Sugere g ou m/s² pela magnitude da aceleração com o carro parado.

    Parado = Velocidade (interpolada no instante de cada amostra da IMU) até
    stationary_speed_kmh. Mediana de sqrt(ax² + ay² + az²) perto de 1 sugere g;
    perto de 9,81 sugere m/s². Só informa; os valores nunca são convertidos.
    """
    out = {"declarada": None, "sugerida": None, "magnitude_mediana": None,
           "amostras_paradas": 0, "mensagem": ""}
    mags = []
    for seg in segments:
        acc = [_find_channel(seg, n) for n in ("Acel_X", "Acel_Y", "Acel_Z")]
        spd = _find_channel(seg, "Velocidade")
        if acc[0] is not None:
            pid0, k0 = acc[0]
            out["declarada"] = seg.groups[pid0].definition.channels[k0].unit
        if None in acc or spd is None or len({p for p, _ in acc}) != 1:
            continue
        imu_pid = acc[0][0]
        all_ts, _ = aligned_timestamps(seg)
        t_spd = all_ts[spd[0]].astype(np.float64)
        v = np.asarray(seg.groups[spd[0]].columns[spd[1]], dtype=np.float64)
        order = np.argsort(t_spd, kind="stable")
        t_spd, v = t_spd[order], v[order]
        t_imu = all_ts[imu_pid].astype(np.float64)
        inside = (t_imu >= t_spd[0]) & (t_imu <= t_spd[-1])
        v_at = np.interp(t_imu, t_spd, v)
        cols = seg.groups[imu_pid].columns
        a = np.sqrt(sum(np.asarray(cols[k], dtype=np.float64) ** 2 for _, k in acc))
        sel = inside & (np.abs(v_at) <= cfg.stationary_speed_kmh) & np.isfinite(a)
        mags.append(a[sel])

    if out["declarada"] is None:
        out["mensagem"] = "Sem canais de aceleração no log."
        return out
    mags = np.concatenate(mags) if mags else np.empty(0)
    out["amostras_paradas"] = int(mags.size)
    if mags.size < cfg.min_stationary_samples:
        out["mensagem"] = ("Unidade da IMU não verificada: poucas amostras com o carro "
                           f"parado ({mags.size} < {cfg.min_stationary_samples}).")
        return out
    m = float(np.median(mags))
    out["magnitude_mediana"] = round(m, 4)
    if abs(m - 1.0) <= cfg.g_tolerance:
        out["sugerida"] = "g"
    elif abs(m - G) <= cfg.ms2_tolerance:
        out["sugerida"] = "m/s²"
    if out["sugerida"] is None:
        out["mensagem"] = (f"Unidade da IMU inconclusiva: |a| parado = {m:.3g} "
                           f"(esperado ~1 para g ou ~9,81 para m/s²).")
    elif out["sugerida"] == out["declarada"]:
        out["mensagem"] = f"Unidade da IMU consistente com {out['declarada']} (|a| parado = {m:.3g})."
    else:
        out["mensagem"] = (f"A IMU parece estar em {out['sugerida']} (|a| parado = {m:.3g}), "
                           f"mas os canais estão rotulados como {out['declarada']}. Os valores "
                           f"NÃO foram convertidos; confira o firmware.")
    return out


def build_quality_report(result: ParseResult, time_check: Optional[TimeCheck] = None,
                         config: Optional[QualityConfig] = None) -> dict:
    """Relatório de qualidade do log, pronto para JSON. `avisos` resume o que merece atenção."""
    cfg = config or QualityConfig()
    avisos = []

    grupos = {}
    for pid, g in result.groups.items():
        d = g.definition
        st = _rate_stats(g.timestamps_ms, d.freq_hz, cfg)
        st["id"] = f"0x{pid:02X}"
        grupos[d.name] = st
        if st["desvio_pct"] is not None and st["desvio_pct"] > cfg.rate_tolerance_pct:
            avisos.append(
                f"{d.name}: taxa real {st['taxa_mediana_hz']:g} Hz (mediana) / "
                f"{st['taxa_media_hz']:g} Hz (média) vs. nominal {d.freq_hz:g} Hz "
                f"(desvio de {st['desvio_pct']:g}% > {cfg.rate_tolerance_pct:g}%).")
        if st["lacunas"]:
            avisos.append(f"{d.name}: {st['lacunas']} lacuna(s) sem pacotes "
                          f"(maior: {st['maior_lacuna_s']:.2f} s).")

    nao_finitos = {}
    for g in result.groups.values():
        for ch, col in zip(g.definition.channels, g.columns):
            arr = np.asarray(col, dtype=np.float64)
            n_nan = int(np.count_nonzero(np.isnan(arr)))
            n_inf = int(np.count_nonzero(np.isinf(arr)))
            nao_finitos[ch.name] = {"nan": n_nan, "inf": n_inf}
            if n_nan or n_inf:
                avisos.append(f"{ch.name}: {n_nan} NaN e {n_inf} inf.")

    dropped_ts = time_check.dropped_packets if time_check else 0
    descartes = {"bytes": result.bytes_discarded,
                 "pacotes_corrompidos": result.packets_discarded,
                 "pacotes_timestamp_isolado": dropped_ts,
                 "ressincronizacoes": len(result.resyncs)}
    if result.bytes_discarded or result.packets_discarded:
        avisos.append(f"{result.bytes_discarded} bytes descartados em "
                      f"{len(result.resyncs)} trecho(s) corrompido(s); "
                      f"{result.packets_discarded} pacote(s) descartado(s) por estarem "
                      f"vizinhos desses trechos.")

    jumps = time_check.jumps if time_check else []
    timestamps = {"saltos": sum(j.kind == "salto" for j in jumps),
                  "resets": sum(j.kind == "reset" for j in jumps),
                  "segmentos": len(time_check.segments) if time_check else 1,
                  "eventos": [{"pacote": j.index, "delta_s": j.delta_ms / 1000.0,
                               "tipo": j.kind} for j in jumps]}
    if time_check:
        avisos.extend(time_check.warnings)

    segments = time_check.segments if time_check else ([result] if result.groups else [])
    imu = imu_unit_check(segments, cfg)
    if imu["sugerida"] is not None and imu["sugerida"] != imu["declarada"]:
        avisos.append(imu["mensagem"])

    return {"ok": not avisos, "avisos": avisos, "grupos": grupos,
            "descartes": descartes, "nao_finitos": nao_finitos,
            "timestamps": timestamps, "imu_unidade": imu,
            "limiares": asdict(cfg)}

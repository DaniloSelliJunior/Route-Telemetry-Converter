"""Utilitários de sinal (NumPy puro) usados pelos canais derivados e pelos KPIs."""

import numpy as np

G = 9.80665


def smooth(v, freq_hz: float, window_s: float) -> np.ndarray:
    """Média móvel centrada de window_s segundos (janela ímpar; bordas repetidas).

    NaN contamina só a própria janela. window_s <= 1 amostra devolve uma cópia.
    """
    v = np.asarray(v, dtype=np.float64)
    n = int(round(window_s * freq_hz))
    if n <= 1 or v.size == 0:
        return v.copy()
    if n % 2 == 0:
        n += 1
    vp = np.pad(v, n // 2, mode="edge")
    return np.convolve(vp, np.ones(n) / n, mode="valid")


def derivative(v, freq_hz: float) -> np.ndarray:
    """Derivada por diferenças centradas (unidade/s)."""
    v = np.asarray(v, dtype=np.float64)
    if v.size < 2:
        return np.zeros_like(v)
    return np.gradient(v, 1.0 / freq_hz)


def fill_nan(t, v) -> np.ndarray:
    """Substitui NaN/inf por interpolação linear entre as amostras finitas vizinhas."""
    v = np.asarray(v, dtype=np.float64)
    fin = np.isfinite(v)
    if fin.all() or not fin.any():
        return v.copy()
    return np.interp(t, np.asarray(t)[fin], v[fin])


def runs(mask) -> list:
    """Trechos contíguos verdadeiros: [(início, fim_exclusivo)] em índices."""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return []
    d = np.diff(np.concatenate(([0], m.astype(np.int8), [0])))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def events(mask, freq_hz: float, min_duration_s: float = 0.0, merge_gap_s: float = 0.0) -> list:
    """Trechos de `mask`, unindo os separados por até merge_gap_s e descartando os curtos."""
    out = []
    gap = int(round(merge_gap_s * freq_hz))
    for s, e in runs(mask):
        if out and s - out[-1][1] <= gap:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    min_n = max(1, int(round(min_duration_s * freq_hz)))
    return [(s, e) for s, e in out if e - s >= min_n]


def interp_to(t_src, v_src, t_dst, hold: bool = False) -> np.ndarray:
    """Valores de (t_src, v_src) nos instantes t_dst (linear ou hold; bordas repetidas)."""
    t_src = np.asarray(t_src, dtype=np.float64)
    v_src = np.asarray(v_src, dtype=np.float64)
    t_dst = np.asarray(t_dst, dtype=np.float64)
    if t_src.size == 0:
        return np.full(t_dst.shape, np.nan)
    if hold:
        idx = np.clip(np.searchsorted(t_src, t_dst, side="right") - 1, 0, t_src.size - 1)
        return v_src[idx]
    return np.interp(t_dst, t_src, v_src)


def percentile(v, q: float):
    """Percentil dos valores finitos, ou None se não houver nenhum."""
    v = np.asarray(v, dtype=np.float64)
    v = v[np.isfinite(v)]
    return float(np.percentile(v, q)) if v.size else None


def rate_of(t) -> float:
    """Frequência de uma grade uniforme (Hz); NaN com menos de 2 pontos."""
    t = np.asarray(t, dtype=np.float64)
    return 1.0 / (t[1] - t[0]) if t.size > 1 and t[1] > t[0] else float("nan")


def cumulative_distance_m(t, speed_kmh) -> np.ndarray:
    """Distância percorrida (m) integrando a velocidade em km/h (trapézios; NaN interpolado)."""
    t = np.asarray(t, dtype=np.float64)
    v = fill_nan(t, speed_kmh) / 3.6
    if v.size == 0:
        return v
    if not np.isfinite(v).any():
        return np.full(v.shape, np.nan)
    return np.concatenate(([0.0], np.cumsum((v[1:] + v[:-1]) / 2 * np.diff(t))))


def decimate(n: int, max_points: int) -> np.ndarray:
    """Índices igualmente espaçados para no máximo max_points pontos (gráficos)."""
    step = max(1, int(np.ceil(n / max_points)))
    return np.arange(0, n, step)

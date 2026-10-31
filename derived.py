"""Canais derivados (math channels), calculados sobre os canais reamostrados.

Entram: {nome: (t, valores)} na grade do .ld, as unidades e as taxas de cada
canal. Saem novos canais na taxa do primeiro canal de entrada. Os 23 canais
originais nunca são alterados; no .ld os derivados vão depois deles, e a GUI
permite incluir ou excluir.

Para acrescentar um canal: escreva a função (ch, units, cfg) -> np.ndarray e
inclua um DerivedChannel em DERIVED.
"""

from dataclasses import dataclass
from typing import Callable

import numpy as np

from signals import G, cumulative_distance_m, derivative, interp_to, rate_of, smooth

# padrões (provisórios); sobrescritos pela seção "derivados" do JSON de limiares
DEFAULT_DERIVED_CONFIG = {
    "balanco_pressao_min_psi": 5.0,     # abaixo disso (Diant + Tras) o balanço é NaN
    "suavizacao_acelerador_s": 0.1,     # antes de derivar o Hall_Acelerador
    "suavizacao_velocidade_s": 0.2,     # antes de derivar a Velocidade
}


@dataclass(frozen=True)
class DerivedChannel:
    name: str
    unit: str                # "" = herda a unidade do 1º canal de entrada
    inputs: tuple
    compute: Callable        # (lista de arrays na grade do 1º input, freq, cfg) -> array
    description: str


def throttle_rate(throttle, freq_hz: float, smoothing_s: float) -> np.ndarray:
    """Taxa de variação do acelerador (%/s) após média móvel."""
    return derivative(smooth(throttle, freq_hz, smoothing_s), freq_hz)


def brake_balance(front, rear, min_total: float) -> np.ndarray:
    """100 * Diant / (Diant + Tras); NaN quando a soma não passa de min_total (sem frenagem)."""
    front = np.asarray(front, dtype=np.float64)
    rear = np.asarray(rear, dtype=np.float64)
    total = front + rear
    out = np.full(front.shape, np.nan)
    ok = np.isfinite(total) & (total > min_total)
    out[ok] = 100.0 * front[ok] / total[ok]
    return out


def _balance(v, f, cfg):
    return brake_balance(v[0], v[1], cfg["balanco_pressao_min_psi"])


def _g_combined(v, f, cfg):
    return np.hypot(v[0], v[1])


def _throttle_rate(v, f, cfg):
    return throttle_rate(v[0], f, cfg["suavizacao_acelerador_s"])


def _distance(v, f, cfg):
    t = np.arange(v[0].size) / f
    return cumulative_distance_m(t, v[0])


def _long_accel_from_speed(v, f, cfg):
    return derivative(smooth(np.asarray(v[0]) / 3.6, f, cfg["suavizacao_velocidade_s"]), f) / G


DERIVED = (
    DerivedChannel("Balanco_Freio_Pct", "%", ("Pressao_Freio_Diant", "Pressao_Freio_Tras"), _balance,
                   "Pressão dianteira / (dianteira + traseira). Indicativo: vem de pressão "
                   "hidráulica, não de força de frenagem; NaN sem frenagem."),
    DerivedChannel("G_Combinado", "", ("Acel_X", "Acel_Y"), _g_combined,
                   "sqrt(Acel_X² + Acel_Y²), na unidade da IMU."),
    DerivedChannel("Taxa_Acelerador", "%/s", ("Hall_Acelerador",), _throttle_rate,
                   "Derivada do Hall_Acelerador após média móvel."),
    DerivedChannel("Distancia", "m", ("Velocidade",), _distance,
                   "Integral da Velocidade desde o início do log."),
    DerivedChannel("Acel_Long_Velocidade", "g", ("Velocidade",), _long_accel_from_speed,
                   "Derivada da Velocidade suavizada, em g (independe da IMU)."),
)


def compute_derived(channels: dict, units: dict, freqs: dict, config: dict = None,
                    names=None):
    """Calcula os derivados cujas entradas existem. Retorna (canais, unidades, taxas) novos.

    names: subconjunto de nomes de DERIVED (None = todos).
    """
    cfg = dict(DEFAULT_DERIVED_CONFIG)
    cfg.update(config or {})
    out_ch, out_units, out_freqs = {}, {}, {}
    for d in DERIVED:
        if names is not None and d.name not in names:
            continue
        if not all(n in channels for n in d.inputs):
            continue
        t0, v0 = channels[d.inputs[0]]
        values = [np.asarray(v0, dtype=np.float64)]
        for n in d.inputs[1:]:
            t, v = channels[n]
            same = len(t) == len(t0) and np.array_equal(t, t0)
            values.append(np.asarray(v, dtype=np.float64) if same else interp_to(t, v, t0))
        f = freqs.get(d.inputs[0]) or rate_of(t0)
        out_ch[d.name] = (t0, d.compute(values, f, cfg))
        out_units[d.name] = d.unit or units.get(d.inputs[0], "")
        out_freqs[d.name] = f
    return out_ch, out_units, out_freqs

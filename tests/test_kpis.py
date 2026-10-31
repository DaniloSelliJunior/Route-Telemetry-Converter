"""KPIs com sinais sintéticos de resultado conhecido (um bloco por categoria)."""

import math

import numpy as np
import pytest

from builders import synthetic_log
from derived import compute_derived
from exporter import resampled_channels
from kpi import SESSION, Segment, compute_kpis, merge_config
from parser import parse_bin

UNITS = {"Pressao_Freio_Diant": "PSI", "Acel_X": "g", "Acel_Y": "g", "Gyro_Z": "deg/s",
         "Velocidade": "km/h", "Temp_Motor": "C", "Pressao_Oleo": "bar", "Tensao_Bateria": "V",
         "Nivel_Combustivel": "L"}


def sig(freq, values):
    v = np.asarray(values, dtype=np.float64)
    return np.arange(v.size) / freq, v


def run(cfg=None, segments=None, **channels):
    return compute_kpis(channels, segments, merge_config(cfg), UNITS)


def val(res, name, seg=SESSION):
    v = res.get(name, seg)
    assert v is not None, f"KPI {name} ausente; avisos: {res.avisos}"
    return v


def no_failures(res):
    assert not [a for a in res.avisos if "falha em" in a], res.avisos


# --- piloto: acelerador ----------------------------------------------------------

def test_constant_full_throttle():
    res = run(Hall_Acelerador=sig(50, np.full(500, 100.0)))
    assert (val(res, "Acelerador_Pleno_Pct"), val(res, "Acelerador_Zero_Pct"),
            val(res, "Acelerador_Parcial_Pct")) == (100, 0, 0)
    no_failures(res)


def test_throttle_split_zero_partial_full():
    thr = np.concatenate([np.zeros(100), np.full(200, 50.0), np.full(200, 100.0)])
    res = run(Hall_Acelerador=sig(50, thr))
    assert (val(res, "Acelerador_Zero_Pct"), val(res, "Acelerador_Parcial_Pct"),
            val(res, "Acelerador_Pleno_Pct")) == pytest.approx((20, 40, 40))


def test_throttle_application_rate_from_ramps():
    # rampas de 0 a 100% em 0,5 s (200 %/s), seguidas de 1 s em 100% e 1 s em 0%
    cycle = np.concatenate([np.linspace(0, 100, 26)[:-1], np.full(50, 100.0), np.zeros(50)])
    res = run(Hall_Acelerador=sig(50, np.tile(cycle, 6)))
    assert val(res, "Taxa_Aplicacao_Acelerador_Mediana") == pytest.approx(200, rel=0.02)


# --- piloto: frenagens ------------------------------------------------------------

def braking_signal():
    """10 s a 50 Hz: frenagem de 1 s a 400 PSI (t=1), 0,5 s a 600 (t=4), 0,1 s a 300 (curta)."""
    front = np.zeros(500)
    front[50:100] = 400
    front[200:225] = 600
    front[350:355] = 300
    return front


def test_injected_braking_events():
    front = braking_signal()
    res = run(Pressao_Freio_Diant=sig(50, front), Pressao_Freio_Tras=sig(50, front / 2))
    assert val(res, "Frenagens_Numero") == 2                     # a de 0,1 s fica de fora
    assert val(res, "Frenagem_Pico_Max") == 600
    assert val(res, "Frenagem_Pico_Medio") == 500
    assert val(res, "Frenagem_Duracao_Media") == pytest.approx(0.75)
    assert val(res, "Frenagem_Balanco_Medio_Pct") == pytest.approx(200 / 3)
    ev = res.eventos[SESSION]["frenagens"]
    assert [(e["inicio_s"], e["duracao_s"]) for e in ev] == [(1.0, 1.0), (4.0, 0.5)]
    assert next(k for k in res.kpis if k.nome == "Frenagem_Pico_Max").unidade == "PSI"


def test_braking_threshold_and_min_duration_are_configurable():
    front = braking_signal()
    cfg = {"piloto": {"freio_limiar_psi": 450, "freio_duracao_min_s": 0.05}}
    res = run(cfg, Pressao_Freio_Diant=sig(50, front))
    assert val(res, "Frenagens_Numero") == 1
    res = run({"piloto": {"freio_duracao_min_s": 0.05}}, Pressao_Freio_Diant=sig(50, front))
    assert val(res, "Frenagens_Numero") == 3


def test_braking_without_rear_pressure_has_no_balance():
    res = run(Pressao_Freio_Diant=sig(50, braking_signal()))
    assert res.get("Frenagem_Balanco_Medio_Pct") is None and val(res, "Frenagens_Numero") == 2


def test_no_braking_reports_zero_events():
    res = run(Pressao_Freio_Diant=sig(50, np.zeros(100)))
    assert val(res, "Frenagens_Numero") == 0 and res.get("Frenagem_Pico_Max") is None


def test_brake_throttle_overlap_percentage():
    thr = np.zeros(500)
    thr[50:100] = 50                                             # acelerador durante a 1ª frenagem
    res = run(Hall_Acelerador=sig(50, thr), Pressao_Freio_Diant=sig(50, braking_signal()))
    assert val(res, "Sobreposicao_Freio_Acelerador_Pct") == pytest.approx(10)


# --- câmbio e motor ----------------------------------------------------------------

def gear_signal():
    """1 por 2 s, 2 por 3 s (com uma "piscada" de 1 amostra em 3), 3 por 3 s, 2 por 2 s."""
    g = np.concatenate([np.full(100, 1.0), np.full(150, 2.0), np.full(150, 3.0), np.full(100, 2.0)])
    g[150] = 3
    return g


def test_time_per_gear_and_shift_count_ignore_flicker():
    rpm = np.full(500, 6000.0)
    rpm[95:100] = 9000                                           # pico antes da 1ª subida
    rpm[400:405] = 9500                                          # sobregiro depois da redução
    res = run(Marcha=sig(50, gear_signal()), RPM=sig(50, rpm))
    assert (val(res, "Tempo_Marcha_1"), val(res, "Tempo_Marcha_2"),
            val(res, "Tempo_Marcha_3")) == pytest.approx((2, 5, 3))
    assert val(res, "Tempo_Marcha_2_Pct") == pytest.approx(50)
    assert (val(res, "Trocas_Numero"), val(res, "Trocas_Subida"), val(res, "Trocas_Reducao")) == (3, 2, 1)
    assert val(res, "RPM_Troca_Subida_Max") == 9000
    assert val(res, "RPM_Troca_Subida_Media") == 7500
    assert val(res, "RPM_Troca_Reducao_Max") == 9500
    trocas = res.eventos[SESSION]["trocas"]
    assert [(e["de"], e["para"], e["t_s"]) for e in trocas] == [(1, 2, 2.0), (2, 3, 5.0), (3, 2, 8.0)]


def test_rpm_histogram_percent_per_band_with_engine_on():
    rpm = np.concatenate([np.zeros(100), np.full(100, 4500.0), np.full(300, 8200.0)])
    res = run(RPM=sig(50, rpm))
    assert val(res, "RPM_Hist_4000_5000_Pct") == pytest.approx(25)
    assert val(res, "RPM_Hist_8000_9000_Pct") == pytest.approx(75)
    assert sum(k.valor for k in res.kpis if k.nome.startswith("RPM_Hist")) == pytest.approx(100)


def test_speed_max_mean_and_moving_mean():
    v = np.concatenate([np.zeros(100), np.full(100, 60.0), np.full(100, 120.0)])
    res = run(Velocidade=sig(50, v))
    assert (val(res, "Velocidade_Max"), val(res, "Velocidade_Media"),
            val(res, "Velocidade_Media_Movimento")) == pytest.approx((120, 60, 90))


# --- dinâmica --------------------------------------------------------------------

def test_lateral_p99_ignores_single_raw_spike():
    t = np.arange(2000) / 200
    lat = 1.5 * np.sin(2 * np.pi * 0.2 * t)
    lat[500] = 10.0                                              # pico isolado da IMU
    res = run(Acel_X=sig(200, np.zeros(2000)), Acel_Y=sig(200, lat))
    assert val(res, "G_Lateral_P99") == pytest.approx(1.5, abs=0.02)


def test_longitudinal_positive_and_negative_sides():
    lon = np.concatenate([np.full(1000, 0.5), np.full(1000, -1.0)])
    res = run(Acel_X=sig(200, lon), Acel_Y=sig(200, np.zeros(2000)))
    assert val(res, "G_Longitudinal_Pos_P99") == pytest.approx(0.5)
    assert val(res, "G_Longitudinal_Neg_P99") == pytest.approx(1.0)
    assert val(res, "G_Combinado_P99") == pytest.approx(1.0)


def test_gg_circle_usage_against_configured_reference():
    lon, lat = np.full(1000, 0.6), np.full(1000, 0.72)          # |a| = 0,937
    cfg = {"dinamica": {"g_max_referencia": 1.25}}
    res = run(cfg, Acel_X=sig(200, lon), Acel_Y=sig(200, lat))
    assert val(res, "Uso_Circulo_GG_Medio_Pct") == pytest.approx(100 * math.hypot(0.6, 0.72) / 1.25)
    assert val(res, "Tempo_Acima_80pct_GG_Pct") == 0
    res = run({"dinamica": {"g_max_referencia": 1.0}}, Acel_X=sig(200, lon), Acel_Y=sig(200, lat))
    assert val(res, "Tempo_Acima_80pct_GG_Pct") == 100


def test_gg_usage_only_counts_moving_samples():
    lon = np.concatenate([np.zeros(1000), np.full(1000, 0.5)])
    speed = np.concatenate([np.zeros(250), np.full(250, 50.0)])  # 50 Hz, para na 1ª metade
    cfg = {"dinamica": {"g_max_referencia": 1.0}}
    res = run(cfg, Acel_X=sig(200, lon), Acel_Y=sig(200, np.zeros(2000)), Velocidade=sig(50, speed))
    assert val(res, "Uso_Circulo_GG_Medio_Pct") == pytest.approx(50, abs=0.5)


def test_axis_channels_are_configurable_and_yaw_p99():
    res = run({"dinamica": {"canal_longitudinal": "Acel_Y", "canal_lateral": "Acel_X"}},
              Acel_X=sig(200, np.full(400, 0.8)), Acel_Y=sig(200, np.zeros(400)),
              Gyro_Z=sig(200, np.full(400, -45.0)))
    assert val(res, "G_Lateral_P99") == pytest.approx(0.8)
    assert val(res, "Yaw_Rate_P99") == pytest.approx(45)


# --- confiabilidade --------------------------------------------------------------

def test_engine_temperature_peak_and_time_over_limit():
    temp = np.full(100, 95.0)
    temp[40:70] = 110.0                                          # 3 s a 10 Hz
    res = run(Temp_Motor=sig(10, temp))
    assert (val(res, "Temp_Motor_Pico"), val(res, "Temp_Motor_Tempo_Acima_Limite")) == (110, 3)


def test_oil_pressure_minimum_by_rpm_ignores_idle():
    rpm = np.concatenate([np.full(50, 1000.0), np.full(50, 5000.0), np.full(50, 7000.0)])
    oil = np.concatenate([np.full(50, 0.5), np.full(50, 3.0), np.full(50, 2.5)])
    res = run(RPM=sig(10, rpm), Pressao_Oleo=sig(10, oil))
    assert val(res, "Pressao_Oleo_Min_Acima_Lenta") == 2.5
    assert val(res, "Pressao_Oleo_Min_RPM_4000_6000") == 3.0
    assert val(res, "Pressao_Oleo_Min_RPM_6000_8000") == 2.5
    assert res.get("Pressao_Oleo_Min_RPM_2000_4000") is None


def test_battery_minimum_and_drop():
    v = np.full(100, 13.5)
    v[60] = 11.0
    res = run(Tensao_Bateria=sig(10, v))
    assert (val(res, "Tensao_Bateria_Min"), val(res, "Tensao_Bateria_Queda_Max")) == \
           pytest.approx((11.0, 2.5))


def test_lambda_distribution_only_at_high_load():
    tps = np.concatenate([np.full(100, 20.0), np.full(100, 90.0)])
    lam = np.concatenate([np.full(100, 1.3), np.full(50, 0.85), np.full(50, 1.0)])
    res = run(TPS=sig(10, tps), Lambda_1=sig(10, lam))
    assert val(res, "Tempo_Carga_Alta") == 10
    assert val(res, "Lambda_Carga_Alta_P10") == pytest.approx(0.85)
    assert val(res, "Lambda_Carga_Alta_P90") == pytest.approx(1.0)
    assert val(res, "Lambda_Carga_Alta_Pobre_Pct") == 50


# --- consumo -------------------------------------------------------------------

def test_fuel_rate_by_linear_regression_with_noise():
    rng = np.random.default_rng(0)
    t = np.arange(6000) / 10                                     # 10 min a 10 Hz
    level = 5.0 - 0.3 * t / 60 + rng.normal(0, 0.05, t.size)
    res = run(Nivel_Combustivel=(t, level))
    assert val(res, "Consumo_Combustivel") == pytest.approx(0.3, abs=0.005)
    assert val(res, "Consumo_R2") > 0.9
    assert not [a for a in res.avisos if "Consumo" in a]


def test_fuel_rate_is_not_fooled_by_endpoints():
    # nível com balanço forte nas pontas: diferença de dois pontos daria ~0
    t = np.arange(6000) / 10
    level = 5.0 - 0.3 * t / 60
    level[:5] -= 3.0
    res = run(Nivel_Combustivel=(t, level))
    assert val(res, "Consumo_Combustivel") == pytest.approx(0.3, abs=0.02)


def test_noisy_fuel_signal_warns():
    rng = np.random.default_rng(1)
    t = np.arange(6000) / 10
    res = run(Nivel_Combustivel=(t, 5.0 - 0.01 * t / 60 + rng.normal(0, 1.0, t.size)))
    assert any("muito ruidoso" in a for a in res.avisos)


def test_short_or_rising_fuel_signal_warns():
    res = run(Nivel_Combustivel=sig(10, np.full(100, 5.0)))
    assert res.get("Consumo_Combustivel") is None and any("menor que o mínimo" in a for a in res.avisos)
    t = np.arange(1200) / 10
    res = run(Nivel_Combustivel=(t, 2.0 + t / 60))
    assert any("nível subiu" in a for a in res.avisos)


# --- arrancadas ------------------------------------------------------------------

def launch_speed(rest_s=2.0, accel=5.0, total_s=12.0, freq=50):
    """Parado por rest_s, depois aceleração constante (m/s²) até total_s; km/h."""
    t = np.arange(int(total_s * freq)) / freq
    return t, np.clip(accel * (t - rest_s), 0, None) * 3.6


def test_zero_to_100_and_zero_to_75m_from_rest():
    t, v = launch_speed()
    res = run({"arrancada": {"repouso_kmh": 0.01}}, Velocidade=(t, v))
    assert val(res, "Arrancadas_Numero") == 1
    assert val(res, "Tempo_0_100kmh_Melhor") == pytest.approx(100 / 3.6 / 5, abs=0.025)
    assert val(res, "Tempo_0_75m_Melhor") == pytest.approx(math.sqrt(2 * 75 / 5), abs=0.025)
    assert val(res, "Velocidade_75m_Melhor") == pytest.approx(math.sqrt(2 * 5 * 75) * 3.6, rel=0.01)


def test_best_of_two_launches_and_slow_rollout_is_not_counted():
    t1, v1 = launch_speed(accel=4.0, total_s=10)
    stop = np.zeros(150)
    t2, v2 = launch_speed(accel=6.0, total_s=10)
    crawl = np.concatenate([np.zeros(100), np.full(100, 10.0), np.zeros(100)])  # não passa de 20 km/h
    v = np.concatenate([v1, stop, v2, stop, crawl])
    res = run({"arrancada": {"repouso_kmh": 0.01}}, Velocidade=sig(50, v))
    assert val(res, "Arrancadas_Numero") == 2
    assert val(res, "Tempo_0_75m_Melhor") == pytest.approx(math.sqrt(2 * 75 / 6), abs=0.025)


def test_launch_that_never_reaches_target_has_no_time():
    t, v = launch_speed(accel=2.0, total_s=6)                    # chega a 28,8 km/h
    res = run(Velocidade=(t, v))
    assert val(res, "Arrancadas_Numero") == 1
    assert res.get("Tempo_0_100kmh_Melhor") is None


# --- segmentos e integração --------------------------------------------------------

def test_kpis_per_segment_and_session():
    thr = np.concatenate([np.full(250, 100.0), np.zeros(250)])
    res = run(segments=[Segment("A", 0, 4.99), Segment("B", 5, 10)],
              Hall_Acelerador=sig(50, thr))
    assert val(res, "Acelerador_Pleno_Pct") == 50
    assert val(res, "Acelerador_Pleno_Pct", "A") == 100
    assert val(res, "Acelerador_Zero_Pct", "B") == 100


def test_segment_outside_log_is_skipped_with_warning():
    res = run(segments=[Segment("fora", 100, 200)], Hall_Acelerador=sig(50, np.zeros(50)))
    assert res.get("Acelerador_Zero_Pct", "fora") is None
    assert any("'fora' começa em 100 s" in a for a in res.avisos)


def test_missing_channels_are_reported_not_crashing():
    res = run(Hall_Acelerador=sig(50, np.zeros(50)))
    no_failures(res)
    assert any("Frenagens: não calculado (canal ausente: Pressao_Freio_Diant)" in a for a in res.avisos)


def test_full_synthetic_log_computes_without_failures():
    data, units, freqs = resampled_channels(parse_bin(synthetic_log(5000)))
    ch, u, _ = compute_derived(data, units, freqs)
    data.update(ch)
    units.update(u)
    res = compute_kpis(data, None, None, units)
    no_failures(res)
    assert len(res.kpis) > 40 and {k.segmento for k in res.kpis} == {SESSION}


def test_nan_samples_do_not_break_kpis():
    v = np.full(500, 100.0)
    v[::7] = np.nan
    res = run(Hall_Acelerador=sig(50, v), Velocidade=sig(50, v), Temp_Motor=sig(10, v[:100]),
              Acel_X=sig(200, v), Acel_Y=sig(200, v))
    no_failures(res)
    assert val(res, "Acelerador_Pleno_Pct") == 100


def test_throttle_histogram_in_events_sums_to_100():
    thr = np.concatenate([np.zeros(100), np.full(100, 55.0), np.full(300, 104.0)])
    ev = run(Hall_Acelerador=sig(50, thr)).eventos[SESSION]["hist_acelerador"]
    assert ev["bordas"][0] == 0 and ev["bordas"][-1] == 100
    assert ev["pct"][0] == 20 and ev["pct"][5] == 20 and ev["pct"][-1] == 60


def test_gg_usage_in_segments_uses_session_reference():
    # 1ª metade forte (|a| = 1), 2ª fraca (0,5): na 2ª o uso é 50% da referência da sessão
    lon = np.concatenate([np.full(1000, 1.0), np.full(1000, 0.5)])
    res = run(segments=[Segment("fraco", 5.0, 10.0)],
              Acel_X=sig(200, lon), Acel_Y=sig(200, np.zeros(2000)))
    assert val(res, "Uso_Circulo_GG_Medio_Pct", "fraco") == pytest.approx(50, abs=1)


def test_longitudinal_side_without_samples_is_zero_not_negative():
    res = run(Acel_X=sig(200, np.full(400, 0.6)), Acel_Y=sig(200, np.zeros(400)))
    assert val(res, "G_Longitudinal_Neg_P99") == 0

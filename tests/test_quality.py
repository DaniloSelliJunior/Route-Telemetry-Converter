"""quality.build_quality_report: taxa real, descartes, NaN/inf, saltos e unidade da IMU."""

import json
import math

import pytest

from builders import packet, payload, synthetic_log, zeros
from parser import check_timestamps, parse_bin
from quality import QualityConfig, build_quality_report, imu_unit_check

IMU, PEDAIS, MOTOR, SLOW = 0x01, 0x02, 0x03, 0x04


def report(data: bytes, **cfg):
    r = parse_bin(data)
    return build_quality_report(r, check_timestamps(r), QualityConfig(**cfg) if cfg else None)


def test_clean_log_is_ok_and_json_serialisable(normal_log_bytes):
    rep = report(normal_log_bytes)
    json.dumps(rep)
    assert (rep["avisos"], rep["ok"]) == ([], True)
    assert rep["grupos"]["Chassi_IMU"]["taxa_mediana_hz"] == 200.0
    assert rep["grupos"]["Motor_Lento"]["taxa_media_hz"] == 10.0
    assert rep["descartes"] == {"bytes": 0, "pacotes_corrompidos": 0,
                                "pacotes_timestamp_isolado": 0, "ressincronizacoes": 0}
    assert rep["timestamps"]["segmentos"] == 1


def test_rate_divergence_above_tolerance_warns():
    # IMU a cada 6 ms (~166,7 Hz) em vez de 5 ms
    rep = report(b"".join(packet(IMU, t, *zeros(IMU)) for t in range(0, 2000, 6)))
    g = rep["grupos"]["Chassi_IMU"]
    assert g["taxa_mediana_hz"] == pytest.approx(166.667, abs=1e-3)
    assert g["desvio_pct"] == pytest.approx(16.67, abs=0.01)
    assert any(a.startswith("Chassi_IMU: taxa real") for a in rep["avisos"])


def test_rate_within_tolerance_does_not_warn():
    # um intervalo de 6 ms a cada 5 (média de 5,2 ms): 3,8% abaixo do nominal
    ts, t = [], 0
    for i in range(400):
        ts.append(t)
        t += 5 if i % 5 else 6
    rep = report(b"".join(packet(IMU, t, *zeros(IMU)) for t in ts))
    assert not any("taxa real" in a for a in rep["avisos"])
    assert rep["grupos"]["Chassi_IMU"]["desvio_pct"] < 5


def test_rate_tolerance_is_configurable():
    ts, t = [], 0
    for i in range(400):
        ts.append(t)
        t += 5 if i % 5 else 6
    data = b"".join(packet(IMU, t, *zeros(IMU)) for t in ts)
    assert any("taxa real" in a for a in report(data, rate_tolerance_pct=1)["avisos"])


def test_gaps_are_counted_and_do_not_bias_the_rate():
    ts = list(range(0, 1000, 5)) + list(range(3000, 4000, 5))
    rep = report(b"".join(packet(IMU, t, *zeros(IMU)) for t in ts))
    g = rep["grupos"]["Chassi_IMU"]
    assert (g["lacunas"], g["maior_lacuna_s"], g["taxa_media_hz"]) == (1, 2.005, 200.0)


def test_discarded_bytes_and_packets_are_reported(normal_log_bytes):
    data = normal_log_bytes[:290] + b"\xfe" * 7 + normal_log_bytes[290:]
    rep = report(data)
    assert rep["descartes"]["ressincronizacoes"] == 1
    assert rep["descartes"]["pacotes_corrompidos"] == 1
    assert rep["descartes"]["bytes"] == 7 + 29
    assert any("bytes descartados" in a for a in rep["avisos"])


@pytest.mark.parametrize("bad, key", [(math.nan, "nan"), (math.inf, "inf"), (-math.inf, "inf")])
def test_non_finite_values_are_counted_per_channel(bad, key):
    data = packet(IMU, 0, bad, 0, 0, 0, 0, 0) + packet(IMU, 5, *zeros(IMU))
    rep = report(data)
    assert rep["nao_finitos"]["Acel_X"][key] == 1
    assert rep["nao_finitos"]["Acel_Y"] == {"nan": 0, "inf": 0}
    assert any(a.startswith("Acel_X:") for a in rep["avisos"])


def test_jumps_resets_and_isolated_packets_are_reported():
    data = synthetic_log(2000, start_ms=500_000) + synthetic_log(1000) \
         + packet(IMU, 4_000_000_000, *zeros(IMU))
    rep = report(data)
    ts = rep["timestamps"]
    assert (ts["resets"], ts["saltos"], ts["segmentos"]) == (1, 0, 2)
    assert ts["eventos"][0]["tipo"] == "reset"
    assert rep["descartes"]["pacotes_timestamp_isolado"] == 1
    assert any(a.startswith("Reset de timestamp") for a in rep["avisos"])


def test_report_without_time_check_still_works(normal_log):
    rep = build_quality_report(normal_log)
    assert rep["timestamps"]["segmentos"] == 1


# --- unidade da IMU ------------------------------------------------------------

def stationary_log(acc_z: float, speed: float = 0.0, seconds: int = 2) -> bytes:
    buf = bytearray()
    for t in range(0, seconds * 1000, 5):
        buf += packet(IMU, t, 0.0, 0.0, acc_z, 0, 0, 0)
        if t % 20 == 0:
            buf += packet(MOTOR, t, 900, 0, 0, 30, 10, speed)
    return bytes(buf)


@pytest.mark.parametrize("acc_z, unit", [(1.0, "g"), (0.98, "g"), (9.81, "m/s²"), (9.6, "m/s²")])
def test_imu_unit_is_suggested_from_magnitude_when_stopped(acc_z, unit):
    r = parse_bin(stationary_log(acc_z))
    assert imu_unit_check([r], QualityConfig())["sugerida"] == unit


def test_imu_in_m_s2_labelled_as_g_warns_but_values_are_untouched():
    r = parse_bin(stationary_log(9.81))
    rep = build_quality_report(r, check_timestamps(r))
    assert any("NÃO foram convertidos" in a for a in rep["avisos"])
    assert r.groups[IMU].columns[2][0] == pytest.approx(9.81, rel=1e-6)


def test_imu_consistent_with_label_does_not_warn():
    rep = report(stationary_log(1.0))
    assert rep["imu_unidade"]["sugerida"] == "g" and rep["avisos"] == []


def test_imu_check_ignores_samples_while_moving():
    r = parse_bin(stationary_log(9.81, speed=40.0))
    chk = imu_unit_check([r], QualityConfig())
    assert (chk["sugerida"], chk["amostras_paradas"]) == (None, 0)
    assert "poucas amostras" in chk["mensagem"]


def test_imu_check_inconclusive_magnitude():
    chk = imu_unit_check([parse_bin(stationary_log(4.0))], QualityConfig())
    assert chk["sugerida"] is None and "inconclusiva" in chk["mensagem"]


def test_imu_check_without_speed_channel():
    r = parse_bin(b"".join(packet(IMU, t, *payload(IMU, t)) for t in range(0, 1000, 5)))
    chk = imu_unit_check([r], QualityConfig())
    assert (chk["declarada"], chk["sugerida"]) == ("g", None)


def test_imu_check_without_imu():
    r = parse_bin(packet(SLOW, 0, *zeros(SLOW)))
    assert imu_unit_check([r], QualityConfig())["mensagem"] == "Sem canais de aceleração no log."

"""Bug A: rollover do uint32 entre grupos (um grupo começa antes de 2**32, outro depois).

Os timestamps eram desenrolados grupo a grupo; um grupo cujo primeiro pacote chega
depois do estouro ficava ~49,7 dias "antes" dos outros, e a grade comum passava a
ter ~860 milhões de amostras por canal (~7 GB).
"""

import csv
import hashlib

import numpy as np
import pytest

import exporter
from builders import U32, packet, payload, staggered_log, synthetic_log
from exporter import write_csv, write_ld
from ldparser.ldparser import read_ldfile
from parser import parse_bin

MAX_SPAN_MS = 3_600_000          # nenhum log de teste passa de alguns segundos


@pytest.fixture
def no_huge_grids(monkeypatch):
    """Falha cedo em vez de alocar gigabytes quando o bug está presente."""
    real = exporter.resample_uniform

    def guarded(ts_ms, values, freq_hz, t0_ms, hold=False):
        span = float(np.max(ts_ms)) - t0_ms
        assert span <= MAX_SPAN_MS, f"grade de {span / 3.6e6:.0f} h pedida ao reamostrador"
        return real(ts_ms, values, freq_hz, t0_ms, hold=hold)

    monkeypatch.setattr(exporter, "resample_uniform", guarded)


def slow_group_starts_after_wrap() -> bytes:
    """IMU desde 2**32 - 50 ms; Motor_Lento só aparece depois do estouro."""
    start, buf = U32 - 50, bytearray()
    for t in range(0, 1000, 5):
        buf += packet(0x01, (start + t) % U32, *payload(0x01, t))
        if t >= 100 and t % 100 == 0:
            buf += packet(0x04, (start + t) % U32, *payload(0x04, t))
    return bytes(buf)


@pytest.mark.xfail(strict=True, reason="Bug A: unwrap por grupo desalinha grupos "
                                       "que começam depois do rollover")
def test_group_starting_after_rollover_shares_origin_with_others(tmp_path, no_huge_grids):
    path = tmp_path / "x.csv"
    write_csv(parse_bin(slow_group_starts_after_wrap()), path)
    lengths = {r[0]: len(r) - 3 for r in csv.reader(path.open())}
    # origem comum = 2**32 - 50: IMU de 0 a 995 ms (200), Motor_Lento até 900 ms (10)
    assert (lengths["Acel_X"], lengths["Temp_Motor"]) == (200, 10)


# --- regressão: a correção não pode mudar a saída de logs sem rollover entre grupos ---

def fingerprint(result, tmp_path) -> str:
    """SHA-256 do CSV e dos canais relidos do .ld (o cabeçalho do .ld tem data/hora)."""
    csv_path, ld_path = tmp_path / "x.csv", str(tmp_path / "x.ld")
    write_csv(result, csv_path)
    write_ld(result, ld_path)
    h = hashlib.sha256(csv_path.read_bytes())
    for c in read_ldfile(ld_path)[1]:
        h.update(f"{c.name}|{c.unit}|{c.freq}|".encode())
        h.update(np.asarray(c.data, dtype=np.float32).tobytes())
    return h.hexdigest()


# capturados com o código ANTES da correção do Bug A (commit 4280f33)
GOLDEN = {
    "normal": "f16e2364c9125898a9756b6c76353bd55b3ff9b8ffe7ca333031ff214dc51e13",
    "wrap_in_all_groups": "f16e2364c9125898a9756b6c76353bd55b3ff9b8ffe7ca333031ff214dc51e13",
    "staggered_event_driven": "b32341bc14b9c01a2fe664aaa00742b0707a77772d8a254b55b7bc47f44aeabd",
}
LOGS = {
    "normal": lambda: synthetic_log(2000),
    "wrap_in_all_groups": lambda: synthetic_log(2000, start_ms=U32 - 1000),
    "staggered_event_driven": staggered_log,
}


@pytest.mark.parametrize("name", sorted(LOGS))
def test_export_of_logs_without_cross_group_rollover_is_unchanged(tmp_path, name):
    assert fingerprint(parse_bin(LOGS[name]()), tmp_path) == GOLDEN[name]

"""Montagem de streams .bin sintéticos com struct.pack (sem arquivos binários no repo)."""

from packets import PACKETS

U32 = 2**32

# período nominal (ms) de cada grupo: 200 / 50 / 50 / 10 Hz
PERIOD_MS = {pid: round(1000 / d.freq_hz) for pid, d in PACKETS.items()}


def packet(pid: int, ts: int, *values) -> bytes:
    """Um pacote no layout do firmware: ID (u8) + timestamp (u32 ms) + payload, little-endian."""
    return PACKETS[pid].struct.pack(pid, ts, *values)


def zeros(pid: int) -> tuple:
    return (0,) * len(PACKETS[pid].channels)


def payload(pid: int, t: int) -> tuple:
    """Valores determinísticos para o instante t (ms).

    Os floats são múltiplos de 1/8, exatos em float32 e float64, para que as
    comparações não dependam de arredondamento da plataforma.
    """
    n = len(PACKETS[pid].channels)
    if pid == 0x03:                             # "Hb4f": RPM (u16), marcha (i8), 4 floats
        rpm = 8000 + (t // 5) % 4000
        gear = 1 + (t // 1000) % 5
        return (rpm, gear) + tuple(((t + 37 * k) % 800) / 8 for k in range(4))
    return tuple(((t + 37 * k) % 800) / 8 - 50 for k in range(n))


def synthetic_log(duration_ms: int, start_ms: int = 0) -> bytes:
    """Log multiplexado com os 4 grupos nas taxas nominais, em ordem de tempo.

    O timestamp gravado é (start_ms + t) mod 2**32, como o contador uint32 do
    ESP32; com start_ms perto de 2**32 o log atravessa o rollover.
    """
    buf = bytearray()
    for t in range(0, duration_ms, PERIOD_MS[0x01]):
        for pid, period in PERIOD_MS.items():
            if t % period == 0:
                buf += packet(pid, (start_ms + t) % U32, *payload(pid, t))
    return bytes(buf)


def ramp(n: int, start: float = 0.0, step: float = 1.0) -> list:
    return [start + i * step for i in range(n)]

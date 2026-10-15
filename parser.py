"""Parser do .bin (leitura inteira em RAM + struct.unpack_from)."""

from dataclasses import dataclass, field

import numpy as np
from typing import Callable, Optional

from packets import PACKETS, PacketDef


@dataclass
class GroupData:
    definition: PacketDef
    timestamps_ms: list = field(default_factory=list)     # absolutos, do dispositivo
    columns: list = field(default_factory=list)           # uma lista por canal

    def __post_init__(self):
        if not self.columns:
            self.columns = [[] for _ in self.definition.channels]


@dataclass
class ParseResult:
    groups: dict                      # packet_id -> GroupData
    total_packets: int = 0
    bytes_read: int = 0
    bytes_total: int = 0
    warnings: list = field(default_factory=list)


def parse_bin(data: bytes,
              progress_cb: Optional[Callable[[float], None]] = None,
              packets: dict = None) -> ParseResult:
    """Percorre o buffer pacote a pacote.

    Se encontrar um ID desconhecido, para (não há como saber o tamanho) e
    registra um aviso com o offset. Um pacote truncado no fim do arquivo é
    descartado com aviso.
    """
    packets = packets or PACKETS
    structs = {pid: (d, d.struct) for pid, d in packets.items()}
    result = ParseResult(groups={}, bytes_total=len(data))
    n = len(data)
    offset = 0
    last_report = 0

    while offset < n:
        pid = data[offset]
        entry = structs.get(pid)
        if entry is None:
            result.warnings.append(
                f"ID desconhecido 0x{pid:02X} no offset {offset}; "
                f"leitura interrompida ({n - offset} bytes ignorados).")
            break
        definition, st = entry
        if offset + st.size > n:
            result.warnings.append(
                f"Pacote 0x{pid:02X} truncado no fim do arquivo "
                f"(offset {offset}); descartado.")
            break

        values = st.unpack_from(data, offset)       # (id, ts, *payload)
        group = result.groups.get(pid)
        if group is None:
            group = result.groups[pid] = GroupData(definition)
        group.timestamps_ms.append(values[1])
        for col, v in zip(group.columns, values[2:]):
            col.append(v)

        offset += st.size
        result.total_packets += 1

        if progress_cb and offset - last_report > 1_000_000:
            last_report = offset
            progress_cb(offset / n)

    result.bytes_read = offset
    if progress_cb:
        progress_cb(1.0)
    return result


def parse_file(path: str, progress_cb=None) -> ParseResult:
    with open(path, "rb") as f:
        data = f.read()
    return parse_bin(data, progress_cb)


def unwrap_timestamps(ts) -> np.ndarray:
    """Corrige estouro do uint32 (~49 dias): soma 2**32 a cada vez que o tempo volta."""
    ts = np.asarray(ts, dtype=np.int64)
    if ts.size < 2:
        return ts
    wraps = np.concatenate(([0], np.cumsum(np.diff(ts) < -(2**31))))
    return ts + wraps * (2**32)


def resample_uniform(ts_ms, values, freq_hz: float, t0_ms: float,
                     hold: bool = False) -> np.ndarray:
    """Reamostra para uma grade uniforme em freq_hz, começando em t0_ms (NumPy).

    O .ld guarda cada canal com frequência fixa, enquanto o log é orientado a
    evento. hold=False: interpolação linear; hold=True: mantém o último valor
    (canais discretos como marcha). Antes do primeiro pacote e depois do último
    o valor da borda é repetido. Retorna np.ndarray float64.
    """
    ts = np.asarray(ts_ms, dtype=np.float64)
    vals = np.asarray(values, dtype=np.float64)
    if ts.size == 0:
        return np.empty(0)
    if ts.size > 1:
        # timestamps repetidos (mesmo ms): fica a última amostra de cada instante
        keep = np.append(ts[1:] != ts[:-1], True)
        ts, vals = ts[keep], vals[keep]
    step = 1000.0 / freq_hz
    n_out = max(int(np.floor((ts[-1] - t0_ms) / step)) + 1, 1)
    grid = t0_ms + np.arange(n_out) * step
    if hold:
        idx = np.clip(np.searchsorted(ts, grid, side="right") - 1, 0, ts.size - 1)
        return vals[idx]
    return np.interp(grid, ts, vals)

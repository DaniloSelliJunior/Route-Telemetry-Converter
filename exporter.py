"""Exportadores: .ld (MoTeC i2 Pro) e CSV de apoio.

A escrita do .ld usa MotecLog do repositório stevendaniluk/MotecLogGenerator
(WTFPL), copiado em `motec_lib/` (sem a dependência `cantools`). O
`add_channel` original cria um objeto Message por amostra e faz np.append em
laço (custo quadrático: ~2 min para 30 min de log). Aqui usamos
`add_fast_channel`, que recebe um array NumPy pronto.
"""

import csv
import os
import sys
from typing import Callable, Optional

import numpy as np

from parser import ParseResult, resample_uniform, unwrap_timestamps

# motec_lib precisa estar no sys.path (imports "data_log" e "ldparser.ldparser")
_BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_BASE, "motec_lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)


def _build_channels(result: ParseResult):
    """Lista de (nome, unidade, freq_hz, np.ndarray reamostrado).

    Todos os canais começam no menor timestamp do arquivo (t = 0 s).
    """
    all_ts = {pid: unwrap_timestamps(g.timestamps_ms)
              for pid, g in result.groups.items()}
    # grupo cujo 1º pacote veio depois de um rollover fica 2**32 "atrás" dos outros
    latest = max(int(ts[0]) for ts in all_ts.values())
    for ts in all_ts.values():
        while latest - ts[0] > 2**31:
            ts += 2**32
    t0 = min(int(ts[0]) for ts in all_ts.values())
    channels = []
    for pid, group in result.groups.items():
        d = group.definition
        for ch, col in zip(d.channels, group.columns):
            data = resample_uniform(all_ts[pid], col, d.freq_hz, t0, hold=ch.hold)
            channels.append((ch.name, ch.unit, d.freq_hz, data))
    return channels


def write_csv(result: ParseResult, path: str):
    """CSV de apoio/depuração: um canal por linha (cada um na sua frequência)."""
    channels = _build_channels(result)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for name, unit, freq, data in channels:
            w.writerow([name, unit, f"{freq:g}Hz"] + [f"{v:.6g}" for v in data])


def write_ld(result: ParseResult, path: str, driver="Piloto Route",
             vehicle="FR2026", venue="UFSCar", event="", session="",
             comment="Convertido do .bin",
             progress_cb: Optional[Callable[[float], None]] = None):
    if not result.groups:
        raise ValueError("Nenhum dado válido encontrado no arquivo.")

    from motec_log import MotecLog
    from ldparser.ldparser import ldChan

    class RouteMotecLog(MotecLog):
        def add_fast_channel(self, name, unit, freq_hz, data):
            """Igual a MotecLog.add_channel, mas recebe um np.ndarray pronto."""
            arr = np.ascontiguousarray(data, dtype=np.float32)

            self.ld_header.data_ptr += self.CHANNEL_HEADER_SIZE
            for ld_channel in self.ld_channels:
                ld_channel.data_ptr += self.CHANNEL_HEADER_SIZE

            if self.ld_channels:
                meta_ptr = self.ld_channels[-1].next_meta_ptr
                prev_meta_ptr = self.ld_channels[-1].meta_ptr
                data_ptr = self.ld_channels[-1].data_ptr + self.ld_channels[-1]._data.nbytes
            else:
                meta_ptr = self.HEADER_PTR
                prev_meta_ptr = 0
                data_ptr = self.ld_header.data_ptr
            next_meta_ptr = meta_ptr + self.CHANNEL_HEADER_SIZE

            # frequência inteira (limitação do .ld); casas decimais = 0 (limitação do ldparser)
            ld_channel = ldChan(None, meta_ptr, prev_meta_ptr, next_meta_ptr, data_ptr,
                                len(arr), np.float32, int(freq_hz), 0, 1, 1, 0,
                                name, "", unit)
            ld_channel._data = arr
            self.ld_channels.append(ld_channel)

    log = RouteMotecLog()
    log.driver = driver
    log.vehicle_id = vehicle
    log.venue_name = venue
    log.event_name = event
    log.event_session = session
    log.short_comment = comment[:8]       # campo curto do cabeçalho .ld
    log.long_comment = comment
    log.initialize()

    channels = _build_channels(result)
    if progress_cb:
        progress_cb(0.5)
    for i, (name, unit, freq, data) in enumerate(channels):
        log.add_fast_channel(name, unit, freq, data)
    if progress_cb:
        progress_cb(0.8)

    log.write(path)
    if progress_cb:
        progress_cb(1.0)

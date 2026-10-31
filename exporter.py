"""Exportadores: .ld (MoTeC i2 Pro) e CSV de apoio.

A escrita do .ld usa MotecLog do repositório stevendaniluk/MotecLogGenerator
(WTFPL), copiado em `motec_lib/` (sem a dependência `cantools`). O
`add_channel` original cria um objeto Message por amostra e faz np.append em
laço (custo quadrático: ~2 min para 30 min de log). Aqui usamos
`add_fast_channel`, que recebe um array NumPy pronto.

Os arquivos são gravados num temporário na mesma pasta e renomeados no fim,
então uma falha no meio nunca deixa um .ld/.csv pela metade nem estraga o
arquivo anterior.
"""

import csv
import datetime
import os
import sys
import uuid
from contextlib import contextmanager
from typing import Callable, Optional

import numpy as np

from parser import ParseResult, aligned_timestamps, resample_uniform

# motec_lib precisa estar no sys.path (imports "data_log" e "ldparser.ldparser")
_BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_BASE, "motec_lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

# teto de segurança da grade reamostrada: acima disso é quase certo que há um
# salto de timestamp não tratado (ver parser.check_timestamps)
MAX_GRID_SPAN_S = 4 * 3600


def require_data(result: ParseResult):
    """ValueError com os avisos do parser (ID e offset) se não houver nenhum dado válido."""
    if not result.groups:
        msg = "Nenhum dado válido encontrado no arquivo."
        if result.warnings:
            msg += " Avisos do parser: " + " | ".join(result.warnings)
        raise ValueError(msg)


@contextmanager
def atomic_path(path):
    """Caminho temporário na mesma pasta de `path`; renomeado para `path` se o bloco terminar sem erro."""
    path = os.fspath(path)
    folder, name = os.path.split(os.path.abspath(path))
    tmp = os.path.join(folder, f".{name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        yield tmp
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def segment_paths(path: str, n_segments: int) -> list:
    """Nome de saída de cada segmento: o próprio `path` se houver um só, senão nome_segN.ext."""
    if n_segments <= 1:
        return [path]
    base, ext = os.path.splitext(path)
    return [f"{base}_seg{i}{ext}" for i in range(1, n_segments + 1)]


def check_span(all_ts: dict, t0: int, max_span_s: float = MAX_GRID_SPAN_S):
    """ValueError se o log cobrir mais que max_span_s (antes de alocar qualquer grade)."""
    span_s = max(int(ts.max()) - t0 for ts in all_ts.values()) / 1000.0
    if span_s > max_span_s:
        raise ValueError(
            f"O log cobre {span_s / 3600:.1f} h, acima do limite de segurança de "
            f"{max_span_s / 3600:g} h para a grade reamostrada. Provável salto de "
            f"timestamp não tratado (use parser.check_timestamps).")


def _build_channels(result: ParseResult, max_span_s: float = MAX_GRID_SPAN_S):
    """Lista de (nome, unidade, freq_hz, np.ndarray reamostrado).

    Todos os canais começam no menor timestamp do arquivo (t = 0 s). Se o log
    cobrir mais de max_span_s, levanta ValueError antes de alocar a grade.
    """
    all_ts, t0 = aligned_timestamps(result)
    check_span(all_ts, t0, max_span_s)
    channels = []
    for pid, group in result.groups.items():
        d = group.definition
        for ch, col in zip(d.channels, group.columns):
            data = resample_uniform(all_ts[pid], col, d.freq_hz, t0, hold=ch.hold)
            channels.append((ch.name, ch.unit, d.freq_hz, data))
    return channels


def resampled_channels(result: ParseResult):
    """Canais na grade do .ld: ({nome: (t_s, valores)}, {nome: unidade}, {nome: freq_hz}).

    t_s em segundos desde o 1º pacote do arquivo (mesma origem do .ld e do CSV).
    Entrada dos canais derivados e dos KPIs.
    """
    require_data(result)
    data, units, freqs = {}, {}, {}
    for name, unit, freq, values in _build_channels(result):
        data[name] = (np.arange(values.size) / freq, values)
        units[name] = unit
        freqs[name] = freq
    return data, units, freqs


def write_csv(result: ParseResult, path: str):
    """CSV de apoio/depuração: um canal por linha (cada um na sua frequência)."""
    require_data(result)
    channels = _build_channels(result)
    with atomic_path(path) as tmp:
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for name, unit, freq, data in channels:
                w.writerow([name, unit, f"{freq:g}Hz"] + [f"{v:.6g}" for v in data])


def write_ld(result: ParseResult, path: str, driver="Piloto Route",
             vehicle="FR2026", venue="UFSCar", event="", session="",
             comment="Convertido do .bin",
             progress_cb: Optional[Callable[[float], None]] = None,
             log_datetime: Optional[datetime.datetime] = None,
             extra_channels: Optional[list] = None):
    """Grava o .ld. A data/hora do cabeçalho é `log_datetime`; sem ela, a data de
    modificação do .bin (result.source_mtime) e, em último caso, a hora atual.

    extra_channels: [(nome, unidade, freq_hz, array)] gravados depois dos canais
    do log (canais derivados)."""
    require_data(result)

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

    if log_datetime is None and result.source_mtime is not None:
        log_datetime = datetime.datetime.fromtimestamp(result.source_mtime)

    log = RouteMotecLog()
    log.driver = driver
    log.vehicle_id = vehicle
    log.venue_name = venue
    log.event_name = event
    log.event_session = session
    log.short_comment = comment[:8]       # campo curto do cabeçalho .ld
    log.long_comment = comment
    if log_datetime is not None:
        log.datetime = log_datetime
    log.initialize()

    channels = _build_channels(result) + list(extra_channels or [])
    if progress_cb:
        progress_cb(0.5)
    for i, (name, unit, freq, data) in enumerate(channels):
        log.add_fast_channel(name, unit, freq, data)
    if progress_cb:
        progress_cb(0.8)

    with atomic_path(path) as tmp:
        log.write(tmp)
    if progress_cb:
        progress_cb(1.0)

"""Parser do .bin (leitura inteira em RAM + struct.unpack_from)."""

import os
import re
from dataclasses import dataclass, field

import numpy as np
from typing import Callable, Optional

from packets import PACKETS, PacketDef

U32 = 2**32
# maior intervalo aceito entre pacotes "vizinhos" no tempo (ressincronização e saltos)
DEFAULT_MAX_GAP_MS = 60_000
# passo para trás tolerado na ordem do arquivo (pacotes event-driven gravados com atraso)
DEFAULT_MAX_BACKSTEP_MS = 1_000
# trecho com menos pacotes que isso entre dois saltos é tratado como pacote(s) isolado(s)
DEFAULT_MIN_SEGMENT_PACKETS = 10

# pacotes seguintes que precisam encadear para aceitar um offset na ressincronização:
# curto quando o timestamp é coerente com o histórico, longo quando não há referência coerente
_CHAIN_SHORT = 1
_CHAIN_LONG = 8
# avisos individuais de ressincronização; acima disso só um resumo no fim
MAX_RESYNC_WARNINGS = 20


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
    bytes_read: int = 0               # bytes de pacotes aceitos
    bytes_total: int = 0
    warnings: list = field(default_factory=list)
    bytes_discarded: int = 0          # lixo, pacotes incompletos e cauda truncada
    packets_discarded: int = 0        # pacotes decodificados e depois descartados (incompletos)
    resyncs: list = field(default_factory=list)   # (offset, offset_retomada | None, bytes, motivo)
    order: bytearray = field(default_factory=bytearray)  # ID de cada pacote aceito, na ordem do arquivo
    source_path: Optional[str] = None
    source_mtime: Optional[float] = None          # data de modificação do .bin (epoch)


def _near(ts: int, ref: int, max_gap_ms: int) -> bool:
    """|ts - ref| <= max_gap_ms em aritmética módulo 2**32 (atravessa o rollover)."""
    d = (ts - ref) & 0xFFFFFFFF
    return d <= max_gap_ms or d >= U32 - max_gap_ms


def parse_bin(data: bytes,
              progress_cb: Optional[Callable[[float], None]] = None,
              packets: dict = None,
              max_gap_ms: int = DEFAULT_MAX_GAP_MS) -> ParseResult:
    """Percorre o buffer pacote a pacote, ressincronizando após dados corrompidos.

    Um pacote é aceito direto quando o ID é conhecido e o timestamp é coerente
    com o último do mesmo grupo (ou o último do arquivo, se o grupo ainda não
    apareceu). Se não for coerente (reset do ESP32, pausa longa), ele só é
    aceito se os _CHAIN_LONG pacotes seguintes encadearem com timestamps
    próximos entre si.

    Com ID desconhecido ou timestamp incoerente, o stream perdeu o alinhamento
    (não há campo de tamanho): procura-se o próximo offset plausível (ID válido,
    timestamp coerente e pacote seguinte encadeado) a partir do byte seguinte
    ao início do último pacote aceito, que também é descartado por ser vizinho
    dos dados corrompidos. Bytes descartados e offsets vão para `warnings`
    (até MAX_RESYNC_WARNINGS avisos individuais) e `resyncs`.
    """
    packets = packets if packets is not None else PACKETS
    structs = {pid: (d, d.struct) for pid, d in packets.items()}
    result = ParseResult(groups={}, bytes_total=len(data))
    n = len(data)
    if not structs:
        if n:
            result.bytes_discarded = n
            result.warnings.append(
                f"Nenhum tipo de pacote definido; {n} bytes ignorados.")
        return result
    id_re = re.compile(b"[" + b"".join(re.escape(bytes([p])) for p in structs) + b"]")

    groups = result.groups
    order = result.order
    last_ts = {}            # pid -> último timestamp aceito
    last_any = None         # último timestamp aceito (qualquer grupo)
    # para desfazer o último pacote aceito: (offset, pid, tamanho, last_ts anterior, last_any anterior)
    last_pkt = None
    omitted = [0, 0]        # ressincronizações / bytes sem aviso individual

    def chain_ok(pos: int, depth: int, prev_ts: int) -> bool:
        """`depth` pacotes encadeados a partir de pos, com timestamps próximos entre si.

        Fim do arquivo (exato ou com pacote truncado) conta como cadeia válida.
        """
        for _ in range(depth):
            if pos >= n:
                return True
            entry = structs.get(data[pos])
            if entry is None:
                return False
            size = entry[1].size
            if pos + size > n:
                return True
            ts = int.from_bytes(data[pos + 1:pos + 5], "little")
            if not _near(ts, prev_ts, max_gap_ms):
                return False
            prev_ts = ts
            pos += size
        return True

    def plausible(pos: int) -> bool:
        entry = structs.get(data[pos])
        if entry is None:
            return False
        size = entry[1].size
        if pos + size > n:
            return False
        ts = int.from_bytes(data[pos + 1:pos + 5], "little")
        ref = last_ts.get(data[pos], last_any)
        if ref is None or _near(ts, ref, max_gap_ms):
            return chain_ok(pos + size, _CHAIN_SHORT, ts)
        return chain_ok(pos + size, _CHAIN_LONG, ts)

    def find_next(pos: int) -> Optional[int]:
        while True:
            m = id_re.search(data, pos)
            if m is None:
                return None
            k = m.start()
            if plausible(k):
                return k
            pos = k + 1

    def drop_last():
        """Desfaz o último pacote aceito (vizinho de dados corrompidos)."""
        nonlocal last_any, last_pkt
        _, pid, size, prev_group_ts, prev_any = last_pkt
        g = groups[pid]
        g.timestamps_ms.pop()
        for col in g.columns:
            col.pop()
        if not g.timestamps_ms:
            del groups[pid]
        order.pop()
        if prev_group_ts is None:
            last_ts.pop(pid, None)
        else:
            last_ts[pid] = prev_group_ts
        last_any = prev_any
        result.total_packets -= 1
        result.bytes_read -= size
        result.packets_discarded += 1
        last_pkt = None

    def warn_resync(msg: str, nbytes: int):
        if len(result.resyncs) <= MAX_RESYNC_WARNINGS:      # já inclui o evento atual
            result.warnings.append(msg)
        else:
            omitted[0] += 1
            omitted[1] += nbytes

    offset = 0
    last_report = 0

    while offset < n:
        pid = data[offset]
        entry = structs.get(pid)
        reason = None
        if entry is None:
            reason = f"ID desconhecido 0x{pid:02X} no offset {offset}"
        else:
            definition, st = entry
            size = st.size
            if offset + size > n:
                reason = "truncado"
            else:
                values = st.unpack_from(data, offset)       # (id, ts, *payload)
                ts = values[1]
                ref = last_ts.get(pid, last_any)
                if ref is not None:
                    d = (ts - ref) & 0xFFFFFFFF
                    ok = (d <= max_gap_ms or d >= U32 - max_gap_ms
                          or chain_ok(offset + size, _CHAIN_LONG, ts))
                else:
                    ok = True       # 1º pacote: desfeito se vier lixo logo depois
                if ok:
                    group = groups.get(pid)
                    if group is None:
                        group = groups[pid] = GroupData(definition)
                    group.timestamps_ms.append(ts)
                    for col, v in zip(group.columns, values[2:]):
                        col.append(v)
                    order.append(pid)
                    last_pkt = (offset, pid, size, last_ts.get(pid), last_any)
                    last_ts[pid] = ts
                    last_any = ts
                    offset += size
                    result.total_packets += 1
                    result.bytes_read += size

                    if progress_cb and offset - last_report > 1_000_000:
                        last_report = offset
                        progress_cb(offset / n)
                    continue
                reason = f"Timestamp incoerente no pacote 0x{pid:02X} (offset {offset})"

        # ---- perda de alinhamento: procurar o próximo offset plausível ------
        # Busca a partir do byte seguinte ao início do último pacote: se ele perdeu
        # bytes, o próximo pacote válido começa dentro dele.
        start = last_pkt[0] + 1 if last_pkt else offset + 1
        k = find_next(start)
        # O pacote logo antes do trecho corrompido também é descartado: não há como
        # saber se ele foi cortado (byte perdido, lixo no meio dele, escrita parcial
        # seguida de zeros). Exceção: pacote truncado no fim do arquivo, sem mais nada.
        truncated_tail = reason == "truncado" and k is None
        if last_pkt is not None and not truncated_tail:
            discard_from = last_pkt[0]
            drop_last()
        else:
            discard_from = offset
        stop = k if k is not None else n
        nbytes = stop - discard_from
        result.bytes_discarded += nbytes

        if truncated_tail:
            result.resyncs.append((offset, None, nbytes, "truncado"))
            result.warnings.append(
                f"Pacote 0x{pid:02X} truncado no fim do arquivo "
                f"(offset {offset}); descartado.")
            break
        if reason == "truncado":
            reason = f"Pacote 0x{pid:02X} sem espaço até o fim do arquivo (offset {offset})"
        result.resyncs.append((discard_from, k, nbytes, reason))
        tail = (f"; pacote anterior (offset {discard_from}) descartado"
                if discard_from < offset else "")
        if k is None:
            warn_resync(f"{reason}; nenhum pacote válido até o fim do arquivo "
                        f"({nbytes} bytes descartados{tail}).", nbytes)
            break
        warn_resync(f"{reason}; ressincronizado no offset {k} "
                    f"({nbytes} bytes descartados{tail}).", nbytes)
        offset = k

    if omitted[0]:
        result.warnings.append(
            f"Mais {omitted[0]} ressincronizações sem aviso individual "
            f"({omitted[1]} bytes descartados).")
    if progress_cb:
        progress_cb(1.0)
    return result


def parse_file(path: str, progress_cb=None, **kwargs) -> ParseResult:
    with open(path, "rb") as f:
        data = f.read()
    result = parse_bin(data, progress_cb, **kwargs)
    result.source_path = os.fspath(path)
    try:
        result.source_mtime = os.path.getmtime(path)
    except OSError:
        pass
    return result


def unwrap_timestamps(ts) -> np.ndarray:
    """Corrige estouro do uint32 (~49 dias): soma 2**32 a cada vez que o tempo volta."""
    ts = np.asarray(ts, dtype=np.int64)
    if ts.size < 2:
        return ts
    wraps = np.concatenate(([0], np.cumsum(np.diff(ts) < -(2**31))))
    return ts + wraps * (2**32)


def aligned_timestamps(result: ParseResult):
    """Timestamps desenrolados por grupo numa escala comum: (dict pid -> int64, t0_ms).

    Um grupo cujo 1º pacote veio depois de um rollover fica 2**32 "atrás" dos
    outros e é deslocado; t0 é o menor timestamp do arquivo.
    """
    all_ts = {pid: unwrap_timestamps(g.timestamps_ms)
              for pid, g in result.groups.items()}
    latest = max(int(ts[0]) for ts in all_ts.values())
    for ts in all_ts.values():
        while latest - ts[0] > 2**31:
            ts += 2**32
    t0 = min(int(ts[0]) for ts in all_ts.values())
    return all_ts, t0


def _signed_delta(d) -> np.ndarray:
    """Diferença de timestamps uint32 com sinal, no intervalo [-2**31, 2**31)."""
    return ((np.asarray(d, dtype=np.int64) + 2**31) % U32) - 2**31


@dataclass
class TimeJump:
    index: int        # posição (ordem do arquivo) do 1º pacote depois do salto
    delta_ms: int     # com sinal: negativo = reset / volta no tempo
    kind: str         # "salto" | "reset"


@dataclass
class TimeCheck:
    segments: list                                # ParseResult por trecho contínuo
    dropped_packets: int = 0                      # pacotes isolados descartados
    jumps: list = field(default_factory=list)     # TimeJump entre segmentos
    warnings: list = field(default_factory=list)


def _file_order(result: ParseResult) -> np.ndarray:
    """IDs na ordem do arquivo. Sem `order` (resultado montado à mão), ordena por tempo."""
    sizes = {pid: len(g.timestamps_ms) for pid, g in result.groups.items()}
    order = np.frombuffer(bytes(result.order), dtype=np.uint8)
    if order.size == sum(sizes.values()) and all(
            int(np.count_nonzero(order == pid)) == k for pid, k in sizes.items()):
        return order
    pids = np.concatenate([np.full(k, pid, dtype=np.uint8) for pid, k in sizes.items()]
                          or [np.empty(0, np.uint8)])
    ts = np.concatenate([np.asarray(g.timestamps_ms, dtype=np.int64)
                         for g in result.groups.values()] or [np.empty(0, np.int64)])
    return pids[np.argsort(ts, kind="stable")]


def _subset(result: ParseResult, order: np.ndarray, mask: np.ndarray) -> ParseResult:
    """Novo ParseResult só com os pacotes marcados em `mask` (ordem do arquivo)."""
    groups = {}
    for pid, g in result.groups.items():
        sel = mask[order == pid]
        if not sel.any():
            continue
        ng = GroupData(g.definition)
        ng.timestamps_ms = np.asarray(g.timestamps_ms)[sel].tolist()
        ng.columns = [np.asarray(col)[sel].tolist() for col in g.columns]
        groups[pid] = ng
    sub = order[mask]
    return ParseResult(groups=groups, total_packets=int(sub.size),
                       bytes_total=result.bytes_total, order=bytearray(sub.tobytes()),
                       source_path=result.source_path, source_mtime=result.source_mtime)


def check_timestamps(result: ParseResult,
                     max_gap_ms: int = DEFAULT_MAX_GAP_MS,
                     max_backstep_ms: int = DEFAULT_MAX_BACKSTEP_MS,
                     min_segment_packets: int = DEFAULT_MIN_SEGMENT_PACKETS) -> TimeCheck:
    """Saltos e resets de timestamp na sequência do arquivo (todos os grupos juntos).

    Entre dois pacotes consecutivos do arquivo, avançar mais de max_gap_ms ou
    voltar mais de max_backstep_ms é uma quebra. Trechos entre quebras com
    menos de min_segment_packets pacotes são pacotes isolados (timestamp
    absurdo) e são descartados; as quebras que sobram (reboot do ESP32, pausa
    do logger) dividem o log em segmentos, exportados separadamente.

    Lacunas que afetam só um grupo (os outros seguem gravando) não quebram o
    log: a linha do tempo continua definida; elas aparecem no relatório de
    qualidade. Sem quebras, devolve o próprio `result` como único segmento.
    """
    order = _file_order(result)
    n = order.size
    if n < 2:
        return TimeCheck(segments=[result] if result.groups else [])
    ts = np.empty(n, dtype=np.int64)
    for pid, g in result.groups.items():
        ts[order == pid] = g.timestamps_ms

    def breaks(t):
        d = _signed_delta(np.diff(t))
        return d, (d > max_gap_ms) | (d < -max_backstep_ms)

    _, brk = breaks(ts)
    if not brk.any():
        return TimeCheck(segments=[result])

    check = TimeCheck(segments=[])
    run_id = np.concatenate(([0], np.cumsum(brk)))
    counts = np.bincount(run_id)
    big = counts >= min_segment_packets
    if not big.any():
        big[np.argmax(counts)] = True
    keep = big[run_id]
    check.dropped_packets = int(n - np.count_nonzero(keep))
    if check.dropped_packets:
        for r in np.flatnonzero(~big):
            idx = np.flatnonzero(run_id == r)
            check.warnings.append(
                f"{idx.size} pacote(s) isolado(s) com timestamp fora da sequência "
                f"(pacote nº {idx[0]}, t = {ts[idx[0]]} ms) descartado(s).")

    kept = np.flatnonzero(keep)
    d2, brk2 = breaks(ts[kept])
    seg_of_kept = np.concatenate(([0], np.cumsum(brk2)))
    for i in np.flatnonzero(brk2):
        jump = TimeJump(index=int(kept[i + 1]), delta_ms=int(d2[i]),
                        kind="reset" if d2[i] < 0 else "salto")
        check.jumps.append(jump)
        what = "Reset de timestamp" if jump.kind == "reset" else "Salto de timestamp"
        check.warnings.append(
            f"{what} de {jump.delta_ms / 1000:+.1f} s no pacote nº {jump.index} "
            f"({ts[kept[i]]} -> {ts[kept[i + 1]]} ms); log dividido em segmentos.")

    seg = np.full(n, -1)
    seg[kept] = seg_of_kept
    for s in range(int(seg_of_kept[-1]) + 1):
        check.segments.append(_subset(result, order, seg == s))
    return check


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
        # np.interp/searchsorted exigem tempo crescente; estável = empate mantém ordem do arquivo
        order = np.argsort(ts, kind="stable")
        ts, vals = ts[order], vals[order]
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

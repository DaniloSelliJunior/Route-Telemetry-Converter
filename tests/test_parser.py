"""parse_bin / parse_file: stream little-endian, event-driven, taxa mista, sem header global."""

import pytest

from builders import PERIOD_MS, packet, payload, synthetic_log, zeros
from packets import PACKETS, Channel, PacketDef
from parser import MAX_RESYNC_WARNINGS, parse_bin, parse_file

IMU = 0x01


def imu_stream(n: int) -> bytes:
    return b"".join(packet(IMU, i * 5, *payload(IMU, i * 5)) for i in range(n))


# --- decodificação ----------------------------------------------------------

def test_decodes_hand_written_little_endian_bytes():
    # escrito à mão (sem struct) para não usar o próprio formato como oráculo:
    # ID 0x01, ts = 0x01020304, Acel_X = 1.0f (0x3F800000), demais = 0.0f
    raw = (b"\x01" + b"\x04\x03\x02\x01" + b"\x00\x00\x80\x3f" + b"\x00" * 20)
    g = parse_bin(raw).groups[IMU]
    assert (g.timestamps_ms[0], g.columns[0][0]) == (0x01020304, 1.0)


@pytest.mark.parametrize("pid", sorted(PACKETS))
def test_decodes_every_payload_field_of_each_packet_type(pid):
    values = payload(pid, 1234)
    g = parse_bin(packet(pid, 1234, *values)).groups[pid]
    assert tuple(col[0] for col in g.columns) == values


@pytest.mark.parametrize("rpm, gear", [(0, -1), (65535, 127), (8000, -128)])
def test_decodes_integer_fields_at_type_limits(rpm, gear):
    g = parse_bin(packet(0x03, 0, rpm, gear, 0, 0, 0, 0)).groups[0x03]
    assert (g.columns[0][0], g.columns[1][0]) == (rpm, gear)


def test_mixed_rate_log_is_split_by_group_with_expected_counts(normal_log):
    # 2 s a 200/50/50/10 Hz
    counts = {pid: len(g.timestamps_ms) for pid, g in normal_log.groups.items()}
    assert counts == {0x01: 400, 0x02: 100, 0x03: 100, 0x04: 20}


def test_mixed_rate_log_keeps_each_group_timestamps_in_order(normal_log):
    for pid, g in normal_log.groups.items():
        assert g.timestamps_ms == list(range(0, 2000, PERIOD_MS[pid]))


def test_event_driven_irregular_order_preserves_per_group_sequence():
    order = [(0x04, 0), (0x01, 1), (0x01, 2), (0x03, 3), (0x02, 4), (0x01, 9), (0x04, 10)]
    r = parse_bin(b"".join(packet(pid, ts, *zeros(pid)) for pid, ts in order))
    seqs = {pid: g.timestamps_ms for pid, g in r.groups.items()}
    assert seqs == {0x04: [0, 10], 0x01: [1, 2, 9], 0x03: [3], 0x02: [4]}


def test_clean_log_has_no_warnings_and_reads_every_byte(normal_log, normal_log_bytes):
    assert (normal_log.warnings, normal_log.bytes_read) == ([], len(normal_log_bytes))


def test_new_packet_type_only_needs_a_definition():
    custom = {0x10: PacketDef(0x10, "Novo", 20.0, "hH", (Channel("a"), Channel("b")))}
    raw = custom[0x10].struct.pack(0x10, 7, -3, 9)
    g = parse_bin(raw, packets=custom).groups[0x10]
    assert (g.timestamps_ms, g.columns) == ([7], [[-3], [9]])


# --- arquivo vazio / truncado / bytes sobrando ------------------------------

def test_empty_input_returns_no_groups_and_no_warnings():
    r = parse_bin(b"")
    assert (r.groups, r.total_packets, r.warnings) == ({}, 0, [])


@pytest.mark.parametrize("partial", [1, 4, 5, 28])
def test_truncated_last_packet_is_dropped_and_earlier_ones_kept(partial):
    data = imu_stream(10) + imu_stream(1)[:partial]
    assert parse_bin(data).total_packets == 10


@pytest.mark.parametrize("partial", [1, 4, 5, 28])
def test_truncated_last_packet_produces_one_warning_with_offset(partial):
    data = imu_stream(10) + imu_stream(1)[:partial]
    assert parse_bin(data).warnings == [
        "Pacote 0x01 truncado no fim do arquivo (offset 290); descartado."]


def test_truncated_packet_leaves_bytes_read_before_partial_tail():
    data = imu_stream(3) + b"\x01\x00\x00"
    assert parse_bin(data).bytes_read == 3 * 29


def test_only_a_partial_packet_yields_no_groups():
    assert parse_bin(imu_stream(1)[:10]).groups == {}


@pytest.mark.parametrize("trailing", [b"\x00", b"\xff" * 7, b"\x00" * 64])
def test_trailing_garbage_keeps_valid_packets_except_the_one_touching_it(trailing):
    # o último pacote pode ter sido cortado (escrita parcial seguida de zeros)
    assert parse_bin(imu_stream(5) + trailing).total_packets == 4


@pytest.mark.parametrize("trailing", [b"\x00", b"\xff" * 7, b"\x00" * 64])
def test_trailing_garbage_is_reported_with_discarded_byte_count(trailing):
    r = parse_bin(imu_stream(5) + trailing)
    assert r.warnings == [f"ID desconhecido 0x{trailing[0]:02X} no offset 145; nenhum pacote "
                          f"válido até o fim do arquivo ({29 + len(trailing)} bytes "
                          f"descartados; pacote anterior (offset 116) descartado)."]
    assert (r.bytes_read, r.bytes_discarded, r.packets_discarded) == (116, 29 + len(trailing), 1)


# --- ID desconhecido / ressincronização --------------------------------------
# Sem campo de tamanho no stream, um ID desconhecido ou um byte perdido tira o
# parser de alinhamento. Ele procura o próximo offset plausível (ID válido,
# timestamp coerente, pacote seguinte encadeado) e segue. O pacote logo antes
# do trecho ruim também é descartado (pode ter sido cortado).

@pytest.mark.parametrize("position", [0, 1, 3, 10])
def test_unknown_id_is_skipped_and_parsing_continues(position):
    good = imu_stream(10)
    data = good[:position * 29] + b"\xfe" + good[position * 29:]
    r = parse_bin(data)
    lost = [] if position == 0 else [(position - 1) * 5]
    assert r.groups[IMU].timestamps_ms == [t for t in range(0, 50, 5) if t not in lost]
    assert r.bytes_discarded == 1 + 29 * len(lost)


@pytest.mark.parametrize("position", [0, 1, 3, 10])
def test_unknown_id_warning_names_id_offset_and_resume_point(position):
    good = imu_stream(10)
    data = good[:position * 29] + b"\xfe" + good[position * 29:]
    w = parse_bin(data).warnings[0]
    assert w.startswith(f"ID desconhecido 0xFE no offset {position * 29};")
    if position == 0:
        assert w.endswith("ressincronizado no offset 1 (1 bytes descartados).")
    elif position < 10:
        assert w.endswith(f"ressincronizado no offset {position * 29 + 1} (30 bytes descartados; "
                          f"pacote anterior (offset {(position - 1) * 29}) descartado).")


def test_unknown_id_at_start_is_skipped():
    r = parse_bin(b"\xfe\xfe\x07" + imu_stream(10))
    assert (r.total_packets, r.bytes_discarded, len(r.resyncs)) == (10, 3, 1)


def test_resync_records_offset_resume_point_and_discarded_bytes():
    good = imu_stream(10)
    r = parse_bin(good[:58] + b"\xfe\xfe" + good[58:])
    assert r.resyncs == [(29, 60, 31, "ID desconhecido 0xFE no offset 58")]


def test_bytes_read_plus_discarded_covers_whole_file():
    good = imu_stream(20)
    data = b"\x99" + good[:100] + good[101:300] + b"lixo" * 5 + good[300:] + b"\x00\x00"
    r = parse_bin(data)
    assert r.bytes_read + r.bytes_discarded == len(data)


def _offsets(raw: bytes):
    """Offset de início de cada pacote de um stream bem formado."""
    out, pos = [], 0
    while pos < len(raw):
        out.append(pos)
        pos += PACKETS[raw[pos]].size
    return out


def _without_packet(ref, raw, start):
    """Colunas de `ref` sem o pacote que começa em raw[start] (comparação exata)."""
    pid = raw[start]
    ts = int.from_bytes(raw[start + 1:start + 5], "little")
    i = ref.groups[pid].timestamps_ms.index(ts)
    cols = {p: g.columns for p, g in ref.groups.items()}
    cols[pid] = [col[:i] + col[i + 1:] for col in cols[pid]]
    return cols


@pytest.mark.parametrize("inside", [0, 13], ids=["at-boundary", "inside-packet"])
def test_garbage_in_the_middle_costs_only_the_packet_touching_it(normal_log_bytes, inside):
    offs = _offsets(normal_log_bytes)
    start = offs[300]
    garbage = bytes(range(256)) * 3                   # inclui bytes com IDs válidos
    # na fronteira, o pacote anterior é o descartado; dentro, o próprio pacote cortado
    victim = offs[299] if inside == 0 else start
    cut = start + inside
    r = parse_bin(normal_log_bytes[:cut] + garbage + normal_log_bytes[cut:])
    ref = parse_bin(normal_log_bytes)
    assert {p: g.columns for p, g in r.groups.items()} == _without_packet(ref, normal_log_bytes, victim)
    assert r.bytes_read + r.bytes_discarded == len(normal_log_bytes) + len(garbage)


@pytest.mark.parametrize("frac", [0.1, 0.5, 0.9])
def test_lost_byte_in_the_middle_only_costs_the_damaged_packet(frac):
    # reprodução do bug: 1 byte a menos a ~10% de um log de 10 s fazia o parser
    # ler só ~10% dos pacotes
    raw = synthetic_log(10_000)
    offs = _offsets(raw)
    start = offs[int(len(offs) * frac)]
    cut = start + 10                                  # dentro do payload do pacote
    r = parse_bin(raw[:cut] + raw[cut + 1:])
    assert r.total_packets == len(offs) - 1
    assert r.packets_discarded == 1
    assert r.bytes_read + r.bytes_discarded == len(raw) - 1


def test_lost_byte_does_not_leave_a_corrupted_packet_behind():
    raw = synthetic_log(10_000)
    offs = _offsets(raw)
    k = len(offs) // 10
    cut = offs[k] + 10
    r = parse_bin(raw[:cut] + raw[cut + 1:])
    # o pacote danificado some; todos os outros ficam idênticos
    assert {p: g.columns for p, g in r.groups.items()} == _without_packet(parse_bin(raw), raw, offs[k])


def test_lost_id_byte_drops_that_packet_and_the_previous_one():
    raw = synthetic_log(2000)
    offs = _offsets(raw)
    cut = offs[200]                                    # remove o byte de ID
    r = parse_bin(raw[:cut] + raw[cut + 1:])
    assert (r.total_packets, r.packets_discarded) == (len(offs) - 2, 1)


def test_isolated_packet_with_absurd_timestamp_in_the_middle_is_discarded():
    good = imu_stream(40)
    bad = packet(IMU, 1_000_000_000, *zeros(IMU))
    r = parse_bin(good[:29 * 20] + bad + good[29 * 20:])
    assert r.groups[IMU].timestamps_ms == [t for t in range(0, 200, 5) if t != 95]
    assert "Timestamp incoerente no pacote 0x01 (offset 580)" in r.warnings[0]


def test_real_timestamp_reset_is_kept_by_the_parser():
    # reboot do ESP32: o contador volta a ~0 e o log continua; o parser aceita
    # (os pacotes seguintes encadeiam) e check_timestamps segmenta depois
    before = b"".join(packet(IMU, 50_000 + 5 * i, *zeros(IMU)) for i in range(20))
    after = b"".join(packet(IMU, 5 * i, *zeros(IMU)) for i in range(20))
    r = parse_bin(before + after)
    assert (r.total_packets, r.warnings) == (40, [])


def test_many_resyncs_are_summarised_in_warnings():
    good = imu_stream(180)
    # um byte ruim a cada 3 pacotes: perde 1 de cada 3
    data = b"".join(good[i * 87:(i + 1) * 87] + b"\xfe" for i in range(60))
    r = parse_bin(data)
    assert (r.total_packets, len(r.resyncs)) == (120, 60)
    assert len(r.warnings) == MAX_RESYNC_WARNINGS + 1
    assert r.warnings[-1] == ("Mais 40 ressincronizações sem aviso individual "
                              "(1200 bytes descartados).")


def test_max_gap_is_configurable():
    # pacote 90 s à frente, isolado entre pacotes normais: incoerente com o limite
    # padrão (60 s), mas coerente com 120 s
    good = imu_stream(10)
    data = good[:145] + packet(IMU, 90_000, *zeros(IMU)) + good[145:]
    assert 90_000 not in parse_bin(data).groups[IMU].timestamps_ms
    assert 90_000 in parse_bin(data, max_gap_ms=120_000).groups[IMU].timestamps_ms


def test_empty_packets_dict_is_not_replaced_by_defaults():
    r = parse_bin(imu_stream(3), packets={})
    assert (r.groups, r.bytes_discarded) == ({}, 87)


# --- progresso e arquivo ----------------------------------------------------

def test_progress_callback_is_monotonic_and_ends_at_one(normal_log_bytes):
    calls = []
    parse_bin(normal_log_bytes * 80, progress_cb=calls.append)   # ~1,3 MB
    assert len(calls) > 1 and calls == sorted(calls) and calls[-1] == 1.0


def test_parse_file_matches_parse_bin(tmp_path, normal_log_bytes):
    path = tmp_path / "log.bin"
    path.write_bytes(normal_log_bytes)
    from_file, from_bytes = parse_file(str(path)), parse_bin(normal_log_bytes)
    assert {p: g.columns for p, g in from_file.groups.items()} == \
           {p: g.columns for p, g in from_bytes.groups.items()}


def test_parse_file_records_source_path_and_mtime(tmp_path, normal_log_bytes):
    import os
    path = tmp_path / "log.bin"
    path.write_bytes(normal_log_bytes)
    os.utime(path, (1_700_000_000, 1_700_000_000))
    r = parse_file(str(path))
    assert (r.source_path, r.source_mtime) == (str(path), 1_700_000_000)

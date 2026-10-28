"""parse_bin / parse_file: stream little-endian, event-driven, taxa mista, sem header global."""

import pytest

from builders import PERIOD_MS, packet, payload, zeros
from packets import PACKETS, Channel, PacketDef
from parser import parse_bin, parse_file

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
def test_trailing_garbage_keeps_valid_packets(trailing):
    assert parse_bin(imu_stream(5) + trailing).total_packets == 5


@pytest.mark.parametrize("trailing", [b"\x00", b"\xff" * 7, b"\x00" * 64])
def test_trailing_garbage_is_reported_with_ignored_byte_count(trailing):
    w = parse_bin(imu_stream(5) + trailing).warnings
    assert w == [f"ID desconhecido 0x{trailing[0]:02X} no offset 145; "
                 f"leitura interrompida ({len(trailing)} bytes ignorados)."]


# --- ID desconhecido ----------------------------------------------------------

@pytest.mark.parametrize("position", [0, 3, 10])
def test_unknown_id_stops_parsing_at_that_packet(position):
    good = imu_stream(10)
    data = good[:position * 29] + b"\xfe" + good[position * 29:]
    assert parse_bin(data).total_packets == position


@pytest.mark.parametrize("position", [0, 3, 10])
def test_unknown_id_warning_names_id_and_offset(position):
    good = imu_stream(10)
    data = good[:position * 29] + b"\xfe" + good[position * 29:]
    assert f"ID desconhecido 0xFE no offset {position * 29};" in parse_bin(data).warnings[0]


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

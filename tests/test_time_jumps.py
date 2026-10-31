"""check_timestamps: pacotes isolados com timestamp absurdo, resets e saltos; teto da grade."""

import numpy as np
import pytest

import exporter
from builders import U32, packet, payload, synthetic_log, zeros
from exporter import MAX_GRID_SPAN_S, write_csv, write_ld
from parser import ParseResult, check_timestamps, parse_bin

IMU, SLOW = 0x01, 0x04


def imu(ts_list) -> bytes:
    return b"".join(packet(IMU, t, *payload(IMU, t % 10_000)) for t in ts_list)


def test_reproduced_isolated_packet_one_billion_ms_is_dropped(tmp_path):
    # reprodução: 1 s de IMU + 1 pacote em 1_000_000_000 ms fazia _build_channels
    # pedir uma grade de ~11,5 dias a 200 Hz e estourar a memória
    r = parse_bin(imu(range(0, 1000, 5)) + packet(IMU, 1_000_000_000, *zeros(IMU)))
    assert r.total_packets == 201                    # o parser aceita (estrutura válida)
    tc = check_timestamps(r)
    assert (len(tc.segments), tc.dropped_packets, tc.jumps) == (1, 1, [])
    assert tc.segments[0].groups[IMU].timestamps_ms == list(range(0, 1000, 5))
    assert "1 pacote(s) isolado(s)" in tc.warnings[0]
    path = tmp_path / "x.ld"
    write_ld(tc.segments[0], str(path))
    from ldparser.ldparser import read_ldfile
    assert len(read_ldfile(str(path))[1][0].data) == 200


def test_reproduced_case_without_check_hits_grid_cap_instead_of_allocating():
    r = parse_bin(imu(range(0, 1000, 5)) + packet(IMU, 1_000_000_000, *zeros(IMU)))
    with pytest.raises(ValueError, match="limite de segurança"):
        exporter._build_channels(r)


def test_grid_cap_is_configurable():
    r = parse_bin(imu(range(0, 1000, 5)))
    with pytest.raises(ValueError, match="limite de segurança"):
        exporter._build_channels(r, max_span_s=0.5)
    assert len(exporter._build_channels(r, max_span_s=1.0)) == 6
    assert MAX_GRID_SPAN_S == 4 * 3600


def test_isolated_packet_at_start_is_dropped():
    r = parse_bin(packet(IMU, 3_000_000_000, *zeros(IMU)) + imu(range(0, 1000, 5)))
    tc = check_timestamps(r)
    assert tc.dropped_packets == 1
    assert tc.segments[0].groups[IMU].timestamps_ms[0] == 0


def test_clean_log_returns_same_result_object(normal_log):
    tc = check_timestamps(normal_log)
    assert tc.segments == [normal_log] and (tc.dropped_packets, tc.jumps, tc.warnings) == (0, [], [])


def test_log_crossing_rollover_is_not_a_jump():
    r = parse_bin(synthetic_log(2000, start_ms=U32 - 1000))
    assert check_timestamps(r).segments == [r]


def test_reset_splits_log_into_segments():
    # reboot do ESP32 no meio: contador volta a 0
    data = synthetic_log(2000, start_ms=500_000) + synthetic_log(1000)
    tc = check_timestamps(parse_bin(data))
    assert [s.total_packets for s in tc.segments] == [620, 310]
    # último pacote antes do reboot em 501_995 ms, primeiro depois em 0 ms
    assert [(j.kind, j.delta_ms, j.index) for j in tc.jumps] == [("reset", -501_995, 620)]
    assert tc.segments[1].groups[IMU].timestamps_ms[:3] == [0, 5, 10]


def test_forward_jump_of_the_whole_log_splits_segments():
    data = imu(range(0, 1000, 5)) + imu(range(200_000, 201_000, 5))
    tc = check_timestamps(parse_bin(data))
    assert [len(s.groups[IMU].timestamps_ms) for s in tc.segments] == [200, 200]
    assert tc.jumps[0].kind == "salto" and tc.jumps[0].delta_ms == 200_000 - 995
    assert "Salto de timestamp de +199.0 s" in tc.warnings[0]


def test_gap_in_one_group_only_does_not_split():
    # Motor_Lento some por 90 s enquanto a IMU continua: a linha do tempo segue definida
    buf = bytearray()
    for t in range(0, 100_000, 5):
        buf += packet(IMU, t, *zeros(IMU))
        if t % 100 == 0 and not 5_000 <= t < 95_000:
            buf += packet(SLOW, t, *zeros(SLOW))
    tc = check_timestamps(parse_bin(bytes(buf)))
    assert (len(tc.segments), tc.dropped_packets) == (1, 0)


def test_max_gap_and_min_segment_are_configurable():
    data = imu(range(0, 1000, 5)) + imu(range(30_000, 31_000, 5))
    r = parse_bin(data)
    assert len(check_timestamps(r).segments) == 1
    assert len(check_timestamps(r, max_gap_ms=10_000).segments) == 2
    # trecho de 3 pacotes: isolado com o padrão (10), segmento com mínimo 3
    data = imu(range(0, 1000, 5)) + imu([500_000, 500_005, 500_010])
    r = parse_bin(data)
    assert check_timestamps(r).dropped_packets == 3
    assert len(check_timestamps(r, min_segment_packets=3).segments) == 2


def test_segments_keep_source_metadata_and_are_idempotent():
    r = parse_bin(imu(range(0, 1000, 5)) + imu(range(500_000, 501_000, 5)))
    r.source_mtime = 123.0
    segs = check_timestamps(r).segments
    assert all(s.source_mtime == 123.0 for s in segs)
    assert all(check_timestamps(s).segments == [s] for s in segs)


def test_result_without_file_order_falls_back_to_time_order():
    r = parse_bin(imu(range(0, 1000, 5)) + packet(IMU, 1_000_000_000, *zeros(IMU)))
    manual = ParseResult(groups=r.groups, total_packets=r.total_packets)
    assert check_timestamps(manual).dropped_packets == 1


def test_empty_result_has_no_segments():
    assert check_timestamps(parse_bin(b"")).segments == []


def test_segmented_export_writes_each_segment(tmp_path):
    r = parse_bin(imu(range(0, 1000, 5)) + imu(range(500_000, 500_500, 5)))
    segs = check_timestamps(r).segments
    paths = exporter.segment_paths(str(tmp_path / "log.csv"), len(segs))
    for s, p in zip(segs, paths):
        write_csv(s, p)
    assert [p.rsplit("/", 1)[-1] for p in paths] == ["log_seg1.csv", "log_seg2.csv"]
    lens = [len(next(iter(open(p))).split(",")) - 3 for p in paths]
    assert lens == [200, 100]


def test_signed_delta_handles_rollover():
    from parser import _signed_delta
    assert _signed_delta(np.array([5 - U32, U32 - 5, 10, -10])).tolist() == [5, -5, 10, -10]

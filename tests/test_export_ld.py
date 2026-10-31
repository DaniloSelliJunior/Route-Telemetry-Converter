"""write_ld: arquivo MoTeC .ld relido com o ldparser vendorizado (motec_lib/ldparser)."""

import numpy as np
import pytest

from builders import PERIOD_MS, payload
from exporter import write_ld
from ldparser.ldparser import read_ldfile          # motec_lib entra no sys.path via exporter
from packets import PACKETS
from parser import ParseResult

ALL_CHANNELS = [(pid, k, ch) for pid, d in PACKETS.items() for k, ch in enumerate(d.channels)]

META = dict(driver="Piloto Teste", vehicle="FR2026", venue="UFSCar",
            event="Enduro", session="Treino 2", comment="Convertido no teste")


@pytest.fixture
def ld(tmp_path, normal_log):
    path = str(tmp_path / "log.ld")
    write_ld(normal_log, path, **META)
    return read_ldfile(path)                       # (cabeçalho, canais)


@pytest.mark.parametrize("attr, expected", [
    ("driver", "Piloto Teste"), ("vehicleid", "FR2026"), ("venue", "UFSCar"),
])
def test_header_stores_driver_vehicle_and_venue(ld, attr, expected):
    head, _ = ld
    assert getattr(head, attr) == expected


# Evento/sessão são gravados pelo MotecLog no bloco de evento (aux_ptr). Os campos
# "event"/"session" que o ldparser lê no fim do cabeçalho ficam no offset 1762, onde
# o MotecLog grava o bloco do veículo, por isso não são verificados aqui.
@pytest.mark.parametrize("attr, expected", [
    ("name", "Enduro"), ("session", "Treino 2"), ("comment", "Convertido no teste"),
])
def test_event_block_stores_event_session_and_full_comment(ld, attr, expected):
    head, _ = ld
    assert getattr(head.aux, attr) == expected


def test_short_comment_is_cut_to_eight_characters(ld):
    head, _ = ld
    assert head.short_comment == "Converti"


def test_overlong_metadata_is_truncated_to_field_size(tmp_path, normal_log):
    path = str(tmp_path / "x.ld")
    write_ld(normal_log, path, driver="D" * 100)
    head, _ = read_ldfile(path)
    assert head.driver == "D" * 64                 # campo de 64 bytes do cabeçalho


def test_all_23_channels_are_written_in_definition_order(ld):
    _, chans = ld
    assert [c.name for c in chans] == [ch.name for _, _, ch in ALL_CHANNELS]


def test_channels_keep_units(ld):
    _, chans = ld
    assert [c.unit for c in chans] == [ch.unit for _, _, ch in ALL_CHANNELS]


def test_channel_frequency_is_group_nominal_rate(ld):
    _, chans = ld
    assert [c.freq for c in chans] == [int(PACKETS[pid].freq_hz) for pid, _, _ in ALL_CHANNELS]


def test_channel_sample_count_matches_rate_and_duration(ld):
    _, chans = ld
    expected = {200: 400, 50: 100, 10: 20}
    assert [len(c.data) for c in chans] == [expected[c.freq] for c in chans]


def test_channels_are_stored_as_float32(ld):
    _, chans = ld
    assert {c.dtype for c in chans} == {np.float32}


@pytest.mark.parametrize("idx", range(len(ALL_CHANNELS)), ids=[c.name for _, _, c in ALL_CHANNELS])
def test_channel_data_round_trips_logged_samples(ld, idx):
    _, chans = ld
    pid, k, _ = ALL_CHANNELS[idx]
    logged = [payload(pid, t)[k] for t in range(0, 2000, PERIOD_MS[pid])]
    assert chans[idx].data.tolist() == logged


def test_empty_result_raises_clear_error(tmp_path):
    with pytest.raises(ValueError, match="Nenhum dado válido"):
        write_ld(ParseResult(groups={}), str(tmp_path / "x.ld"))


def test_progress_callback_ends_at_one(tmp_path, normal_log):
    calls = []
    write_ld(normal_log, str(tmp_path / "x.ld"), progress_cb=calls.append)
    assert calls == [0.5, 0.8, 1.0]


# --- data do cabeçalho -------------------------------------------------------

def test_header_date_is_bin_modification_time(tmp_path, normal_log_bytes):
    import datetime
    import os
    from parser import parse_file
    src = tmp_path / "log.bin"
    src.write_bytes(normal_log_bytes)
    when = datetime.datetime(2025, 3, 14, 15, 9, 26)
    os.utime(src, (when.timestamp(), when.timestamp()))
    path = str(tmp_path / "log.ld")
    write_ld(parse_file(str(src)), path)
    head, _ = read_ldfile(path)
    assert head.datetime == when


def test_explicit_log_datetime_wins_over_bin_mtime(tmp_path, normal_log):
    import datetime
    normal_log.source_mtime = 0.0
    when = datetime.datetime(2026, 1, 2, 3, 4, 5)
    path = str(tmp_path / "log.ld")
    write_ld(normal_log, path, log_datetime=when)
    assert read_ldfile(path)[0].datetime == when


# --- erro e escrita atômica --------------------------------------------------

def test_empty_result_error_includes_parser_warnings(tmp_path):
    from parser import parse_bin
    r = parse_bin(b"\xfe" * 10)
    with pytest.raises(ValueError, match=r"Nenhum dado válido.*ID desconhecido 0xFE no offset 0"):
        write_ld(r, str(tmp_path / "x.ld"))


def test_failed_write_keeps_previous_file_and_leaves_no_temp(tmp_path, normal_log, monkeypatch):
    import motec_log
    path = tmp_path / "log.ld"
    path.write_bytes(b"anterior")

    def broken_write(self, filename):
        with open(filename, "wb") as f:
            f.write(b"pela metade")
        raise OSError("disco cheio")

    monkeypatch.setattr(motec_log.MotecLog, "write", broken_write)
    with pytest.raises(OSError, match="disco cheio"):
        write_ld(normal_log, str(path))
    assert path.read_bytes() == b"anterior"
    assert [p.name for p in tmp_path.iterdir()] == ["log.ld"]


def test_successful_write_replaces_existing_file(tmp_path, normal_log):
    path = tmp_path / "log.ld"
    path.write_bytes(b"anterior")
    write_ld(normal_log, str(path))
    assert read_ldfile(str(path))[1][0].name == "Acel_X"
    assert [p.name for p in tmp_path.iterdir()] == ["log.ld"]


@pytest.mark.parametrize("n, names", [(1, ["a.ld"]), (2, ["a_seg1.ld", "a_seg2.ld"])])
def test_segment_paths(n, names):
    from exporter import segment_paths
    assert segment_paths("a.ld", n) == names

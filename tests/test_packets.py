"""Contrato com o firmware: tamanhos e layout dos pacotes (tabela "Input Format" do README)."""

import pytest

from packets import PACKETS, Channel, PacketDef


@pytest.mark.parametrize("pid, size", [(0x01, 29), (0x02, 21), (0x03, 24), (0x04, 33)])
def test_packet_size_matches_firmware_packed_struct(pid, size):
    assert PACKETS[pid].size == size


@pytest.mark.parametrize("pid, fmt", [(0x01, "<BI6f"), (0x02, "<BI4f"),
                                      (0x03, "<BIHb4f"), (0x04, "<BI7f")])
def test_packet_struct_is_little_endian_id_timestamp_payload(pid, fmt):
    assert PACKETS[pid].struct.format == fmt


@pytest.mark.parametrize("pid, hz", [(0x01, 200), (0x02, 50), (0x03, 50), (0x04, 10)])
def test_packet_nominal_rate(pid, hz):
    assert PACKETS[pid].freq_hz == hz


def test_total_channel_count_is_23():
    assert sum(len(d.channels) for d in PACKETS.values()) == 23


def test_channel_names_are_unique_across_groups():
    names = [ch.name for d in PACKETS.values() for ch in d.channels]
    assert len(names) == len(set(names))


def test_only_gear_channel_holds_last_value():
    held = [ch.name for d in PACKETS.values() for ch in d.channels if ch.hold]
    assert held == ["Marcha"]


@pytest.mark.parametrize("fmt, n_channels", [("2f", 1), ("2f", 3), ("Hb", 1)])
def test_packetdef_rejects_channel_count_mismatch(fmt, n_channels):
    channels = tuple(Channel(f"c{i}") for i in range(n_channels))
    with pytest.raises(ValueError, match="campos no formato"):
        PacketDef(0x7F, "x", 10.0, fmt, channels)

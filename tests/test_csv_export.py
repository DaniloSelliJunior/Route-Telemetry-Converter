"""csv_export: tabelas largas por grupo (taxa nativa) e unificada, perfis e metadados."""

import csv
import json
import math

import numpy as np
import pytest

from builders import PERIOD_MS, U32, packet, payload, synthetic_log, zeros
from csv_export import (PROFILES, export_csv, format_column, header_name, native_tables,
                        plan_csv, unified_table, write_table)
from packets import PACKETS
from parser import ParseResult, check_timestamps, parse_bin

IMU, PEDAIS, MOTOR, SLOW = 0x01, 0x02, 0x03, 0x04


def read(path, profile="padrao"):
    p = PROFILES[profile]
    with open(path, newline="", encoding="utf-8-sig" if p.bom else "utf-8") as f:
        return list(csv.reader(f, delimiter=p.delimiter))


def num(s: str, profile="padrao") -> float:
    return float(s.replace(",", ".")) if profile == "excel_br" else float(s)


# --- layout ------------------------------------------------------------------

def test_header_name_with_and_without_unit():
    assert (header_name("RPM", "rpm"), header_name("Marcha", "")) == ("RPM [rpm]", "Marcha")


def test_native_tables_one_per_group_with_time_and_channel_columns(normal_log):
    tables = native_tables(normal_log)
    assert list(tables) == [d.name for d in PACKETS.values()]
    header, cols = tables["Motor_Rapido"]
    assert header == ["tempo_s", "RPM [rpm]", "Marcha", "TPS [%]", "MAP [kPa]",
                      "Angulo_Ignicao [deg]", "Velocidade [km/h]"]
    assert len(cols) == len(header)


@pytest.mark.parametrize("pid", sorted(PACKETS))
def test_native_tables_keep_logged_samples_at_native_rate(normal_log, pid):
    header, cols = native_tables(normal_log)[PACKETS[pid].name]
    ts = list(range(0, 2000, PERIOD_MS[pid]))
    assert cols[0].tolist() == [t / 1000 for t in ts]
    for k in range(len(PACKETS[pid].channels)):
        assert cols[k + 1].tolist() == [payload(pid, t)[k] for t in ts]


def test_native_tables_are_not_interpolated_for_event_driven_group():
    data = b"".join(packet(IMU, t, *zeros(IMU)) for t in range(0, 1000, 5))
    data += packet(PEDAIS, 103, 1, 2, 3, 4) + packet(PEDAIS, 977, 5, 6, 7, 8)
    _, cols = native_tables(parse_bin(data))["Pedais_Freios"]
    assert (cols[0].tolist(), cols[1].tolist()) == ([0.103, 0.977], [1.0, 5.0])


def test_native_tables_sort_out_of_order_samples():
    data = b"".join(packet(SLOW, t, t, *([0] * 6)) for t in (0, 200, 100, 300))
    _, cols = native_tables(parse_bin(data))["Motor_Lento"]
    assert cols[1].tolist() == [0, 100, 200, 300]


@pytest.mark.parametrize("freq, n", [(10, 20), (50, 100), (200, 400)])
def test_unified_table_rate_sets_grid_for_all_channels(normal_log, freq, n):
    header, cols = unified_table(normal_log, freq)
    assert len(header) == 24 and {len(c) for c in cols} == {n}
    assert cols[0][1] == pytest.approx(1 / freq)


def test_unified_table_interpolates_slow_channels_and_holds_gear():
    buf = bytearray()
    for t in range(0, 1001, 20):
        buf += packet(MOTOR, t, 8000, 2 if t < 500 else 3, 0, 0, 0, 0)
    for t in range(0, 1001, 100):
        buf += packet(SLOW, t, float(t), 0, 0, 0, 0, 0, 0)
    header, cols = unified_table(parse_bin(bytes(buf)), 50)
    temp = cols[header.index("Temp_Motor [C]")]
    gear = cols[header.index("Marcha")]
    assert temp[:6].tolist() == [0, 20, 40, 60, 80, 100]       # linear entre amostras a 10 Hz
    assert set(gear.tolist()) == {2.0, 3.0}


def test_unified_table_pads_group_that_ends_early_with_last_value():
    data = b"".join(packet(IMU, t, *zeros(IMU)) for t in range(0, 1000, 5))
    data += packet(SLOW, 0, 1, 0, 0, 0, 0, 0, 0) + packet(SLOW, 300, 4, 0, 0, 0, 0, 0, 0)
    header, cols = unified_table(parse_bin(data), 50)
    temp = cols[header.index("Temp_Motor [C]")]
    assert len(temp) == 50 and temp[-1] == 4.0


def test_unified_table_matches_ld_grid_values(normal_log):
    import exporter
    ld = {name: data for name, _, freq, data in exporter._build_channels(normal_log) if freq == 50}
    header, cols = unified_table(normal_log, 50)
    for name, data in ld.items():
        h = next(x for x in header if x.split(" [")[0] == name)
        assert cols[header.index(h)].tolist() == data.tolist()


def test_unified_table_rejects_invalid_rate(normal_log):
    with pytest.raises(ValueError, match="Taxa inválida"):
        unified_table(normal_log, 0)


def test_rollover_gives_same_tables_as_log_without_it():
    a = parse_bin(synthetic_log(2000))
    b = parse_bin(synthetic_log(2000, start_ms=U32 - 1000))
    ha, ca = unified_table(a, 50)
    hb, cb = unified_table(b, 50)
    assert ha == hb and all(np.array_equal(x, y) for x, y in zip(ca, cb))
    na, nb = native_tables(a), native_tables(b)
    assert all(np.array_equal(x, y) for k in na for x, y in zip(na[k][1], nb[k][1]))


def test_empty_result_raises_clear_error():
    with pytest.raises(ValueError, match="Nenhum dado válido"):
        native_tables(ParseResult(groups={}))


# --- formatação e perfis -----------------------------------------------------

def test_format_column_seven_significant_digits_and_non_finite_text():
    vals = [1234.5678, 1 / 3, 8000.0, math.nan, math.inf, -math.inf]
    assert format_column(vals) == ["1234.568", "0.3333333", "8000", "nan", "inf", "-inf"]


def test_format_column_with_decimal_comma():
    assert format_column([1.5, -0.25, math.nan], ",") == ["1,5", "-0,25", "nan"]


@pytest.mark.parametrize("profile, sep, bom", [("padrao", ",", False), ("excel_br", ";", True)])
def test_profile_separator_decimal_and_bom(tmp_path, profile, sep, bom):
    path = tmp_path / "x.csv"
    write_table(path, ["tempo_s", "Pressão [bar]"], [np.array([0.0, 0.005]),
                                                     np.array([1.5, 2.25])], PROFILES[profile])
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") == bom
    text = raw.decode("utf-8-sig")
    dec = "," if profile == "excel_br" else "."
    assert text.splitlines() == [f"tempo_s{sep}Pressão [bar]",
                                 f"0{dec}000{sep}1{dec}5", f"0{dec}005{sep}2{dec}25"]


# --- export_csv: arquivos e metadados ----------------------------------------

META = dict(piloto="Ana", veiculo="FR2026", local="UFSCar", evento="Enduro", sessao="T2")


def test_export_unified_writes_one_csv_and_metadata(tmp_path, normal_log):
    base = str(tmp_path / "log")
    out = export_csv([normal_log], base, "unificado", 50, "padrao", META, source="/x/log.bin")
    assert [p.rsplit("/", 1)[-1] for p in out] == ["log_50Hz.csv", "log_metadados.json"]
    rows = read(out[0])
    assert rows[0][0] == "tempo_s" and len(rows) == 101
    meta = json.loads(open(out[1], encoding="utf-8").read())
    assert {k: meta[k] for k in META} == META
    assert (meta["arquivo_origem"], meta["modo"], meta["taxa_hz"], meta["perfil"]) == \
           ("log.bin", "unificado", 50, "Padrão")
    assert meta["arquivos"] == ["log_50Hz.csv"] and "versao" in meta


def test_export_groups_writes_one_csv_per_group(tmp_path, normal_log):
    out = export_csv([normal_log], str(tmp_path / "log"), "grupos", profile="excel_br")
    names = [p.rsplit("/", 1)[-1] for p in out]
    assert names == ["log_Chassi_IMU.csv", "log_Pedais_Freios.csv", "log_Motor_Rapido.csv",
                     "log_Motor_Lento.csv", "log_metadados.json"]
    rows = read(out[3], "excel_br")
    assert len(rows) == 21 and rows[1][0] == "0,000"
    assert num(rows[2][1], "excel_br") == payload(SLOW, 100)[0]


def test_export_with_segments_suffixes_files(tmp_path):
    data = synthetic_log(1000, start_ms=500_000) + synthetic_log(1000)
    segs = check_timestamps(parse_bin(data)).segments
    out = export_csv(segs, str(tmp_path / "log"), "unificado", 10)
    assert [p.rsplit("/", 1)[-1] for p in out] == ["log_seg1_10Hz.csv", "log_seg2_10Hz.csv",
                                                   "log_metadados.json"]


def test_plan_rejects_unknown_mode(normal_log):
    with pytest.raises(ValueError, match="Modo de CSV inválido"):
        plan_csv([normal_log], "x", "largo")


def test_nan_is_written_as_text_in_both_modes(tmp_path):
    data = packet(IMU, 0, math.nan, 0, 0, 0, 0, 0) + packet(IMU, 5, math.inf, 0, 0, 0, 0, 0)
    r = parse_bin(data)
    g = export_csv([r], str(tmp_path / "a"), "grupos")[0]
    u = export_csv([r], str(tmp_path / "b"), "unificado", 200)[0]
    assert [row[1] for row in read(g)[1:]] == ["nan", "inf"]
    assert [row[1] for row in read(u)[1:]] == ["nan", "inf"]

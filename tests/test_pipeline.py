"""pipeline: carga única do .bin, saídas por segmento e conversão em lote."""

import os

import pytest

from builders import synthetic_log
from pipeline import (BatchItem, CsvOptions, SessionMeta, batch_summary, convert_file,
                      convert_folder, csv_paths, ld_paths, list_bins, load_log,
                      write_csv_outputs, write_ld_outputs)


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "a.bin").write_bytes(synthetic_log(1000))
    (tmp_path / "B.BIN").write_bytes(synthetic_log(500))
    (tmp_path / "ruim.bin").write_bytes(b"\xfe" * 100)
    (tmp_path / "notas.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.bin").write_bytes(synthetic_log(500))
    return tmp_path


def test_load_log_parses_once_and_builds_quality(tmp_path):
    p = tmp_path / "log.bin"
    p.write_bytes(synthetic_log(1000))
    calls = []
    log = load_log(str(p), calls.append)
    assert (log.result.total_packets, len(log.segments), log.quality["ok"]) == (310, 1, True)
    assert calls[-1] == 1.0


def test_load_log_without_valid_data_raises_with_parser_warnings(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"\xfe" * 10)
    with pytest.raises(ValueError, match="ID desconhecido 0xFE no offset 0"):
        load_log(str(p))


def test_outputs_next_to_bin_or_in_out_dir(tmp_path):
    p = tmp_path / "log.bin"
    p.write_bytes(synthetic_log(1000))
    log = load_log(str(p))
    assert ld_paths(log) == [str(tmp_path / "log.ld")]
    assert ld_paths(log, "/saida") == ["/saida/log.ld"]
    assert csv_paths(log, CsvOptions("unificado", 10)) == [
        str(tmp_path / "log_10Hz.csv"), str(tmp_path / "log_metadados.json")]


def test_same_loaded_log_feeds_ld_and_csv(tmp_path):
    p = tmp_path / "log.bin"
    p.write_bytes(synthetic_log(1000))
    log = load_log(str(p))
    meta = SessionMeta(piloto="Ana")
    assert write_ld_outputs(log, meta) == ld_paths(log)
    out = write_csv_outputs(log, meta, CsvOptions("grupos"))
    assert out == csv_paths(log, CsvOptions("grupos"))
    assert all(os.path.exists(x) for x in out)


def test_list_bins_is_case_insensitive_and_not_recursive(folder):
    assert [os.path.basename(p) for p in list_bins(str(folder))] == ["B.BIN", "a.bin", "ruim.bin"]


def test_batch_bad_file_does_not_abort_the_others(folder):
    calls = []
    items = convert_folder(str(folder), SessionMeta(), ld=True, csv=True,
                           progress_cb=lambda i, n, f: calls.append((i, n)))
    status = {os.path.basename(it.source): it.status for it in items}
    assert status == {"B.BIN": "ok", "a.bin": "ok", "ruim.bin": "erro"}
    bad = next(it for it in items if it.status == "erro")
    assert "Nenhum dado válido" in bad.message
    assert os.path.exists(folder / "a.ld") and os.path.exists(folder / "a_50Hz.csv")
    assert calls[0] == (0, 3) and calls[-1] == (3, 3)
    assert batch_summary(items) == "3 arquivo(s): 2 convertido(s), 0 pulado(s), 1 com erro."


def test_batch_skips_existing_outputs_unless_overwrite(folder):
    (folder / "a.ld").write_bytes(b"anterior")
    items = convert_folder(str(folder), SessionMeta(), ld=True)
    a = next(it for it in items if it.source.endswith("a.bin"))
    assert (a.status, a.message) == ("pulado", "já existe: a.ld")
    assert (folder / "a.ld").read_bytes() == b"anterior"
    items = convert_folder(str(folder), SessionMeta(), ld=True, overwrite=True)
    assert next(it for it in items if it.source.endswith("a.bin")).status == "ok"


def test_batch_to_output_folder(folder, tmp_path_factory):
    out = tmp_path_factory.mktemp("saida")
    convert_folder(str(folder), SessionMeta(), ld=False, csv=True,
                   csv_options=CsvOptions("unificado", 10, "excel_br"), out_dir=str(out))
    assert sorted(os.listdir(out)) == ["B_10Hz.csv", "B_metadados.json",
                                       "a_10Hz.csv", "a_metadados.json"]


def test_batch_requires_some_output(folder):
    with pytest.raises(ValueError, match="ao menos uma saída"):
        convert_folder(str(folder), SessionMeta(), ld=False, csv=False)


def test_convert_file_reports_segments(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(synthetic_log(1000, start_ms=500_000) + synthetic_log(1000))
    it = convert_file(str(p), SessionMeta())
    assert it.status == "ok" and it.outputs == [str(tmp_path / "x_seg1.ld"),
                                                str(tmp_path / "x_seg2.ld")]
    assert it.message.startswith("2 segmentos")


def test_empty_batch_summary():
    assert batch_summary([]) == "0 arquivo(s): 0 convertido(s), 0 pulado(s), 0 com erro."
    assert BatchItem("x").status == "ok"

"""Preferências e limiares persistidos: carregar, salvar, valores inválidos, arquivo corrompido."""

import json
import os
from pathlib import Path

import pytest

import settings as st
from kpi import merge_config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv(st.ENV_OVERRIDE, str(tmp_path / "cfg"))
    return tmp_path / "cfg"


# --- diretório ----------------------------------------------------------------

def test_config_dir_per_platform():
    home = Path("/home/x")
    assert st.config_dir({}, "linux", home) == home / ".config" / "RouteTelemetryConverter"
    assert st.config_dir({"XDG_CONFIG_HOME": "/xdg"}, "linux", home) == \
           Path("/xdg/RouteTelemetryConverter")
    assert st.config_dir({"APPDATA": "C:/Users/x/AppData/Roaming"}, "win32", home) == \
           Path("C:/Users/x/AppData/Roaming/RouteTelemetryConverter")
    assert st.config_dir({}, "win32", home) == home / "AppData" / "Roaming" / "RouteTelemetryConverter"
    assert st.config_dir({}, "darwin", home) == home / "Library/Application Support/RouteTelemetryConverter"
    assert st.config_dir({st.ENV_OVERRIDE: "/p"}, "linux", home) == Path("/p")


# --- preferências -------------------------------------------------------------

def test_missing_file_gives_defaults_without_warning():
    assert st.load_settings() == (st.Settings(), [])


def test_save_and_load_round_trip(isolated_config):
    s = st.Settings(tema="claro", piloto="Ana", csv_taxa_hz=200, csv_perfil="excel_br",
                    pasta_saida=str(isolated_config.parent))
    assert st.save_settings(s) is None
    data = json.loads((isolated_config / st.SETTINGS_FILE).read_text(encoding="utf-8"))
    assert data["versao_formato"] == 1 and data["tema"] == "claro"
    assert st.load_settings() == (s, [])


@pytest.mark.parametrize("key, bad", [
    ("tema", "roxo"), ("csv_taxa_hz", 33), ("csv_taxa_hz", "50"), ("csv_perfil", "xls"),
    ("csv_modo", 1), ("piloto", 5), ("piloto", "x" * 500), ("csv_taxa_hz", True),
])
def test_invalid_value_falls_back_to_default_keeping_the_others(isolated_config, key, bad):
    isolated_config.mkdir()
    (isolated_config / st.SETTINGS_FILE).write_text(
        json.dumps({key: bad, "veiculo": "FR2027"}), encoding="utf-8")
    s, warnings = st.load_settings()
    assert getattr(s, key) == getattr(st.Settings(), key)
    assert s.veiculo == "FR2027"
    assert len(warnings) == 1 and f"valor inválido para {key!r}" in warnings[0]


def test_unknown_key_is_ignored_with_warning(isolated_config):
    isolated_config.mkdir()
    (isolated_config / st.SETTINGS_FILE).write_text('{"cor": 1, "versao_formato": 1}', encoding="utf-8")
    s, warnings = st.load_settings()
    assert s == st.Settings() and warnings == ["Preferências: chave desconhecida 'cor' ignorada."]


@pytest.mark.parametrize("content", ['{"tema": "claro"', "", "\x00\x01lixo", "[1, 2]"])
def test_corrupted_file_gives_defaults_and_warning(isolated_config, content):
    isolated_config.mkdir()
    (isolated_config / st.SETTINGS_FILE).write_text(content, encoding="utf-8")
    s, warnings = st.load_settings()
    assert s == st.Settings() and len(warnings) == 1


def test_binary_garbage_file_does_not_raise(isolated_config):
    isolated_config.mkdir()
    (isolated_config / st.SETTINGS_FILE).write_bytes(b"\xff\xfe\x00\x80")
    s, warnings = st.load_settings()
    assert s == st.Settings() and warnings


def test_missing_output_folder_falls_back_to_bin_folder(isolated_config):
    st.save_settings(st.Settings(pasta_saida="/nao/existe/mesmo"))
    s, warnings = st.load_settings()
    assert s.pasta_saida == "" and "não existe mais" in warnings[0]


def test_save_failure_returns_message_instead_of_raising(tmp_path):
    blocker = tmp_path / "arquivo"
    blocker.write_text("x")
    err = st.save_settings(st.Settings(), blocker / "sub" / "prefs.json")
    assert err.startswith("Preferências não salvas:")


def test_corrupted_file_is_replaced_on_save(isolated_config):
    isolated_config.mkdir()
    (isolated_config / st.SETTINGS_FILE).write_text("{{{", encoding="utf-8")
    assert st.save_settings(st.Settings(tema="escuro")) is None
    assert st.load_settings() == (st.Settings(tema="escuro"), [])


# --- limiares -----------------------------------------------------------------

def test_thresholds_default_when_missing():
    assert st.load_thresholds() == (merge_config(), None)
    assert json.loads(st.thresholds_text())["piloto"]["freio_limiar_psi"] == 50


def test_save_thresholds_validates_and_persists():
    cfg = st.save_thresholds_text('{"piloto": {"freio_limiar_psi": 80}}')
    assert cfg["piloto"]["freio_limiar_psi"] == 80
    assert st.load_thresholds()[0]["piloto"]["freio_limiar_psi"] == 80
    assert '"freio_limiar_psi": 80' in st.thresholds_text()


@pytest.mark.parametrize("text, msg", [
    ('{"piloto": ', "JSON inválido"),
    ('{"piloto": {"freio_limiar_psi": "x"}}', "esperado número"),
    ('{"nada": {}}', "seção desconhecida"),
])
def test_invalid_thresholds_are_rejected_and_not_written(text, msg):
    with pytest.raises(ValueError, match=msg):
        st.save_thresholds_text(text)
    assert not st.thresholds_path().exists()


def test_corrupted_thresholds_file_falls_back_with_warning():
    st.thresholds_path().parent.mkdir(parents=True)
    st.thresholds_path().write_text("{oops", encoding="utf-8")
    cfg, warning = st.load_thresholds()
    assert cfg == merge_config() and "usando os padrões" in warning


def test_reset_thresholds_writes_defaults():
    st.save_thresholds_text('{"motor": {"rpm_hist_faixa": 500}}')
    cfg, text, err = st.reset_thresholds()
    assert (cfg, err) == (merge_config(), None)
    assert st.load_thresholds() == (merge_config(), None) and "_aviso" in text


def test_reset_thresholds_failure_is_reported(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    cfg, _, err = st.reset_thresholds(blocker / "x" / "lim.json")
    assert cfg == merge_config() and err.startswith("Limiares não salvos")

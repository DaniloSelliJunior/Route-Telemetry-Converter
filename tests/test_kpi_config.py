"""Limiares (padrão + JSON) e arquivo de marcações de segmentos."""

import json

import pytest

from kpi import DEFAULT_CONFIG, Segment, config_json, load_config, merge_config, parse_segments
from kpi.segments import check_segments, load_segments


def test_defaults_are_returned_as_copy():
    cfg = merge_config()
    cfg["piloto"]["freio_limiar_psi"] = 1
    assert DEFAULT_CONFIG["piloto"]["freio_limiar_psi"] == 50.0


def test_override_only_given_keys_and_ignore_comments():
    cfg = merge_config({"_nota": "x", "piloto": {"freio_limiar_psi": 80, "_c": 1}})
    assert cfg["piloto"]["freio_limiar_psi"] == 80.0
    assert cfg["piloto"]["acelerador_pleno_pct"] == 95.0


@pytest.mark.parametrize("bad, msg", [
    ({"nada": {}}, "seção desconhecida: 'nada'"),
    ({"piloto": {"x": 1}}, "chave desconhecida: piloto.x"),
    ({"piloto": {"freio_limiar_psi": "alto"}}, "piloto.freio_limiar_psi: esperado número"),
    ({"piloto": {"freio_limiar_psi": True}}, "esperado número"),
    ({"piloto": {"freio_limiar_psi": None}}, "valor nulo não permitido"),
    ({"dinamica": {"canal_lateral": 3}}, "esperado texto"),
    ({"piloto": 5}, "piloto: esperado objeto"),
    ([1, 2], "objeto JSON"),
])
def test_invalid_overrides_raise_clear_errors(bad, msg):
    with pytest.raises(ValueError, match=msg):
        merge_config(bad)


def test_nullable_reference_and_error_lists_all_problems():
    assert merge_config({"dinamica": {"g_max_referencia": None}})["dinamica"]["g_max_referencia"] is None
    with pytest.raises(ValueError, match=r"chave desconhecida: piloto.a; chave desconhecida: piloto.b"):
        merge_config({"piloto": {"a": 1, "b": 2}})


def test_load_config_and_round_trip_of_template(tmp_path):
    p = tmp_path / "lim.json"
    p.write_text(config_json(), encoding="utf-8")
    assert load_config(str(p)) == merge_config()
    assert json.loads(p.read_text(encoding="utf-8"))["_aviso"].startswith("Limiares provisórios")


def test_load_config_reports_json_syntax_error(tmp_path):
    p = tmp_path / "lim.json"
    p.write_text("{\n  \"piloto\": {,}\n}", encoding="utf-8")
    with pytest.raises(ValueError, match="linha 2"):
        load_config(str(p))


# --- segmentos -------------------------------------------------------------------

def test_parse_segments_comma_file():
    text = "nome,inicio_s,fim_s\n# comentário\nVolta 1,0,60.5\n\nVolta 2,60.5,120\n"
    assert parse_segments(text) == [Segment("Volta 1", 0, 60.5), Segment("Volta 2", 60.5, 120)]


def test_parse_segments_semicolon_with_decimal_comma_and_bom(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("﻿Nome;Inicio_s;Fim_s\nTrecho A;1,5;2,25\n", encoding="utf-8")
    assert load_segments(str(p)) == [Segment("Trecho A", 1.5, 2.25)]


@pytest.mark.parametrize("text, msg", [
    ("", "vazio"),
    ("a,b,c\n", "Cabeçalho deve ser nome,inicio_s,fim_s"),
    ("nome,inicio_s,fim_s\n", "sem nenhuma linha"),
    ("nome,inicio_s,fim_s\nV,1\n", "linha 2: esperadas 3 colunas"),
    ("nome,inicio_s,fim_s\nV,x,2\n", "linha 2: inicio_s/fim_s não numéricos"),
    ("nome,inicio_s,fim_s\nV,5,2\n", r"linha 2: fim_s \(2\) deve ser maior que inicio_s \(5\)"),
    ("nome,inicio_s,fim_s\nV,-1,2\n", "inicio_s negativo"),
    ("nome,inicio_s,fim_s\n,1,2\n", "nome vazio"),
    ("nome,inicio_s,fim_s\nsessao,1,2\n", "reservado"),
    ("nome,inicio_s,fim_s\nV,1,2\nV,2,3\n", "linha 3: nome repetido 'V'"),
    ("nome,inicio_s,fim_s\nV,1,inf\n", "finitos"),
])
def test_parse_segments_validation_messages(text, msg):
    with pytest.raises(ValueError, match=msg):
        parse_segments(text)


def test_check_segments_outside_log_duration():
    w = check_segments([Segment("a", 0, 5), Segment("b", 8, 20), Segment("c", 30, 40)], 10)
    assert len(w) == 2 and "'b' termina em 20 s" in w[0] and "'c' começa em 30 s" in w[1]

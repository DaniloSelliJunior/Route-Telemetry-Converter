"""Exportação CSV em formato largo (funções puras sobre NumPy).

Dois modos:
  "grupos"     um CSV por grupo de pacotes, nas taxas nativas (200/50/10 Hz),
               com as amostras como gravadas (sem interpolação), em ordem de tempo;
  "unificado"  um CSV só, numa taxa escolhida (10/50/200 Hz), na mesma grade
               do .ld: canais contínuos interpolados, canais hold (Marcha)
               mantidos; antes do 1º e depois do último pacote de um grupo o
               valor da borda é repetido, como no .ld.

Layout: coluna tempo_s (s desde o 1º pacote, 3 casas) + uma coluna por canal,
cabeçalho "Nome [unidade]" ("Nome" se o canal não tem unidade).

Valores: 7 algarismos significativos (o dado de origem é float32). NaN e inf
são escritos como texto "nan", "inf" e "-inf" nos dois perfis (o pandas lê
como float; o Excel mostra como texto).

O exporter.write_csv (um canal por linha) continua existindo para depuração.
"""

import csv
import datetime
import json
import os
from dataclasses import dataclass

import numpy as np

from exporter import atomic_path, check_span, require_data, segment_paths
from parser import ParseResult, aligned_timestamps, resample_uniform
from version import __version__

MODES = ("grupos", "unificado")
UNIFIED_RATES = (10, 50, 200)
DEFAULT_RATE = 50


@dataclass(frozen=True)
class CsvProfile:
    label: str
    delimiter: str
    decimal: str
    bom: bool         # UTF-8 com BOM (o Excel precisa para acentos)


PROFILES = {
    "padrao": CsvProfile("Padrão", ",", ".", False),
    "excel_br": CsvProfile("Excel BR", ";", ",", True),
}


def header_name(name: str, unit: str) -> str:
    return f"{name} [{unit}]" if unit else name


def native_tables(result: ParseResult) -> dict:
    """{nome do grupo: (cabeçalho, colunas)} com as amostras gravadas, sem interpolação."""
    require_data(result)
    all_ts, t0 = aligned_timestamps(result)
    check_span(all_ts, t0)
    tables = {}
    for pid, g in result.groups.items():
        d = g.definition
        order = np.argsort(all_ts[pid], kind="stable")      # fora de ordem -> no seu instante
        t = (all_ts[pid][order] - t0) / 1000.0
        cols = [t] + [np.asarray(col, dtype=np.float64)[order] for col in g.columns]
        header = ["tempo_s"] + [header_name(ch.name, ch.unit) for ch in d.channels]
        tables[d.name] = (header, cols)
    return tables


def unified_table(result: ParseResult, freq_hz: float = DEFAULT_RATE):
    """(cabeçalho, colunas) com todos os canais numa grade comum a freq_hz."""
    require_data(result)
    if freq_hz <= 0:
        raise ValueError(f"Taxa inválida: {freq_hz} Hz.")
    all_ts, t0 = aligned_timestamps(result)
    check_span(all_ts, t0)
    step = 1000.0 / freq_hz
    n = max(int(np.floor((int(ts.max()) - t0) / step)) + 1 for ts in all_ts.values())
    header, cols = ["tempo_s"], [np.arange(n) * step / 1000.0]
    for pid, g in result.groups.items():
        for ch, col in zip(g.definition.channels, g.columns):
            data = resample_uniform(all_ts[pid], col, freq_hz, t0, hold=ch.hold)
            if data.size < n:                       # grupo que termina antes: repete a borda
                data = np.pad(data, (0, n - data.size), mode="edge")
            header.append(header_name(ch.name, ch.unit))
            cols.append(data)
    return header, cols


def format_column(values, decimal: str = ".", fmt: str = ".7g") -> list:
    """Texto de cada valor; nan/inf/-inf como o Python escreve; vírgula decimal se pedido."""
    out = [format(v, fmt) for v in np.asarray(values, dtype=np.float64).tolist()]
    if decimal != ".":
        out = [s.replace(".", decimal) for s in out]
    return out


def write_table(path, header: list, columns: list, profile: CsvProfile):
    """Grava uma tabela larga (1ª coluna = tempo, 3 casas) de forma atômica."""
    cols = [format_column(columns[0], profile.decimal, ".3f")]
    cols += [format_column(c, profile.decimal) for c in columns[1:]]
    with atomic_path(path) as tmp:
        with open(tmp, "w", newline="", encoding="utf-8-sig" if profile.bom else "utf-8") as f:
            w = csv.writer(f, delimiter=profile.delimiter)
            w.writerow(header)
            w.writerows(zip(*cols))


def plan_csv(segments: list, base_path: str, mode: str, freq_hz: float = DEFAULT_RATE) -> list:
    """[(índice do segmento, chave da tabela, caminho)] que export_csv vai gravar.

    grupos: <base>_<Grupo>.csv; unificado: <base>_<taxa>Hz.csv. Com mais de um
    segmento, <base> vira <base>_segN.
    """
    if mode not in MODES:
        raise ValueError(f"Modo de CSV inválido: {mode!r} (use {' ou '.join(MODES)}).")
    bases = [os.path.splitext(p)[0] for p in segment_paths(base_path + ".csv", len(segments))]
    plan = []
    for i, (seg, base) in enumerate(zip(segments, bases)):
        if mode == "unificado":
            plan.append((i, None, f"{base}_{freq_hz:g}Hz.csv"))
        else:
            for g in seg.groups.values():
                plan.append((i, g.definition.name, f"{base}_{g.definition.name}.csv"))
    return plan


def metadata_path(base_path: str) -> str:
    return base_path + "_metadados.json"


def export_csv(segments: list, base_path: str, mode: str = "unificado",
               freq_hz: float = DEFAULT_RATE, profile: str = "padrao",
               metadata: dict = None, source: str = None, progress_cb=None) -> list:
    """Grava os CSVs de todos os segmentos e o .json de metadados. Retorna os caminhos.

    base_path: caminho sem extensão (ex.: pasta/log). metadata: piloto, veiculo,
    local, evento, sessao (o que vier é copiado para o .json).
    """
    if not segments:
        raise ValueError("Nenhum dado válido encontrado no arquivo.")
    prof = PROFILES[profile]
    plan = plan_csv(segments, base_path, mode, freq_hz)
    written = []
    tables_cache = {}
    for k, (i, key, path) in enumerate(plan):
        if mode == "unificado":
            header, cols = unified_table(segments[i], freq_hz)
        else:
            if i not in tables_cache:
                tables_cache = {i: native_tables(segments[i])}
            header, cols = tables_cache[i][key]
        write_table(path, header, cols, prof)
        written.append(path)
        if progress_cb:
            progress_cb((k + 1) / (len(plan) + 1))

    meta = dict(metadata or {})
    meta.update({
        "arquivo_origem": os.path.basename(source) if source else None,
        "versao": __version__,
        "gerado_em": datetime.datetime.now().isoformat(timespec="seconds"),
        "modo": mode,
        "taxa_hz": freq_hz if mode == "unificado" else None,
        "perfil": prof.label,
        "separador": prof.delimiter,
        "decimal": prof.decimal,
        "codificacao": "utf-8-sig" if prof.bom else "utf-8",
        "valores_nao_finitos": "nan, inf, -inf (texto)",
        "segmentos": len(segments),
        "arquivos": [os.path.basename(p) for p in written],
    })
    mpath = metadata_path(base_path)
    write_json(mpath, meta)
    written.append(mpath)
    if progress_cb:
        progress_cb(1.0)
    return written


def write_json(path, data: dict):
    with atomic_path(path) as tmp:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

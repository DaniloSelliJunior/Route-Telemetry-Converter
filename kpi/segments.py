"""Arquivo de marcações (voltas/trechos) para KPIs por segmento.

Formato próprio, CSV com cabeçalho:

    nome,inicio_s,fim_s
    Volta 1,12.5,78.0
    Volta 2,78.0,141.2

- inicio_s / fim_s: segundos desde o início do log (mesma origem do .ld e do CSV);
- separador vírgula ou ponto e vírgula (com ";" o decimal pode ser vírgula);
- linhas vazias e linhas começando com "#" são ignoradas;
- nomes únicos; "sessao" é reservado (o log inteiro sempre entra).
"""

import csv
import io
import math

from kpi.model import SESSION, Segment

COLUMNS = ("nome", "inicio_s", "fim_s")
TOLERANCE_S = 0.5           # fim um pouco além do log (arredondamento das marcações) não avisa


def parse_segments(text: str) -> list:
    """Segmentos a partir do texto do CSV. ValueError lista todos os problemas com a linha."""
    text = text.lstrip("﻿")
    lines = [(i, ln) for i, ln in enumerate(text.splitlines(), 1)
             if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        raise ValueError("Arquivo de marcações vazio.")
    delim = ";" if lines[0][1].count(";") > lines[0][1].count(",") else ","
    header = [h.strip().lower() for h in next(csv.reader([lines[0][1]], delimiter=delim))]
    if header != list(COLUMNS):
        raise ValueError(f"Cabeçalho deve ser {','.join(COLUMNS)} (encontrado: {','.join(header)}).")
    errors, segments, seen = [], [], set()
    for lineno, line in lines[1:]:
        row = next(csv.reader(io.StringIO(line), delimiter=delim))
        if len(row) != 3:
            errors.append(f"linha {lineno}: esperadas 3 colunas, encontradas {len(row)}")
            continue
        name = row[0].strip()
        try:
            start, end = (float(x.strip().replace(",", ".") if delim == ";" else x.strip())
                          for x in row[1:])
        except ValueError:
            errors.append(f"linha {lineno}: inicio_s/fim_s não numéricos ({row[1]!r}, {row[2]!r})")
            continue
        if not name:
            errors.append(f"linha {lineno}: nome vazio")
        elif name.lower() == SESSION:
            errors.append(f"linha {lineno}: o nome {SESSION!r} é reservado")
        elif name in seen:
            errors.append(f"linha {lineno}: nome repetido {name!r}")
        if not (math.isfinite(start) and math.isfinite(end)):
            errors.append(f"linha {lineno}: tempos devem ser finitos")
        elif start < 0:
            errors.append(f"linha {lineno}: inicio_s negativo")
        elif end <= start:
            errors.append(f"linha {lineno}: fim_s ({end:g}) deve ser maior que inicio_s ({start:g})")
        seen.add(name)
        segments.append(Segment(name, start, end))
    if errors:
        raise ValueError("Marcações inválidas: " + "; ".join(errors))
    if not segments:
        raise ValueError("Arquivo de marcações sem nenhuma linha de dados.")
    return segments


def load_segments(path: str) -> list:
    with open(path, encoding="utf-8-sig") as f:
        return parse_segments(f.read())


def check_segments(segments: list, duration_s: float) -> list:
    """Avisos para segmentos fora da duração do log (não impedem o cálculo)."""
    out = []
    for s in segments:
        if s.inicio_s >= duration_s:
            out.append(f"Segmento {s.nome!r} começa em {s.inicio_s:g} s, depois do fim do log "
                       f"({duration_s:.1f} s); ignorado.")
        elif s.fim_s > duration_s + TOLERANCE_S and math.isfinite(s.fim_s):
            out.append(f"Segmento {s.nome!r} termina em {s.fim_s:g} s, depois do fim do log "
                       f"({duration_s:.2f} s); cortado.")
    return out

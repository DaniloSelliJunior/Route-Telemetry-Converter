"""Orquestração sem GUI: carregar um .bin uma vez e gerar .ld / CSV, inclusive em lote.

A GUI usa as mesmas funções: load_log() é chamado ao escolher o arquivo e o
LoadedLog fica no estado compartilhado entre as abas.
"""

import glob
import os
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

import csv_export
from exporter import require_data, segment_paths, write_ld
from parser import ParseResult, TimeCheck, check_timestamps, parse_file
from quality import build_quality_report


@dataclass
class SessionMeta:
    piloto: str = "Piloto Route"
    veiculo: str = "FR2026"
    local: str = "UFSCar"
    evento: str = ""
    sessao: str = ""

    def ld_kwargs(self) -> dict:
        return dict(driver=self.piloto, vehicle=self.veiculo, venue=self.local,
                    event=self.evento, session=self.sessao)


@dataclass
class CsvOptions:
    mode: str = "unificado"
    freq_hz: float = csv_export.DEFAULT_RATE
    profile: str = "padrao"


@dataclass
class LoadedLog:
    path: str
    result: ParseResult
    check: TimeCheck
    quality: dict

    @property
    def segments(self) -> list:
        return self.check.segments

    @property
    def warnings(self) -> list:
        return self.result.warnings + self.check.warnings


def load_log(path: str, progress_cb: Optional[Callable[[float], None]] = None) -> LoadedLog:
    """Lê, decodifica, checa timestamps e monta o relatório de qualidade (uma vez por arquivo)."""
    result = parse_file(path, (lambda p: progress_cb(p * 0.9)) if progress_cb else None)
    require_data(result)
    check = check_timestamps(result)
    quality = build_quality_report(result, check)
    if progress_cb:
        progress_cb(1.0)
    return LoadedLog(path, result, check, quality)


def output_base(src: str, out_dir: Optional[str] = None) -> str:
    """Caminho sem extensão para as saídas: ao lado do .bin ou em out_dir."""
    base = os.path.splitext(os.path.basename(src))[0]
    return os.path.join(out_dir or os.path.dirname(os.path.abspath(src)), base)


def ld_paths(log: LoadedLog, out_dir: Optional[str] = None) -> list:
    return segment_paths(output_base(log.path, out_dir) + ".ld", len(log.segments))


def csv_paths(log: LoadedLog, options: CsvOptions, out_dir: Optional[str] = None) -> list:
    base = output_base(log.path, out_dir)
    plan = csv_export.plan_csv(log.segments, base, options.mode, options.freq_hz)
    return [p for _, _, p in plan] + [csv_export.metadata_path(base)]


def write_ld_outputs(log: LoadedLog, meta: SessionMeta, out_dir: Optional[str] = None,
                     progress_cb: Optional[Callable[[float], None]] = None) -> list:
    outs = ld_paths(log, out_dir)
    n = len(outs)
    for i, (seg, out) in enumerate(zip(log.segments, outs)):
        write_ld(seg, out, progress_cb=(lambda p, i=i: progress_cb((i + p) / n))
                 if progress_cb else None, **meta.ld_kwargs())
    return outs


def write_csv_outputs(log: LoadedLog, meta: SessionMeta, options: CsvOptions,
                      out_dir: Optional[str] = None,
                      progress_cb: Optional[Callable[[float], None]] = None) -> list:
    return csv_export.export_csv(
        log.segments, output_base(log.path, out_dir), options.mode, options.freq_hz,
        options.profile, metadata=asdict(meta), source=log.path, progress_cb=progress_cb)


@dataclass
class BatchItem:
    source: str
    status: str = "ok"                 # "ok" | "pulado" | "erro"
    outputs: list = field(default_factory=list)
    message: str = ""
    warnings: int = 0


def list_bins(folder: str) -> list:
    """Arquivos .bin (qualquer caixa) da pasta, sem subpastas, em ordem alfabética."""
    return sorted(p for p in glob.glob(os.path.join(folder, "*"))
                  if os.path.isfile(p) and p.lower().endswith(".bin"))


def convert_file(src: str, meta: SessionMeta, ld: bool = True, csv: bool = False,
                 csv_options: Optional[CsvOptions] = None, out_dir: Optional[str] = None,
                 overwrite: bool = False) -> BatchItem:
    """Converte um arquivo; nunca levanta exceção (o erro vai para o BatchItem)."""
    item = BatchItem(source=src)
    csv_options = csv_options or CsvOptions()
    try:
        log = load_log(src)
        item.warnings = len(log.warnings)
        planned = (ld_paths(log, out_dir) if ld else []) + \
                  (csv_paths(log, csv_options, out_dir) if csv else [])
        existing = [p for p in planned if os.path.exists(p)]
        if existing and not overwrite:
            item.status = "pulado"
            item.message = "já existe: " + ", ".join(os.path.basename(p) for p in existing)
            return item
        if ld:
            item.outputs += write_ld_outputs(log, meta, out_dir)
        if csv:
            item.outputs += write_csv_outputs(log, meta, csv_options, out_dir)
        if len(log.segments) > 1:
            item.message = f"{len(log.segments)} segmentos (saltos/resets de timestamp)"
    except Exception as ex:          # um arquivo ruim não aborta o lote
        item.status = "erro"
        item.message = str(ex)
    return item


def convert_folder(folder: str, meta: SessionMeta, ld: bool = True, csv: bool = False,
                   csv_options: Optional[CsvOptions] = None, out_dir: Optional[str] = None,
                   overwrite: bool = False,
                   progress_cb: Optional[Callable[[int, int, str], None]] = None) -> list:
    """Converte todos os .bin da pasta. progress_cb(i, total, arquivo) antes de cada um."""
    if not (ld or csv):
        raise ValueError("Escolha ao menos uma saída (.ld ou CSV).")
    files = list_bins(folder)
    items = []
    for i, src in enumerate(files):
        if progress_cb:
            progress_cb(i, len(files), src)
        items.append(convert_file(src, meta, ld, csv, csv_options, out_dir, overwrite))
    if progress_cb:
        progress_cb(len(files), len(files), "")
    return items


def batch_summary(items: list) -> str:
    """Resumo de uma linha: quantos ok, pulados e com erro."""
    counts = {s: sum(it.status == s for it in items) for s in ("ok", "pulado", "erro")}
    return (f"{len(items)} arquivo(s): {counts['ok']} convertido(s), "
            f"{counts['pulado']} pulado(s), {counts['erro']} com erro.")

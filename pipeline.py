"""Orquestração sem GUI: carregar um .bin uma vez e gerar .ld / CSV, inclusive em lote.

A GUI usa as mesmas funções: load_log() é chamado ao escolher o arquivo e o
LoadedLog fica no estado compartilhado entre as abas.
"""

import glob
import os
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

import csv_export
import kpi
from derived import compute_derived
from exporter import require_data, resampled_channels, segment_paths, write_ld
from kpi import output as kpi_output
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


def channel_set(segment: ParseResult, include_derived: bool = True, config: dict = None):
    """(canais, unidades, taxas) reamostrados de um segmento, com os derivados se pedido."""
    data, units, freqs = resampled_channels(segment)
    if include_derived:
        cfg = (config or kpi.merge_config())["derivados"]
        d, u, f = compute_derived(data, units, freqs, cfg)
        data.update(d)
        units.update(u)
        freqs.update(f)
    return data, units, freqs


def derived_ld_channels(segment: ParseResult, config: dict = None) -> list:
    """[(nome, unidade, freq, array)] dos canais derivados, para write_ld(extra_channels=...)."""
    data, units, freqs = resampled_channels(segment)
    cfg = (config or kpi.merge_config())["derivados"]
    d, u, f = compute_derived(data, units, freqs, cfg)
    return [(n, u[n], f[n], v) for n, (_, v) in d.items()]


def write_ld_outputs(log: LoadedLog, meta: SessionMeta, out_dir: Optional[str] = None,
                     progress_cb: Optional[Callable[[float], None]] = None,
                     include_derived: bool = False, config: dict = None) -> list:
    outs = ld_paths(log, out_dir)
    n = len(outs)
    for i, (seg, out) in enumerate(zip(log.segments, outs)):
        extra = derived_ld_channels(seg, config) if include_derived else None
        write_ld(seg, out, progress_cb=(lambda p, i=i: progress_cb((i + p) / n))
                 if progress_cb else None, extra_channels=extra, **meta.ld_kwargs())
    return outs


def write_csv_outputs(log: LoadedLog, meta: SessionMeta, options: CsvOptions,
                      out_dir: Optional[str] = None,
                      progress_cb: Optional[Callable[[float], None]] = None) -> list:
    return csv_export.export_csv(
        log.segments, output_base(log.path, out_dir), options.mode, options.freq_hz,
        options.profile, metadata=asdict(meta), source=log.path, progress_cb=progress_cb)


# ---- KPIs ----------------------------------------------------------------------

def session_names(log: LoadedLog) -> list:
    """Nome de cada segmento do log nas saídas de KPI: nome do .bin (ou nome_segN)."""
    stem = os.path.splitext(os.path.basename(log.path))[0]
    return [os.path.splitext(os.path.basename(p))[0]
            for p in segment_paths(stem + ".x", len(log.segments))]


def compute_log_kpis(log: LoadedLog, config: dict = None, marks: list = None) -> list:
    """[(nome da sessão, KpiResult)], um por segmento do log (timestamps)."""
    cfg = config or kpi.merge_config()
    out = []
    for name, seg in zip(session_names(log), log.segments):
        data, units, _ = channel_set(seg, True, cfg)
        out.append((name, kpi.compute_kpis(data, marks, cfg, units)))
    return out


def kpi_paths(log: LoadedLog, out_dir: Optional[str] = None) -> list:
    base = output_base(log.path, out_dir)
    return [base + "_kpis.csv", base + "_kpis.json"]


def comparison_path(log_a: LoadedLog, log_b: LoadedLog, out_dir: Optional[str] = None) -> str:
    stem_b = os.path.splitext(os.path.basename(log_b.path))[0]
    return output_base(log_a.path, out_dir) + f"_vs_{stem_b}_comparacao.csv"


def write_kpi_outputs(log: LoadedLog, meta: SessionMeta, sessions: list, config: dict = None,
                      out_dir: Optional[str] = None, profile: str = "padrao") -> list:
    """Grava <base>_kpis.csv e <base>_kpis.json a partir de compute_log_kpis."""
    csv_path, json_path = kpi_paths(log, out_dir)
    kpi_output.write_kpis_csv(csv_path, sessions, profile)
    metadata = asdict(meta)
    metadata["arquivo_origem"] = os.path.basename(log.path)
    kpi_output.write_kpis_json(json_path, sessions, metadata, config or kpi.merge_config(),
                               log.quality)
    return [csv_path, json_path]


def write_comparison(log_a: LoadedLog, sessions_a: list, log_b: LoadedLog, sessions_b: list,
                     out_dir: Optional[str] = None, profile: str = "padrao") -> str:
    path = comparison_path(log_a, log_b, out_dir)
    kpi_output.write_comparison_csv(path, kpi_output.compare(sessions_a, sessions_b), profile)
    return path


# ---- relatório (requer matplotlib: requirements-report.txt) ---------------------

REPORT_FORMATS = ("html", "pdf")


def report_paths(log: LoadedLog, formats=REPORT_FORMATS, out_dir: Optional[str] = None) -> list:
    base = output_base(log.path, out_dir)
    return [f"{base}_relatorio.{fmt}" for fmt in formats]


def write_report(log: LoadedLog, meta: SessionMeta, sessions: list, log_b: LoadedLog = None,
                 sessions_b: list = None, formats=REPORT_FORMATS,
                 out_dir: Optional[str] = None) -> list:
    """Grava <base>_relatorio.html/.pdf (comparação com log_b se houver)."""
    import report
    import report_data
    notes = []
    if len(log.segments) > 1:
        notes.append(f"O log tem {len(log.segments)} segmentos (saltos/resets de timestamp); "
                     f"os gráficos usam o primeiro.")
    inp = report.ReportInput(
        summary=report_data.session_summary(log, meta), quality=log.quality,
        sessions_a=sessions, label_a=os.path.splitext(os.path.basename(log.path))[0],
        sessions_b=sessions_b,
        label_b=os.path.splitext(os.path.basename(log_b.path))[0] if log_b else "B",
        notes=notes)
    paths = report_paths(log, formats, out_dir)
    for fmt, path in zip(formats, paths):
        if fmt == "html":
            report.write_html(path, inp)
        elif fmt == "pdf":
            report.write_pdf(path, inp)
        else:
            raise ValueError(f"Formato de relatório inválido: {fmt!r}.")
    return paths


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
                 overwrite: bool = False, include_derived: bool = False,
                 config: dict = None) -> BatchItem:
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
            item.outputs += write_ld_outputs(log, meta, out_dir, None, include_derived, config)
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
                   progress_cb: Optional[Callable[[int, int, str], None]] = None,
                   include_derived: bool = False, config: dict = None) -> list:
    """Converte todos os .bin da pasta. progress_cb(i, total, arquivo) antes de cada um."""
    if not (ld or csv):
        raise ValueError("Escolha ao menos uma saída (.ld ou CSV).")
    files = list_bins(folder)
    items = []
    for i, src in enumerate(files):
        if progress_cb:
            progress_cb(i, len(files), src)
        items.append(convert_file(src, meta, ld, csv, csv_options, out_dir, overwrite,
                                  include_derived, config))
    if progress_cb:
        progress_cb(len(files), len(files), "")
    return items


def batch_summary(items: list) -> str:
    """Resumo de uma linha: quantos ok, pulados e com erro."""
    counts = {s: sum(it.status == s for it in items) for s in ("ok", "pulado", "erro")}
    return (f"{len(items)} arquivo(s): {counts['ok']} convertido(s), "
            f"{counts['pulado']} pulado(s), {counts['erro']} com erro.")

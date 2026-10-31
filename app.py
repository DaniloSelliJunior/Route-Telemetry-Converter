"""Route Telemetry Converter - GUI (Flet, API clássica 0.25-0.27).

Executar:  python app.py

Identidade visual: as paletas (escuro e claro) ficam em theme.py; THEME abaixo
é a paleta ativa. Para exibir o logo da equipe, coloque o arquivo em
assets/logo.png (fundo transparente).

A interface é montada por build(page, state). Trocar o tema reconstrói os
controles (as cores são aplicadas na criação) sem reiniciar: o estado (log
carregado, KPIs, campos, aba atual) fica em `state`, fora de build.
"""

import os
import subprocess
import sys
import threading
import time

from json import loads as json_loads

import flet as ft

import csv_export
import kpi
import pipeline
import report
import report_data
import settings as prefs
from theme import PALETTES, THEME_CHOICES, on_color, resolve_theme
from report_data import fmt_value as fmt_kpi
from parser import unwrap_timestamps

# paleta ativa (atualizada no lugar por apply_theme; as funções abaixo a leem na criação)
THEME = dict(PALETTES["escuro"])
TEAM_NAME = "FORMULA ROUTE"
TEAM_SUB = "UFSCar  ·  Telemetria"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
HAS_LOGO = os.path.exists(os.path.join(ASSETS_DIR, "logo.png"))


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60:d}:{seconds % 60:02d} min"


def open_folder(path: str):
    folder = os.path.dirname(os.path.abspath(path))
    try:
        if sys.platform.startswith("win"):
            os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception:
        pass


def quality_lines(report: dict, limit: int = 30) -> list:
    """Avisos do relatório de qualidade para exibir (no máximo `limit`)."""
    avisos = report["avisos"]
    lines = list(avisos[:limit])
    if len(avisos) > limit:
        lines.append(f"... e mais {len(avisos) - limit} aviso(s).")
    return lines


def rates_summary(report: dict) -> str:
    """Uma linha com a taxa real (mediana) x nominal de cada grupo."""
    parts = []
    for name, g in report["grupos"].items():
        real = "-" if g["taxa_mediana_hz"] is None else f"{g['taxa_mediana_hz']:g}"
        parts.append(f"{name}: {real} / {g['taxa_nominal_hz']:g} Hz")
    return "  ·  ".join(parts)


def batch_lines(items: list) -> list:
    """Uma linha por arquivo do lote: status, nome e mensagem."""
    icons = {"ok": "OK", "pulado": "PULADO", "erro": "ERRO"}
    out = []
    for it in items:
        line = f"[{icons[it.status]}] {os.path.basename(it.source)}"
        if it.status == "ok":
            line += f": {len(it.outputs)} arquivo(s)"
            if it.warnings:
                line += f", {it.warnings} aviso(s)"
        if it.message:
            line += f" ({it.message})" if it.status == "ok" else f": {it.message}"
        out.append(line)
    return out


def kpi_table_rows(sessions_a: list, sessions_b: list = None, segment: str = kpi.SESSION) -> list:
    """Linhas da tabela de KPIs de um segmento (1º segmento de log de cada arquivo).

    Sem comparação: (kpi, valor, unidade). Com: (kpi, valor A, unidade, valor B, delta, delta %).
    """
    from kpi.output import compare
    if not sessions_a:
        return []
    if not sessions_b:
        return [(k.nome, fmt_kpi(k.valor), k.unidade)
                for k in sessions_a[0][1].kpis if k.segmento == segment]
    rows = compare(sessions_a[:1], sessions_b[:1])
    return [(r["kpi"], fmt_kpi(r["valor_a"]), r["unidade"], fmt_kpi(r["valor_b"]),
             fmt_kpi(r["delta"]),
             "–" if r["delta_pct"] is None else f"{r['delta_pct']:+.1f}%")
            for r in rows if r["segmento"] == segment]


def chart_series(kind: str, res_a, res_b=None, segment: str = kpi.SESSION):
    """(rótulos, valores A, valores B ou None) de um gráfico de barras, ou None sem dados.

    kind: "hist_rpm", "hist_acelerador", "tempo_marcha" ou "frenagens" (pico por evento).
    """
    if kind == "frenagens":
        evs = report_data.braking(res_a, segment)
        if not evs:
            return None
        return [str(i) for i in range(1, len(evs) + 1)], [e["pico_psi"] for e in evs], None
    get = (lambda r: report_data.gear_bars(r, segment)) if kind == "tempo_marcha" else \
          (lambda r: report_data.hist_bars(r, kind, segment))
    a = get(res_a)
    b = get(res_b) if res_b is not None else None
    joined = report_data.align_bars(a, b)
    if joined is None:
        return None
    labels, va, vb = joined
    return labels, va, (vb if res_b is not None else None)


def log_duration_s(result) -> float:
    """Duração do log (maior intervalo entre os grupos de pacotes)."""
    unwrapped = (unwrap_timestamps(g.timestamps_ms) for g in result.groups.values())
    spans = [(ts[-1] - ts[0]) / 1000.0 for ts in unwrapped if len(ts) > 1]
    return max(spans) if spans else 0.0


# ----------------------------------------------------------------------------
# Componentes de interface
# ----------------------------------------------------------------------------
def section_card(step: str, title: str, content: ft.Control) -> ft.Container:
    return ft.Container(
        bgcolor=THEME["surface"],
        border=ft.border.all(1, THEME["border"]),
        border_radius=16,
        padding=20,
        content=ft.Column(
            spacing=14,
            controls=[
                ft.Row(
                    spacing=10,
                    controls=[
                        ft.Container(
                            width=26, height=26, border_radius=13,
                            bgcolor=THEME["primary"], alignment=ft.alignment.center,
                            content=ft.Text(step, size=13, weight=ft.FontWeight.BOLD,
                                            color=THEME["on_primary"]),
                        ),
                        ft.Text(title, size=15, weight=ft.FontWeight.W_600,
                                color=THEME["text"]),
                    ],
                ),
                content,
            ],
        ),
    )


def stat_tile(label: str, value_ctrl: ft.Text) -> ft.Container:
    return ft.Container(
        expand=True,
        bgcolor=THEME["surface2"],
        border_radius=12,
        padding=ft.padding.symmetric(vertical=12, horizontal=14),
        content=ft.Column(
            spacing=2,
            controls=[ft.Text(label.upper(), size=10, color=THEME["muted"],
                              weight=ft.FontWeight.W_600),
                      value_ctrl],
        ),
    )


def styled_field(label: str, value: str, expand: bool = True) -> ft.TextField:
    return ft.TextField(
        label=label, value=value, dense=True, expand=expand,
        bgcolor=THEME["surface2"],
        border_color=THEME["border"], focused_border_color=THEME["primary"],
        border_radius=10, color=THEME["text"],
        label_style=ft.TextStyle(color=THEME["muted"], size=12),
        cursor_color=THEME["primary"],
    )


def bar_chart(title: str, unit: str, labels: list, a: list, b: list = None,
              label_a: str = "A", label_b: str = "B") -> ft.Container:
    """Gráfico de barras nativo do Flet (tooltip por barra; legenda só com duas séries)."""
    col_a, col_b = report.STYLES[THEME["chart"]]["a"], report.STYLES[THEME["chart"]]["b"]
    width = 14 if b is None else 8
    top = max([v for v in list(a) + list(b or []) if v is not None] + [1e-9])
    groups = []
    for i, lab in enumerate(labels):
        rods = [ft.BarChartRod(from_y=0, to_y=a[i], width=width, color=col_a,
                               border_radius=ft.border_radius.only(top_left=4, top_right=4),
                               tooltip=f"{label_a} · {lab}: {fmt_kpi(a[i])} {unit}")]
        if b is not None:
            rods.append(ft.BarChartRod(from_y=0, to_y=b[i], width=width, color=col_b,
                                       border_radius=ft.border_radius.only(top_left=4, top_right=4),
                                       tooltip=f"{label_b} · {lab}: {fmt_kpi(b[i])} {unit}"))
        groups.append(ft.BarChartGroup(x=i, bar_rods=rods, bars_space=2))
    step = max(1, len(labels) // 12)
    chart = ft.BarChart(
        bar_groups=groups, max_y=top * 1.1, height=190,
        horizontal_grid_lines=ft.ChartGridLines(color=THEME["border"], width=1),
        tooltip_bgcolor=THEME["surface2"],
        left_axis=ft.ChartAxis(labels_size=40, title=ft.Text(unit, size=10, color=THEME["muted"]),
                               title_size=16),
        bottom_axis=ft.ChartAxis(labels_size=24, labels=[
            ft.ChartAxisLabel(value=i, label=ft.Text(lab, size=9, color=THEME["muted"]))
            for i, lab in enumerate(labels) if i % step == 0]),
    )
    head = [ft.Text(title, size=13, weight=ft.FontWeight.W_600, color=THEME["text"])]
    if b is not None:
        for name, col in ((label_a, col_a), (label_b, col_b)):
            head.append(ft.Row(spacing=4, controls=[
                ft.Container(width=10, height=10, bgcolor=col, border_radius=2),
                ft.Text(name, size=11, color=THEME["muted"])]))
    return ft.Container(bgcolor=THEME["surface2"], border_radius=12, padding=12,
                        content=ft.Column(spacing=8, controls=[ft.Row(spacing=12, wrap=True,
                                                                      controls=head), chart]))


def styled_dropdown(label: str, options: list, value: str, width: int = 200) -> ft.Dropdown:
    """options: [(chave, texto)]."""
    return ft.Dropdown(
        label=label, value=value, width=width, dense=True,
        options=[ft.dropdown.Option(key=k, text=t) for k, t in options],
        bgcolor=THEME["surface2"], border_color=THEME["border"],
        focused_border_color=THEME["primary"], border_radius=10, color=THEME["text"],
        label_style=ft.TextStyle(color=THEME["muted"], size=12),
    )


def primary_button(label: str, icon) -> ft.Container:
    return ft.Container(
        ink=True, disabled=True, opacity=0.45,
        border_radius=12, padding=ft.padding.symmetric(vertical=15),
        alignment=ft.alignment.center,
        gradient=ft.LinearGradient(
            begin=ft.alignment.center_left, end=ft.alignment.center_right,
            colors=[THEME["primary"], THEME["primary_d"]]),
        content=ft.Row(
            alignment=ft.MainAxisAlignment.CENTER, spacing=10,
            controls=[ft.Icon(icon, color=THEME["on_primary"]),
                      ft.Text(label, size=15, weight=ft.FontWeight.BOLD, color=THEME["on_primary"])]),
    )


def outline_button(label: str, icon, on_click=None) -> ft.OutlinedButton:
    return ft.OutlinedButton(
        label, icon=icon, on_click=on_click,
        style=ft.ButtonStyle(color=THEME["text"],
                             side=ft.BorderSide(1, THEME["border"]),
                             shape=ft.RoundedRectangleBorder(radius=10)))


def styled_checkbox(label: str, value: bool) -> ft.Checkbox:
    return ft.Checkbox(label=label, value=value, active_color=THEME["primary"],
                       label_style=ft.TextStyle(color=THEME["text"], size=13))


# ----------------------------------------------------------------------------
# Aplicação
# ----------------------------------------------------------------------------
def apply_theme(page: ft.Page, state: dict):
    """Ativa a paleta escolhida (Sistema segue o brilho do SO)."""
    system_dark = page.platform_brightness == ft.Brightness.DARK
    name = resolve_theme(state["settings"].tema, system_dark)
    THEME.clear()
    THEME.update(PALETTES[name])
    page.theme_mode = ft.ThemeMode.DARK if name == "escuro" else ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=THEME["primary"])
    page.dark_theme = ft.Theme(color_scheme_seed=THEME["primary"])
    page.bgcolor = THEME["bg"]


def initial_state() -> dict:
    """Estado que sobrevive à reconstrução da interface. Preferências nunca travam o app."""
    s, warnings = prefs.load_settings()
    cfg, w = prefs.load_thresholds()
    if w:
        warnings.append(w)
    return {
        "settings": s, "startup_warnings": warnings,
        # o .bin é lido uma vez só (pipeline.load_log) e reaproveitado pelas abas
        "path": None, "log": None, "busy": False, "out": None, "batch_dir": None,
        "config": cfg, "config_path": None, "marks": None, "marks_path": None,
        "log_b": None, "kpis": None, "kpis_b": None, "tab": "Converter",
        "form": {
            "piloto": s.piloto, "veiculo": s.veiculo, "local": s.local, "evento": "", "sessao": "",
            "include_derived": True, "csv_mode": s.csv_modo, "csv_rate": str(s.csv_taxa_hz),
            "csv_profile": s.csv_perfil, "batch_ld": True, "batch_csv": False,
            "batch_overwrite": False, "report_html": True, "report_pdf": True,
            "thr_text": prefs.thresholds_text(),
        },
    }


def main(page: ft.Page):
    page.title = "Route Telemetry Converter"
    page.window_width = 820
    page.window_height = 880
    page.window_min_width = 680
    page.window_min_height = 720
    page.padding = ft.padding.symmetric(horizontal=28, vertical=22)
    page.scroll = ft.ScrollMode.AUTO
    state = initial_state()

    def rebuild():
        page.controls.clear()
        page.overlay.clear()
        apply_theme(page, state)
        build(page, state, rebuild)

    def on_brightness(_):
        if state["settings"].tema == "sistema" and not state["busy"]:
            state["save_form"]()
            rebuild()

    page.on_platform_brightness_change = on_brightness
    apply_theme(page, state)
    build(page, state, rebuild)
    if state["startup_warnings"]:
        page.snack_bar = ft.SnackBar(ft.Text(
            f"Preferências: {len(state['startup_warnings'])} aviso(s); veja a aba Configurações.",
            color=on_color(THEME["warn"])), bgcolor=THEME["warn"])
        page.snack_bar.open = True
        page.update()


def build(page: ft.Page, state: dict, rebuild):
    """Cria todos os controles com a paleta ativa e liga os eventos."""
    form = state["form"]
    out_dir = lambda: state["settings"].pasta_saida or None      # noqa: E731

    # ---- cabeçalho -------------------------------------------------------
    brand = []
    if HAS_LOGO:
        brand.append(ft.Image(src="/logo.png", height=44, fit=ft.ImageFit.CONTAIN))
    brand.append(
        ft.Column(
            spacing=0,
            controls=[
                ft.Text(TEAM_NAME, size=20, weight=ft.FontWeight.W_900,
                        color=THEME["text"]),
                ft.Text(TEAM_SUB, size=11, color=THEME["muted"]),
            ],
        )
    )
    header = ft.Container(
        padding=ft.padding.only(bottom=16),
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(spacing=12, controls=brand),
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=12, vertical=6),
                    border_radius=20,
                    border=ft.border.all(1, THEME["primary"]),
                    content=ft.Text("Route Telemetry Converter", size=11,
                                    color=THEME["primary"], weight=ft.FontWeight.W_600),
                ),
            ],
        ),
    )
    accent_bar = ft.Container(
        height=3, border_radius=2,
        gradient=ft.LinearGradient(
            begin=ft.alignment.center_left, end=ft.alignment.center_right,
            colors=[THEME["primary"], THEME["primary_d"], THEME["bg"]]),
    )
    intro = ft.Text(
        "Converta o log bruto do datalogger (.bin) para MoTeC i2 Pro (.ld) ou CSV.",
        size=13, color=THEME["muted"])

    # ---- 1. arquivo ------------------------------------------------------
    drop_icon = ft.Icon(ft.Icons.UPLOAD_FILE_ROUNDED, size=38, color=THEME["primary"])
    drop_title = ft.Text("Selecionar arquivo .bin", size=15,
                         weight=ft.FontWeight.W_600, color=THEME["text"])
    drop_hint = ft.Text("Clique para escolher o log do datalogger",
                        size=12, color=THEME["muted"])
    drop_zone = ft.Container(
        ink=True,
        border_radius=14,
        bgcolor=THEME["surface2"],
        border=ft.border.all(1.5, THEME["border"]),
        padding=ft.padding.symmetric(vertical=26, horizontal=16),
        alignment=ft.alignment.center,
        content=ft.Column(
            spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[drop_icon, drop_title, drop_hint]),
    )

    # ---- 2. sessão (compartilhado: .ld e metadados do CSV) ----------------
    driver = styled_field("Piloto", form["piloto"])
    vehicle = styled_field("Veículo", form["veiculo"])
    venue = styled_field("Local", form["local"])
    event = styled_field("Evento", form["evento"])
    session = styled_field("Sessão", form["sessao"])

    def session_meta() -> pipeline.SessionMeta:
        return pipeline.SessionMeta(driver.value, vehicle.value, venue.value,
                                    event.value, session.value)

    # ---- progresso (uma operação por vez) -------------------------------
    stage = ft.Text("Selecione um arquivo para começar.", size=13, color=THEME["muted"])
    pct = ft.Text("", size=12, color=THEME["muted"])
    bar = ft.ProgressBar(value=0, visible=False, color=THEME["primary"],
                         bgcolor=THEME["surface2"], bar_height=6, border_radius=3)
    progress_box = ft.Column(spacing=8, controls=[
        ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[stage, pct]),
        bar,
    ])

    def show(p: float, label: str):
        bar.value = p
        pct.value = f"{int(p * 100)}%"
        stage.value = label
        page.update()

    # ---- qualidade do log (acima das abas) -------------------------------
    quality_icon = ft.Icon(ft.Icons.VERIFIED_ROUNDED, color=THEME["ok"], size=22)
    quality_title = ft.Text("", size=15, weight=ft.FontWeight.W_600, color=THEME["text"])
    quality_list = ft.Column(spacing=4)
    quality_rates = ft.Text("", size=12, color=THEME["muted"], selectable=True)
    quality_imu = ft.Text("", size=12, color=THEME["muted"], selectable=True)
    quality_card = ft.Container(
        visible=False,
        bgcolor=THEME["surface"],
        border=ft.border.all(1, THEME["ok"]),
        border_radius=16, padding=20,
        content=ft.Column(spacing=10, controls=[
            ft.Row(spacing=8, controls=[quality_icon, quality_title]),
            quality_list, quality_rates, quality_imu,
        ]),
    )

    error_text = ft.Text("", size=13, color=THEME["err"], selectable=True)
    error_card = ft.Container(
        visible=False, bgcolor=THEME["surface"],
        border=ft.border.all(1, THEME["err"]), border_radius=16, padding=18,
        content=ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.START,
                       controls=[ft.Icon(ft.Icons.ERROR_OUTLINE_ROUNDED,
                                         color=THEME["err"], size=22),
                                 ft.Container(expand=True, content=error_text)]),
    )

    # ---- aba Converter (.ld) ----------------------------------------------
    convert_btn = primary_button("Converter para .ld", ft.Icons.SWAP_HORIZ_ROUNDED)
    v_packets = ft.Text("-", size=18, weight=ft.FontWeight.BOLD, color=THEME["text"])
    v_channels = ft.Text("-", size=18, weight=ft.FontWeight.BOLD, color=THEME["text"])
    v_duration = ft.Text("-", size=18, weight=ft.FontWeight.BOLD, color=THEME["text"])
    v_time = ft.Text("-", size=18, weight=ft.FontWeight.BOLD, color=THEME["text"])
    out_path = ft.Text("", size=12, color=THEME["muted"], selectable=True)
    warn_text = ft.Text("", size=12, color=THEME["warn"], visible=False, selectable=True)
    result_card = ft.Container(
        visible=False,
        bgcolor=THEME["surface"],
        border=ft.border.all(1, THEME["ok"]),
        border_radius=16, padding=20,
        content=ft.Column(spacing=12, controls=[
            ft.Row(spacing=8, controls=[
                ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=THEME["ok"], size=22),
                ft.Text("Conversão concluída", size=15,
                        weight=ft.FontWeight.W_600, color=THEME["text"])]),
            ft.Row(spacing=10, controls=[
                stat_tile("Pacotes", v_packets), stat_tile("Canais", v_channels),
                stat_tile("Duração do log", v_duration), stat_tile("Tempo", v_time)]),
            out_path, warn_text,
            ft.Row(controls=[outline_button(
                "Abrir pasta", ft.Icons.FOLDER_OPEN_ROUNDED,
                lambda _: state["out"] and open_folder(state["out"]))]),
        ]),
    )
    include_derived = styled_checkbox(
        "Incluir canais derivados no .ld (Balanço de freio, G combinado, Taxa do acelerador, "
        "Distância, Acel. pela velocidade)", form["include_derived"])
    tab_converter = ft.Column(spacing=14, controls=[
        section_card("3", "Converter para MoTeC .ld", ft.Column(spacing=12, controls=[
            include_derived, convert_btn])),
        result_card])

    # ---- aba CSV ------------------------------------------------------------
    csv_mode = ft.RadioGroup(
        value=form["csv_mode"],
        content=ft.Column(spacing=2, controls=[
            ft.Radio(value="unificado", label="Unificado: um CSV numa taxa só (interpolado)",
                     active_color=THEME["primary"],
                     label_style=ft.TextStyle(color=THEME["text"], size=13)),
            ft.Radio(value="grupos", label="Por grupo: um CSV por grupo, taxas nativas, sem interpolação",
                     active_color=THEME["primary"],
                     label_style=ft.TextStyle(color=THEME["text"], size=13)),
        ]))
    csv_rate = styled_dropdown("Taxa (unificado)", [(str(r), f"{r} Hz") for r in csv_export.UNIFIED_RATES],
                               form["csv_rate"], width=170)
    csv_profile = styled_dropdown("Perfil", [(k, p.label) for k, p in csv_export.PROFILES.items()],
                                  form["csv_profile"], width=170)
    csv_rate.disabled = form["csv_mode"] != "unificado"
    csv_btn = primary_button("Exportar CSV", ft.Icons.TABLE_CHART_ROUNDED)
    csv_result = ft.Text("", size=12, color=THEME["muted"], selectable=True)
    csv_result_card = ft.Container(
        visible=False, bgcolor=THEME["surface"], border=ft.border.all(1, THEME["ok"]),
        border_radius=16, padding=20,
        content=ft.Column(spacing=10, controls=[
            ft.Row(spacing=8, controls=[
                ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=THEME["ok"], size=22),
                ft.Text("CSV exportado", size=15, weight=ft.FontWeight.W_600,
                        color=THEME["text"])]),
            csv_result,
            ft.Row(controls=[outline_button(
                "Abrir pasta", ft.Icons.FOLDER_OPEN_ROUNDED,
                lambda _: state["out"] and open_folder(state["out"]))]),
        ]))

    def csv_options() -> pipeline.CsvOptions:
        return pipeline.CsvOptions(csv_mode.value, float(csv_rate.value), csv_profile.value)

    def on_mode_change(_):
        csv_rate.disabled = csv_mode.value != "unificado"
        page.update()

    csv_mode.on_change = on_mode_change

    # lote (pasta inteira): usa as opções de CSV acima e os dados da sessão
    batch_folder = ft.Text(
        "Nenhuma pasta escolhida." if not state["batch_dir"] else
        f"{state['batch_dir']}  ·  {len(pipeline.list_bins(state['batch_dir']))} arquivo(s) .bin",
        size=12, color=THEME["muted"], selectable=True)
    batch_ld = styled_checkbox(".ld (MoTeC)", form["batch_ld"])
    batch_csv = styled_checkbox("CSV (opções acima)", form["batch_csv"])
    batch_overwrite = styled_checkbox("Sobrescrever arquivos existentes", form["batch_overwrite"])
    batch_btn = primary_button("Converter pasta", ft.Icons.DRIVE_FOLDER_UPLOAD_ROUNDED)
    batch_pick_btn = outline_button("Escolher pasta", ft.Icons.FOLDER_ROUNDED)
    batch_summary_text = ft.Text("", size=13, weight=ft.FontWeight.W_600, color=THEME["text"])
    batch_list = ft.Column(spacing=3)

    tab_csv = ft.Column(spacing=14, controls=[
        section_card("3", "Exportar CSV", ft.Column(spacing=12, controls=[
            csv_mode,
            ft.Row(spacing=10, controls=[csv_rate, csv_profile]),
            ft.Text("Excel BR: ponto e vírgula, vírgula decimal, UTF-8 com BOM. "
                    "NaN/inf são escritos como texto (nan, inf, -inf). "
                    "Um .json com os metadados da sessão é gravado ao lado.",
                    size=11, color=THEME["muted"]),
            csv_btn,
        ])),
        csv_result_card,
        section_card("4", "Conversão em lote (pasta)", ft.Column(spacing=10, controls=[
            ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                batch_pick_btn, ft.Container(expand=True, content=batch_folder)]),
            ft.Row(spacing=16, wrap=True, controls=[batch_ld, batch_csv, batch_overwrite]),
            batch_btn, batch_summary_text, batch_list,
        ])),
    ])

    # ---- aba KPIs ---------------------------------------------------------
    settings_cfg_text = (f"Limiares das Configurações ({prefs.thresholds_path()}); "
                         f"provisórios até calibrar com logs reais.")
    cfg_label = ft.Text(
        settings_cfg_text if not state["config_path"] else
        f"{state['config_path']}  (provisórios até calibrar com logs reais)",
        size=12, color=THEME["muted"], selectable=True)
    marks_label = ft.Text(
        "Sem marcações: KPIs só da sessão inteira." if not state["marks"] else
        f"{state['marks_path']}  ·  {len(state['marks'])} segmento(s)",
        size=12, color=THEME["muted"], selectable=True)
    cmp_label = ft.Text(
        "Sem comparação." if not state["log_b"] else
        f"B = {os.path.basename(state['log_b'].path)}  (A = arquivo principal)",
        size=12, color=THEME["muted"], selectable=True)
    cfg_pick_btn = outline_button("Escolher JSON", ft.Icons.TUNE_ROUNDED)
    cfg_reset_btn = outline_button("Usar os das Configurações", ft.Icons.RESTART_ALT_ROUNDED)
    cfg_save_btn = outline_button("Salvar modelo", ft.Icons.SAVE_ALT_ROUNDED)
    marks_pick_btn = outline_button("Escolher CSV", ft.Icons.FLAG_ROUNDED)
    marks_clear_btn = outline_button("Limpar", ft.Icons.CLEAR_ROUNDED)
    cmp_pick_btn = outline_button("Escolher .bin", ft.Icons.COMPARE_ARROWS_ROUNDED)
    cmp_clear_btn = outline_button("Limpar", ft.Icons.CLEAR_ROUNDED)
    kpi_btn = primary_button("Calcular KPIs", ft.Icons.INSIGHTS_ROUNDED)
    kpi_export_btn = primary_button("Exportar KPIs (CSV + JSON)", ft.Icons.SAVE_ROUNDED)
    kpi_segment = styled_dropdown("Segmento", [(kpi.SESSION, "Sessão inteira")], kpi.SESSION,
                                  width=260)
    kpi_table = ft.Column(spacing=0)
    kpi_charts = ft.Column(spacing=12)
    report_html = styled_checkbox("HTML", form["report_html"])
    report_pdf = styled_checkbox("PDF", form["report_pdf"])
    report_btn = primary_button("Gerar relatório", ft.Icons.DESCRIPTION_ROUNDED)
    report_hint = ft.Text(
        "" if report.matplotlib_available() else
        "Relatório e gráficos de dispersão precisam do matplotlib "
        "(pip install -r requirements-report.txt).", size=11, color=THEME["warn"],
        visible=not report.matplotlib_available())
    kpi_warn = ft.Column(spacing=2)
    kpi_result = ft.Text("", size=12, color=THEME["muted"], selectable=True)
    kpi_card = ft.Container(
        visible=False, bgcolor=THEME["surface"], border=ft.border.all(1, THEME["border"]),
        border_radius=16, padding=20,
        content=ft.Column(spacing=12, controls=[
            ft.Row(spacing=10, controls=[kpi_segment]), kpi_table, kpi_charts, kpi_warn]))

    def option_row(label: str, info: ft.Text, *buttons):
        return ft.Column(spacing=4, controls=[
            ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=THEME["text"]),
            ft.Row(spacing=8, wrap=True, controls=list(buttons)), info])

    tab_kpis = ft.Column(spacing=14, controls=[
        section_card("3", "KPIs", ft.Column(spacing=14, controls=[
            option_row("Limiares", cfg_label, cfg_pick_btn, cfg_reset_btn, cfg_save_btn),
            option_row("Marcações de voltas/trechos (nome,inicio_s,fim_s)", marks_label,
                       marks_pick_btn, marks_clear_btn),
            option_row("Comparar com outra sessão", cmp_label, cmp_pick_btn, cmp_clear_btn),
            kpi_btn, kpi_export_btn,
            ft.Row(spacing=16, controls=[ft.Text("Relatório:", size=12, color=THEME["muted"]),
                                         report_html, report_pdf]),
            report_btn, report_hint, kpi_result,
        ])),
        kpi_card,
    ])

    # ---- aba Configurações ------------------------------------------------
    st_ = state["settings"]
    theme_group = ft.RadioGroup(value=st_.tema, content=ft.Row(spacing=18, controls=[
        ft.Radio(value=k, label=v, active_color=THEME["primary"],
                 label_style=ft.TextStyle(color=THEME["text"], size=13))
        for k, v in THEME_CHOICES.items()]))
    def_driver = styled_field("Piloto", st_.piloto)
    def_vehicle = styled_field("Veículo", st_.veiculo)
    def_venue = styled_field("Local", st_.local)
    def_mode = styled_dropdown("Modo do CSV", [("unificado", "Unificado"), ("grupos", "Por grupo")],
                               st_.csv_modo, width=170)
    def_rate = styled_dropdown("Taxa padrão", [(str(r), f"{r} Hz") for r in csv_export.UNIFIED_RATES],
                               str(st_.csv_taxa_hz), width=170)
    def_profile = styled_dropdown("Perfil de CSV", [(k, p.label) for k, p in csv_export.PROFILES.items()],
                                  st_.csv_perfil, width=170)
    out_label = ft.Text(st_.pasta_saida or "Ao lado do .bin (padrão).", size=12,
                        color=THEME["muted"], selectable=True)
    out_pick_btn = outline_button("Escolher pasta", ft.Icons.FOLDER_ROUNDED)
    out_clear_btn = outline_button("Ao lado do .bin", ft.Icons.CLEAR_ROUNDED)
    prefs_save_btn = primary_button("Salvar preferências", ft.Icons.SAVE_ROUNDED)
    thr_editor = ft.TextField(
        value=form["thr_text"], multiline=True, min_lines=12, max_lines=22,
        bgcolor=THEME["surface2"], border_color=THEME["border"],
        focused_border_color=THEME["primary"], border_radius=10, color=THEME["text"],
        text_style=ft.TextStyle(font_family="monospace", size=12), cursor_color=THEME["primary"])
    thr_save_btn = outline_button("Validar e salvar limiares", ft.Icons.CHECK_ROUNDED)
    thr_reset_btn = outline_button("Restaurar padrões", ft.Icons.RESTART_ALT_ROUNDED)
    settings_status = ft.Column(spacing=2, controls=[
        ft.Text(f"•  {w}", size=11, color=THEME["warn"], selectable=True)
        for w in state["startup_warnings"]])
    tab_settings = ft.Column(spacing=14, controls=[
        section_card("3", "Aparência", ft.Column(spacing=6, controls=[
            theme_group,
            ft.Text("A troca vale na hora. \"Sistema\" segue o tema claro/escuro do sistema "
                    "operacional.", size=11, color=THEME["muted"])])),
        section_card("4", "Valores padrão", ft.Column(spacing=12, controls=[
            ft.Text("Sessão (preenchidos ao abrir o app)", size=12, weight=ft.FontWeight.W_600,
                    color=THEME["text"]),
            ft.Row(spacing=10, controls=[def_driver, def_vehicle, def_venue]),
            ft.Text("CSV", size=12, weight=ft.FontWeight.W_600, color=THEME["text"]),
            ft.Row(spacing=10, wrap=True, controls=[def_mode, def_rate, def_profile]),
            ft.Text("Pasta de saída (.ld, CSV, KPIs, relatório e lote)", size=12,
                    weight=ft.FontWeight.W_600, color=THEME["text"]),
            ft.Row(spacing=8, wrap=True, controls=[out_pick_btn, out_clear_btn]), out_label,
            prefs_save_btn,
        ])),
        section_card("5", "Limiares dos KPIs (JSON, provisórios)", ft.Column(spacing=10, controls=[
            ft.Text(f"Arquivo: {prefs.thresholds_path()}. Só as chaves que mudam são necessárias; "
                    f"chaves com \"_\" são comentários.", size=11, color=THEME["muted"],
                    selectable=True),
            thr_editor,
            ft.Row(spacing=8, wrap=True, controls=[thr_save_btn, thr_reset_btn]),
        ])),
        settings_status,
        ft.Text(f"Preferências em {prefs.config_dir() / prefs.SETTINGS_FILE}", size=11,
                color=THEME["muted"], selectable=True),
    ])

    # ---- abas (seletor próprio: evita altura ilimitada do ft.Tabs numa página com rolagem)
    tabs = {"Converter": tab_converter, "CSV": tab_csv, "KPIs": tab_kpis,
            "Configurações": tab_settings}
    tab_buttons = {}

    def select_tab(name: str):
        state["tab"] = name
        for n, btn in tab_buttons.items():
            sel = n == name
            btn.bgcolor = THEME["primary"] if sel else THEME["surface2"]
            btn.content.color = THEME["on_primary"] if sel else THEME["muted"]
            tabs[n].visible = sel
        page.update()

    for name in tabs:
        tab_buttons[name] = ft.Container(
            ink=True, border_radius=10,
            padding=ft.padding.symmetric(horizontal=18, vertical=9),
            content=ft.Text(name, size=13, weight=ft.FontWeight.W_600),
            on_click=lambda _, n=name: select_tab(n))
    tab_bar = ft.Row(spacing=8, controls=list(tab_buttons.values()))

    # ---- lógica ----------------------------------------------------------
    def enable(btn: ft.Container, enabled: bool):
        btn.disabled = not enabled
        btn.opacity = 1.0 if enabled else 0.45

    def refresh_buttons():
        busy, loaded = state["busy"], state["log"] is not None
        enable(convert_btn, loaded and not busy)
        enable(csv_btn, loaded and not busy)
        enable(batch_btn, state["batch_dir"] is not None and not busy)
        enable(kpi_btn, loaded and not busy)
        enable(kpi_export_btn, state.get("kpis") is not None and not busy)
        enable(report_btn, state.get("kpis") is not None and not busy
               and report.matplotlib_available())
        for b in (cfg_pick_btn, cfg_reset_btn, cfg_save_btn, marks_pick_btn, marks_clear_btn,
                  cmp_pick_btn, cmp_clear_btn, out_pick_btn, out_clear_btn, thr_save_btn,
                  thr_reset_btn, theme_group):
            b.disabled = busy
        enable(prefs_save_btn, not busy)
        drop_zone.disabled = busy
        batch_pick_btn.disabled = busy

    def set_busy(busy: bool):
        state["busy"] = busy
        bar.visible = busy
        refresh_buttons()
        page.update()

    def notify(msg, ok=True):
        bg = THEME["ok"] if ok else THEME["err"]
        page.snack_bar = ft.SnackBar(ft.Text(msg, color=on_color(bg)), bgcolor=bg)
        page.snack_bar.open = True
        page.update()

    def show_error(msg: str):
        error_text.value = msg
        error_card.visible = True

    def show_quality(report: dict):
        lines = quality_lines(report)
        color = THEME["ok"] if report["ok"] else THEME["warn"]
        quality_icon.name = (ft.Icons.VERIFIED_ROUNDED if report["ok"]
                             else ft.Icons.WARNING_AMBER_ROUNDED)
        quality_icon.color = color
        quality_card.border = ft.border.all(1, color)
        quality_title.value = ("Qualidade do log: nenhum problema encontrado" if report["ok"]
                               else f"Qualidade do log: {len(report['avisos'])} aviso(s)")
        quality_list.controls = [ft.Text(f"•  {a}", size=12, color=THEME["text"], selectable=True)
                                 for a in lines]
        quality_rates.value = "Taxa real / nominal  ·  " + rates_summary(report)
        quality_imu.value = report["imu_unidade"]["mensagem"]
        quality_card.visible = True

    def confirm_overwrite(paths: list) -> bool:
        """Pergunta (da thread de trabalho) se pode sobrescrever; bloqueia até a resposta."""
        answer = {"ok": False}
        done = threading.Event()

        def close(ok: bool):
            answer["ok"] = ok
            page.close(dialog)
            done.set()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Sobrescrever arquivos?"),
            content=ft.Text("Já existe(m) na pasta de destino:\n"
                            + "\n".join(os.path.basename(p) for p in paths)),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: close(False)),
                     ft.FilledButton("Sobrescrever", on_click=lambda _: close(True))],
        )
        page.open(dialog)
        done.wait()
        return answer["ok"]

    def run_task(task):
        """Executa `task` numa thread; erros vão para o card de erro (a GUI nunca trava)."""
        error_card.visible = False
        set_busy(True)

        def worker():
            try:
                task()
            except Exception as ex:
                show_error(f"Falha: {ex}")
                stage.value = "Erro."
                pct.value = ""
                notify("Falha na operação.", ok=False)
            finally:
                set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    def cancelled():
        stage.value = "Operação cancelada: nenhum arquivo foi alterado."
        pct.value = ""

    # carregar o .bin assim que for escolhido (uma vez; as abas reutilizam)
    def load_task():
        path = state["path"]
        state["log"] = None
        clear_kpis()
        label = "Lendo, decodificando e verificando o log..."
        show(0.0, label)
        try:
            log = pipeline.load_log(path, lambda p: show(p, label))
        except Exception:
            drop_zone.border = ft.border.all(1.5, THEME["err"])
            raise
        state["log"] = log
        show_quality(log.quality)
        n = len(log.segments)
        extra = f"  ·  {n} segmentos" if n > 1 else ""
        show(1.0, f"Log carregado: {log.result.total_packets:,} pacotes{extra}.".replace(",", "."))

    def on_pick(e: ft.FilePickerResultEvent):
        if not e.files:
            return
        path = e.files[0].path
        state["path"] = path
        drop_icon.name = ft.Icons.DESCRIPTION_ROUNDED
        drop_icon.color = THEME["ok"]
        drop_title.value = os.path.basename(path)
        try:
            size = fmt_size(os.path.getsize(path))
        except OSError:
            size = "tamanho desconhecido"
        drop_hint.value = f"{size}  ·  clique para trocar o arquivo"
        drop_zone.border = ft.border.all(1.5, THEME["ok"])
        result_card.visible = False
        csv_result_card.visible = False
        quality_card.visible = False
        run_task(load_task)

    picker = ft.FilePicker(on_result=on_pick)
    page.overlay.append(picker)
    drop_zone.on_click = lambda _: picker.pick_files(
        allowed_extensions=["bin"], dialog_title="Selecione o log .bin")

    def convert_task():
        log = state["log"]
        t_start = time.time()
        outs = pipeline.ld_paths(log, out_dir())
        existing = [o for o in outs if os.path.exists(o)]
        if existing and not confirm_overwrite(existing):
            return cancelled()
        label = "Reamostrando canais e gerando o .ld..."
        show(0.0, label)
        pipeline.write_ld_outputs(log, session_meta(), out_dir(), lambda p: show(p, label),
                                  include_derived=include_derived.value, config=state["config"])

        segments = log.segments
        state["out"] = outs[0]
        v_packets.value = f"{sum(s.total_packets for s in segments):,}".replace(",", ".")
        v_channels.value = str(len({ch.name for seg in segments for g in seg.groups.values()
                                    for ch in g.definition.channels}))
        v_duration.value = fmt_duration(sum(log_duration_s(s) for s in segments))
        v_time.value = f"{time.time() - t_start:.1f} s"
        out_path.value = "\n".join(outs)
        if len(outs) > 1:
            out_path.value = f"{len(outs)} segmentos (saltos/resets de timestamp):\n" + out_path.value
        warn_text.value = "Avisos do parser: " + " | ".join(log.result.warnings)
        warn_text.visible = bool(log.result.warnings)
        result_card.visible = True
        show(1.0, "Concluído.")
        notify("Conversão concluída!", ok=True)

    def csv_task():
        log, opts = state["log"], csv_options()
        outs = pipeline.csv_paths(log, opts, out_dir())
        existing = [o for o in outs if os.path.exists(o)]
        if existing and not confirm_overwrite(existing):
            return cancelled()
        label = "Gerando CSV..."
        show(0.0, label)
        written = pipeline.write_csv_outputs(log, session_meta(), opts, out_dir(),
                                             progress_cb=lambda p: show(p, label))
        state["out"] = written[0]
        csv_result.value = "\n".join(written)
        csv_result_card.visible = True
        show(1.0, "CSV exportado.")
        notify("CSV exportado!", ok=True)

    def batch_task():
        if not (batch_ld.value or batch_csv.value):
            raise ValueError("Escolha ao menos uma saída (.ld ou CSV).")
        batch_list.controls = []
        batch_summary_text.value = ""

        def prog(i, n, f):
            show(i / n if n else 1.0,
                 f"Lote: {i + 1}/{n}  ·  {os.path.basename(f)}" if f else "Lote concluído.")

        items = pipeline.convert_folder(
            state["batch_dir"], session_meta(), ld=batch_ld.value, csv=batch_csv.value,
            csv_options=csv_options(), out_dir=out_dir(), overwrite=batch_overwrite.value,
            progress_cb=prog,
            include_derived=include_derived.value, config=state["config"])
        colors = {"ok": THEME["ok"], "pulado": THEME["warn"], "erro": THEME["err"]}
        batch_summary_text.value = pipeline.batch_summary(items)
        batch_list.controls = [ft.Text(line, size=12, color=colors[it.status], selectable=True)
                               for it, line in zip(items, batch_lines(items))]
        if items:
            state["out"] = items[0].source
        show(1.0, "Lote concluído.")
        notify(batch_summary_text.value, ok=all(it.status != "erro" for it in items))

    def on_dir(e: ft.FilePickerResultEvent):
        if not e.path:
            return
        state["batch_dir"] = e.path
        n = len(pipeline.list_bins(e.path))
        batch_folder.value = f"{e.path}  ·  {n} arquivo(s) .bin"
        refresh_buttons()
        page.update()

    dir_picker = ft.FilePicker(on_result=on_dir)
    page.overlay.append(dir_picker)
    batch_pick_btn.on_click = lambda _: dir_picker.get_directory_path(
        dialog_title="Pasta com os logs .bin")

    def guarded(task, btn):
        def handler(_):
            if not btn.disabled and not state["busy"]:
                run_task(task)
        return handler

    # ---- KPIs ------------------------------------------------------------
    def clear_kpis():
        state["kpis"] = state["kpis_b"] = None
        kpi_card.visible = False
        kpi_result.value = ""

    def render_kpis():
        sessions = state["kpis"]
        if not sessions:
            return
        res = sessions[0][1]
        segs = [kpi.SESSION] + [m.nome for m in (state["marks"] or [])]
        kpi_segment.options = [ft.dropdown.Option(key=s, text="Sessão inteira" if s == kpi.SESSION
                                                  else s) for s in segs]
        if kpi_segment.value not in segs:
            kpi_segment.value = kpi.SESSION
        rows = kpi_table_rows(sessions, state["kpis_b"], kpi_segment.value)
        cmp = state["kpis_b"] is not None
        heads = ["KPI", "A" if cmp else "Valor", "Unidade"] + (["B", "Δ (B − A)", "Δ %"] if cmp else [])
        kpi_table.controls = [ft.DataTable(
            heading_row_height=34, data_row_min_height=28, data_row_max_height=32,
            column_spacing=18,
            heading_text_style=ft.TextStyle(color=THEME["muted"], size=12,
                                            weight=ft.FontWeight.W_600),
            data_text_style=ft.TextStyle(color=THEME["text"], size=12),
            columns=[ft.DataColumn(ft.Text(h), numeric=i not in (0, 2))
                     for i, h in enumerate(heads)],
            rows=[ft.DataRow(cells=[ft.DataCell(ft.Text(c, selectable=True)) for c in r])
                  for r in rows])]
        avisos = res.avisos + (state["kpis_b"][0][1].avisos if cmp else [])
        kpi_warn.controls = [ft.Text(f"•  {a}", size=11, color=THEME["warn"], selectable=True)
                             for a in avisos[:40]]
        render_charts()
        kpi_card.visible = True

    def render_charts():
        seg = kpi_segment.value
        res_a = state["kpis"][0][1]
        res_b = state["kpis_b"][0][1] if state["kpis_b"] else None
        la = os.path.splitext(os.path.basename(state["log"].path))[0]
        lb = os.path.splitext(os.path.basename(state["log_b"].path))[0] if res_b else "B"
        controls = []
        brake_unit = next(
            (k.unidade for k in res_a.kpis if k.nome == "Frenagem_Pico_Max"), "")
        for kind, title, unit in (("hist_rpm", "Tempo por faixa de RPM", "%"),
                                  ("hist_acelerador", "Tempo por faixa de acelerador", "%"),
                                  ("tempo_marcha", "Tempo por marcha (N = neutro)", "s"),
                                  ("frenagens", f"Pico de pressão por frenagem ({la})", brake_unit)):
            # frenagens: só A (eventos de sessões diferentes não se pareiam)
            series = chart_series(kind, res_a, res_b if kind != "frenagens" else None, seg)
            if series:
                controls.append(bar_chart(title, unit, series[0], series[1], series[2], la, lb))
        if report.matplotlib_available():
            style = dict(report.STYLES[THEME["chart"]], bg=THEME["surface2"], grid=THEME["border"],
                         text=THEME["text"], muted=THEME["muted"])
            for c in report.build_charts(res_a, res_b, la, lb, seg, style=style,
                                         only=("gg", "oleo")):
                controls.append(ft.Container(
                    bgcolor=THEME["surface2"], border_radius=12, padding=8,
                    content=ft.Image(src_base64=report.figure_png_b64(c.figure),
                                     fit=ft.ImageFit.CONTAIN)))
        kpi_charts.controls = controls

    kpi_segment.on_change = lambda _: (render_kpis(), page.update())

    def kpi_task():
        label = "Calculando KPIs..."
        show(0.2, label)
        state["kpis"] = pipeline.compute_log_kpis(state["log"], state["config"], state["marks"])
        state["kpis_b"] = None
        if state["log_b"] is not None:
            show(0.6, label)
            state["kpis_b"] = pipeline.compute_log_kpis(state["log_b"], state["config"],
                                                        state["marks"])
        n = sum(len(r.kpis) for _, r in state["kpis"])
        kpi_result.value = f"{n} KPIs calculados" + (
            f" ({len(state['kpis'])} segmentos de log)." if len(state["kpis"]) > 1 else ".")
        render_kpis()
        show(1.0, "KPIs calculados.")

    def kpi_export_task():
        log = state["log"]
        outs = pipeline.kpi_paths(log, out_dir())
        if state["kpis_b"] is not None:
            outs.append(pipeline.comparison_path(log, state["log_b"], out_dir()))
        existing = [o for o in outs if os.path.exists(o)]
        if existing and not confirm_overwrite(existing):
            return cancelled()
        written = pipeline.write_kpi_outputs(log, session_meta(), state["kpis"], state["config"],
                                             out_dir(), csv_profile.value)
        if state["kpis_b"] is not None:
            written.append(pipeline.write_comparison(log, state["kpis"], state["log_b"],
                                                     state["kpis_b"], out_dir(), csv_profile.value))
        state["out"] = written[0]
        kpi_result.value = "Gravado:\n" + "\n".join(written)
        show(1.0, "KPIs exportados.")
        notify("KPIs exportados!", ok=True)

    def on_cfg(e: ft.FilePickerResultEvent):
        if not e.files:
            return
        path = e.files[0].path
        try:
            state["config"] = kpi.load_config(path)
        except Exception as ex:
            show_error(f"Limiares não carregados: {ex}")
            page.update()
            return
        state["config_path"] = path
        cfg_label.value = f"{path}  (provisórios até calibrar com logs reais)"
        error_card.visible = False
        clear_kpis()
        refresh_buttons()
        page.update()

    def on_cfg_reset(_):
        cfg, warning = prefs.load_thresholds()
        state["config"], state["config_path"] = cfg, None
        cfg_label.value = settings_cfg_text if not warning else warning
        clear_kpis()
        refresh_buttons()
        page.update()

    def on_cfg_save(e: ft.FilePickerResultEvent):
        if not e.path:
            return
        path = e.path if e.path.lower().endswith(".json") else e.path + ".json"
        try:
            csv_export.write_json(path, json_loads(kpi.config_json(state["config"])))
            notify(f"Modelo de limiares salvo: {os.path.basename(path)}", ok=True)
        except Exception as ex:
            show_error(f"Falha ao salvar limiares: {ex}")
            page.update()

    def on_marks(e: ft.FilePickerResultEvent):
        if not e.files:
            return
        path = e.files[0].path
        try:
            state["marks"] = kpi.load_segments(path)
        except Exception as ex:
            show_error(f"Marcações não carregadas: {ex}")
            page.update()
            return
        state["marks_path"] = path
        marks_label.value = f"{path}  ·  {len(state['marks'])} segmento(s)"
        error_card.visible = False
        clear_kpis()
        refresh_buttons()
        page.update()

    def on_marks_clear(_):
        state["marks"] = None
        marks_label.value = "Sem marcações: KPIs só da sessão inteira."
        clear_kpis()
        refresh_buttons()
        page.update()

    def on_cmp(e: ft.FilePickerResultEvent):
        if not e.files:
            return
        path = e.files[0].path

        def task():
            show(0.0, "Lendo a sessão de comparação...")
            state["log_b"] = pipeline.load_log(path, lambda p: show(p, "Lendo a sessão de comparação..."))
            cmp_label.value = f"B = {os.path.basename(path)}  (A = arquivo principal)"
            clear_kpis()
            show(1.0, "Sessão de comparação carregada.")

        run_task(task)

    def on_cmp_clear(_):
        state["log_b"] = None
        cmp_label.value = "Sem comparação."
        clear_kpis()
        refresh_buttons()
        page.update()

    cfg_picker = ft.FilePicker(on_result=on_cfg)
    cfg_saver = ft.FilePicker(on_result=on_cfg_save)
    marks_picker = ft.FilePicker(on_result=on_marks)
    cmp_picker = ft.FilePicker(on_result=on_cmp)
    page.overlay.extend([cfg_picker, cfg_saver, marks_picker, cmp_picker])
    cfg_pick_btn.on_click = lambda _: cfg_picker.pick_files(
        allowed_extensions=["json"], dialog_title="Arquivo de limiares (.json)")
    cfg_reset_btn.on_click = on_cfg_reset
    cfg_save_btn.on_click = lambda _: cfg_saver.save_file(
        dialog_title="Salvar limiares", file_name="limiares_kpi.json", allowed_extensions=["json"])
    marks_pick_btn.on_click = lambda _: marks_picker.pick_files(
        allowed_extensions=["csv"], dialog_title="Marcações (nome,inicio_s,fim_s)")
    marks_clear_btn.on_click = on_marks_clear
    cmp_pick_btn.on_click = lambda _: cmp_picker.pick_files(
        allowed_extensions=["bin"], dialog_title="Sessão para comparar (.bin)")
    cmp_clear_btn.on_click = on_cmp_clear
    def report_task():
        formats = tuple(f for f, cb in (("html", report_html), ("pdf", report_pdf)) if cb.value)
        if not formats:
            raise ValueError("Escolha HTML e/ou PDF.")
        log = state["log"]
        outs = pipeline.report_paths(log, formats, out_dir())
        existing = [o for o in outs if os.path.exists(o)]
        if existing and not confirm_overwrite(existing):
            return cancelled()
        show(0.3, "Gerando relatório...")
        written = pipeline.write_report(log, session_meta(), state["kpis"], state["log_b"],
                                        state["kpis_b"], formats, out_dir())
        state["out"] = written[0]
        kpi_result.value = "Relatório gravado:\n" + "\n".join(written)
        show(1.0, "Relatório gerado.")
        notify("Relatório gerado!", ok=True)

    report_btn.on_click = guarded(report_task, report_btn)
    kpi_btn.on_click = guarded(kpi_task, kpi_btn)
    kpi_export_btn.on_click = guarded(kpi_export_task, kpi_export_btn)

    convert_btn.on_click = guarded(convert_task, convert_btn)
    csv_btn.on_click = guarded(csv_task, csv_btn)
    batch_btn.on_click = guarded(batch_task, batch_btn)

    # ---- Configurações ------------------------------------------------------
    def save_form():
        """Guarda os valores dos controles no estado (antes de reconstruir a interface)."""
        form.update(
            piloto=driver.value, veiculo=vehicle.value, local=venue.value, evento=event.value,
            sessao=session.value, include_derived=include_derived.value, csv_mode=csv_mode.value,
            csv_rate=csv_rate.value, csv_profile=csv_profile.value, batch_ld=batch_ld.value,
            batch_csv=batch_csv.value, batch_overwrite=batch_overwrite.value,
            report_html=report_html.value, report_pdf=report_pdf.value, thr_text=thr_editor.value)

    state["save_form"] = save_form

    def status(msg: str, ok: bool = True):
        settings_status.controls = [ft.Text(f"•  {msg}", size=11, selectable=True,
                                            color=THEME["ok"] if ok else THEME["err"])]

    def on_theme(_):
        if state["busy"]:
            theme_group.value = state["settings"].tema
            page.update()
            return
        state["settings"].tema = theme_group.value
        err = prefs.save_settings(state["settings"])
        save_form()
        rebuild()
        if err:
            notify(err, ok=False)

    theme_group.on_change = on_theme

    def on_prefs_save(_):
        if prefs_save_btn.disabled:
            return
        s = state["settings"]
        candidate = dict(vars(s), piloto=def_driver.value or "", veiculo=def_vehicle.value or "",
                         local=def_venue.value or "", csv_modo=def_mode.value,
                         csv_taxa_hz=int(def_rate.value), csv_perfil=def_profile.value)
        new, warnings = prefs.settings_from_dict(candidate)
        if warnings:
            status(" ".join(warnings), ok=False)
            page.update()
            return
        state["settings"] = new
        err = prefs.save_settings(new)
        # aplica já: campos da sessão e opções da aba CSV
        driver.value, vehicle.value, venue.value = new.piloto, new.veiculo, new.local
        csv_mode.value, csv_rate.value, csv_profile.value = (new.csv_modo, str(new.csv_taxa_hz),
                                                             new.csv_perfil)
        csv_rate.disabled = new.csv_modo != "unificado"
        status(err or "Preferências salvas e aplicadas.", ok=err is None)
        page.update()

    prefs_save_btn.on_click = on_prefs_save

    def on_out_dir(e: ft.FilePickerResultEvent):
        if not e.path:
            return
        state["settings"].pasta_saida = e.path
        out_label.value = e.path
        err = prefs.save_settings(state["settings"])
        status(err or "Pasta de saída salva.", ok=err is None)
        page.update()

    def on_out_clear(_):
        state["settings"].pasta_saida = ""
        out_label.value = "Ao lado do .bin (padrão)."
        err = prefs.save_settings(state["settings"])
        status(err or "Saídas voltam a ficar ao lado do .bin.", ok=err is None)
        page.update()

    out_picker = ft.FilePicker(on_result=on_out_dir)
    page.overlay.append(out_picker)
    out_pick_btn.on_click = lambda _: out_picker.get_directory_path(dialog_title="Pasta de saída")
    out_clear_btn.on_click = on_out_clear

    def apply_thresholds(cfg):
        state["config"], state["config_path"] = cfg, None
        cfg_label.value = settings_cfg_text
        clear_kpis()
        refresh_buttons()

    def on_thr_save(_):
        try:
            cfg = prefs.save_thresholds_text(thr_editor.value or "")
        except ValueError as ex:
            status(str(ex), ok=False)
            page.update()
            return
        apply_thresholds(cfg)
        status("Limiares validados, salvos e em uso nos KPIs.")
        page.update()

    def on_thr_reset(_):
        cfg, text, err = prefs.reset_thresholds()
        thr_editor.value = text
        apply_thresholds(cfg)
        status(err or "Limiares padrão restaurados.", ok=err is None)
        page.update()

    thr_save_btn.on_click = on_thr_save
    thr_reset_btn.on_click = on_thr_reset

    # ---- montagem --------------------------------------------------------
    page.add(
        header, accent_bar,
        ft.Container(height=6), intro, ft.Container(height=6),
        section_card("1", "Arquivo de telemetria", drop_zone),
        section_card("2", "Dados da sessão", ft.Column(spacing=10, controls=[
            ft.Row(spacing=10, controls=[driver, vehicle, venue]),
            ft.Row(spacing=10, controls=[event, session]),
        ])),
        progress_box,
        quality_card, error_card,
        tab_bar,
        tab_converter, tab_csv, tab_kpis, tab_settings,
        ft.Container(height=4),
        ft.Text("Formula Route UFSCar  ·  Route Telemetry Converter",
                size=11, color=THEME["muted"], text_align=ft.TextAlign.CENTER),
    )
    # reconstrução: reapresenta o que já estava carregado
    if state["log"] is not None:
        drop_icon.name = ft.Icons.DESCRIPTION_ROUNDED
        drop_icon.color = THEME["ok"]
        drop_title.value = os.path.basename(state["log"].path)
        drop_hint.value = "Clique para trocar o arquivo"
        drop_zone.border = ft.border.all(1.5, THEME["ok"])
        show_quality(state["log"].quality)
        stage.value = "Log carregado."
    if state["kpis"]:
        render_kpis()
    refresh_buttons()
    select_tab(state["tab"])


if __name__ == "__main__":
    ft.app(target=main, assets_dir=ASSETS_DIR if os.path.isdir(ASSETS_DIR) else None)

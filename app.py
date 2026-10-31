"""Route Telemetry Converter - GUI (Flet, API clássica 0.25-0.27).

Executar:  python app.py

Identidade visual: ajuste a paleta no bloco THEME logo abaixo. Para exibir o
logo da equipe, coloque o arquivo em  assets/logo.png  (fundo transparente).
"""

import os
import subprocess
import sys
import threading
import time

import flet as ft

import csv_export
import pipeline
from parser import unwrap_timestamps

# ----------------------------------------------------------------------------
# PALETA (valores provisórios: troque pelos hex oficiais da equipe)
# ----------------------------------------------------------------------------
THEME = {
    "bg":        "#0C0E11",   # fundo da janela
    "surface":   "#151920",   # cartões
    "surface2":  "#1C212A",   # campos / blocos internos
    "border":    "#272D38",
    "primary":   "#E4002B",   # cor de destaque da equipe
    "primary_d": "#9E001E",   # destaque escuro (gradiente/hover)
    "text":      "#F2F4F7",
    "muted":     "#8B95A5",
    "ok":        "#34D17E",
    "warn":      "#F5A524",
    "err":       "#FF5C5C",
}
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
                                            color="#FFFFFF"),
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
            controls=[ft.Icon(icon, color="#FFFFFF"),
                      ft.Text(label, size=15, weight=ft.FontWeight.BOLD, color="#FFFFFF")]),
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
def main(page: ft.Page):
    page.title = "Route Telemetry Converter"
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(color_scheme_seed=THEME["primary"])
    page.bgcolor = THEME["bg"]
    page.window_width = 820
    page.window_height = 880
    page.window_min_width = 680
    page.window_min_height = 720
    page.padding = ft.padding.symmetric(horizontal=28, vertical=22)
    page.scroll = ft.ScrollMode.AUTO

    # estado compartilhado entre as abas: o .bin é lido uma vez só (pipeline.load_log)
    state = {"path": None, "log": None, "busy": False, "out": None, "batch_dir": None}

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
    driver = styled_field("Piloto", "Piloto Route")
    vehicle = styled_field("Veículo", "FR2026")
    venue = styled_field("Local", "UFSCar")
    event = styled_field("Evento", "")
    session = styled_field("Sessão", "")

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
    tab_converter = ft.Column(spacing=14, controls=[
        section_card("3", "Converter para MoTeC .ld", convert_btn), result_card])

    # ---- aba CSV ------------------------------------------------------------
    csv_mode = ft.RadioGroup(
        value="unificado",
        content=ft.Column(spacing=2, controls=[
            ft.Radio(value="unificado", label="Unificado: um CSV numa taxa só (interpolado)",
                     active_color=THEME["primary"],
                     label_style=ft.TextStyle(color=THEME["text"], size=13)),
            ft.Radio(value="grupos", label="Por grupo: um CSV por grupo, taxas nativas, sem interpolação",
                     active_color=THEME["primary"],
                     label_style=ft.TextStyle(color=THEME["text"], size=13)),
        ]))
    csv_rate = styled_dropdown("Taxa (unificado)", [(str(r), f"{r} Hz") for r in csv_export.UNIFIED_RATES],
                               str(csv_export.DEFAULT_RATE), width=170)
    csv_profile = styled_dropdown("Perfil", [(k, p.label) for k, p in csv_export.PROFILES.items()],
                                  "padrao", width=170)
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
    batch_folder = ft.Text("Nenhuma pasta escolhida.", size=12, color=THEME["muted"],
                           selectable=True)
    batch_ld = styled_checkbox(".ld (MoTeC)", True)
    batch_csv = styled_checkbox("CSV (opções acima)", False)
    batch_overwrite = styled_checkbox("Sobrescrever arquivos existentes", False)
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

    # ---- abas (seletor próprio: evita altura ilimitada do ft.Tabs numa página com rolagem)
    tabs = {"Converter": tab_converter, "CSV": tab_csv}
    tab_buttons = {}

    def select_tab(name: str):
        for n, btn in tab_buttons.items():
            sel = n == name
            btn.bgcolor = THEME["primary"] if sel else THEME["surface2"]
            btn.content.color = "#FFFFFF" if sel else THEME["muted"]
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
        drop_zone.disabled = busy
        batch_pick_btn.disabled = busy

    def set_busy(busy: bool):
        state["busy"] = busy
        bar.visible = busy
        refresh_buttons()
        page.update()

    def notify(msg, ok=True):
        page.snack_bar = ft.SnackBar(
            ft.Text(msg, color="#FFFFFF"),
            bgcolor=THEME["ok"] if ok else THEME["err"])
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
        outs = pipeline.ld_paths(log)
        existing = [o for o in outs if os.path.exists(o)]
        if existing and not confirm_overwrite(existing):
            return cancelled()
        label = "Reamostrando canais e gerando o .ld..."
        show(0.0, label)
        pipeline.write_ld_outputs(log, session_meta(), progress_cb=lambda p: show(p, label))

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
        outs = pipeline.csv_paths(log, opts)
        existing = [o for o in outs if os.path.exists(o)]
        if existing and not confirm_overwrite(existing):
            return cancelled()
        label = "Gerando CSV..."
        show(0.0, label)
        written = pipeline.write_csv_outputs(log, session_meta(), opts,
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
            csv_options=csv_options(), overwrite=batch_overwrite.value, progress_cb=prog)
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

    convert_btn.on_click = guarded(convert_task, convert_btn)
    csv_btn.on_click = guarded(csv_task, csv_btn)
    batch_btn.on_click = guarded(batch_task, batch_btn)

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
        tab_converter, tab_csv,
        ft.Container(height=4),
        ft.Text("Formula Route UFSCar  ·  Route Telemetry Converter",
                size=11, color=THEME["muted"], text_align=ft.TextAlign.CENTER),
    )
    refresh_buttons()
    select_tab("Converter")


if __name__ == "__main__":
    ft.app(target=main, assets_dir=ASSETS_DIR if os.path.isdir(ASSETS_DIR) else None)

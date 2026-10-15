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

from exporter import write_ld
from parser import parse_file

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


def log_duration_s(result) -> float:
    """Duração do log (maior intervalo entre os grupos de pacotes)."""
    spans = [(g.timestamps_ms[-1] - g.timestamps_ms[0]) / 1000.0
             for g in result.groups.values() if len(g.timestamps_ms) > 1]
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


# ----------------------------------------------------------------------------
# Aplicação
# ----------------------------------------------------------------------------
def main(page: ft.Page):
    page.title = "Route Telemetry Converter"
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(color_scheme_seed=THEME["primary"])
    page.bgcolor = THEME["bg"]
    page.window_width = 760
    page.window_height = 820
    page.window_min_width = 640
    page.window_min_height = 700
    page.padding = ft.padding.symmetric(horizontal=28, vertical=22)
    page.scroll = ft.ScrollMode.AUTO

    state = {"path": None, "out": None}

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
        "Converta o log bruto do datalogger (.bin) para o formato do MoTeC i2 Pro (.ld).",
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

    # ---- 2. sessão -------------------------------------------------------
    driver = styled_field("Piloto", "Piloto Route")
    vehicle = styled_field("Veículo", "FR2026")
    venue = styled_field("Local", "UFSCar")
    event = styled_field("Evento", "")
    session = styled_field("Sessão", "")

    # ---- 3. conversão ----------------------------------------------------
    convert_btn = ft.Container(
        ink=True, disabled=True, opacity=0.45,
        border_radius=12, padding=ft.padding.symmetric(vertical=15),
        alignment=ft.alignment.center,
        gradient=ft.LinearGradient(
            begin=ft.alignment.center_left, end=ft.alignment.center_right,
            colors=[THEME["primary"], THEME["primary_d"]]),
        content=ft.Row(
            alignment=ft.MainAxisAlignment.CENTER, spacing=10,
            controls=[ft.Icon(ft.Icons.SWAP_HORIZ_ROUNDED, color="#FFFFFF"),
                      ft.Text("Converter para .ld", size=15,
                              weight=ft.FontWeight.BOLD, color="#FFFFFF")]),
    )
    stage = ft.Text("Selecione um arquivo para começar.", size=13, color=THEME["muted"])
    pct = ft.Text("", size=12, color=THEME["muted"])
    bar = ft.ProgressBar(value=0, visible=False, color=THEME["primary"],
                         bgcolor=THEME["surface2"], bar_height=6, border_radius=3)
    progress_box = ft.Column(spacing=8, controls=[
        ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[stage, pct]),
        bar,
    ])

    # ---- resultado -------------------------------------------------------
    v_packets = ft.Text("-", size=18, weight=ft.FontWeight.BOLD, color=THEME["text"])
    v_channels = ft.Text("-", size=18, weight=ft.FontWeight.BOLD, color=THEME["text"])
    v_duration = ft.Text("-", size=18, weight=ft.FontWeight.BOLD, color=THEME["text"])
    v_time = ft.Text("-", size=18, weight=ft.FontWeight.BOLD, color=THEME["text"])
    out_path = ft.Text("", size=12, color=THEME["muted"], selectable=True)
    warn_text = ft.Text("", size=12, color=THEME["warn"], visible=False)
    open_btn = ft.OutlinedButton(
        "Abrir pasta", icon=ft.Icons.FOLDER_OPEN_ROUNDED,
        style=ft.ButtonStyle(color=THEME["text"],
                             side=ft.BorderSide(1, THEME["border"]),
                             shape=ft.RoundedRectangleBorder(radius=10)),
        on_click=lambda _: state["out"] and open_folder(state["out"]))
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
            out_path, warn_text, ft.Row(controls=[open_btn]),
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

    # ---- lógica ----------------------------------------------------------
    def set_convert_enabled(enabled: bool):
        convert_btn.disabled = not enabled
        convert_btn.opacity = 1.0 if enabled else 0.45

    def notify(msg, ok=True):
        page.snack_bar = ft.SnackBar(
            ft.Text(msg, color="#FFFFFF"),
            bgcolor=THEME["ok"] if ok else THEME["err"])
        page.snack_bar.open = True
        page.update()

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
        error_card.visible = False
        set_convert_enabled(True)
        stage.value = "Pronto para converter."
        pct.value = ""
        page.update()

    picker = ft.FilePicker(on_result=on_pick)
    page.overlay.append(picker)
    drop_zone.on_click = lambda _: picker.pick_files(
        allowed_extensions=["bin"], dialog_title="Selecione o log .bin")

    def set_busy(busy: bool):
        bar.visible = busy
        set_convert_enabled(not busy and state["path"] is not None)
        drop_zone.disabled = busy
        page.update()

    def run_conversion():
        src = state["path"]
        out = os.path.splitext(src)[0] + ".ld"
        t_start = time.time()

        def show(p: float, label: str):
            bar.value = p
            pct.value = f"{int(p * 100)}%"
            stage.value = label
            page.update()

        try:
            show(0.0, "Lendo e decodificando pacotes...")
            result = parse_file(src, lambda p: show(p * 0.7, "Lendo e decodificando pacotes..."))

            show(0.7, "Reamostrando canais e gerando o .ld...")
            write_ld(result, out, driver.value, vehicle.value, venue.value,
                     event.value, session.value,
                     progress_cb=lambda p: show(0.7 + p * 0.3, "Reamostrando canais e gerando o .ld..."))

            state["out"] = out
            n_channels = sum(len(g.definition.channels) for g in result.groups.values())
            v_packets.value = f"{result.total_packets:,}".replace(",", ".")
            v_channels.value = str(n_channels)
            v_duration.value = fmt_duration(log_duration_s(result))
            v_time.value = f"{time.time() - t_start:.1f} s"
            out_path.value = out
            if result.warnings:
                warn_text.value = "Avisos: " + " | ".join(result.warnings)
                warn_text.visible = True
            else:
                warn_text.visible = False
            result_card.visible = True
            error_card.visible = False
            show(1.0, "Concluído.")
            set_busy(False)
            notify("Conversão concluída!", ok=True)
        except Exception as ex:  # a GUI nunca deve travar
            error_text.value = f"Falha na conversão: {ex}"
            error_card.visible = True
            result_card.visible = False
            stage.value = "Erro na conversão."
            pct.value = ""
            set_busy(False)
            notify("Falha na conversão.", ok=False)

    def on_convert(_):
        if convert_btn.disabled or state["path"] is None:
            return
        result_card.visible = False
        error_card.visible = False
        set_busy(True)
        threading.Thread(target=run_conversion, daemon=True).start()

    convert_btn.on_click = on_convert

    # ---- montagem --------------------------------------------------------
    page.add(
        header, accent_bar,
        ft.Container(height=6), intro, ft.Container(height=6),
        section_card("1", "Arquivo de telemetria", drop_zone),
        section_card("2", "Dados da sessão", ft.Column(spacing=10, controls=[
            ft.Row(spacing=10, controls=[driver, vehicle, venue]),
            ft.Row(spacing=10, controls=[event, session]),
        ])),
        section_card("3", "Converter", ft.Column(spacing=14,
                                                 controls=[convert_btn, progress_box])),
        result_card, error_card,
        ft.Container(height=4),
        ft.Text("Formula Route UFSCar  ·  Route Telemetry Converter",
                size=11, color=THEME["muted"], text_align=ft.TextAlign.CENTER),
    )


if __name__ == "__main__":
    ft.app(target=main, assets_dir=ASSETS_DIR if os.path.isdir(ASSETS_DIR) else None)

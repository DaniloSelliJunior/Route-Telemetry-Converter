"""Paletas da interface (escuro e claro) e escolha do tema. Sem dependência do Flet.

Identidade da equipe: o vermelho de destaque é o mesmo nos dois temas. As
cores de texto foram escolhidas para contraste legível (WCAG >= 4,5:1) sobre os
fundos de cartão; tests/test_theme.py confere isso.
"""

THEME_CHOICES = {"sistema": "Sistema", "escuro": "Escuro", "claro": "Claro"}

PALETTES = {
    "escuro": {
        "bg":        "#0C0E11",   # fundo da janela
        "surface":   "#151920",   # cartões
        "surface2":  "#1C212A",   # campos / blocos internos
        "border":    "#2C3340",
        "primary":   "#E4002B",   # destaque da equipe
        "primary_d": "#9E001E",   # destaque escuro (gradiente)
        "accent_text": "#FF5A6E", # destaque usado como texto (contraste no fundo escuro)
        "on_primary": "#FFFFFF",
        "text":      "#F2F4F7",
        "muted":     "#9AA4B4",
        "ok":        "#34D17E",
        "warn":      "#F5A524",
        "err":       "#FF6B6B",
        "chart":     "dark",      # estilo dos gráficos (report.STYLES)
    },
    "claro": {
        "bg":        "#F3F4F6",
        "surface":   "#FFFFFF",
        "surface2":  "#F0F2F5",
        "border":    "#D4D9E1",
        "primary":   "#E4002B",
        "primary_d": "#9E001E",
        "accent_text": "#C00025",
        "on_primary": "#FFFFFF",
        "text":      "#14181F",
        "muted":     "#545E6E",
        "ok":        "#1B7A43",
        "warn":      "#8F5300",
        "err":       "#C62828",
        "chart":     "light",
    },
}


def resolve_theme(choice: str, system_dark: bool) -> str:
    """"sistema" | "escuro" | "claro" -> nome da paleta. Valor desconhecido = sistema."""
    if choice in ("escuro", "claro"):
        return choice
    return "escuro" if system_dark else "claro"


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(fg: str, bg: str) -> float:
    """Razão de contraste WCAG 2 entre duas cores hex."""
    a, b = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def on_color(bg: str, light: str = "#FFFFFF", dark: str = "#0C0E11") -> str:
    """Cor de texto (clara ou escura) com mais contraste sobre `bg` (ex.: snackbars)."""
    return light if contrast_ratio(light, bg) >= contrast_ratio(dark, bg) else dark

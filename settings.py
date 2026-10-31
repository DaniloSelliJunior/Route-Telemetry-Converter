"""Preferências do usuário e limiares dos KPIs persistidos em JSON (sem Flet).

Diretório de configuração (pathlib + variáveis de ambiente do SO):
  Windows : %APPDATA%\\RouteTelemetryConverter
  Linux   : $XDG_CONFIG_HOME/RouteTelemetryConverter (padrão ~/.config/...)
  macOS   : ~/Library/Application Support/RouteTelemetryConverter
  ROUTE_TELEMETRY_CONFIG_DIR sobrescreve (testes, instalações portáteis).

Nada aqui pode travar o app: carregar devolve os padrões com avisos quando o
arquivo falta, está corrompido ou tem valores inválidos (cada valor ruim volta
ao padrão, os bons são mantidos); salvar devolve a mensagem de erro em vez de
levantar exceção.
"""

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

import csv_export
import kpi
from exporter import atomic_path
from theme import THEME_CHOICES

APP_DIR_NAME = "RouteTelemetryConverter"
ENV_OVERRIDE = "ROUTE_TELEMETRY_CONFIG_DIR"
SETTINGS_FILE = "preferencias.json"
THRESHOLDS_FILE = "limiares_kpi.json"
FORMAT_VERSION = 1


def config_dir(env: dict = None, platform: str = None, home: Path = None) -> Path:
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    if env.get(ENV_OVERRIDE):
        return Path(env[ENV_OVERRIDE])
    if platform.startswith("win"):
        base = Path(env["APPDATA"]) if env.get("APPDATA") else home / "AppData" / "Roaming"
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else home / ".config"
    return base / APP_DIR_NAME


@dataclass
class Settings:
    tema: str = "sistema"
    piloto: str = "Piloto Route"
    veiculo: str = "FR2026"
    local: str = "UFSCar"
    csv_modo: str = "unificado"
    csv_taxa_hz: int = csv_export.DEFAULT_RATE
    csv_perfil: str = "padrao"
    pasta_saida: str = ""            # "" = ao lado do .bin


# valores aceitos por campo (None = qualquer texto)
_CHOICES = {
    "tema": set(THEME_CHOICES),
    "csv_modo": set(csv_export.MODES),
    "csv_taxa_hz": set(csv_export.UNIFIED_RATES),
    "csv_perfil": set(csv_export.PROFILES),
}
MAX_TEXT = 200


def settings_from_dict(data) -> tuple:
    """(Settings, avisos): campos inválidos ou desconhecidos voltam ao padrão com aviso."""
    s, warnings = Settings(), []
    if not isinstance(data, dict):
        return s, ["Preferências: conteúdo não é um objeto JSON; usando os padrões."]
    known = {f.name for f in fields(Settings)}
    for key, value in data.items():
        if key == "versao_formato":
            continue
        if key not in known:
            warnings.append(f"Preferências: chave desconhecida {key!r} ignorada.")
            continue
        default = getattr(s, key)
        ok = isinstance(value, type(default)) and not isinstance(value, bool)
        if ok and isinstance(value, str) and len(value) > MAX_TEXT:
            ok = False
        if ok and key in _CHOICES and value not in _CHOICES[key]:
            ok = False
        if ok:
            setattr(s, key, value)
        else:
            warnings.append(f"Preferências: valor inválido para {key!r} ({value!r}); "
                            f"usando {default!r}.")
    return s, warnings


def load_settings(path: Optional[Path] = None) -> tuple:
    """(Settings, avisos). Nunca levanta exceção."""
    path = Path(path) if path else config_dir() / SETTINGS_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Settings(), []
    except (OSError, UnicodeDecodeError) as ex:
        return Settings(), [f"Preferências não lidas ({ex}); usando os padrões."]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as ex:
        return Settings(), [f"Arquivo de preferências corrompido ({ex.msg}, linha {ex.lineno}); "
                            f"usando os padrões. Ele será substituído ao salvar."]
    s, warnings = settings_from_dict(data)
    if s.pasta_saida and not os.path.isdir(s.pasta_saida):
        warnings.append(f"Pasta de saída padrão não existe mais ({s.pasta_saida}); "
                        f"usando a pasta do .bin.")
        s.pasta_saida = ""
    return s, warnings


def save_settings(settings: Settings, path: Optional[Path] = None) -> Optional[str]:
    """Grava as preferências. Devolve None ou a mensagem de erro (nunca levanta)."""
    path = Path(path) if path else config_dir() / SETTINGS_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"versao_formato": FORMAT_VERSION, **asdict(settings)}
        with atomic_path(path) as tmp:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        return None
    except Exception as ex:
        return f"Preferências não salvas: {ex}"


# ---- limiares dos KPIs ------------------------------------------------------------

def thresholds_path() -> Path:
    return config_dir() / THRESHOLDS_FILE


def load_thresholds(path: Optional[Path] = None) -> tuple:
    """(configuração completa, aviso ou None). Sem arquivo = padrões, sem aviso."""
    path = Path(path) if path else thresholds_path()
    if not path.exists():
        return kpi.merge_config(), None
    try:
        return kpi.load_config(str(path)), None
    except Exception as ex:
        return kpi.merge_config(), f"Limiares de {path} não usados ({ex}); usando os padrões."


def thresholds_text(path: Optional[Path] = None) -> str:
    """Texto para o editor: o arquivo salvo ou o modelo com os padrões."""
    path = Path(path) if path else thresholds_path()
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return kpi.config_json()


def save_thresholds_text(text: str, path: Optional[Path] = None) -> dict:
    """Valida o JSON do editor e grava. ValueError com a mensagem se inválido ou se falhar."""
    path = Path(path) if path else thresholds_path()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as ex:
        raise ValueError(f"JSON inválido ({ex.msg}, linha {ex.lineno}, coluna {ex.colno}).") from None
    cfg = kpi.merge_config(data)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_path(path) as tmp:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text if text.endswith("\n") else text + "\n")
    except OSError as ex:
        raise ValueError(f"Limiares não salvos: {ex}") from None
    return cfg


def reset_thresholds(path: Optional[Path] = None) -> tuple:
    """Grava o modelo com os padrões. (configuração, texto, erro ou None)."""
    text = kpi.config_json()
    try:
        return save_thresholds_text(text, path), text, None
    except ValueError as ex:
        return kpi.merge_config(), text, str(ex)

"""Limiares dos KPIs e dos canais derivados.

TODOS OS VALORES SÃO PROVISÓRIOS: não há logs reais para calibrar. Os padrões
ficam aqui e podem ser sobrescritos por um JSON com a mesma estrutura (só as
chaves que mudam). Chaves começando com "_" são comentários e são ignoradas.
"""

import copy
import json

from derived import DEFAULT_DERIVED_CONFIG

DEFAULT_CONFIG = {
    "derivados": dict(DEFAULT_DERIVED_CONFIG),
    "piloto": {
        "acelerador_pleno_pct": 95.0,       # acima disso = pé embaixo
        "acelerador_zero_pct": 5.0,         # abaixo disso = sem acelerador
        "taxa_acelerador_min_pct_s": 50.0,  # taxa acima disso = aplicação do acelerador
        "freio_limiar_psi": 50.0,           # Pressao_Freio_Diant acima disso = frenagem
        "freio_duracao_min_s": 0.2,
        "freio_intervalo_uniao_s": 0.1,     # frenagens separadas por menos que isso viram uma
        "sobreposicao_acelerador_pct": 10.0,
    },
    "motor": {
        "troca_min_s": 0.15,                # marcha mantida por menos que isso não conta como troca
        "janela_rpm_troca_s": 0.3,
        "rpm_hist_faixa": 1000.0,
        "rpm_motor_ligado": 500.0,
        "movimento_kmh": 1.0,
    },
    "dinamica": {
        "canal_longitudinal": "Acel_X",
        "canal_lateral": "Acel_Y",
        "canal_yaw": "Gyro_Z",
        "suavizacao_s": 0.1,
        "percentil": 99.0,                  # "máximo" = percentil do sinal suavizado
        "g_max_referencia": None,           # None = percentil do G combinado da própria sessão
        "gg_limiar_pct": 80.0,
        "movimento_kmh": 5.0,
    },
    "confiabilidade": {
        "temp_motor_limite_c": 105.0,
        "rpm_marcha_lenta": 2000.0,         # pressão de óleo só acima disso
        "oleo_rpm_faixa": 2000.0,
        "carga_alta_tps_pct": 80.0,
        "lambda_pobre_limite": 0.95,
    },
    "consumo": {
        "duracao_min_s": 30.0,
        "r2_min": 0.5,                      # abaixo disso: sinal muito ruidoso
    },
    "arrancada": {
        "repouso_kmh": 1.0,
        "repouso_min_s": 1.0,
        "arrancada_min_kmh": 20.0,          # precisa passar disso para contar como arrancada
        "alvo_kmh": 100.0,
        "alvo_distancia_m": 75.0,
    },
}

# chaves que aceitam null
_NULLABLE = {("dinamica", "g_max_referencia")}


def _check_value(section: str, key: str, value, default):
    where = f"{section}.{key}"
    if value is None:
        if (section, key) in _NULLABLE:
            return None
        raise ValueError(f"{where}: valor nulo não permitido.")
    if isinstance(default, str):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{where}: esperado texto, recebido {value!r}.")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where}: esperado número, recebido {value!r}.")
    return float(value)


def merge_config(overrides: dict = None) -> dict:
    """Padrões + sobrescritas validadas. Erros listam todas as chaves inválidas."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if not overrides:
        return cfg
    if not isinstance(overrides, dict):
        raise ValueError("Configuração de limiares deve ser um objeto JSON.")
    errors = []
    for section, values in overrides.items():
        if section.startswith("_"):
            continue
        if section not in cfg:
            errors.append(f"seção desconhecida: {section!r}")
            continue
        if not isinstance(values, dict):
            errors.append(f"{section}: esperado objeto.")
            continue
        for key, value in values.items():
            if key.startswith("_"):
                continue
            if key not in DEFAULT_CONFIG[section]:
                errors.append(f"chave desconhecida: {section}.{key}")
                continue
            try:
                cfg[section][key] = _check_value(section, key, value,
                                                 DEFAULT_CONFIG[section][key])
            except ValueError as ex:
                errors.append(str(ex))
    if errors:
        raise ValueError("Limiares inválidos: " + "; ".join(errors))
    return cfg


def load_config(path: str) -> dict:
    """Lê um JSON de limiares e devolve a configuração completa (padrões + arquivo)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as ex:
        raise ValueError(f"Arquivo de limiares inválido ({ex.msg}, linha {ex.lineno}).") from None
    return merge_config(data)


def config_json(cfg: dict = None) -> str:
    """Texto JSON da configuração (padrão se None), com aviso de provisório."""
    data = {"_aviso": "Limiares provisórios: ainda não calibrados com logs reais."}
    data.update(copy.deepcopy(cfg or DEFAULT_CONFIG))
    return json.dumps(data, ensure_ascii=False, indent=2)

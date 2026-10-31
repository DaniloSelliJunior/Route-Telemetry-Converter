"""KPIs de sessão e de segmento (funções puras sobre os canais reamostrados).

Entrada: {nome: (t_s, valores)} na grade do .ld (mais os canais derivados),
segmentos e configuração. Saída: KpiResult com a lista de KPI (nome, valor,
unidade, segmento), avisos e eventos (frenagens, trocas, arrancadas...).

Fora de escopo (o log não tem GPS, volante, velocidade por roda nem curso
de suspensão): voltas automáticas, setores, mapa de pista, slip, gradiente de
rolagem. Voltas e trechos entram por marcações manuais (kpi.segments).
"""

from kpi.config import DEFAULT_CONFIG, config_json, load_config, merge_config  # noqa: F401
from kpi.core import compute_kpis  # noqa: F401
from kpi.model import KPI, SESSION, KpiResult, Segment  # noqa: F401
from kpi.segments import load_segments, parse_segments  # noqa: F401

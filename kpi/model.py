"""Estruturas dos KPIs: valor, segmento (trecho do log) e resultado."""

import math
from dataclasses import dataclass, field

SESSION = "sessao"          # segmento que cobre o log inteiro


@dataclass
class KPI:
    nome: str
    valor: float
    unidade: str
    segmento: str


@dataclass(frozen=True)
class Segment:
    nome: str
    inicio_s: float = 0.0
    fim_s: float = math.inf


@dataclass
class KpiResult:
    kpis: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    eventos: dict = field(default_factory=dict)   # segmento -> {tipo: dados} (relatório)

    def get(self, nome: str, segmento: str = SESSION):
        """Valor do KPI (ou None)."""
        for k in self.kpis:
            if k.nome == nome and k.segmento == segmento:
                return k.valor
        return None


@dataclass
class Ctx:
    """Contexto de um segmento: configuração, unidades, avisos e eventos."""
    seg: Segment
    cfg: dict
    units: dict
    avisos: list
    eventos: dict
    kpis: list = field(default_factory=list)
    shared: dict = field(default_factory=dict)    # valores da sessão inteira usados nos segmentos

    def add(self, nome: str, valor, unidade: str = ""):
        if valor is None:
            return
        v = float(valor)
        if math.isfinite(v):
            self.kpis.append(KPI(nome, v, unidade, self.seg.nome))

    def warn(self, msg: str):
        self.avisos.append(f"[{self.seg.nome}] {msg}")

    def missing(self, what: str, channels):
        self.warn(f"{what}: não calculado (canal ausente: {', '.join(channels)}).")

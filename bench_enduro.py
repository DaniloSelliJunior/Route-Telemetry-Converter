"""Teste de desempenho: gera um .bin sintético longo e mede a conversão.

Uso:  python bench_enduro.py [minutos]     (padrão: 30)
Cria bench_enduro.bin e bench_enduro.ld na pasta atual (apague depois).
"""

import math
import os
import struct
import sys
import time

from exporter import write_ld
from parser import parse_file


def gerar_bin(path, minutos):
    p1, p2 = struct.Struct("<BI6f"), struct.Struct("<BI4f")
    p3, p4 = struct.Struct("<BIHb4f"), struct.Struct("<BI7f")
    n = int(minutos * 60 * 200)                      # amostras a 200 Hz
    with open(path, "wb") as f:
        buf = []
        for i in range(n):
            t = i * 5
            buf.append(p1.pack(1, t, math.sin(i / 30), 0.0, 1.0, 0.1, 0.0, 0.0))
            if i % 4 == 0:                           # 50 Hz
                buf.append(p2.pack(2, t, 10.0, 0.0, 30.0, 25.0))
                buf.append(p3.pack(3, t, 8000 + i % 4000, 1 + (i // 20000) % 5,
                                   55.0, 90.0, 20.0, 60.0))
            if i % 20 == 0:                          # 10 Hz
                buf.append(p4.pack(4, t, 90, 35, 4.2, 3.9, 13.1, 0.98, 5.5))
            if len(buf) > 50000:
                f.write(b"".join(buf)); buf.clear()
        f.write(b"".join(buf))


def pico_memoria_mb():
    try:
        import resource                              # Linux/macOS
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return kb / 1024 if sys.platform != "darwin" else kb / 1024 / 1024
    except ImportError:
        try:
            import psutil                            # Windows: pip install psutil
            return psutil.Process().memory_info().peak_wset / 1e6
        except Exception:
            return None


if __name__ == "__main__":
    minutos = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    src, dst = "bench_enduro.bin", "bench_enduro.ld"

    t = time.time(); gerar_bin(src, minutos)
    print(f"{minutos:g} min -> .bin de {os.path.getsize(src)/1e6:.1f} MB (gerado em {time.time()-t:.1f} s)")

    t = time.time(); r = parse_file(src)
    t_parse = time.time() - t
    t = time.time(); write_ld(r, dst)
    t_ld = time.time() - t

    print(f"leitura/decodificação: {t_parse:.1f} s  ({r.total_packets} pacotes)")
    print(f"reamostragem + .ld:    {t_ld:.1f} s  ({os.path.getsize(dst)/1e6:.1f} MB)")
    print(f"TOTAL da conversão:    {t_parse + t_ld:.1f} s")
    mem = pico_memoria_mb()
    if mem:
        print(f"pico de memória:       {mem:.0f} MB (inclui a geração do teste)")
    if r.warnings:
        print("avisos:", r.warnings)

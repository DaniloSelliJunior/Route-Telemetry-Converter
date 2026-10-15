"""Teste sintético do parser (não depende de flet nem da lib .ld).

Rodar:  python test_parser.py
"""

import math
import os
import struct
import tempfile

from exporter import write_csv
from parser import parse_bin, resample_uniform


def make_bin(n=1000, hz=200):
    buf = bytearray()
    for i in range(n):
        ts = i * (1000 // hz)
        vals = [math.sin(i / 20), math.cos(i / 20), 1.0, 0.1 * i, -0.1 * i, 5.0]
        buf += struct.pack("<BI6f", 0x01, ts, *vals)
    return bytes(buf)


def main():
    data = make_bin()
    assert len(data) == 1000 * 29, "pacote 0x01 deve ter 29 bytes"

    r = parse_bin(data)
    g = r.groups[0x01]
    assert r.total_packets == 1000 and not r.warnings
    assert g.timestamps_ms[:3] == [0, 5, 10]
    assert abs(g.columns[3][10] - 1.0) < 1e-5

    # pacote truncado + ID desconhecido
    r2 = parse_bin(data + b"\x01\x00\x00")
    assert r2.total_packets == 1000 and len(r2.warnings) == 1
    r3 = parse_bin(data[:29] + b"\xFE" + data[29:])
    assert r3.total_packets == 1 and "0xFE" in r3.warnings[0]

    # reamostragem: dado a 100 Hz de uma rampa vira 200 Hz com interpolação
    out = resample_uniform([0, 10, 20], [0.0, 1.0, 2.0], 200.0, 0)
    assert len(out) == 5 and abs(out[1] - 0.5) < 1e-9

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.csv")
        write_csv(r, p)
        assert os.path.getsize(p) > 0

        # .ld: escreve e relê com o ldparser (requer numpy)
        from exporter import write_ld
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "motec_lib"))
        from ldparser.ldparser import read_ldfile
        ld = os.path.join(d, "x.ld")
        write_ld(r, ld, driver="Piloto", vehicle="FR2026", venue="UFSCar")
        head, chans = read_ldfile(ld)
        assert head.driver == "Piloto" and len(chans) == 6
        assert all(c.freq == 200 and len(c.data) == 1000 for c in chans)
    print("OK: parser, reamostragem, CSV e .ld (escrita + releitura) funcionando.")


if __name__ == "__main__":
    main()

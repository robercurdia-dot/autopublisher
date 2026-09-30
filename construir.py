#!/usr/bin/env python3
"""Mete los vídeos dentro de la página.

autopublisher.src.html es el fuente editable, con huecos @@V:nombre@@.
autopublisher.html es lo que se publica, con los vídeos incrustados como data: URI.

Se incrustan y no se sirven desde el almacén de assets porque dentro del artifact
la petición de vídeo se bloquea sin lanzar error. Los .mp4 de web/ van recodificados
a 440 px con -movflags +faststart: sin el moov al principio el navegador no puede
empezar a reproducir hasta tener el archivo entero.
"""
import base64
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
FUENTE = RAIZ / "autopublisher.src.html"
SALIDA = RAIZ / "autopublisher.html"
VIDEOS = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "assets" / "web"

s = FUENTE.read_text()
faltan = []

def mete(m):
    nombre = m.group(1)
    f = VIDEOS / (nombre + ".mp4")
    if not f.exists():
        faltan.append(str(f)); return m.group(0)
    b64 = base64.b64encode(f.read_bytes()).decode()
    print("  %-18s %6d KB -> %6d KB" % (nombre, f.stat().st_size // 1024, len(b64) // 1024))
    return "data:video/mp4;base64," + b64

print("incrustando:")
s = re.sub(r"@@V:([a-z0-9_]+)@@", mete, s)
if faltan:
    sys.exit("Faltan: " + ", ".join(faltan))

SALIDA.write_text(s)
kb = SALIDA.stat().st_size // 1024
print("\n%s · %d KB (tope de la página: 16384 KB)" % (SALIDA.name, kb))
if kb > 15000:
    sys.exit("Demasiado grande.")

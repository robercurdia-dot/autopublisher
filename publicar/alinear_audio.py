#!/usr/bin/env python3
"""Recorta una pista para que sus golpes caigan en los cortes del clip.

Con el sonido de otra cuenta el problema era imposible: había que forzar al
generador a cortar donde sonaba la música. Con una pista propia es al revés y es
fácil — se mueve la música, no el vídeo. Esto busca el desplazamiento que más
cortes hace coincidir con un golpe y recorta ahí, a la duración exacta del clip.

Uso:
    python3 alinear_audio.py clip.mp4 musica/pista.mp3 salida.m4a
    python3 alinear_audio.py clip.mp4 pista.mp3 salida.m4a --tolerancia 0.15 --json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "ingesta"))

from analizar_referencia import cortes, datos_video          # noqa: E402
from perfil_musical import SALTO, SR, a_mono, espectro, flujo  # noqa: E402

REJILLA = 0.01          # resolución de la búsqueda de desplazamiento, en segundos
ENTRADA = 0.12          # fundido de entrada
SALIDA_F = 0.25         # fundido de salida


def golpes_pista(ruta):
    """Instantes donde la música pega, con su fuerza."""
    f = flujo(espectro(a_mono(ruta)))
    t = np.arange(len(f)) * SALTO / SR
    umbral = f.mean() + f.std()
    pico = (f > umbral) & (f >= np.roll(f, 1)) & (f >= np.roll(f, -1))
    return t[pico], f[pico]


def curva(t, fuerza, dur, tolerancia):
    """Golpes llevados a una rejilla fija y ensanchados a la tolerancia: así
    'hay un golpe cerca' se convierte en una simple consulta por índice."""
    n = int(dur / REJILLA) + 1
    c = np.zeros(n)
    idx = np.clip((t / REJILLA).astype(int), 0, n - 1)
    np.maximum.at(c, idx, fuerza)
    radio = max(1, int(tolerancia / REJILLA))
    ancha = c.copy()
    for d in range(1, radio + 1):
        caida = 1 - d / (radio + 1)          # cuanto más lejos del corte, menos cuenta
        ancha = np.maximum(ancha, np.roll(c, d) * caida)
        ancha = np.maximum(ancha, np.roll(c, -d) * caida)
    return ancha, c


def coincidencias(cortes_s, golpes_s, tolerancia):
    if not len(cortes_s) or not len(golpes_s):
        return 0
    return int(sum(1 for c in cortes_s if np.min(np.abs(golpes_s - c)) <= tolerancia))


def alinear(clip, pista, salida, tolerancia=0.15, json_out=False):
    info = datos_video(clip)
    dur_clip = info["duracion"]
    cortes_s = np.array(cortes(clip), dtype=float)

    t, fuerza = golpes_pista(pista)
    dur_pista = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(pista)]).decode())

    if dur_pista < dur_clip:
        raise SystemExit(f"la pista dura {dur_pista:.2f} s y el clip {dur_clip:.2f} s: no llega")

    ancha, _ = curva(t, fuerza, dur_pista, tolerancia)
    margen = int((dur_pista - dur_clip) / REJILLA)
    desplazamientos = np.arange(0, margen + 1)

    if len(cortes_s):
        idx_cortes = (cortes_s / REJILLA).astype(int)
        tabla = desplazamientos[:, None] + idx_cortes[None, :]
        tabla = np.clip(tabla, 0, len(ancha) - 1)
        nota = ancha[tabla].sum(axis=1)
    else:
        nota = np.zeros(len(desplazamientos))
    # Que además empiece en golpe: un arranque a media frase se nota.
    nota = nota + ancha[np.clip(desplazamientos, 0, len(ancha) - 1)] * 0.5

    mejor = int(desplazamientos[int(np.argmax(nota))])
    desplazamiento = round(mejor * REJILLA, 2)

    antes = coincidencias(cortes_s, t, tolerancia)
    despues = coincidencias(cortes_s, t - desplazamiento, tolerancia)

    fin = max(0.0, dur_clip - SALIDA_F)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{desplazamiento}", "-i", str(pista),
         "-t", f"{dur_clip}",
         "-af", f"afade=t=in:st=0:d={ENTRADA},afade=t=out:st={fin:.3f}:d={SALIDA_F}",
         "-c:a", "aac", "-b:a", "192k", str(salida)], check=True)

    inf = {
        "clip": str(clip), "pista": str(pista), "salida": str(salida),
        "duracion_clip": dur_clip, "duracion_pista": round(dur_pista, 2),
        "cortes": [round(float(c), 2) for c in cortes_s],
        "golpes_pista": len(t),
        "desplazamiento_s": desplazamiento,
        "tolerancia_s": tolerancia,
        "encajan_sin_alinear": antes,
        "encajan_alineado": despues,
        "porcentaje": round(despues / len(cortes_s) * 100, 1) if len(cortes_s) else 0.0,
    }
    if json_out:
        print(json.dumps(inf, indent=2, ensure_ascii=False))
    else:
        print(f"clip {dur_clip:.2f} s · {len(cortes_s)} cortes · pista {dur_pista:.2f} s "
              f"con {len(t)} golpes")
        print(f"desplazamiento {desplazamiento:.2f} s → "
              f"{despues}/{len(cortes_s)} cortes sobre un golpe "
              f"({inf['porcentaje']:.0f} %; sin alinear eran {antes})")
        print(f"listo: {salida}")
    return inf


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip")
    ap.add_argument("pista")
    ap.add_argument("salida")
    ap.add_argument("--tolerancia", type=float, default=0.15,
                    help="qué se considera 'cae sobre el golpe', en segundos")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    alinear(Path(a.clip), Path(a.pista), Path(a.salida), a.tolerancia, a.json)


if __name__ == "__main__":
    main()

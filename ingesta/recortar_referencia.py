#!/usr/bin/env python3
"""Arma la referencia que se le pasa al modelo: solo lo útil, a la duración del audio.

Darle 54 segundos de anuncio a un generador que produce 10 es tirar la mitad de
la señal: se queda con lo que le parece. Esto monta un tramo por función —gancho,
plano principal, movimiento— y lo corta a la duración exacta de la locución, que
es la que manda cuando hay voz.

    python3 recortar_referencia.py ../assets/videos/ugc_tom_bulk.mp4 \
        --tramos "0-2.2,13.23-16.4" --audio ../assets/audio/voz.wav \
        --salida ../assets/videos/ref_montada.mp4
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def dur(ruta):
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(ruta)]).decode())


def filtro_sin_rotulo(video, pct):
    """Quita la franja superior donde vive el rótulo quemado y vuelve a encuadrar
    a la misma proporción. El material del nicho va SIEMPRE rotulado, y el modelo
    reproduce ese texto si se lo dejas ver — pasó en el run 01."""
    w, h = (int(x) for x in subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0:s=,", str(video)]).decode().strip().split(","))
    corte = int(h * pct / 100)
    alto = h - corte
    ancho = int(alto * w / h)            # se recupera la proporción recortando los lados
    ancho -= ancho % 2
    return f"crop={ancho}:{alto}:{(w - ancho) // 2}:{corte},scale={w}:{h}"


def montar(video, tramos, salida, objetivo=None, sin_rotulo=0):
    partes, total = [], 0.0
    tmp = Path(tempfile.mkdtemp())

    for i, (a, b) in enumerate(tramos):
        largo = b - a
        # El último tramo se recorta para clavar la duración: cortar por el final
        # es lo que menos duele, porque el gancho ya está dentro.
        if objetivo and total + largo > objetivo:
            largo = max(0.2, objetivo - total)
        if largo <= 0:
            break
        p = tmp / f"t{i:02d}.mp4"
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{a}", "-t", f"{largo}",
               "-i", str(video), "-an"]
        if sin_rotulo:
            cmd += ["-vf", filtro_sin_rotulo(video, sin_rotulo)]
        cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
                "-pix_fmt", "yuv420p", str(p)]
        subprocess.run(cmd, check=True)
        partes.append(p)
        total += largo

    lista = tmp / "lista.txt"
    lista.write_text("".join(f"file '{p}'\n" for p in partes))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lista), "-c", "copy", "-movflags", "+faststart",
                    str(salida)], check=True)
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--tramos", required=True,
                    help="segundos del original: «0-2.2,13.23-16.4». Uno por función.")
    ap.add_argument("--audio", help="la locución: su duración manda sobre el montaje")
    ap.add_argument("--duracion", type=float, help="duración objetivo, si no hay audio")
    ap.add_argument("--sin-rotulo", type=float, default=0, dest="sin_rotulo",
                    help="%% de alto a recortar por arriba para eliminar texto quemado")
    ap.add_argument("--salida", required=True)
    a = ap.parse_args()

    tramos = []
    for t in a.tramos.split(","):
        ini, fin = t.split("-")
        tramos.append((float(ini), float(fin)))

    objetivo = a.duracion
    if a.audio:
        objetivo = dur(a.audio)
        print(f"la locución dura {objetivo:.2f} s: el montaje se corta ahí")

    total = montar(Path(a.video), tramos, Path(a.salida), objetivo, a.sin_rotulo)
    real = dur(a.salida)
    print(f"{len(tramos)} tramos · {real:.2f} s · {a.salida}")
    if objetivo and abs(real - objetivo) > 0.3:
        print(f"AVISO: quedan {real:.2f} s frente a {objetivo:.2f} s de voz. "
              f"Añade o alarga tramos.")


if __name__ == "__main__":
    main()

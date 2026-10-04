#!/usr/bin/env python3
"""Quema el gancho sobre el clip, en montaje, nunca en el modelo.

Son dos cosas distintas y conviene no mezclarlas: la etiqueta de IA es una
declaracion -pequena, discreta, en una esquina- y la pone etiquetar_ia.py. El
gancho es lo contrario: grande, arriba, desde el primer fotograma, y existe
para que alguien que esta bajando el dedo se pare.

Lo quemamos nosotros porque al modelo se le sigue prohibiendo inventar texto:
si lo escribiera el, saldrian letras deformes y marcas alucinadas. Aqui el
texto es exacto porque lo ponemos despues.

    python3 quemar_gancho.py clip.mp4 salida.mp4 --texto "No tires esa botella"
    python3 quemar_gancho.py clip.mp4 salida.mp4 --texto "..." --hasta 3.5
    python3 quemar_gancho.py clip.mp4 salida.mp4 --texto "..." --alto 0.18 --tam 0.075

Nada de esto sabe de que producto se trata: recibe un texto y lo pinta.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# De mas a menos preferida. La negrita importa: el gancho compite con el video
# que hay debajo y una tipografia fina se pierde sobre fondo claro.
FUENTES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

# Fraccion del ancho del video. 6,2 % da una linea de ~14 caracteres en 9:16,
# que es la escala a la que lo pone el nicho que funciona.
TAM = 0.062
ALTO = 0.14       # altura del bloque, por debajo de la cabecera de Reels
MARGEN = 0.07     # margen lateral: el texto nunca llega al borde
CONTORNO = 0.14   # grosor del contorno negro, en fracciones del tamano de letra


def medidas(ruta):
    d = json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-show_entries", "format=duration",
         "-of", "json", str(ruta)]))
    s = d["streams"][0]
    return s["width"], s["height"], float(d["format"]["duration"])


def partir(texto, fuente, ancho_util):
    """Reparte el texto en lineas que quepan, sin cortar palabras."""
    medir = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = f"{actual} {palabra}".strip()
        if medir.textbbox((0, 0), prueba, font=fuente)[2] <= ancho_util or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def dibujar(texto, w, h, destino, tam_frac, margen_frac):
    ruta = next((f for f in FUENTES if Path(f).exists()), None)
    if not ruta:
        sys.exit("No encuentro una fuente utilizable.")
    tam = max(20, round(w * tam_frac))
    f = ImageFont.truetype(ruta, tam)
    util = w - 2 * round(w * margen_frac)
    lineas = partir(texto, f, util)

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    alto_linea = round(tam * 1.18)
    grosor = max(2, round(tam * CONTORNO))
    y = 0
    for linea in lineas:
        caja = d.textbbox((0, 0), linea, font=f, stroke_width=grosor)
        x = (w - (caja[2] - caja[0])) // 2 - caja[0]
        # Contorno negro en vez de caja: deja ver el vídeo y se lee sobre
        # cualquier fondo, que es como lo resuelve el nicho.
        d.text((x, y - caja[1]), linea, font=f, fill=(255, 255, 255, 255),
               stroke_width=grosor, stroke_fill=(0, 0, 0, 215))
        y += alto_linea
    img.crop((0, 0, w, min(h, y + grosor * 2))).save(destino)
    return len(lineas)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada")
    ap.add_argument("salida")
    ap.add_argument("--texto", required=True)
    ap.add_argument("--hasta", type=float,
                    help="segundo en que desaparece (por defecto, dura todo el clip)")
    ap.add_argument("--alto", type=float, default=ALTO,
                    help="posición vertical del bloque, en fracción de la altura")
    ap.add_argument("--tam", type=float, default=TAM,
                    help="tamaño de letra, en fracción del ancho")
    ap.add_argument("--margen", type=float, default=MARGEN)
    a = ap.parse_args()

    ent, sal = Path(a.entrada), Path(a.salida)
    if not ent.exists():
        sys.exit(f"No existe: {ent}")
    if not a.texto.strip():
        sys.exit("El gancho no puede ir vacío: sin rótulo no se publica "
                 "(enmienda «gancho_quemado_propio»).")

    w, h, dur = medidas(ent)
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "gancho.png"
        n = dibujar(a.texto, w, h, png, a.tam, a.margen)
        y = round(h * a.alto)
        filtro = f"[0:v][1:v]overlay=x=0:y={y}"
        if a.hasta:
            filtro += f":enable='lt(t,{a.hasta})'"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(ent), "-i", str(png),
             "-filter_complex", filtro,
             "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
             "-c:a", "copy", "-movflags", "+faststart", str(sal)], check=True)

    cuando = f"hasta el segundo {a.hasta}" if a.hasta else f"los {dur:.1f} s enteros"
    print(f"gancho quemado en {n} línea{'s' if n > 1 else ''} · {cuando}")
    print(f"listo: {sal}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Quema una etiqueta visible de IA en el vídeo.

Por qué visible y no metadato: el Reglamento europeo de IA (art. 50, en vigor desde el
2 ago 2026) obliga a quien publica contenido sintético realista a avisar de forma
"perceptible sin herramientas técnicas". La Comisión dice expresamente que el marcado
legible por máquina (C2PA, is_ai_generated) NO basta para cumplir esa obligación.

Va en una ESQUINA superior, no centrada: la franja inferior la tapa la interfaz de
Instagram (caption, usuario, botones), y el centro superior es donde baja el producto en
estos vídeos — centrada tapaba la varilla del topper, que es lo único que no se puede tapar.

Nuestro ffmpeg no trae drawtext (sin libfreetype), así que la etiqueta se dibuja
como imagen con Pillow y se superpone con el filtro overlay.

    python3 etiquetar_ia.py entrada.mp4 salida.mp4
    python3 etiquetar_ia.py entrada.mp4 salida.mp4 --texto "AI-generated content"
"""
import argparse, json, subprocess, sys, tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FUENTES = ["/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial Unicode.ttf"]

def medidas(ruta):
    d = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", str(ruta)]))
    s = d["streams"][0]
    return s["width"], s["height"]

def dibujar(texto, ancho_video, destino):
    fuente = next((f for f in FUENTES if Path(f).exists()), None)
    if not fuente:
        sys.exit("No encuentro una fuente utilizable.")
    tam = max(16, round(ancho_video * 0.030))
    f = ImageFont.truetype(fuente, tam)
    caja = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), texto, font=f)
    tw, th = caja[2] - caja[0], caja[3] - caja[1]
    px, py = round(tam * 0.62), round(tam * 0.38)
    img = Image.new("RGBA", (tw + 2 * px, th + 2 * py + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=img.height // 2, fill=(0, 0, 0, 160))
    d.text((px - caja[0], py - caja[1]), texto, font=f, fill=(255, 255, 255, 240))
    img.save(destino)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entrada"); ap.add_argument("salida")
    ap.add_argument("--texto", default="Contenido generado con IA")
    ap.add_argument("--posicion", default="arriba-der",
                    choices=["arriba-der", "arriba-izq", "arriba-centro"])
    a = ap.parse_args()
    ent, sal = Path(a.entrada), Path(a.salida)
    if not ent.exists():
        sys.exit("No existe: %s" % ent)
    w, h = medidas(ent)
    y = round(h * 0.12)          # por debajo de la cabecera de Reels
    margen = round(w * 0.04)
    x = {"arriba-der": "W-w-%d" % margen,
         "arriba-izq": str(margen),
         "arriba-centro": "(W-w)/2"}[a.posicion]
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "etiqueta.png"
        dibujar(a.texto, w, png)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ent), "-i", str(png),
            "-filter_complex", "[0:v][1:v]overlay=x=%s:y=%d" % (x, y),
            "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart", str(sal)], check=True)
    pistas = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type", "-of", "csv=p=0", str(sal)]).decode().split()
    print("etiquetado: %s · %dx%d · %s y=%d · pistas: %s" % (sal.name, w, h, a.posicion, y, ",".join(pistas)))
    if "audio" not in pistas:
        print("AVISO: la salida no tiene audio")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Baja un vídeo y lo transcribe entero, para elegir los clips leyendo.

Es el primer paso del flujo «editor»: con la transcripción completa se eligen
los momentos por lo que se dice (no por el volumen) y luego se cortan con
autoclipper.py --tramos. Así se hicieron los seis clips del Xokas del 8 oct.

    python3 transcribir_fuente.py "https://www.youtube.com/watch?v=..." [--salida DIR]

Deja en la carpeta: original.mp4, origen.json y transcripcion.json
({duracion, titulo, segmentos: [{ini, fin, t}]}).
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ.parent / "ingesta"))
from analizar_referencia import datos_video  # noqa: E402
from autoclipper import guardar_origen  # noqa: E402
from descargar import descargar, metadatos, plataforma  # noqa: E402
import subtitulos  # noqa: E402


def segmentos(video, vocabulario=None):
    """Frases con su tiempo (segmentación normal de whisper, no palabra a palabra)."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(video), "-vn",
                        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True)
        base = Path(tmp) / "t"
        cmd = [subtitulos.WHISPER, "-m", str(subtitulos.MODELO), "-f", str(wav), "-l", "es",
               "-oj", "-of", str(base), "-np"]
        if vocabulario:
            cmd += ["--prompt", vocabulario]
        subprocess.run(cmd, check=True, capture_output=True)
        datos = json.loads(Path(f"{base}.json").read_text(errors="replace"))
    out = []
    for s in datos.get("transcription", []):
        t = s["text"].strip().lstrip("-–—").strip()
        if t and not re.fullmatch(r"\[.*\]|\(.*\)", t):
            out.append({"ini": round(subtitulos._ms(s["timestamps"]["from"]), 2),
                        "fin": round(subtitulos._ms(s["timestamps"]["to"]), 2), "t": t})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--salida", default=None)
    ap.add_argument("--vocabulario", default=None)
    ap.add_argument("--cookies-de", default=None)
    a = ap.parse_args()

    meta = metadatos(a.url, a.cookies_de)
    if not a.salida:
        cuenta = re.sub(r"[^\w.-]", "", meta.get("uploader") or "video")[:30]
        a.salida = str(Path.home() / "Downloads" / "clips"
                       / f"{plataforma(a.url).lower()}_{cuenta}_{datetime.now():%Y%m%d-%H%M}")
    carpeta = Path(a.salida)
    carpeta.mkdir(parents=True, exist_ok=True)
    print(f"bajando de {plataforma(a.url)} …", flush=True)
    video = descargar(a.url, carpeta / "original.mp4", a.cookies_de)
    meta.setdefault("webpage_url", a.url)
    guardar_origen(video, meta)
    print("transcribiendo …", flush=True)
    segs = segmentos(video, a.vocabulario)
    (carpeta / "transcripcion.json").write_text(json.dumps(
        {"duracion": datos_video(video)["duracion"], "titulo": meta.get("title"),
         "canal": meta.get("uploader"), "url": a.url, "segmentos": segs},
        ensure_ascii=False, indent=1))
    print(f"{len(segs)} frases transcritas en {carpeta}/", flush=True)


if __name__ == "__main__":
    main()

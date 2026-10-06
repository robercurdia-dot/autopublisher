#!/usr/bin/env python3
"""Baja un vídeo de un enlace para poder clipearlo.

Separado del clipper a propósito: bajar falla por motivos que no tienen nada
que ver con cortar -la red, un vídeo privado, una plataforma que cambia su
web- y conviene que el error diga cuál de las dos cosas se rompió.

    python3 descargar.py "https://www.tiktok.com/@cuenta/video/123"
    python3 descargar.py "https://youtu.be/xxxx" --salida /tmp/v.mp4 --json

Instagram y algunas plataformas piden sesión. Si falla por eso, se puede pasar
--cookies-de chrome para que use la sesión del navegador.
"""

import argparse
import json
import warnings
import re
import subprocess
import sys
from pathlib import Path

PLATAFORMAS = {
    "tiktok.com": "TikTok", "instagram.com": "Instagram", "youtube.com": "YouTube",
    "youtu.be": "YouTube", "x.com": "X", "twitter.com": "X",
    "facebook.com": "Facebook", "vimeo.com": "Vimeo",
}


def plataforma(url):
    for dom, nombre in PLATAFORMAS.items():
        if dom in url:
            return nombre
    return "desconocida"


def descargar(url, destino=None, cookies_de=None):
    destino = Path(destino) if destino else Path.cwd() / "fuente.mp4"
    destino.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["yt-dlp", "--no-playlist", "--no-warnings",
           # mp4 reproducible por ffmpeg sin recodificar el contenedor
           "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b[height<=1080]/b",
           "--merge-output-format", "mp4",
           "-o", str(destino), url]
    if cookies_de:
        cmd[1:1] = ["--cookies-from-browser", cookies_de]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not destino.exists():
        err = (r.stderr or r.stdout or "").strip().splitlines()
        pista = ""
        texto = " ".join(err[-4:])
        if "login" in texto.lower() or "cookies" in texto.lower():
            pista = ("\n  Esa plataforma pide sesión. Prueba con "
                     "--cookies-de chrome para usar la del navegador.")
        raise SystemExit(f"no se pudo bajar de {plataforma(url)}:\n  "
                         + "\n  ".join(err[-4:]) + pista)
    return destino


def metadatos(url, cookies_de=None):
    """Lo que la plataforma dice del vídeo: sirve para el informe y para saber
    si lo que hemos bajado es lo que creíamos."""
    cmd = ["yt-dlp", "--no-playlist", "--no-warnings", "-J", url]
    if cookies_de:
        cmd[1:1] = ["--cookies-from-browser", cookies_de]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        d = json.loads(r.stdout) if r.returncode == 0 else None
    except json.JSONDecodeError:
        d = None
    if d is None:
        # Antes devolvía {} sin decir nada, y el informe salía sin origen.
        motivo = (r.stderr.strip().splitlines() or ["sin salida"])[-1][:300]
        warnings.warn(f"sin metadatos de {url}: {motivo}", stacklevel=2)
        return {}
    return {k: d.get(k) for k in
            ("title", "uploader", "duration", "view_count", "like_count",
             "comment_count", "upload_date", "webpage_url")}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--salida", default=None)
    ap.add_argument("--cookies-de", default=None,
                    help="navegador del que tomar la sesión: chrome, safari, firefox")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    meta = metadatos(a.url, a.cookies_de)
    ruta = descargar(a.url, a.salida, a.cookies_de)
    if a.json:
        print(json.dumps({"archivo": str(ruta), **meta}, indent=2, ensure_ascii=False))
    else:
        print(f"{plataforma(a.url)} · {meta.get('uploader') or '—'}")
        if meta.get("title"):
            print(f"  {meta['title'][:90]}")
        if meta.get("view_count"):
            print(f"  {meta['view_count']:,} reproducciones · "
                  f"{(meta.get('like_count') or 0):,} likes · "
                  f"{(meta.get('comment_count') or 0):,} comentarios")
        print(f"  {ruta}")


if __name__ == "__main__":
    main()

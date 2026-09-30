#!/usr/bin/env python3
"""Fase 0 - Validacion de la API de fal.

Reproduce en fal el clip que ya salio bien por Flashboards el 05/09/2026
(Jack Daniel's), cambiando UNA sola variable: el proveedor. Todo lo demas
-referencias, prompt, parametros- se mantiene identico, para que si el
resultado difiere sepamos que la causa es fal y no otra cosa.

REGLA DE DINERO: este script NO dispara nada sin --confirmar. Por defecto
sube los assets (gratis), imprime el payload exacto y el coste estimado, y para.

Uso:
    python3 validar_fal.py                # ensayo: sube, muestra payload y coste, no dispara
    python3 validar_fal.py --confirmar    # dispara de verdad (cuesta dinero)
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
REPO = RAIZ.parent
CACHE_SUBIDAS = RAIZ / ".upload_cache.json"

ENDPOINT = "bytedance/seedance-2.0/reference-to-video"
ENDPOINT_FAST = "bytedance/seedance-2.0/fast/reference-to-video"

# $/segundo de salida verificado en la pagina del modelo (11/09/2026).
# Con video de referencia fal multiplica la tarifa por 0,6 (es un descuento,
# no un recargo: en Flashboards el video adjunto se SUMABA a la duracion).
TARIFA_POR_SEG = {"720p": 0.3024, "1080p": 0.682}
MULT_VIDEO_REF = 0.6

# El setup exacto del 05/09: el video real como ancla principal + UNA foto de
# la botella. Nada mas. "Pocas referencias, bien elegidas: 2-3. Mas degrada."
VIDEO_REF = REPO / "assets" / "videos" / "bar_cabinet_negro_1080.mp4"
FOTO_BOTELLA = REPO / "marcas" / "fotos" / "jack_daniels.png"

PARAMS = {
    "resolution": "720p",
    "aspect_ratio": "9:16",
    "duration": "10",      # enum de strings en fal, no entero
    "generate_audio": False,  # la trampa documentada: por defecto viene True
}


def cargar_env():
    """Lee FAL_KEY de .env si no esta ya en el entorno."""
    env = RAIZ / ".env"
    if not env.exists():
        return
    for linea in env.read_text().splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


def huella(ruta):
    st = ruta.stat()
    return "%s:%d:%d" % (ruta.name, st.st_size, int(st.st_mtime))


def subir(fal_client, ruta):
    """Sube un archivo al CDN de fal y devuelve su URL publica.

    Cachea por (nombre, tamano, mtime) para que repetir el ensayo no vuelva a
    subir los mismos 1,5 MB. Subir es gratis; generar no.
    """
    cache = {}
    if CACHE_SUBIDAS.exists():
        cache = json.loads(CACHE_SUBIDAS.read_text())
    k = huella(ruta)
    if k in cache:
        print("   [cache] %s" % ruta.name)
        return cache[k]
    print("   subiendo %s (%.1f KB)..." % (ruta.name, ruta.stat().st_size / 1024))
    url = fal_client.upload_file(str(ruta))
    cache[k] = url
    CACHE_SUBIDAS.write_text(json.dumps(cache, indent=2))
    return url


def estimar(params, con_video_ref):
    res = params["resolution"]
    if res not in TARIFA_POR_SEG:
        return None
    segs = float(params["duration"])
    tarifa = TARIFA_POR_SEG[res]
    if con_video_ref:
        tarifa *= MULT_VIDEO_REF
    return segs * tarifa


def frames_qa(video, destino):
    """Congela primer / medio / ultimo frame, que es el checklist de la spec."""
    destino.mkdir(parents=True, exist_ok=True)
    try:
        dur = float(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(video)]).decode().strip())
    except Exception as e:
        print("   (no se pudieron sacar frames de QA: %s)" % e)
        return
    for etiqueta, t in (("inicio", 0.1), ("medio", dur / 2), ("final", max(0.0, dur - 0.2))):
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-ss", "%.2f" % t, "-i", str(video),
            "-frames:v", "1", str(destino / ("%s.jpg" % etiqueta))], check=False)
    print("   frames de QA en %s" % destino)


def main():
    ap = argparse.ArgumentParser(description="Fase 0 - validacion de fal")
    ap.add_argument("--confirmar", action="store_true",
                    help="dispara de verdad. Sin esto solo hace el ensayo.")
    ap.add_argument("--fast", action="store_true",
                    help="usa el tier fast (mas barato). NO para la Fase 0: "
                         "cambiaria dos variables a la vez.")
    ap.add_argument("--prompt", default="prompts/jack_daniels.txt")
    args = ap.parse_args()

    cargar_env()
    if not os.environ.get("FAL_KEY"):
        sys.exit("Falta FAL_KEY. Ponla en %s como FAL_KEY=... o exportala." % (RAIZ / ".env"))

    try:
        import fal_client
    except ImportError:
        sys.exit("Falta el cliente: pip3 install fal-client")

    for f in (VIDEO_REF, FOTO_BOTELLA):
        if not f.exists():
            sys.exit("No existe el asset: %s" % f)

    prompt = (RAIZ / args.prompt).read_text().strip()
    endpoint = ENDPOINT_FAST if args.fast else ENDPOINT

    print("\n=== Fase 0 - validacion de fal ===")
    print("Endpoint: %s\n" % endpoint)

    print("1. Subiendo referencias al CDN de fal (gratis):")
    url_video = subir(fal_client, VIDEO_REF)
    url_foto = subir(fal_client, FOTO_BOTELLA)

    payload = dict(PARAMS)
    payload["prompt"] = prompt
    payload["video_urls"] = [url_video]
    payload["image_urls"] = [url_foto]

    coste = estimar(PARAMS, con_video_ref=True)

    print("\n2. Payload:")
    resumen = dict(payload)
    resumen["prompt"] = prompt[:80] + "... (%d caracteres)" % len(prompt)
    print(json.dumps(resumen, indent=2, ensure_ascii=False))

    print("\n3. Coste estimado: %s" % ("$%.2f" % coste if coste else "desconocido"))
    print("   (%s s x $%.4f/s x %.1f por llevar video de referencia)"
          % (PARAMS["duration"], TARIFA_POR_SEG[PARAMS["resolution"]], MULT_VIDEO_REF))
    print("   El estimado es techo, no precio final. Los fallos no se cobran.")

    if not args.confirmar:
        print("\nEnsayo. No se ha disparado nada y no se ha cobrado nada.")
        print("Para disparar de verdad: python3 %s --confirmar\n" % Path(__file__).name)
        return

    print("\n4. DISPARANDO...\n")
    t0 = datetime.now()

    def log(update):
        for entrada in getattr(update, "logs", None) or []:
            print("   %s" % entrada.get("message", ""))

    try:
        resultado = fal_client.subscribe(endpoint, arguments=payload,
                                         with_logs=True, on_queue_update=log)
    except Exception as e:
        print("\nFALLO: %s" % e)
        print("Sin output no hay cargo. Revisa el mensaje antes de reintentar.")
        raise SystemExit(1)

    segs = (datetime.now() - t0).total_seconds()
    destino = RAIZ / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    destino.mkdir(parents=True, exist_ok=True)

    url_salida = resultado["video"]["url"]
    salida = destino / "video.mp4"
    print("\n5. Descargando %s" % url_salida)
    urllib.request.urlretrieve(url_salida, salida)

    # Esto es el embrion de job_events: lo que entro y lo que salio, literal.
    (destino / "metadata.json").write_text(json.dumps({
        "fase": 0,
        "endpoint": endpoint,
        "payload": payload,
        "prompt_completo": prompt,
        "resultado": resultado,
        "coste_estimado_usd": coste,
        "segundos_generacion": round(segs, 1),
        "assets_locales": {"video_ref": str(VIDEO_REF), "foto_botella": str(FOTO_BOTELLA)},
        "cuando": datetime.now().isoformat(),
    }, indent=2, ensure_ascii=False))

    frames_qa(salida, destino / "qa")

    print("\n=== LISTO en %.0f s ===" % segs)
    print("Clip:     %s" % salida)
    print("Metadata: %s" % (destino / "metadata.json"))
    print("\nApunta el CARGO REAL del panel de fal: el estimado era $%.2f." % coste)
    print("Criterio de salida de la Fase 0: calidad equivalente a Flashboards.")
    print("QA: silueta y proporcion del topper, negro mate, luz calida,")
    print("    etiqueta legible, y que NO haya salido el rotulo quemado.\n")


if __name__ == "__main__":
    main()

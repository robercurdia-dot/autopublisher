#!/usr/bin/env python3
"""Informe de una referencia — vídeo, audio y concordancia entre los dos.

Lo produce el descargador al meter un clip en la biblioteca. Sirve para dos cosas:

  1. Dejar el audio original extraído y listo, para que el publisher monte el clip
     generado con LA MISMA pista. El generador siempre devuelve vídeo mudo
     (generate_audio: false, obligatorio), así que sin este paso se publica en silencio.

  2. Medir la concordancia: dónde corta el vídeo y dónde pega el audio. Si los cortes
     caen sobre los golpes, el clip se lee montado; si no, se lee pegado.

Uso:
    python3 analizar_referencia.py ../assets/videos/lemon_art_negro.mp4
    python3 analizar_referencia.py --todos
"""

import argparse
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent
REPO = RAIZ.parent
SALIDA = REPO / "assets" / "audio"
INFORMES = REPO / "assets" / "informes"

# Umbral de detección de corte de plano. 0,30 es el habitual; por debajo
# empieza a contar el temblor de la mano como si fuera un corte.
UMBRAL_CORTE = 0.30


def ffprobe(ruta, args):
    return subprocess.check_output(
        ["ffprobe", "-v", "error"] + args + [str(ruta)]
    ).decode().strip()


def datos_video(ruta):
    crudo = ffprobe(ruta, ["-show_streams", "-show_format", "-of", "json"])
    d = json.loads(crudo)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    fps = 0.0
    if v and v.get("r_frame_rate", "0/1") != "0/0":
        num, den = v["r_frame_rate"].split("/")
        fps = round(float(num) / float(den), 2)
    return {
        "duracion": round(float(d["format"]["duration"]), 3),
        "tamano_bytes": int(d["format"]["size"]),
        "video": {"codec": v["codec_name"], "ancho": v["width"], "alto": v["height"],
                  "fps": fps, "proporcion": f'{v["width"]}:{v["height"]}'} if v else None,
        "audio": {"codec": a["codec_name"], "sample_rate": int(a.get("sample_rate", 0)),
                  "canales": int(a.get("channels", 0))} if a else None,
    }


def cortes(ruta):
    """Marcas de tiempo donde cambia el plano."""
    p = subprocess.run(
        ["ffmpeg", "-i", str(ruta), "-filter:v",
         "select='gt(scene,%s)',showinfo" % UMBRAL_CORTE, "-f", "null", "-"],
        capture_output=True, text=True)
    ts = []
    for linea in p.stderr.splitlines():
        if "pts_time:" in linea:
            try:
                ts.append(round(float(linea.split("pts_time:")[1].split()[0]), 2))
            except (IndexError, ValueError):
                pass
    return sorted(set(ts))


def envolvente(ruta_wav, n=200):
    """Energía RMS por tramos. Es la técnica ya usada en el proyecto para
    comparar audios con un número en vez de con una impresión."""
    w = wave.open(str(ruta_wav))
    d = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float)
    w.close()
    if not len(d):
        return np.zeros(n), 0.0
    bordes = np.linspace(0, len(d), n + 1).astype(int)
    rms = np.array([np.sqrt((d[a:b] ** 2).mean() + 1e-9) for a, b in zip(bordes[:-1], bordes[1:])])
    return rms / (rms.max() or 1), float(len(d))


def golpes(env, dur, cuantos=12):
    """Los picos de energía: dónde 'pega' el audio."""
    if not len(env):
        return []
    subida = np.diff(env, prepend=env[0])
    idx = np.argsort(subida)[-cuantos:]
    return sorted(round(float(i) / len(env) * dur, 2) for i in idx if subida[i] > 0.04)


def concordancia(cortes_ts, golpes_ts, tolerancia=0.35):
    """Cuántos cortes caen sobre un golpe de audio."""
    if not cortes_ts or not golpes_ts:
        return {"cortes": len(cortes_ts), "golpes": len(golpes_ts),
                "encajan": 0, "porcentaje": 0.0}
    encajan = sum(1 for c in cortes_ts
                  if min(abs(c - g) for g in golpes_ts) <= tolerancia)
    return {"cortes": len(cortes_ts), "golpes": len(golpes_ts), "encajan": encajan,
            "porcentaje": round(encajan / len(cortes_ts) * 100, 1),
            "tolerancia_s": tolerancia}


def analizar(ruta):
    ruta = Path(ruta)
    ident = ruta.stem
    SALIDA.mkdir(parents=True, exist_ok=True)
    INFORMES.mkdir(parents=True, exist_ok=True)

    info = datos_video(ruta)
    inf = {"id": ident, "archivo": str(ruta.relative_to(REPO)), **info}

    if not info["audio"]:
        inf["aviso"] = "Sin pista de audio: no hay nada que reutilizar."
        inf["cortes"] = cortes(ruta)
        return inf

    # el audio original, tal cual, para volver a montarlo sin recodificar
    original = SALIDA / (ident + ".m4a")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ruta),
                    "-vn", "-c:a", "copy", str(original)], check=True)

    # y una copia mono a 16 k solo para medir
    medir = SALIDA / ("." + ident + "_medir.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ruta),
                    "-vn", "-ac", "1", "-ar", "16000", str(medir)], check=True)

    env, _ = envolvente(medir)
    medir.unlink(missing_ok=True)

    ts_cortes = cortes(ruta)
    ts_golpes = golpes(env, info["duracion"])

    inf["audio"]["extraido"] = str(original.relative_to(REPO))
    inf["audio"]["silencio_inicial_s"] = round(
        float(np.argmax(env > 0.08)) / len(env) * info["duracion"], 2) if (env > 0.08).any() else None
    inf["audio"]["energia_media"] = round(float(env.mean()), 3)
    inf["cortes"] = ts_cortes
    inf["golpes_audio"] = ts_golpes
    inf["concordancia"] = concordancia(ts_cortes, ts_golpes)
    inf["planos"] = len(ts_cortes) + 1
    return inf


def main():
    ap = argparse.ArgumentParser(description="Informe de una referencia")
    ap.add_argument("videos", nargs="*")
    ap.add_argument("--todos", action="store_true",
                    help="analiza toda la biblioteca de assets/videos")
    args = ap.parse_args()

    rutas = [Path(v) for v in args.videos]
    if args.todos:
        rutas = sorted((REPO / "assets" / "videos").glob("*.mp4"))
    if not rutas:
        sys.exit("Dime qué vídeo, o pasa --todos.")

    todos = []
    for r in rutas:
        if not r.exists():
            print("  no existe: %s" % r); continue
        inf = analizar(r)
        todos.append(inf)
        (INFORMES / (inf["id"] + ".json")).write_text(
            json.dumps(inf, indent=2, ensure_ascii=False))

        c = inf.get("concordancia")
        print("\n%s" % inf["id"])
        print("  %.2f s · %s · %s fps" % (inf["duracion"],
              inf["video"]["proporcion"], inf["video"]["fps"]))
        if inf.get("audio"):
            print("  audio: %s %d Hz %dch -> %s" % (
                inf["audio"]["codec"], inf["audio"]["sample_rate"],
                inf["audio"]["canales"], inf["audio"]["extraido"]))
            print("  %d planos · %d golpes de audio" % (inf["planos"], len(inf["golpes_audio"])))
            print("  concordancia: %d de %d cortes sobre un golpe  (%.0f%%)" % (
                c["encajan"], c["cortes"], c["porcentaje"]))
        else:
            print("  SIN AUDIO")

    print("\nInformes en assets/informes/ · audio en assets/audio/")


if __name__ == "__main__":
    main()

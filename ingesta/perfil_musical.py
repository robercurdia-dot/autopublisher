#!/usr/bin/env python3
"""Perfil musical de un audio — con qué números se busca un sonido parecido.

El informe de referencia (analizar_referencia.py) mide DÓNDE pega el audio.
Esto mide CÓMO SUENA: tempo, brillo, timbre, densidad de golpes y tono. Con eso
el nodo de sonido puede buscar en la biblioteca de Instagram algo equivalente en
vez de reutilizar la pista de la competencia.

Sin dependencias nuevas: ffmpeg decodifica y numpy hace el resto, igual que el
resto de la cadena.

Uso:
    python3 perfil_musical.py ../assets/audio/lemon_art_negro.m4a
    python3 perfil_musical.py --todos
    python3 perfil_musical.py --todos --json
"""

import argparse
import json
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent
REPO = RAIZ.parent
AUDIO = REPO / "assets" / "audio"
INFORMES = REPO / "assets" / "informes" / "musica"

SR = 22050
VENTANA = 1024
SALTO = 256
# Bordes de las ocho bandas de timbre, en hercios. Logarítmicas porque el oído
# también lo es: de 40 a 300 se juega el cuerpo, de 3000 arriba el aire.
BANDAS = [40, 120, 300, 700, 1400, 2800, 5000, 8000, 11025]
NOTAS = ["do", "do#", "re", "re#", "mi", "fa", "fa#", "sol", "sol#", "la", "la#", "si"]


def a_mono(ruta):
    """Decodifica a WAV mono 22050 Hz. Devuelve la señal normalizada."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as t:
        tmp = Path(t.name)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(ruta),
         "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(tmp)],
        check=True)
    w = wave.open(str(tmp))
    d = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float)
    w.close()
    tmp.unlink()
    return d / 32768.0


def espectro(x):
    """Magnitudes STFT: una columna por salto de análisis."""
    if len(x) < VENTANA:
        x = np.pad(x, (0, VENTANA - len(x)))
    n = 1 + (len(x) - VENTANA) // SALTO
    marcos = np.lib.stride_tricks.as_strided(
        x, shape=(n, VENTANA), strides=(x.strides[0] * SALTO, x.strides[0])).copy()
    marcos *= np.hanning(VENTANA)
    return np.abs(np.fft.rfft(marcos, axis=1))


def flujo(mag):
    """Flujo espectral: cuánta energía NUEVA entra en cada marco. Es la curva
    donde se leen los golpes."""
    d = np.diff(mag, axis=0, prepend=mag[:1])
    f = np.maximum(d, 0).sum(axis=1)
    return f / (f.max() or 1)


def tempo(f, marcos_por_s):
    """Autocorrelación del flujo. El lag que más se repite es el pulso."""
    c = f - f.mean()
    ac = np.correlate(c, c, mode="full")[len(c) - 1:]
    lag_min = max(2, int(marcos_por_s * 60 / 180))   # 180 BPM
    lag_max = min(len(ac) - 1, int(marcos_por_s * 60 / 60))   # 60 BPM
    if lag_max <= lag_min:
        return 0.0, 0.0
    tramo = ac[lag_min:lag_max + 1]
    lag = int(np.argmax(tramo)) + lag_min
    fuerza = float(tramo.max() / (ac[0] or 1))
    return round(60 * marcos_por_s / lag, 1), round(fuerza, 3)


def perfil(ruta):
    x = a_mono(ruta)
    dur = len(x) / SR
    mag = espectro(x)
    marcos_por_s = SR / SALTO
    f = flujo(mag)
    bpm, pulso = tempo(f, marcos_por_s)

    frec = np.fft.rfftfreq(VENTANA, 1 / SR)
    energia = mag.sum(axis=1) + 1e-9
    centroide = float((mag * frec).sum(axis=1).sum() / energia.sum())

    bandas = []
    for a, b in zip(BANDAS[:-1], BANDAS[1:]):
        sel = (frec >= a) & (frec < b)
        bandas.append(float(mag[:, sel].mean()))
    bandas = np.array(bandas)
    bandas = bandas / (bandas.sum() or 1)

    umbral = f.mean() + f.std()
    picos = int(((f > umbral) & (f > np.roll(f, 1)) & (f > np.roll(f, -1))).sum())

    rms = np.sqrt((x[: (len(x) // 512) * 512].reshape(-1, 512) ** 2).mean(axis=1) + 1e-9)
    dinamica = float(rms.std() / (rms.mean() or 1))

    croma = np.zeros(12)
    vivas = frec > 55
    notas = np.round(12 * np.log2(frec[vivas] / 440.0) + 69).astype(int) % 12
    peso = mag[:, vivas].mean(axis=0)
    for n, p in zip(notas, peso):
        croma[n] += p
    croma = croma / (croma.sum() or 1)

    return {
        "archivo": str(Path(ruta).relative_to(REPO)) if str(ruta).startswith(str(REPO)) else str(ruta),
        "duracion": round(dur, 2),
        "bpm": bpm,
        "pulso": pulso,                       # 0-1: cuán marcado está el ritmo
        "brillo_hz": round(centroide, 1),
        "bandas": [round(float(v), 4) for v in bandas],
        "golpes_por_s": round(picos / dur, 2) if dur else 0.0,
        "dinamica": round(dinamica, 3),       # >0,8 hay silencios y subidas
        "croma": [round(float(v), 4) for v in croma],
        "tonica_aprox": NOTAS[int(np.argmax(croma))],
    }


def descripcion(p):
    """Traduce los números a términos de búsqueda para la app. Orientativo:
    sirve para acotar el cajón, no para nombrar el género."""
    t = []
    b = p["bpm"]
    t.append("lento" if b < 90 else "medio" if b < 120 else "rápido")
    t.append("grave" if p["brillo_hz"] < 1800 else "equilibrado" if p["brillo_hz"] < 3200 else "brillante")
    t.append("percusivo" if p["pulso"] > 0.25 else "atmosférico")
    if p["dinamica"] > 0.8:
        t.append("con subidas")
    if p["golpes_por_s"] > 3:
        t.append("denso")
    return t


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", nargs="?")
    ap.add_argument("--todos", action="store_true", help="todos los audios de assets/audio")
    ap.add_argument("--json", action="store_true", help="volcado crudo")
    a = ap.parse_args()

    rutas = sorted(AUDIO.glob("*.m4a")) if a.todos else [Path(a.audio).resolve()]
    if not rutas:
        raise SystemExit("sin audios que analizar")

    INFORMES.mkdir(parents=True, exist_ok=True)
    salida = {}
    for r in rutas:
        p = perfil(r)
        p["terminos"] = descripcion(p)
        salida[r.stem] = p
        (INFORMES / f"{r.stem}.json").write_text(json.dumps(p, indent=2, ensure_ascii=False))
        if not a.json:
            print(f"{r.stem:26} {p['bpm']:6.1f} BPM  pulso {p['pulso']:.2f}  "
                  f"brillo {p['brillo_hz']:7.0f} Hz  {p['golpes_por_s']:.1f} golpes/s  "
                  f"din {p['dinamica']:.2f}  {p['tonica_aprox']:>3}  · {', '.join(p['terminos'])}")
    if a.json:
        print(json.dumps(salida, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

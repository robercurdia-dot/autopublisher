#!/usr/bin/env python3
"""Puerta de originalidad: ¿se parece demasiado nuestro clip a su referencia?

Meta deja de recomendar a no seguidores las cuentas que publican sobre todo contenido
ajeno, y detecta duplicados automáticamente. No publica sus umbrales. Esto mide las
tres señales que sí podemos medir, contra la referencia usada:

  vídeo    dHash por fotograma con la mejor coincidencia (tolera reordenar planos)
  audio    correlación de la envolvente de energía (la técnica ya usada en el proyecto)
  caption  parecido de texto con los captions de TODA la biblioteca

Los umbrales son NUESTRA calibración, no los de Meta. Con la biblioteca real (14 sep):
  toma casi idéntica 0,964 · otro reel mismo set 0,718 · otro set 0,631 · run 01 0,598
Es un proxy grueso: un modelo de embeddings vería más parecido semántico (mismo producto,
misma acción) que un dHash. Por eso el umbral visual es conservador.

    python3 originalidad.py salida.mp4 --referencia lemon_art_negro --caption "texto"
Sale con código 1 si algo FALLA.
"""
import argparse, difflib, json, subprocess, sys, tempfile, wave
from pathlib import Path
import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
VID = REPO / "assets" / "videos"

UMBRAL = {                       # (aviso, fallo)
    "visual":  (0.70, 0.85),
    "audio":   (0.45, 0.60),
    "caption": (0.40, 0.60),
}

def duracion(r):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "default=nw=1:nk=1", str(r)]).decode())

def fotogramas(r, n=16):
    d, out = duracion(r), []
    with tempfile.TemporaryDirectory() as t:
        for i in range(n):
            f = Path(t) / ("%02d.png" % i)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "%.2f" % (d * (i + .5) / n), "-i", str(r),
                            "-frames:v", "1", "-vf", "scale=96:170", str(f)], check=True)
            out.append(Image.open(f).convert("RGB").copy())
    return out

def dhash(img, s=12):
    g = np.asarray(img.convert("L").resize((s + 1, s), Image.LANCZOS), dtype=float)
    return (g[:, 1:] > g[:, :-1]).flatten()

def visual(a, b):
    ha, hb = [dhash(x) for x in a], [dhash(x) for x in b]
    return float(np.mean([max(1 - np.mean(x != y) for y in hb) for x in ha]))

def envolvente(r, n=40):
    with tempfile.TemporaryDirectory() as t:
        w = Path(t) / "a.wav"
        p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(r), "-vn", "-ac", "1", "-ar", "16000", str(w)])
        if p.returncode or not w.exists():
            return None
        with wave.open(str(w)) as fh:
            d = np.frombuffer(fh.readframes(fh.getnframes()), dtype=np.int16).astype(float)
    if not len(d):
        return None
    b = np.linspace(0, len(d), n + 1).astype(int)
    rms = np.array([np.sqrt((d[x:y] ** 2).mean() + 1e-9) for x, y in zip(b[:-1], b[1:])])
    return rms / (rms.max() or 1)

def audio(a, b):
    ea, eb = envolvente(a), envolvente(b)
    if ea is None or eb is None:
        return None
    return float(np.corrcoef(ea, eb)[0, 1])

def veredicto(clave, valor):
    if valor is None:
        return "N/A"
    aviso, fallo = UMBRAL[clave]
    return "FALLO" if valor >= fallo else ("AVISO" if valor >= aviso else "OK")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("salida"); ap.add_argument("--referencia", required=True); ap.add_argument("--caption", default="")
    a = ap.parse_args()
    meta = json.loads((REPO / "assets" / "videos.json").read_text())
    ref = next((v for v in meta["videos"] if v["id"] == a.referencia), None)
    if not ref:
        sys.exit("No conozco la referencia '%s'" % a.referencia)
    ruta_ref = REPO / "assets" / ref["archivo"]
    sal = Path(a.salida)

    filas = []
    vis = visual(fotogramas(ruta_ref), fotogramas(sal))
    filas.append(("vídeo vs referencia", "visual", vis))
    aud = audio(ruta_ref, sal)
    filas.append(("audio vs referencia", "audio", aud))
    cap_max, cap_de = 0.0, "—"
    if a.caption:
        for v in meta["videos"]:
            c = v.get("caption_original")
            if c:
                r = difflib.SequenceMatcher(None, a.caption.lower(), c.lower()).ratio()
                if r > cap_max:
                    cap_max, cap_de = r, v["id"]
    filas.append(("caption vs biblioteca (%s)" % cap_de, "caption", cap_max if a.caption else None))

    peor = "OK"
    print("%-40s %8s  %s" % ("señal", "valor", "veredicto"))
    for nombre, clave, valor in filas:
        ver = veredicto(clave, valor)
        print("%-40s %8s  %s" % (nombre, "—" if valor is None else "%.3f" % valor, ver))
        if ver == "FALLO": peor = "FALLO"
        elif ver == "AVISO" and peor == "OK": peor = "AVISO"
    print("\nORIGINALIDAD: %s" % peor)
    sys.exit(1 if peor == "FALLO" else 0)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Corta un vídeo en las piezas que mejor funcionarían publicadas.

La diferencia con un clipper de suite no está en el corte -eso lo hace ffmpeg-
sino en POR QUÉ elige un trozo y no otro. Los clippers comerciales puntúan por
transcripción, y por eso rechazan vídeos sin habla.

Aquí cada ventana se puntúa con cuatro señales, y cada una se convierte en
PERCENTIL DENTRO DEL PROPIO VÍDEO. Ningún criterio compara contra un número de
otro sitio: así vale igual para una pieza de producto de 15 s que para un
directo de cuatro horas. (La primera versión usaba constantes medidas en el
nicho de la lámpara y, aplicada a un vídeo de Rubius, eligió la intro. Ver
clipper/errores.json.)

  audio        cuánto sube el volumen sobre lo normal del vídeo: las reacciones
               son picos, y en contenido de charla es la mejor pista que hay
  movimiento   cuánto pasa en pantalla frente al resto del vídeo
  arco         cuánto se separa el final del principio: un trozo que empieza y
               acaba igual no cuenta nada
  ritmo        densidad de cortes; pesa poco porque lo más montado suele ser la
               intro, que es envoltorio y no contenido

En fuentes de más de 3 minutos se descartan la intro y el cierre.

Si el vídeo tiene audio, cada clip se transcribe en local (whisper.cpp), sus
cortes se mueven a una pausa del habla y se le queman subtítulos animados
palabra a palabra (clipper/subtitulos.py). --sin-subtitulos lo desactiva.

    python3 autoclipper.py "https://www.youtube.com/watch?v=..."
    python3 autoclipper.py entrada.mp4 --cuantos 5 --duracion 20
    python3 autoclipper.py "https://..." --encuadre completo --json

Acepta un enlace o un fichero local. Con enlace lo baja primero (TikTok,
Instagram, YouTube, X, Facebook) y guarda las métricas que publique la
plataforma, que es el único dato de rendimiento real del vídeo de origen.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent
REPO = RAIZ.parent
sys.path.insert(0, str(REPO / "ingesta"))
sys.path.insert(0, str(RAIZ))
from analizar_referencia import cortes, datos_video  # noqa: E402
from descargar import descargar, metadatos, plataforma  # noqa: E402
import subtitulos  # noqa: E402

# Cuánto pesa cada señal. Suman 1. La duración no está: todas las ventanas
# candidatas miden lo mismo, así que como criterio sumaría una constante.
PESOS = {"audio": 0.40, "movimiento": 0.25, "arco": 0.20, "ritmo": 0.15}

# A partir de aquí una fuente se considera larga: tiene intro y cierre que no
# son contenido, y sus clips buenos duran más.
LARGO = 180.0
# Duración por defecto. La corta se midió en el nicho de producto (las piezas
# que ganan están entre 13,5 y 14,9 s). La larga es la convención de Shorts de
# charla: NO la hemos medido nosotros.
DURACION_CORTA = 14.0
DURACION_LARGA = 30.0
# Muestras por segundo para medir imagen y sonido. Más no aporta y multiplica
# el tiempo de análisis.
MUESTREO = 4
# Si las bandas laterales que tira el recorte vertical tienen al menos esta
# fracción del detalle del centro, ahí hay algo (un rótulo, información) y se
# encuadra completo en vez de recortar.
UMBRAL_LATERALES = 0.55


# ---------------------------------------------------------------- medición

def muestrear_imagen(ruta):
    """Brillo y movimiento a MUESTREO fotogramas por segundo, en una pasada.

    A 64x64 en gris: medir movimiento no necesita píxeles, necesita que los
    números cambien.
    """
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(ruta),
           "-vf", f"fps={MUESTREO},scale=64:64,format=gray", "-f", "rawvideo", "-"]
    crudo = subprocess.run(cmd, capture_output=True, check=True).stdout
    m = np.frombuffer(crudo, dtype=np.uint8)
    m = m[: (len(m) // 4096) * 4096].reshape(-1, 64, 64).astype(float)
    if len(m) < 2:
        raise SystemExit("el vídeo es demasiado corto para analizarlo")
    brillo = m.mean(axis=(1, 2))
    mov = np.abs(np.diff(m, axis=0)).mean(axis=(1, 2))
    return brillo, np.append(mov, mov[-1])


def muestrear_audio(ruta, n):
    """Volumen en dB a MUESTREO valores por segundo. None si no hay audio."""
    tasa = 8000
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(ruta), "-vn",
                        "-ac", "1", "-ar", str(tasa), "-f", "s16le", "-"],
                       capture_output=True)
    s = np.frombuffer(r.stdout, dtype=np.int16).astype(float)
    if r.returncode != 0 or len(s) < tasa:
        return None
    paso = tasa // MUESTREO
    s = s[: (len(s) // paso) * paso].reshape(-1, paso)
    db = 20 * np.log10(np.sqrt((s ** 2).mean(axis=1)) + 1.0)
    if len(db) < n:
        db = np.append(db, np.full(n - len(db), db.min()))
    return db[:n]


def percentil(valores):
    """Rango 0..1 de cada valor dentro del conjunto. Los empates comparten rango."""
    v = np.asarray(valores, dtype=float)
    if len(v) < 2 or np.ptp(v) == 0:
        return np.full(len(v), 0.5)
    orden = v.argsort().argsort().astype(float)
    for x in np.unique(v):
        idx = v == x
        orden[idx] = orden[idx].mean()
    return orden / (len(v) - 1)


# --------------------------------------------------------------- selección

def ventanas(dur, largo, margen):
    """Ventanas candidatas, fuera de la intro y del cierre."""
    paso = max(0.5, dur / 1500)
    ini, fin = margen, dur - margen
    if fin - ini < largo:
        ini, fin = 0.0, dur
    v, t = [], ini
    while t + largo <= fin + 0.01:
        v.append((round(t, 2), round(t + largo, 2)))
        t += paso
    return v or [(0.0, round(dur, 2))]


def analizar(ruta, cuantos=3, duracion=None, todas=False):
    """Puntúa todas las ventanas y devuelve las mejores. No corta nada.

    todas=True añade todas las candidatas puntuadas, para inspección y tests.
    """
    ruta = Path(ruta)
    dur = datos_video(ruta)["duracion"]
    largo_fuente = dur > LARGO
    duracion = duracion or (DURACION_LARGA if largo_fuente else DURACION_CORTA)
    duracion = min(duracion, dur)
    margen = max(30.0, dur * 0.03) if largo_fuente else 0.0

    ts = np.array(cortes(ruta))
    brillo, mov = muestrear_imagen(ruta)
    audio = muestrear_audio(ruta, len(brillo))
    base = float(np.median(audio)) if audio is not None else 0.0

    crudo = {"audio": [], "movimiento": [], "arco": [], "ritmo": []}
    vs = ventanas(dur, duracion, margen)
    for ini, fin in vs:
        i0, i1 = int(ini * MUESTREO), max(int(fin * MUESTREO), int(ini * MUESTREO) + 2)
        b = brillo[i0:i1]
        n = max(1, len(b) // 4)
        crudo["arco"].append(abs(b[-n:].mean() - b[:n].mean()))
        crudo["movimiento"].append(mov[i0:i1].mean())
        crudo["ritmo"].append(((ts >= ini) & (ts <= fin)).sum() / (fin - ini))
        if audio is not None:
            a = audio[i0:i1]
            # Lo que el tramo sube sobre lo normal del vídeo, mirando su décimo
            # más alto: capta tanto un grito como una racha de emoción.
            top = np.sort(a)[-max(1, len(a) // 10):]
            crudo["audio"].append(top.mean() - base)

    pesos = dict(PESOS)
    if audio is None:
        # Sin audio, su peso se reparte entre las otras en proporción.
        resto = sum(v for k, v in pesos.items() if k != "audio")
        pesos = {k: (0.0 if k == "audio" else v / resto) for k, v in pesos.items()}
        crudo["audio"] = [0.0] * len(vs)

    pct = {k: percentil(v) for k, v in crudo.items()}
    cands = []
    for i, (ini, fin) in enumerate(vs):
        partes = {k: round(float(pct[k][i]), 3) for k in pesos}
        total = sum(pesos[k] * pct[k][i] for k in pesos)
        cands.append({"ini": ini, "fin": fin, "puntos": round(float(total), 3), **partes,
                      "cortes_por_s": round(float(crudo["ritmo"][i]), 2)})

    r = {"duracion_fuente": dur, "planos": len(ts) + 1, "duracion_clip": duracion,
         "margen": margen, "con_audio": audio is not None, "pesos": pesos,
         "candidatas": len(cands), "clips": separados(cands, cuantos, duracion)}
    if todas:
        r["todas"] = cands
    return r


def separados(cands, cuantos, largo):
    """Las mejores ventanas sin solape y con media ventana de separación.

    Dos clips que comparten planos no son dos clips: en la primera prueba, dos
    de los tres salieron del mismo minuto de un vídeo de 25.
    """
    hueco = largo / 2
    elegidas = []
    for c in sorted(cands, key=lambda x: -x["puntos"]):
        if len(elegidas) >= cuantos:
            break
        if all(c["ini"] >= e["fin"] + hueco or c["fin"] <= e["ini"] - hueco
               for e in elegidas):
            elegidas.append(c)
    return sorted(elegidas, key=lambda x: x["ini"])


# ---------------------------------------------------------------- encuadre

def medidas(ruta):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
                        str(ruta)], capture_output=True, text=True, check=True)
    w, h = r.stdout.strip().split("x")[:2]
    return int(w), int(h)


def detalle_laterales(fotograma):
    """Detalle de las bandas que tiraría un recorte 9:16, relativo al centro.

    Detalle = energía de bordes. Un rótulo, una tabla o una cámara de cara en
    un lateral la disparan; una pared lisa no.

    Se mide por FRANJAS horizontales y se toma la peor: un rótulo es una banda
    fina, y promediar toda la altura lo diluía hasta hacerlo invisible (30
    filas de texto entre 180 daban un 17 %). La primera versión del arreglo
    tenía ese fallo y lo cazó su propio test.
    """
    g = np.asarray(fotograma, dtype=float)
    h, w = g.shape
    bordes = np.abs(np.diff(g, axis=1))[:-1, :] + np.abs(np.diff(g, axis=0))[:, :-1]
    ancho_util = int(h * 9 / 16)
    x0 = (w - ancho_util) // 2
    if x0 <= 0:
        return 0.0
    franjas = np.array_split(np.arange(bordes.shape[0]), 12)
    lados = [np.concatenate([bordes[f, :x0].ravel(), bordes[f, x0 + ancho_util:].ravel()]).mean()
             for f in franjas]
    centro = [bordes[f, x0:x0 + ancho_util].mean() for f in franjas]
    # Detalle típico del centro: la mediana, para que una zona muy cargada del
    # plano no rebaje la comparación.
    referencia = max(float(np.median(centro)), 1.0)
    return float(max(lados) / referencia)


def decidir_encuadre(ruta, ini, fin):
    """recorte o completo, mirando tres fotogramas del tramo."""
    ratios = []
    for t in np.linspace(ini + 0.5, fin - 0.5, 3):
        r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.2f}",
                            "-i", str(ruta), "-frames:v", "1", "-vf",
                            "scale=320:180,format=gray", "-f", "rawvideo", "-"],
                           capture_output=True)
        if len(r.stdout) == 320 * 180:
            ratios.append(detalle_laterales(
                np.frombuffer(r.stdout, dtype=np.uint8).reshape(180, 320)))
    ratio = max(ratios) if ratios else 0.0
    return ("completo" if ratio >= UMBRAL_LATERALES else "recorte"), round(ratio, 2)


FILTROS = {
    "recorte": "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=lanczos",
    # El plano entero, centrado, sobre una versión ampliada y desenfocada de
    # sí mismo: no se pierde nada y no quedan barras negras.
    "completo": ("split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,"
                 "crop=1080:1920,boxblur=24:2[fondo];[b]scale=1080:-2:flags=lanczos[plano];"
                 "[fondo][plano]overlay=(W-w)/2:(H-h)/2"),
}


def cortar(entrada, ini, fin, destino, encuadre=None):
    """Corte preciso. encuadre: None (original), 'recorte' o 'completo'."""
    vf = ["-vf", FILTROS[encuadre]] if encuadre else []
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{max(0, ini - 2):.2f}",
         "-i", str(entrada), "-ss", f"{min(ini, 2):.2f}", "-t", f"{fin - ini:.2f}", *vf,
         "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-movflags", "+faststart", str(destino)], check=True)


# -------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada", help="enlace al vídeo o ruta a un fichero local")
    ap.add_argument("--cuantos", type=int, default=3)
    ap.add_argument("--duracion", type=float, default=None,
                    help=f"segundos por clip (por defecto {DURACION_CORTA:.0f} en fuentes "
                         f"cortas y {DURACION_LARGA:.0f} en largas)")
    ap.add_argument("--salida", default=None, help="carpeta donde dejar los clips")
    ap.add_argument("--solo-analizar", action="store_true", help="puntúa y no corta")
    ap.add_argument("--encuadre", choices=("auto", "recorte", "completo", "original"),
                    default="auto",
                    help="auto: vertical si la fuente es horizontal, recortando salvo que "
                         "los laterales tengan información")
    ap.add_argument("--sin-subtitulos", action="store_true",
                    help="no transcribir ni quemar subtítulos")
    ap.add_argument("--vocabulario", default=None,
                    help="nombres propios y jerga del canal, separados por comas")
    ap.add_argument("--cookies-de", default=None,
                    help="navegador del que tomar la sesión si la plataforma la pide")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    meta = {}
    if re.match(r"^https?://", a.entrada):
        meta = metadatos(a.entrada, a.cookies_de)
        if not a.salida:
            # Una carpeta por vídeo, con nombre que diga de dónde salió: si se
            # clipean diez enlaces, no se mezclan ni se pisan.
            cuenta = re.sub(r"[^\w.-]", "", meta.get("uploader") or "video")[:30]
            sello = datetime.now().strftime("%Y%m%d-%H%M")
            a.salida = str(Path.home() / "Downloads" / "clips"
                           / f"{plataforma(a.entrada).lower()}_{cuenta}_{sello}")
        destino = Path(a.salida) / "original.mp4"
        if not a.json:
            print(f"bajando de {plataforma(a.entrada)}"
                  + (f" · @{meta['uploader']}" if meta.get("uploader") else "") + " …")
        ent = descargar(a.entrada, destino, a.cookies_de)
        if not a.json and meta.get("view_count"):
            print(f"  {meta['view_count']:,} reproducciones · "
                  f"{(meta.get('like_count') or 0):,} likes\n")
    else:
        ent = Path(a.entrada)
        if not ent.exists():
            raise SystemExit(f"no existe: {ent}")

    r = analizar(ent, a.cuantos, a.duracion)
    if not a.json:
        print(f"{ent.name} · {r['duracion_fuente']:.0f}s · {r['planos']} planos"
              + (f" · intro y cierre fuera ({r['margen']:.0f}s)" if r["margen"] else "")
              + ("" if r["con_audio"] else " · SIN AUDIO"))
        print(f"\n{a.cuantos} clips de {r['duracion_clip']:.0f}s entre {r['candidatas']} candidatas\n")
        print(f"{'desde':>7}{'hasta':>8}{'puntos':>8}{'audio':>7}{'movim':>7}{'arco':>6}{'ritmo':>7}")
        for c in r["clips"]:
            print(f"{c['ini']:>7.0f}{c['fin']:>8.0f}{c['puntos']:>8.2f}{c['audio']:>7.2f}"
                  f"{c['movimiento']:>7.2f}{c['arco']:>6.2f}{c['ritmo']:>7.2f}")

    if not a.solo_analizar:
        destino = Path(a.salida) if a.salida else ent.parent / f"{ent.stem}_clips"
        destino.mkdir(parents=True, exist_ok=True)
        w, h = medidas(ent)
        subtitular = not a.sin_subtitulos and r["con_audio"]
        if subtitular and not (subtitulos.MODELO.exists() and Path(subtitulos.FFMPEG_SUB).exists()):
            # No se salta en silencio: se dice qué falta.
            print("  aviso: sin subtítulos — falta el modelo de whisper o ffmpeg-full")
            subtitular = False
        for i, c in enumerate(r["clips"], 1):
            enc = None
            if a.encuadre in ("recorte", "completo"):
                enc = a.encuadre
            elif a.encuadre == "auto" and w > h:
                enc, ratio = decidir_encuadre(ent, c["ini"], c["fin"])
                c["detalle_laterales"] = ratio
            c["encuadre"] = enc or "original"
            palabras = []
            if subtitular:
                # Se transcribe con margen para poder mover los cortes a una
                # pausa del habla: un clip que empieza a media palabra suena roto.
                h = subtitulos.HOLGURA_CORTE + 1
                palabras = subtitulos.transcribir(ent, max(0.0, c["ini"] - h),
                                                  min(r["duracion_fuente"], c["fin"] + h),
                                                  vocabulario=a.vocabulario)
                c["ini_medido"], c["fin_medido"] = c["ini"], c["fin"]
                c["ini"], c["fin"] = subtitulos.ajustar_cortes(c["ini"], c["fin"], palabras)
                palabras = [p for p in palabras if p["fin"] > c["ini"] and p["ini"] < c["fin"]]
                c["texto"] = " ".join(p["t"] for p in palabras)
            sal = destino / f"clip{i}_{c['ini']:.0f}-{c['fin']:.0f}s.mp4"
            if palabras:
                crudo = destino / f".clip{i}_sin_sub.mp4"
                cortar(ent, c["ini"], c["fin"], crudo, enc)
                w_sal, h_sal = medidas(crudo)
                subtitulos.quemar(crudo, subtitulos.ass(palabras, c["ini"], w_sal, h_sal), sal)
                crudo.unlink()
            else:
                cortar(ent, c["ini"], c["fin"], sal, enc)
            c["subtitulos"] = bool(palabras)
            c["archivo"] = str(sal)
            if not a.json:
                print(f"  clip{i}: {c['encuadre']}"
                      + (f" (laterales al {c['detalle_laterales']:.0%} del centro)"
                         if "detalle_laterales" in c else "")
                      + (f" · {len(palabras)} palabras subtituladas" if palabras else ""))
        (destino / "informe.json").write_text(json.dumps(
            {"origen": meta or None, "fuente": str(ent), **r},
            indent=2, ensure_ascii=False, default=float))
        if not a.json:
            print(f"\n{len(r['clips'])} clips en {destino}/")

    if a.json:
        print(json.dumps({"origen": meta or None, "fuente": str(ent), **r},
                         indent=2, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main()

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
from analizar_referencia import UMBRAL_CORTE, cortes, datos_video  # noqa: E402
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
# Un plano más corto que esto no tiene encuadre propio: se suma al anterior.
PLANO_MINIMO = 2.5
# Una cara que ocupa al menos esta fracción del alto es alguien hablando a
# cámara: se recorta sobre ella. Medido en el Xokas: a cámara 0,54-0,60; su
# webcam en una esquina sobre un tuit, 0,20.
UMBRAL_CARA = 0.35
# Por debajo de eso pero por encima de este mínimo, y siempre en el mismo
# sitio, es la webcam del streamer superpuesta a lo que enseña: el Xokas
# leyendo un tuit con su cámara en una esquina mide 0,20; en la reacción a
# la casa de Grefg, 0,078.
UMBRAL_WEBCAM = 0.05
# Pantalla de reacción: la webcam ocupa la franja de arriba y lo que enseña,
# la de abajo. Alturas en un lienzo de 1080x1920.
ALTO_WEBCAM = 768
DETECTOR_CARAS = RAIZ / "modelos" / "yunet.onnx"


# ------------------------------------------------------------------ origen

def guardar_origen(video, meta):
    """Los metadatos de la descarga, junto al vídeo: origen.json."""
    Path(video).with_name("origen.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, default=str))


def leer_origen(video):
    """El origen de un vídeo ya descargado, o {} si no se sabe.

    Re-procesar el fichero local perdía de dónde salió: el informe quedaba
    con origen nulo y el clip no podía llevar el crédito al vídeo original.
    """
    f = Path(video).with_name("origen.json")
    return json.loads(f.read_text()) if f.exists() else {}


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


def tramos_fijos(ruta, texto):
    """Clips elegidos a mano o leyendo la transcripción: «356-386,19:30-20:02».

    Se saltan la puntuación automática; el resto de la cadena (ajuste a frases,
    encuadre, subtítulos) es la misma.
    """
    def seg(v):
        v = v.strip()
        if ":" in v:
            m, s_ = v.split(":")
            return int(m) * 60 + float(s_)
        return float(v)
    dur = datos_video(ruta)["duracion"]
    clips = []
    for parte in texto.split(","):
        a, b = (seg(x) for x in parte.split("-"))
        if not 0 <= a < b <= dur + 0.5:
            raise SystemExit(f"tramo fuera del vídeo: {parte}")
        clips.append({"ini": round(a, 2), "fin": round(min(b, dur), 2), "puntos": None,
                      "elegido": "a mano"})
    audio = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                            "stream=index", "-of", "csv=p=0", str(ruta)],
                           capture_output=True, text=True).stdout.strip()
    return {"duracion_fuente": dur, "con_audio": bool(audio), "clips": clips, "tramos": texto}


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


def fotograma(ruta, t, ancho=640, alto=360, formato="bgr24"):
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.2f}", "-i", str(ruta),
                        "-frames:v", "1", "-vf", f"scale={ancho}:{alto}", "-f", "rawvideo",
                        "-pix_fmt", formato, "-"], capture_output=True)
    canales = 3 if formato == "bgr24" else 1
    if len(r.stdout) != ancho * alto * canales:
        return None
    return np.frombuffer(r.stdout, dtype=np.uint8).reshape(alto, ancho, canales).squeeze()


def detectar_caras(ruta, ini, fin, n=7):
    """Todas las caras de n fotogramas: una lista por fotograma de (cx, alto, cy, ancho), relativos."""
    if not DETECTOR_CARAS.exists():
        return None
    import cv2
    det = cv2.FaceDetectorYN.create(str(DETECTOR_CARAS), "", (640, 360), 0.7)
    r = []
    for t in np.linspace(ini + 0.5, fin - 0.5, n):
        img = fotograma(ruta, t)
        if img is None:
            continue
        _, f = det.detect(img)
        r.append([((x + w / 2) / 640, h / 360, (y + h / 2) / 360, w / 640)
                  for x, y, w, h in (c[:4] for c in (f if f is not None else []))])
    return r


def caras(ruta, ini, fin, n=5):
    """La cara más grande de cada fotograma (los que tienen alguna)."""
    todas = detectar_caras(ruta, ini, fin, n)
    if todas is None:
        return None
    return [max(f, key=lambda c: c[1]) for f in todas if f]


def es_a_camara(lista, n=5):
    """Alguien hablando a cámara: cara grande en la mayoría de los fotogramas."""
    grandes = [c for c in (lista or []) if c[1] >= UMBRAL_CARA]
    return len(grandes) >= max(2, int(n * 0.6))


def webcam(fotogramas, n=None):
    """La caja de la webcam superpuesta (cx, cy, ancho, alto), o None.

    Una cara pequeña que aparece en la mayoría de los fotogramas y casi en el
    mismo sitio: es la cámara del streamer encima de lo que está enseñando.
    Se miran TODAS las caras de cada fotograma: la primera versión solo veía
    la mayor, y en cuanto el vídeo de la reacción enseñaba una cara grande la
    webcam desaparecía (reacción a la casa de Grefg).

    Acepta una lista por fotograma o, por compatibilidad, una cara por fotograma.
    """
    frames = [f if isinstance(f, list) else [f] for f in (fotogramas or [])]
    n = n or len(frames)
    peque = [[c for c in f if len(c) >= 4 and UMBRAL_WEBCAM <= c[1] < UMBRAL_CARA] for f in frames]
    mejor = []
    for f in peque:
        for c in f:
            # En cada fotograma, la cara pequeña más cercana a esta.
            cerca = []
            for g in peque:
                d = [(abs(o[0] - c[0]) + abs(o[2] - c[2]), o) for o in g]
                d = [x for x in d if x[0] <= 0.06]
                if d:
                    cerca.append(min(d)[1])
            if len(cerca) > len(mejor):
                mejor = cerca
    if len(mejor) < max(2, int(np.ceil(n * 0.5))):
        return None
    caja = tuple(round(float(np.median([c[i] for c in mejor])), 4) for i in (0, 2, 3, 1))
    # Una webcam superpuesta vive en un borde. Caras del contenido que andan
    # por el centro (un tour por una casa) no lo son, aunque se repitan.
    cx, cy, ancho, alto = caja
    # En una esquina, no solo en un borde...
    if not ((cx <= 0.3 or cx >= 0.7) and (cy <= 0.3 or cy >= 0.7)):
        return None
    # ...y con la cara entera: la de una webcam superpuesta está dentro de su
    # recuadro. Una cabeza cortada por el borde de la imagen es alguien que
    # entra en el plano (el Xokas yendo a su armario en la reacción a Grefg).
    if cy - alto / 2 < 0.02 or cy + alto / 2 > 0.98 or cx - ancho / 2 < 0.01 or cx + ancho / 2 > 0.99:
        return None
    return caja


def decidir_encuadre(ruta, ini, fin):
    """(encuadre, detalle_laterales, extra).

    Primero la cara: si alguien habla a cámara, se recorta sobre él aunque el
    fondo tenga detalle (extra = su centro x). La versión anterior solo medía
    detalle en los laterales y confundía las estanterías del cuarto del Xokas
    con información: su cara salía pequeña en una franja central.

    Luego la webcam: si el streamer reacciona a algo en pantalla con su cámara
    en una esquina, «reaccion» pone la cámara arriba y la pantalla abajo
    (extra = la caja de la webcam). Antes salía la pantalla entera en una
    franja y la cara del streamer, diminuta en su esquina.
    """
    todas = detectar_caras(ruta, ini, fin)
    # Primero la webcam: en una reacción, el vídeo que se ve puede tener una
    # cara grande, y entonces parecería «alguien a cámara» y se recortaría
    # sobre la persona equivocada.
    caja = webcam(todas)
    if caja:
        return "reaccion", None, caja
    lista = [max(f, key=lambda c: c[1]) for f in (todas or []) if f]
    if es_a_camara(lista, len(todas or [])):
        cx = float(np.median([c[0] for c in lista if c[1] >= UMBRAL_CARA]))
        return "cara", None, round(cx, 3)
    ratios = []
    for t in np.linspace(ini + 0.5, fin - 0.5, 3):
        g = fotograma(ruta, t, 320, 180, "gray")
        if g is not None:
            ratios.append(detalle_laterales(g))
    ratio = max(ratios) if ratios else 0.0
    return ("completo" if ratio >= UMBRAL_LATERALES else "recorte"), round(ratio, 2), None


def x_recorte(cx, w, h, ancho_rel=9 / 16):
    """Píxel izquierdo de un recorte de ancho h*ancho_rel centrado en cx (0..1), sin salirse."""
    ancho = h * ancho_rel
    return int(min(max(cx * w - ancho / 2, 0), w - ancho))


def cortes_en(ruta, ini, fin):
    """Cambios de plano entre ini y fin, en segundos del vídeo."""
    r = subprocess.run(["ffmpeg", "-nostdin", "-ss", f"{ini:.2f}", "-t", f"{fin - ini:.2f}", "-i", str(ruta),
                        "-filter:v", f"scale=320:-2,select='gt(scene,{UMBRAL_CORTE})',showinfo",
                        "-f", "null", "-"], capture_output=True, text=True)
    ts = []
    for linea in r.stderr.splitlines():
        if "pts_time:" in linea:
            try:
                ts.append(round(ini + float(linea.split("pts_time:")[1].split()[0]), 2))
            except (IndexError, ValueError):
                pass
    return sorted(set(ts))


def planos(cambios, ini, fin, minimo=PLANO_MINIMO):
    """Tramos [(a, b)] entre cambios de plano; los que no llegan al mínimo se suman al anterior."""
    bordes = [ini]
    for t in cambios:
        if t - bordes[-1] >= minimo and fin - t >= minimo:
            bordes.append(t)
    bordes.append(fin)
    return list(zip(bordes[:-1], bordes[1:]))


def mismo_encuadre(x, y):
    if x["encuadre"] != y["encuadre"]:
        return False
    if x["encuadre"] == "cara":
        return abs(x["extra"] - y["extra"]) < 0.1
    if x["encuadre"] == "reaccion":
        return abs(x["extra"][0] - y["extra"][0]) < 0.06 and abs(x["extra"][1] - y["extra"][1]) < 0.06
    return True


def unir_planos(lista):
    """Junta planos seguidos con el mismo encuadre; manda el primero de cada grupo."""
    out = []
    for p in lista:
        if out and mismo_encuadre(out[-1], p):
            out[-1] = dict(out[-1], fin=p["fin"])
        else:
            out.append(dict(p))
    return out


def encuadres_por_plano(ruta, ini, fin):
    """El encuadre de cada plano del clip.

    Un solo encuadre para todo el clip fallaba en cuanto el streamer cambiaba
    de la pantalla con su webcam a hablar a cámara (Grefg, primeros 7 s): la
    pantalla salía recortada por el centro, ilegible, justo en el gancho.
    """
    lista = []
    for a, b in planos(cortes_en(ruta, ini, fin), ini, fin):
        enc, ratio, extra = decidir_encuadre(ruta, a, b)
        lista.append({"ini": a, "fin": b, "encuadre": enc, "extra": extra, "detalle_laterales": ratio})
    return unir_planos(lista)


def args_plano(p):
    return {"encuadre": p["encuadre"], "cx": p["extra"] if p["encuadre"] == "cara" else None,
            "caja": p["extra"] if p["encuadre"] == "reaccion" else None}


def cortar_planos(entrada, ini, fin, destino, lista):
    """Corta cada plano con su encuadre y los une. El audio sale de un único
    corte continuo: unido por trozos, cada empalme mete un chasquido."""
    if len(lista) == 1:
        return cortar(entrada, ini, fin, destino, **args_plano(lista[0]))
    tmp = destino.parent / f".{destino.stem}_planos"
    tmp.mkdir(exist_ok=True)
    try:
        partes = []
        for k, p in enumerate(lista):
            a, b = max(ini, p["ini"]), min(fin, p["fin"])
            parte = tmp / f"{k}.mp4"
            cortar(entrada, a, b, parte, **args_plano(p))
            partes.append(parte)
        (tmp / "lista.txt").write_text("".join(f"file '{x.name}'\n" for x in partes))
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(tmp / "lista.txt"), "-an", "-c:v", "copy", str(tmp / "video.mp4")],
                       check=True)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(tmp / "video.mp4"),
                        "-ss", f"{ini:.2f}", "-t", f"{fin - ini:.2f}", "-i", str(entrada),
                        "-map", "0:v", "-map", "1:a?", "-c:v", "copy",
                        "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(destino)], check=True)
    finally:
        for x in tmp.iterdir():
            x.unlink()
        tmp.rmdir()


def recorte_webcam(caja, w, h, ancho_rel=1080 / ALTO_WEBCAM):
    """(x, y, ancho, alto) en píxeles del recorte de la webcam para la franja de arriba.

    La caja de la cara se amplía para que entren hombros y algo de cuarto, se
    baja un poco (la cara no va pegada al borde de arriba) y nunca se sale.
    """
    cx, cy, fw, fh = caja
    cw = min(w, fw * w * 3.2)
    ch = cw / ancho_rel
    if ch > h:
        ch, cw = h, h * ancho_rel
    x = min(max(cx * w - cw / 2, 0), w - cw)
    y = min(max(cy * h + 0.15 * fh * h - ch / 2, 0), h - ch)
    par = lambda v: int(v) // 2 * 2
    return par(x), par(y), par(cw), par(ch)


def pantalla_sin_webcam(caja, x, cw, w):
    """(x, ancho) de la pantalla dejando fuera la columna donde está la webcam.

    Con la webcam en un lateral se quita esa franja. La primera versión solo
    recortaba un 10 % por cada lado y el Xokas salía dos veces: grande arriba
    y pequeño en su esquina abajo.
    """
    if caja[0] >= 0.6:
        return 0, x // 2 * 2
    if caja[0] <= 0.4:
        return x + cw, (w - x - cw) // 2 * 2
    return int(w * 0.1) // 2 * 2, int(w * 0.8) // 2 * 2


def filtro(encuadre, w, h, cx=None, con_fondo=False, caja=None):
    """filter_complex que deja el vídeo en [v].

    con_fondo: pantalla partida. Arriba el clip (sobre la cara si hay, o
    entero sobre su propio desenfoque si es una pantalla con información),
    abajo el vídeo de fondo [1:v] sin su sonido.
    """
    if encuadre == "reaccion" and not con_fondo:
        x, y, cw, ch = recorte_webcam(caja, w, h)
        abajo = 1920 - ALTO_WEBCAM
        px, pw = pantalla_sin_webcam(caja, x, cw, w)
        # Abajo, la pantalla sin la columna de la webcam (si no, el streamer
        # sale dos veces) y a todo el ancho, sobre un desenfoque de sí misma.
        return (f"[0:v]split=3[a][b][c];[a]crop={cw}:{ch}:{x}:{y},"
                f"scale=1080:{ALTO_WEBCAM}:flags=lanczos,setsar=1[arriba];"
                f"[b]scale=1080:{abajo}:force_original_aspect_ratio=increase,crop=1080:{abajo},"
                f"boxblur=20:2[fondo];[c]crop={pw}:ih:{px}:0,scale=1080:-2:flags=lanczos[pant];"
                f"[fondo][pant]overlay=(W-w)/2:(H-h)/2,setsar=1[abajo];[arriba][abajo]vstack[v]")
    if not con_fondo:
        if encuadre == "cara":
            return (f"[0:v]crop=ih*9/16:ih:{x_recorte(cx, w, h)}:0,"
                    "scale=1080:1920:flags=lanczos[v]")
        if encuadre:
            return f"[0:v]{FILTROS[encuadre]}[v]"
        return "[0:v]null[v]"
    if encuadre == "cara":
        arriba = (f"[0:v]crop=ih*9/8:ih:{x_recorte(cx, w, h, 9 / 8)}:0,"
                  "scale=1080:960:flags=lanczos[arriba]")
    else:
        arriba = ("[0:v]split[a][b];[a]scale=1080:960:force_original_aspect_ratio=increase,"
                  "crop=1080:960,boxblur=20:2[fa];[b]scale=1080:960:force_original_aspect_ratio=decrease"
                  "[pa];[fa][pa]overlay=(W-w)/2:(H-h)/2[arriba]")
    abajo = ("[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,"
             "setsar=1[abajo]")
    return f"{arriba};{abajo};[arriba][abajo]vstack,setsar=1[v]"


FILTROS = {
    "recorte": "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=lanczos",
    # El plano entero, centrado, sobre una versión ampliada y desenfocada de
    # sí mismo: no se pierde nada y no quedan barras negras.
    "completo": ("split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,"
                 "crop=1080:1920,boxblur=24:2[fondo];[b]scale=1080:-2:flags=lanczos[plano];"
                 "[fondo][plano]overlay=(W-w)/2:(H-h)/2"),
}


def cortar(entrada, ini, fin, destino, encuadre=None, cx=None, fondo=None, fondo_ini=0.0,
           caja=None):
    """Corte preciso. encuadre: None (original), 'recorte', 'completo' o 'cara'.

    fondo: vídeo para la mitad de abajo (pantalla partida), desde fondo_ini.
    Se repite si es más corto que el clip. Su audio se descarta.
    """
    w, h = medidas(entrada)
    entradas = ["-ss", f"{max(0, ini - 2):.2f}", "-i", str(entrada)]
    if fondo:
        entradas += ["-stream_loop", "-1", "-ss", f"{fondo_ini:.2f}", "-i", str(fondo)]
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", *entradas,
         "-ss", f"{min(ini, 2):.2f}", "-t", f"{fin - ini:.2f}",
         "-filter_complex", filtro(encuadre, w, h, cx, bool(fondo), caja), "-map", "[v]", "-map", "0:a?",
         "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-movflags", "+faststart", str(destino)], check=True)


def estilo_subtitulos(encuadre, con_fondo):
    """Dónde va el rótulo: siempre en la costura entre las dos mitades, si las hay."""
    if con_fondo:
        return dict(subtitulos.ESTILO, alineacion=5, margen_v=0)
    if encuadre == "reaccion":
        # Justo debajo de la webcam, sobre el borde de arriba de la pantalla.
        return dict(subtitulos.ESTILO, margen_v=1920 - ALTO_WEBCAM - 140)
    return subtitulos.ESTILO


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
                    help="auto: vertical si la fuente es horizontal; sobre la cara si alguien "
                         "habla a cámara, entero si los laterales tienen información")
    ap.add_argument("--tramos", default=None,
                    help="cortar estos tramos en vez de buscarlos: «356-386,19:30-20:02»")
    ap.add_argument("--fondo", default=None,
                    help="vídeo para la mitad de abajo: además de cada clip, saca su versión "
                         "en pantalla partida (clipN_fondo.mp4), para comparar las dos")
    ap.add_argument("--sin-subtitulos", action="store_true",
                    help="no transcribir ni quemar subtítulos")
    ap.add_argument("--vocabulario", default=None,
                    help="nombres propios y jerga del canal, separados por comas")
    ap.add_argument("--corregir", default=None,
                    help="palabras mal oídas en los subtítulos: «pagos=pavos,Bolt=goat»")
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
        meta.setdefault("webpage_url", a.entrada)
        guardar_origen(ent, meta)
        if not a.json and meta.get("view_count"):
            print(f"  {meta['view_count']:,} reproducciones · "
                  f"{(meta.get('like_count') or 0):,} likes\n")
    else:
        ent = Path(a.entrada)
        if not ent.exists():
            raise SystemExit(f"no existe: {ent}")
        meta = leer_origen(ent)

    r = tramos_fijos(ent, a.tramos) if a.tramos else analizar(ent, a.cuantos, a.duracion)
    if not a.json and not a.tramos:
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
        fondo = Path(a.fondo) if a.fondo else None
        if fondo and not fondo.exists():
            raise SystemExit(f"no existe el fondo: {fondo}")
        dur_fondo = datos_video(fondo)["duracion"] if fondo else 0.0
        for i, c in enumerate(r["clips"], 1):
            palabras = []
            if subtitular:
                # Se transcribe con margen para poder mover los cortes a una
                # pausa del habla: un clip que empieza a media palabra suena roto.
                margen = subtitulos.ATRAS_FIN + 1
                palabras = subtitulos.transcribir(ent, max(0.0, c["ini"] - subtitulos.ENTRADA_TRANSCRIPCION),
                                                  min(r["duracion_fuente"], c["fin"] + margen),
                                                  vocabulario=a.vocabulario)
                palabras = subtitulos.corregir(palabras, a.corregir)
                c["ini_medido"], c["fin_medido"] = c["ini"], c["fin"]
                # Un tramo elegido leyendo la transcripción ya cae casi donde debe:
                # retrocede unas décimas como mucho (con la holgura normal el clip 2
                # del cirujano llegó al nombre de una paciente) y avanza hasta el
                # cierre de frase que el redondeo a segundos deja justo detrás.
                ajuste = ({"holgura": subtitulos.TRAMO_ADELANTE, "atras_fin": subtitulos.TRAMO_ATRAS}
                          if a.tramos else {})
                c["ini"], c["fin"] = subtitulos.ajustar_cortes(c["ini"], c["fin"], palabras, **ajuste)
                palabras = [p for p in palabras if p["fin"] > c["ini"] and p["ini"] < c["fin"]]
                c["texto"] = " ".join(p["t"] for p in palabras)

            # Encuadre, plano a plano, sobre el corte ya ajustado.
            if a.encuadre in ("recorte", "completo"):
                lista = [{"ini": c["ini"], "fin": c["fin"], "encuadre": a.encuadre, "extra": None}]
            elif a.encuadre == "auto" and w > h:
                lista = encuadres_por_plano(ent, c["ini"], c["fin"])
            else:
                lista = [{"ini": c["ini"], "fin": c["fin"], "encuadre": None, "extra": None}]
            c["encuadre"] = "+".join(dict.fromkeys(p["encuadre"] or "original" for p in lista))
            c["planos"] = [{"ini": p["ini"], "fin": p["fin"], "encuadre": p["encuadre"] or "original"}
                           for p in lista]
            # La versión con fondo usa un solo encuadre: el del plano más largo.
            principal = max(lista, key=lambda p: p["fin"] - p["ini"])

            versiones = [("", None)]
            if fondo:
                # Mismo clip, mismo corte, mismos subtítulos: la única diferencia
                # entre las dos versiones es el fondo. Cada clip toma un tramo
                # distinto del fondo para que no se repita entre clips.
                largo = c["fin"] - c["ini"]
                ini_fondo = (i - 1) * largo % max(1.0, dur_fondo - largo) if dur_fondo > largo else 0.0
                versiones.append(("_fondo", ini_fondo))
            c["archivos"] = []
            for sufijo, ini_fondo in versiones:
                sal = destino / f"clip{i}_{c['ini']:.0f}-{c['fin']:.0f}s{sufijo}.mp4"
                objetivo = (destino / f".clip{i}{sufijo}_sin_sub.mp4") if palabras else sal
                if sufijo:
                    cortar(ent, c["ini"], c["fin"], objetivo, fondo=fondo, fondo_ini=ini_fondo or 0.0,
                           **args_plano(principal))
                    por_tramo = None
                    estilo = estilo_subtitulos(principal["encuadre"], True)
                else:
                    cortar_planos(ent, c["ini"], c["fin"], objetivo, lista)
                    # El rótulo cambia de sitio con el encuadre de cada plano.
                    por_tramo = [(p["ini"], p["fin"], estilo_subtitulos(p["encuadre"], False)) for p in lista]
                    estilo = por_tramo[0][2]
                if palabras:
                    w_sal, h_sal = medidas(objetivo)
                    subtitulos.quemar(objetivo, subtitulos.ass(palabras, c["ini"], w_sal, h_sal, estilo,
                                                               por_tramo), sal)
                    objetivo.unlink()
                c["archivos"].append(str(sal))
            c["subtitulos"] = bool(palabras)
            if not a.json:
                print(f"  clip{i}: {c['encuadre']}"
                      + (f" ({len(c['planos'])} planos)" if len(c["planos"]) > 1 else "")
                      + (f" · {len(palabras)} palabras subtituladas" if palabras else "")
                      + (" · con y sin fondo" if fondo else ""))
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

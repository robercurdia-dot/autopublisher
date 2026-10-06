#!/usr/bin/env python3
"""Transcribe un clip y le quema subtítulos animados palabra a palabra.

Todo en local: whisper.cpp transcribe (con la GPU del Mac) y ffmpeg-full los
pinta con libass. Nada sale de esta máquina.

  transcribir()   palabras con su instante de inicio y fin
  ajustar_cortes  mueve el inicio y el fin de un clip a pausas del habla, para
                  no empezar ni acabar a media palabra
  ass()           el fichero de subtítulos: frases de pocas palabras, la que
                  suena resaltada y con un pequeño salto
  quemar()        los pinta sobre el vídeo

    python3 subtitulos.py clip.mp4                 # deja clip_sub.mp4 al lado
    python3 subtitulos.py clip.mp4 --vocabulario "Rubius, Pokémon, Charizard"
"""

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent
MODELO = RAIZ / "modelos" / "ggml-large-v3-turbo.bin"
WHISPER = "whisper-cli"
# El ffmpeg de siempre no trae libass. ffmpeg-full se instala aparte (keg-only)
# y solo se usa para este paso, para no tocar el resto de la cadena.
FFMPEG_SUB = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"

# Cuántas palabras se ven a la vez. En Shorts se lee de un vistazo: más de
# tres obliga a leer en vez de mirar.
PALABRAS_POR_FRASE = 3
CARACTERES_POR_FRASE = 18
# Un silencio así entre dos palabras corta la frase aunque no esté llena.
PAUSA_FRASE = 0.35
# Hasta dónde se puede mover el inicio o el fin de un clip para caer en una
# pausa del habla.
HOLGURA_CORTE = 3.0
# El final puede adelantarse más: es mejor un clip unos segundos más corto que
# uno que acaba a media frase o con el arranque de otra persona hablando.
ATRAS_FIN = 8.0


# ------------------------------------------------------------ transcripción

def _ms(marca):
    h, m, s = marca.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def transcribir(ruta, ini=0.0, fin=None, idioma="es", vocabulario=None, modelo=MODELO):
    """Palabras [{t, ini, fin}] del tramo ini..fin, en segundos ABSOLUTOS del vídeo."""
    if not Path(modelo).exists():
        raise SystemExit(f"falta el modelo de whisper: {modelo}")
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        rango = ["-ss", f"{ini:.2f}"] + (["-t", f"{fin - ini:.2f}"] if fin else [])
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *rango, "-i", str(ruta),
                        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)],
                       check=True)
        base = Path(tmp) / "t"
        # -ml 1 -sow: un segmento por palabra, con su tiempo. Es lo que necesita
        # el resaltado; el texto de frases se reconstruye después.
        cmd = [WHISPER, "-m", str(modelo), "-f", str(wav), "-l", idioma,
               "-ml", "1", "-sow", "-oj", "-of", str(base), "-np"]
        if vocabulario:
            cmd += ["--prompt", vocabulario]
        subprocess.run(cmd, check=True, capture_output=True)
        datos = json.loads(Path(f"{base}.json").read_text(errors="replace"))
    palabras = []
    for seg in datos.get("transcription", []):
        t = seg["text"].strip()
        if not t or re.fullmatch(r"\[.*\]|\(.*\)", t):
            continue
        a, b = _ms(seg["timestamps"]["from"]), _ms(seg["timestamps"]["to"])
        if palabras and not re.search(r"\w", t):
            # Puntuación suelta: pertenece a la palabra anterior.
            palabras[-1]["t"] += t
            continue
        palabras.append({"t": t, "ini": round(ini + a, 2), "fin": round(ini + max(b, a + 0.05), 2)})
    return palabras


# -------------------------------------------------------------------- cortes

def pausas(palabras):
    """Instantes donde se puede cortar sin partir una palabra: entre dos de ellas."""
    if not palabras:
        return []
    p = [palabras[0]["ini"]]
    for a, b in zip(palabras, palabras[1:]):
        p.append((a["fin"] + b["ini"]) / 2)
    p.append(palabras[-1]["fin"])
    return p


def ajustar_cortes(ini, fin, palabras, holgura=HOLGURA_CORTE, atras_fin=ATRAS_FIN):
    """Lleva ini y fin a un límite de frase cercano, dentro de la holgura.

    Manda la PUNTUACIÓN: whisper da los tiempos de palabra pegados unos a otros
    (los huecos salen a 0,00 s), así que el silencio no sirve para encontrar
    dónde acaba una idea. La primera versión puntuaba huecos y, como nunca los
    había, cortaba en la palabra más cercana: un clip arrancó con «7.», el
    final de la frase anterior. Ver clipper/errores.json.

    El inicio busca a ±holgura: tras un punto (. ! ? …), si no tras una coma.
    El final SOLO acepta un cierre de frase, y lo busca hasta atras_fin antes
    del corte. Si no hay ninguno, entre dos palabras. Si nadie habla cerca, no
    lo toca.
    """
    if not palabras:
        return ini, fin

    def mejor(objetivo, antes_max, despues_max, niveles):
        opciones = []
        for i, t in enumerate(pausas(palabras)):
            if not objetivo - antes_max <= t <= objetivo + despues_max:
                continue
            previa = palabras[i - 1]["t"] if i > 0 else "."
            nivel = 0 if re.search(r"[.!?…]$", previa) else 1 if re.search(r"[,;:]$", previa) else 2
            if nivel in niveles:
                opciones.append((nivel, abs(t - objetivo), t))
        if opciones:
            return min(opciones)[2]
        # Sin cierre a mano: al menos entre dos palabras, cerca del corte.
        cerca = [t for t in pausas(palabras) if abs(t - objetivo) <= holgura]
        return min(cerca, key=lambda t: abs(t - objetivo)) if cerca else objetivo

    # Empezar tras una coma vale (arranca una cláusula); ACABAR en una coma
    # deja la idea colgando: en el Xokas, dos de tres clips terminaron así.
    nuevo_ini = mejor(ini, holgura, holgura, (0, 1))
    nuevo_fin = mejor(fin, atras_fin, holgura, (0,))
    if nuevo_fin - nuevo_ini < (fin - ini) * 0.7:
        return ini, fin
    return round(nuevo_ini, 2), round(nuevo_fin, 2)


# ----------------------------------------------------------------- frases

def frases(palabras):
    """Agrupa en frases cortas para leer de un vistazo.

    Primero se separa por pausas y puntuación (donde la voz corta); luego cada
    tramo se reparte en trozos IGUALES de como mucho PALABRAS_POR_FRASE. Llenar
    de tres en tres dejaba palabras huérfanas: «ESTO ES UNA» + «PRUEBA.».
    """
    tramos, actual = [], []
    for p in palabras:
        if actual and (p["ini"] - actual[-1]["fin"] > PAUSA_FRASE
                       or re.search(r"[.!?…,;:]$", actual[-1]["t"])):
            tramos.append(actual)
            actual = []
        actual.append(p)
    if actual:
        tramos.append(actual)

    grupos = []
    for t in tramos:
        n = -(-len(t) // PALABRAS_POR_FRASE)
        # Se parte más mientras algún trozo no quepa en una línea: un rótulo
        # en dos líneas invade el plano («PELÍCULA DE / INTERESTRAL»).
        while True:
            trozos = [[t[k] for k in tr] for tr in np.array_split(np.arange(len(t)), n)]
            if n >= len(t) or all(len(" ".join(x["t"] for x in tr)) <= CARACTERES_POR_FRASE
                                  for tr in trozos):
                break
            n += 1
        grupos.extend(trozos)
    return grupos


# -------------------------------------------------------------------- ASS

def _t(s):
    s = max(0.0, s)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _limpiar(t):
    return t.replace("\\", "").replace("{", "(").replace("}", ")").upper()


ESTILO = {
    "fuente": "Arial Black",
    "tam": 92,
    "blanco": "&H00FFFFFF",
    "resalte": "&H0000E5FF",   # amarillo (ASS es BGR)
    "borde": 7,
    # Distancia del borde inferior en un lienzo de 1920: por encima de la
    # interfaz de Shorts (botones y descripción ocupan la franja de abajo).
    "margen_v": 520,
}


def ass(palabras, desplazamiento=0.0, ancho=1080, alto=1920, estilo=ESTILO):
    """Subtítulos ASS. desplazamiento: segundo del vídeo donde empieza el clip.

    Un evento por palabra que suena: muestra la frase entera con esa palabra
    resaltada y un salto de escala. Los eventos de una frase son consecutivos y
    no se pisan, así que nunca hay dos rótulos a la vez.
    """
    e = estilo
    cab = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {ancho}\nPlayResY: {alto}\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
        "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
        "MarginV, Encoding\n"
        f"Style: Base,{e['fuente']},{e['tam']},{e['blanco']},{e['blanco']},&H00000000,"
        f"&H64000000,-1,0,0,0,100,100,0,0,1,{e['borde']},3,{e.get('alineacion', 2)},60,60,"
        f"{e['margen_v']},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n")
    lineas = []
    grupos = frases(palabras)
    for k, g in enumerate(grupos):
        # La frase siguiente manda: el alargue de la última palabra no la pisa.
        siguiente = grupos[k + 1][0]["ini"] if k + 1 < len(grupos) else None
        for i, p in enumerate(g):
            a = p["ini"] - desplazamiento
            # Hasta que empieza la siguiente palabra de la frase; la última se
            # queda un poco más, sin llegar a pisar la frase siguiente.
            b = (g[i + 1]["ini"] if i + 1 < len(g) else p["fin"] + 0.25) - desplazamiento
            if siguiente is not None:
                b = min(b, siguiente - desplazamiento)
            if b <= 0:
                continue
            texto = []
            for j, q in enumerate(g):
                w = _limpiar(q["t"])
                if j == i:
                    texto.append("{\\c%s\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)}%s"
                                 "{\\c%s\\fscx100\\fscy100}" % (e["resalte"], w, e["blanco"]))
                else:
                    texto.append(w)
            lineas.append(f"Dialogue: 0,{_t(a)},{_t(b)},Base,,0,0,0,,{' '.join(texto)}")
    return cab + "\n".join(lineas) + "\n"


def eventos(texto_ass):
    """(inicio, fin) de cada Dialogue, en segundos. Para comprobar solapes."""
    r = []
    for l in texto_ass.splitlines():
        if l.startswith("Dialogue:"):
            _, a, b = l.split(",")[:3]
            r.append((_ms(a), _ms(b)))
    return r


def quemar(video, texto_ass, salida):
    if not Path(FFMPEG_SUB).exists():
        raise SystemExit("falta ffmpeg-full (brew install ffmpeg-full): el ffmpeg normal no trae libass")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "sub.ass"
        f.write_text(texto_ass, encoding="utf-8")
        subprocess.run([FFMPEG_SUB, "-nostdin", "-v", "error", "-y", "-i", str(video),
                        "-vf", f"ass={f}", "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                        "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
                        str(salida)], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--vocabulario", default=None,
                    help="nombres propios y jerga, separados por comas, para que los escriba bien")
    ap.add_argument("--salida", default=None)
    a = ap.parse_args()
    v = Path(a.video)
    pal = transcribir(v, vocabulario=a.vocabulario)
    sal = Path(a.salida) if a.salida else v.with_name(f"{v.stem}_sub.mp4")
    quemar(v, ass(pal), sal)
    print(" ".join(p["t"] for p in pal))
    print(f"\n{len(pal)} palabras → {sal}")


if __name__ == "__main__":
    main()

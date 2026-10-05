#!/usr/bin/env python3
"""Corta un vídeo largo en las piezas que mejor funcionarían publicadas.

La diferencia con un clipper de suite no está en el corte -eso lo hace ffmpeg-
sino en POR QUÉ elige un trozo y no otro. Los clippers comerciales puntúan por
transcripción: buscan el momento donde alguien dice algo gracioso. Eso sirve
para un pódcast y no sirve para una pieza de producto, que a menudo no tiene
habla.

Aquí se puntúa por lo que medimos en el nicho el 4 de octubre de 2026, barriendo
40 piezas reales:

  ritmo        las que ganan cortan cada 1,4 s de media; un plano sostenido
               mata la retención (nuestro run 07 tenía el 69 % del clip estático)
  movimiento   un trozo donde no pasa nada no retiene, por bien encuadrado que esté
  arco         las piezas que ganan viajan de un estado a otro -apagado a
               encendido, de día a noche-; un trozo que empieza y acaba igual
               no demuestra nada
  duracion     la mediana del montón son 10 s y las cinco de más alcance están
               entre 13,5 y 14,9: se premia acercarse a eso, no a la mediana

No necesita transcripción. Si la hay, se puede usar para afinar, pero el motor
funciona con vídeo mudo, que es el caso de la mayoría de piezas de producto.

    python3 autoclipper.py entrada.mp4
    python3 autoclipper.py entrada.mp4 --cuantos 3 --duracion 14
    python3 autoclipper.py entrada.mp4 --salida clips/ --json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent
REPO = RAIZ.parent
sys.path.insert(0, str(REPO / "ingesta"))
from analizar_referencia import cortes, datos_video  # noqa: E402

# Lo que buscamos en una ventana, y cuánto pesa cada cosa. Suman 1.
PESOS = {"ritmo": 0.30, "movimiento": 0.30, "arco": 0.25, "duracion": 0.15}

# Medido en el barrido: las piezas de más alcance del nicho duran esto.
DURACION_OBJETIVO = 14.0
# Cortes por segundo de la pieza top del nicho (13 planos en 17,7 s).
RITMO_OBJETIVO = 0.73
# A cuántas imágenes por segundo se muestrea para medir. Más no aporta y
# multiplica el tiempo de análisis.
MUESTREO = 4


def muestrear(ruta, dur):
    """Brillo medio y diferencia entre fotogramas, a lo largo del vídeo.

    Se saca en una sola pasada de ffmpeg a resolución mínima: medir movimiento
    no necesita píxeles, necesita que los números cambien.
    """
    n = max(2, int(dur * MUESTREO))
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(ruta),
           "-vf", f"fps={MUESTREO},scale=64:64,format=gray", "-f", "rawvideo", "-"]
    crudo = subprocess.run(cmd, capture_output=True, check=True).stdout
    marcos = np.frombuffer(crudo, dtype=np.uint8)
    marcos = marcos[: (len(marcos) // 4096) * 4096].reshape(-1, 64, 64).astype(float)
    if len(marcos) < 2:
        raise SystemExit("el vídeo es demasiado corto para analizarlo")
    brillo = marcos.mean(axis=(1, 2))
    # Diferencia media entre fotograma y fotograma: eso es "cuánto pasa".
    mov = np.abs(np.diff(marcos, axis=0)).mean(axis=(1, 2))
    mov = np.append(mov, mov[-1])
    return brillo, mov


def ventanas(dur, objetivo, paso=0.5):
    """Todas las ventanas candidatas de la duración objetivo."""
    v, t = [], 0.0
    while t + objetivo <= dur + 0.01:
        v.append((round(t, 2), round(t + objetivo, 2)))
        t += paso
    if not v:
        v = [(0.0, round(dur, 2))]
    return v


def puntuar(ini, fin, ts_cortes, brillo, mov):
    """Cuánto promete esta ventana, de 0 a 1, y por qué."""
    i0, i1 = int(ini * MUESTREO), max(int(fin * MUESTREO), int(ini * MUESTREO) + 1)
    b, m = brillo[i0:i1], mov[i0:i1]
    largo = fin - ini
    if len(b) < 2:
        return 0.0, {}

    dentro = [t for t in ts_cortes if ini <= t <= fin]
    ritmo_real = len(dentro) / largo
    # Se premia acercarse al ritmo del que gana, no superarlo: cortar cada
    # tres décimas no es mejor, es epilepsia.
    ritmo = max(0.0, 1 - abs(ritmo_real - RITMO_OBJETIVO) / RITMO_OBJETIVO)

    # Movimiento normalizado contra el del vídeo entero: lo que importa es si
    # ESTA ventana se mueve más o menos que el resto de la pieza.
    movimiento = float(np.clip(m.mean() / (mov.mean() + 1e-6), 0, 2) / 2)

    # Arco: cuánto se separa el final del principio. Un trozo que empieza y
    # acaba igual puede estar muy bien rodado y no contar nada.
    n = max(1, len(b) // 4)
    salto = abs(b[-n:].mean() - b[:n].mean())
    arco = float(np.clip(salto / 40.0, 0, 1))

    duracion = max(0.0, 1 - abs(largo - DURACION_OBJETIVO) / DURACION_OBJETIVO)

    partes = {"ritmo": ritmo, "movimiento": movimiento, "arco": arco, "duracion": duracion}
    total = sum(PESOS[k] * v for k, v in partes.items())
    partes["cortes_por_s"] = round(ritmo_real, 2)
    partes["salto_de_brillo"] = round(float(salto), 1)
    return total, partes


def sin_solapar(cands, cuantos, solape_max=0.35):
    """Las mejores ventanas que no se pisan: dos clips casi iguales no son dos."""
    elegidas = []
    for c in sorted(cands, key=lambda x: -x["puntos"]):
        if len(elegidas) >= cuantos:
            break
        if all(min(c["fin"], e["fin"]) - max(c["ini"], e["ini"])
               <= solape_max * (c["fin"] - c["ini"]) for e in elegidas):
            elegidas.append(c)
    return sorted(elegidas, key=lambda x: x["ini"])


def cortar(entrada, ini, fin, destino):
    """Corte con recodificación: -ss antes de -i va al keyframe y desplaza."""
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(entrada),
         "-ss", f"{ini:.2f}", "-to", f"{fin:.2f}",
         "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-movflags", "+faststart", str(destino)], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada")
    ap.add_argument("--cuantos", type=int, default=3)
    ap.add_argument("--duracion", type=float, default=DURACION_OBJETIVO)
    ap.add_argument("--salida", default=None, help="carpeta donde dejar los clips")
    ap.add_argument("--solo-analizar", action="store_true", help="puntúa y no corta")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    ent = Path(a.entrada)
    if not ent.exists():
        raise SystemExit(f"no existe: {ent}")

    dur = datos_video(ent)["duracion"]
    ts = cortes(ent)
    brillo, mov = muestrear(ent, dur)

    cands = []
    for ini, fin in ventanas(dur, a.duracion):
        p, partes = puntuar(ini, fin, ts, brillo, mov)
        cands.append({"ini": ini, "fin": fin, "puntos": round(p, 3), **partes})
    elegidas = sin_solapar(cands, a.cuantos)

    if not a.json:
        print(f"{ent.name} · {dur:.1f}s · {len(ts)+1} planos · "
              f"{len(ts)/dur:.2f} cortes/s de media")
        print(f"\nbuscando {a.cuantos} ventanas de {a.duracion:.0f}s "
              f"entre {len(cands)} candidatas\n")
        print(f"{'desde':>7}{'hasta':>8}{'puntos':>9}{'ritmo':>8}{'movim':>8}{'arco':>7}{'cortes/s':>10}")
        for c in elegidas:
            print(f"{c['ini']:>7.1f}{c['fin']:>8.1f}{c['puntos']:>9.3f}"
                  f"{c['ritmo']:>8.2f}{c['movimiento']:>8.2f}{c['arco']:>7.2f}{c['cortes_por_s']:>10.2f}")

    if not a.solo_analizar:
        destino = Path(a.salida) if a.salida else ent.parent / f"{ent.stem}_clips"
        destino.mkdir(parents=True, exist_ok=True)
        for i, c in enumerate(elegidas, 1):
            sal = destino / f"{ent.stem}_clip{i}.mp4"
            cortar(ent, c["ini"], c["fin"], sal)
            c["archivo"] = str(sal)
        if not a.json:
            print(f"\n{len(elegidas)} clips en {destino}/")

    if a.json:
        print(json.dumps({"fuente": str(ent), "duracion": dur,
                          "planos": len(ts) + 1, "clips": elegidas},
                         indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

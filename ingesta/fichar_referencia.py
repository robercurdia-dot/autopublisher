#!/usr/bin/env python3
"""Ficha estructural de una referencia — de qué va el vídeo, no de qué va ESTE producto.

El prompt de generación no se escribe a mano. Se construye a partir de lo que el
vídeo de referencia dicta: cuántos planos tiene, cuántos objetos salen, y sobre
todo **qué acción lo vertebra y en qué estado termina**. Eso vale para una
lámpara, para unas zapatillas o para lo que vendamos mañana; lo que cambia es el
producto, que sale de contexto.json, no de aquí.

Esta mitad es la medible: trocea por planos y saca un fotograma de cada uno más
una hoja de contactos. La otra mitad —la lectura semántica— la rellena un modelo
de visión sobre esos fotogramas, con el esquema que imprime --esquema.

Uso:
    python3 fichar_referencia.py ../assets/videos/lemon_art_negro.mp4
    python3 fichar_referencia.py --esquema
"""

import argparse
import json
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
REPO = RAIZ.parent
PLANOS = REPO / "assets" / "informes" / "planos"
FICHAS = REPO / "assets" / "informes" / "fichas"

import sys
sys.path.insert(0, str(RAIZ))
from analizar_referencia import cortes, datos_video  # noqa: E402

# El papel de cada elemento decide qué hace el motor con él. Es la única
# clasificación que importa, y por eso va primero:
#
#   protagonista  lo que el vídeo vende. En NUESTRO clip se SUSTITUYE por el
#                 producto de contexto.json y no deriva jamás: es lo que vendemos.
#   interactua    aquello sobre lo que el producto actúa. Se VARÍA en cada pieza
#                 —marca y cantidad— tirando de la biblioteca que diga contexto.json.
#                 Su variedad dentro del clip es el argumento de venta.
#   escenario     dónde ocurre. Se CAMBIA entero, porque copiarlo nos acerca a la
#                 referencia justo en lo que la identifica.
#   constante     manos, luz, ritmo. Se HEREDA: es lo que hace que el clip se lea
#                 como del mismo nicho.
PAPELES = ("protagonista", "interactua", "escenario", "constante")

ESQUEMA = {
    "producto_protagonista": "qué objeto vertebra el vídeo (el de la referencia, no el nuestro)",
    "accion": {
        "verbo": "la acción en una palabra: colocar, servir, encender, abrir…",
        "estado_inicial": "cómo empieza la escena",
        "estado_final": "cómo tiene que terminar — ESTO ES OBLIGATORIO, la acción se completa",
        "se_completa_en_plano": "índice del plano donde se cierra",
    },
    "objetos": [{"tipo": "el sustantivo genérico: botella, taza, zapatilla…",
                 "cantidad": 0,
                 "papel": " | ".join(PAPELES)}],
    "escenario": "dónde ocurre",
    "iluminacion": "natural, cálida, nocturna…",
    "encuadre_por_plano": ["primer plano", "plano medio", "detalle"],
    "personas": "ninguna | manos | cuerpo | cara visible",
}


def planos(ruta, ts, dur):
    """Tramos entre cortes, con el instante del que se saca el fotograma."""
    bordes = [0.0] + list(ts) + [dur]
    out = []
    for i, (a, b) in enumerate(zip(bordes[:-1], bordes[1:])):
        if b - a < 0.25:          # un parpadeo no es un plano
            continue
        out.append({"plano": len(out), "desde": round(a, 2), "hasta": round(b, 2),
                    "duracion": round(b - a, 2), "muestra": round(a + (b - a) / 2, 2)})
    return out


def fichar(ruta):
    ruta = Path(ruta)
    ident = ruta.stem
    carpeta = PLANOS / ident
    carpeta.mkdir(parents=True, exist_ok=True)
    FICHAS.mkdir(parents=True, exist_ok=True)

    info = datos_video(ruta)
    ps = planos(ruta, cortes(ruta), info["duracion"])

    for p in ps:
        destino = carpeta / f"plano_{p['plano']:02d}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(p["muestra"]),
                        "-i", str(ruta), "-frames:v", "1", "-vf", "scale=360:-2",
                        str(destino)], check=True)
        p["fotograma"] = str(destino.relative_to(REPO))

    # Hoja de contactos: todos los planos de un vistazo, para leerlos de una vez.
    lista = carpeta / "lista.txt"
    rutas = [carpeta / ("plano_%02d.jpg" % p["plano"]) for p in ps]
    lista.write_text("".join("file '%s'\n" % r for r in rutas))
    columnas = min(4, len(ps)) or 1
    filas = (len(ps) + columnas - 1) // columnas
    contactos = carpeta / "contactos.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lista), "-vf", f"tile={columnas}x{filas}:margin=6:padding=6",
                    "-frames:v", "1", str(contactos)], check=True)
    lista.unlink()

    ficha = {
        "id": ident,
        "duracion": info["duracion"],
        "proporcion": info["video"]["proporcion"] if info["video"] else None,
        "planos": ps,
        "contactos": str(contactos.relative_to(REPO)),
        "lectura": None,          # lo rellena el modelo de visión con ESQUEMA
    }
    destino = FICHAS / f"{ident}.json"
    if destino.exists():          # no pisar una lectura ya hecha
        previo = json.loads(destino.read_text())
        ficha["lectura"] = previo.get("lectura")
    destino.write_text(json.dumps(ficha, indent=2, ensure_ascii=False))

    print(f"{ident}: {len(ps)} planos · {info['duracion']} s")
    for p in ps:
        print(f"  plano {p['plano']}  {p['desde']:5.2f}–{p['hasta']:5.2f} s  ({p['duracion']:.2f})")
    print(f"hoja de contactos: {contactos.relative_to(REPO)}")
    print(f"ficha: {destino.relative_to(REPO)}  ·  lectura "
          f"{'hecha' if ficha['lectura'] else 'PENDIENTE'}")
    return ficha


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", nargs="?")
    ap.add_argument("--esquema", action="store_true", help="imprime el esquema de la lectura")
    a = ap.parse_args()
    if a.esquema:
        print(json.dumps(ESQUEMA, indent=2, ensure_ascii=False))
        print("\nPAPELES — lo único que el motor necesita decidir de cada elemento:")
        print("  protagonista  se sustituye por el nuestro y NO deriva")
        print("  interactua    se varía en cada pieza (marca y cantidad)")
        print("  escenario     se cambia entero")
        print("  constante     se hereda tal cual")
        return
    if not a.video:
        raise SystemExit("pásame un vídeo, o --esquema")
    fichar(a.video)


if __name__ == "__main__":
    main()

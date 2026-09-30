#!/usr/bin/env python3
"""Del clip mudo a la pista lista para montar: elige y alinea.

Une las dos mitades: buscar_sonido.py ordena el catálogo por parecido con el
sonido de la referencia, y alinear_audio.py recorta la elegida para que pegue en
los cortes de ESTE clip. Deja el audio listo para publicar_clip.sh.

    python3 preparar_sonido.py clip.mp4 lemon_art_negro
    python3 preparar_sonido.py clip.mp4 lemon_art_negro --elegir meta_soft_bounce
    python3 preparar_sonido.py clip.mp4 lemon_art_negro --salida /tmp/pista.m4a --json

La elección es tuya: sin --elegir coge el primero del ranking, pero imprime los
tres para que puedas cambiarlo antes de publicar.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "ingesta"))

from buscar_sonido import MUSICA, catalogo, indice, parecido, perfil_referencia, usadas  # noqa: E402
from perfil_musical import descripcion                                            # noqa: E402
from alinear_audio import alinear                                                 # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip")
    ap.add_argument("referencia", help="id de la referencia que marca el estilo")
    ap.add_argument("--elegir", help="id del catálogo, saltándose el ranking")
    ap.add_argument("--salida", help="dónde dejar el audio (por defecto junto al clip)")
    ap.add_argument("--tolerancia", type=float, default=0.15)
    ap.add_argument("--catalogo")
    ap.add_argument("--repetir", action="store_true",
                    help="permite volver a usar una pista ya publicada")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    clip = Path(a.clip)
    if not clip.exists():
        raise SystemExit(f"no existe el clip: {clip}")

    ref = perfil_referencia(a.referencia)
    ref.setdefault("terminos", descripcion(ref))
    entradas = [e for e in indice(catalogo(a.catalogo)) if e.get("perfil")]
    ya = [] if a.repetir else usadas()
    frescas = [e for e in entradas if e["id"] not in ya]
    if ya and frescas:
        entradas = frescas      # no se repite pista mientras haya catálogo
    if not entradas:
        raise SystemExit(
            "catálogo vacío: no hay ninguna pista que elegir.\n"
            "  Descarga pistas de la Colección de sonidos de Meta y anótalas en\n"
            f"  {(MUSICA / 'catalogo.json').relative_to(REPO)} — ver assets/musica/LEEME.md")

    ranking = []
    for e in entradas:
        nota, desglose = parecido(ref, e["perfil"])
        ranking.append({"id": e["id"], "nombre": e.get("nombre", e["id"]),
                        "origen": e.get("origen", "?"), "archivo": e["archivo"],
                        "bpm": e["perfil"]["bpm"], "duracion": e["perfil"]["duracion"],
                        "nota": nota, "desglose": desglose})
    ranking.sort(key=lambda c: -c["nota"])

    if a.elegir:
        elegida = next((c for c in ranking if c["id"] == a.elegir), None)
        if not elegida:
            raise SystemExit(f"«{a.elegir}» no está en el catálogo")
    else:
        elegida = ranking[0]

    if elegida["origen"] == "ig":
        print("AVISO: esta pista viene de la biblioteca de la app (origen «ig»).")
        print("       La API no puede seleccionar ese sonido: la pieza habría que")
        print("       subirla a mano. Para cadena automática usa una de la Colección.")

    pista = MUSICA / elegida["archivo"] if not Path(elegida["archivo"]).is_absolute() \
        else Path(elegida["archivo"])
    salida = Path(a.salida) if a.salida else clip.with_name(clip.stem + "_pista.m4a")

    if not a.json:
        print(f"REFERENCIA  {a.referencia} · {ref['bpm']} BPM · {', '.join(ref['terminos'])}")
        print("CANDIDATAS")
        for i, c in enumerate(ranking[:3], 1):
            marca = "←" if c["id"] == elegida["id"] else " "
            print(f"  {marca} {i}. {c['nota']:5.1f}  {c['nombre']}  "
                  f"[{c['origen']}]  {c['bpm']} BPM · {c['duracion']} s")
        print()

    inf = alinear(clip, pista, salida, a.tolerancia, json_out=False)

    if a.json:
        print(json.dumps({"referencia": a.referencia, "elegida": elegida,
                          "alineacion": inf, "ranking": ranking[:3]},
                         indent=2, ensure_ascii=False))
    else:
        print()
        print("Siguiente paso:")
        print(f'  bash publicar/publicar_clip.sh {clip} {salida} {a.referencia} "<caption propio>"')


if __name__ == "__main__":
    main()

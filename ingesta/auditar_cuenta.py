#!/usr/bin/env python3
"""¿Los números de esta cuenta son suyos, o están inflados?

Al estudiar un nicho se copia la forma de quien parece que gana. Si esa cuenta
tiene la audiencia comprada o apagada, se copia la forma equivocada y encima se
fija un listón inalcanzable que no corresponde a nada real. Esto lo separa.

El test es de CONSISTENCIA, no de tamaño: dadas F seguidores y unas piezas que
sacan L interacciones, ¿se pudo construir F publicando eso? Una cuenta que hace
92 likes por pieza no llega a 3,3 millones de seguidores por las suyas.

    python3 auditar_cuenta.py --seguidores 3300000 --likes 92,338
    python3 auditar_cuenta.py --seguidores 416000 --likes 16500 --comentarios 0
    python3 auditar_cuenta.py --nicho          # audita lo que haya en nicho.json

Las bandas son heurísticas, no ley: salen de lo que hemos medido nosotros y de
que la tasa sana baja al crecer la cuenta. Sirven para ordenar y para levantar
la ceja, no para acusar a nadie.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Tasa de interaccion (interacciones / seguidores) que cabe esperar de una
# cuenta viva, por tamano. Las cuentas grandes rinden menos en porcentaje: es
# normal y no es sospechoso por si solo. Lo sospechoso es caer un orden de
# magnitud por debajo del suelo de su tramo.
BANDAS = [
    (10_000,     0.030, 0.060),
    (100_000,    0.020, 0.035),
    (1_000_000,  0.012, 0.025),
    (float("inf"), 0.008, 0.018),
]

# Por debajo de esta fraccion del suelo de su tramo, los seguidores no se
# explican por el contenido que publica.
FACTOR_INFLADA = 0.10
FACTOR_SOSPECHOSA = 0.40


def banda(seguidores):
    for tope, suelo, techo in BANDAS:
        if seguidores <= tope:
            return suelo, techo
    return BANDAS[-1][1], BANDAS[-1][2]


def auditar(seguidores, interacciones, comentarios=None):
    """interacciones: lista de likes (o likes+guardados+compartidos) por pieza."""
    if not seguidores or not interacciones:
        raise ValueError("hacen falta seguidores y al menos una pieza medida")

    mediana = statistics.median(interacciones)
    tasa = mediana / seguidores
    suelo, techo = banda(seguidores)

    if tasa < suelo * FACTOR_INFLADA:
        veredicto = "inflada"
        porque = (f"{tasa:.4%} es menos de la decima parte del suelo de su tramo "
                  f"({suelo:.1%}). Con {mediana:,.0f} interacciones por pieza no se "
                  f"construyen {seguidores:,.0f} seguidores.")
    elif tasa < suelo * FACTOR_SOSPECHOSA:
        veredicto = "sospechosa"
        porque = (f"{tasa:.4%} queda muy por debajo del suelo de su tramo ({suelo:.1%}). "
                  f"Puede ser audiencia vieja y apagada, no necesariamente comprada.")
    elif tasa < suelo:
        veredicto = "floja"
        porque = f"{tasa:.4%}, por debajo del suelo esperado ({suelo:.1%}) pero en el orden."
    else:
        veredicto = "viva"
        porque = f"{tasa:.4%}, dentro o por encima de lo esperado ({suelo:.1%}-{techo:.1%})."

    # Una cuenta viva tiene piezas buenas y malas. Si todas rinden casi igual,
    # el numero puede no venir del contenido.
    dispersion = None
    if len(interacciones) >= 3:
        mx, mn = max(interacciones), max(min(interacciones), 1)
        dispersion = mx / mn
        if dispersion < 1.5 and veredicto == "viva":
            veredicto, porque = "sospechosa", (
                f"tasa normal pero todas las piezas rinden casi igual (x{dispersion:.1f} "
                f"entre la mejor y la peor). Una cuenta viva tiene mas varianza.")

    r = {"seguidores": seguidores, "piezas": len(interacciones),
         "mediana_interacciones": mediana, "tasa": round(tasa, 6),
         "suelo_esperado": suelo, "veredicto": veredicto, "porque": porque}
    if dispersion:
        r["dispersion"] = round(dispersion, 2)
    if comentarios:
        r["comentarios_por_100_likes"] = round(100 * statistics.median(comentarios) / max(mediana, 1), 2)
    return r


def del_nicho():
    d = json.loads((REPO / "assets" / "nicho.json").read_text())
    filas = []
    for p in d.get("piezas", []):
        seg, likes = p.get("seguidores"), p.get("likes")
        nombre = p.get("handle") or p.get("creador") or "?"
        if not seg or not likes:
            filas.append((nombre, None, "sin datos: falta 'seguidores' o 'likes'"))
            continue
        r = auditar(seg, [likes], [p["comentarios"]] if p.get("comentarios") else None)
        filas.append((nombre, r, None))
    return filas


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seguidores", type=int)
    ap.add_argument("--likes", help="interacciones por pieza, separadas por coma")
    ap.add_argument("--comentarios", help="comentarios por pieza, separados por coma")
    ap.add_argument("--nicho", action="store_true", help="audita assets/nicho.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.nicho:
        for nombre, r, err in del_nicho():
            if err:
                print(f"  {nombre:<24} —          {err}")
            else:
                print(f"  {nombre:<24} {r['veredicto']:<11} {r['tasa']:.4%}  ({r['mediana_interacciones']:,.0f} de {r['seguidores']:,.0f})")
        return

    if not (a.seguidores and a.likes):
        raise SystemExit("hacen falta --seguidores y --likes, o bien --nicho")

    likes = [float(x) for x in a.likes.split(",")]
    coms = [float(x) for x in a.comentarios.split(",")] if a.comentarios else None
    r = auditar(a.seguidores, likes, coms)
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return
    print(f"seguidores        {r['seguidores']:,}")
    print(f"piezas medidas    {r['piezas']}")
    print(f"mediana           {r['mediana_interacciones']:,.0f} interacciones")
    print(f"tasa              {r['tasa']:.4%}   (suelo del tramo: {r['suelo_esperado']:.1%})")
    if "dispersion" in r:
        print(f"dispersion        x{r['dispersion']}")
    print(f"\nVEREDICTO: {r['veredicto'].upper()}")
    print(f"  {r['porque']}")


if __name__ == "__main__":
    main()

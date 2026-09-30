#!/usr/bin/env python3
"""Las enmiendas: lo aprendido publicando, en un sitio que el constructor lee.

La diferencia entre esto y un documento es que aquí cada entrada **cambia el
prompt o la selección**. Si una enmienda no se aplica en ningún sitio, sobra.

    python3 enmiendas.py listar
    python3 enmiendas.py listar --aplica prompt
    python3 enmiendas.py anadir --id gancho_producto --origen run03 \
        --evidencia "..." --aplica prompt --regla "..."
    python3 enmiendas.py retirar entrada_corta --porque "probado y no movió la retención"
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

RUTA = Path(__file__).resolve().parent / "enmiendas.json"
CONTEXTO = Path(__file__).resolve().parent.parent / "contexto.json"
AMBITOS = ("prompt", "escena", "seleccion", "caption", "publicacion")


def vocabulario_del_producto():
    """Las palabras que nombran ESTE producto y su atrezzo.

    Una regla que las use deja de valer para el siguiente producto, y la
    herramienta se vuelve una herramienta de lámparas. El vocabulario sale de
    contexto.json, no de una lista fija: así el aviso se adapta solo a lo que
    se esté vendiendo.
    """
    import re
    if not CONTEXTO.exists():
        return set()
    ctx = json.loads(CONTEXTO.read_text())
    crudo = []
    prod = ctx.get("producto", {})
    crudo += [prod.get("nombre", "")] + list(prod.get("variantes", {}).values())
    atz = ctx.get("atrezzo") or {}
    crudo += [str(atz.get("tipo", "")), str(atz.get("tipo_en", ""))]
    palabras = set()
    for t in crudo:
        for w in re.findall(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ]{4,}", str(t)):
            palabras.add(w.lower())
    # Palabras que describen cualquier producto: no delatan a este.
    genericas = {"product", "producto", "shape", "same", "with", "that", "than",
                 "which", "carrying", "small", "flat", "into", "when", "turns",
                 "underneath", "centre", "round", "light", "colour", "warm",
                 "finish", "proportions", "matte", "black", "metal", "wider",
                 "bottom", "tall", "across", "widest", "lower", "face", "narrow",
                 "short", "plugs", "cylindrical", "luminous", "truncated", "cone",
                 "shaped", "brushed", "copper", "touch", "button"}
    return palabras - genericas


def avisar_si_no_es_general(regla):
    """No bloquea: avisa. Hay reglas que legítimamente nombran algo concreto."""
    import re
    vocab = vocabulario_del_producto()
    if not vocab:
        return
    hallados = sorted({w.lower() for w in re.findall(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ]{4,}", regla)
                       if w.lower() in vocab})
    if hallados:
        print("AVISO: la regla nombra cosas de ESTE producto: " + ", ".join(hallados),
              file=sys.stderr)
        print("  Una enmienda describe el problema general, no el objeto concreto.",
              file=sys.stderr)
        print("  Los datos van en «evidencia»; la regla tiene que valer para el "
              "siguiente producto o servicio.", file=sys.stderr)


def cargar():
    return json.loads(RUTA.read_text())


def guardar(d):
    RUTA.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")


def activas(aplica=None):
    """Lo que el constructor consume. Una enmienda retirada sigue escrita —el
    porqué de un experimento fallido vale tanto como el de uno bueno— pero no
    toca el prompt."""
    e = [x for x in cargar()["enmiendas"] if x.get("estado") == "activa"]
    return [x for x in e if not aplica or x["aplica_en"] == aplica]


def cmd_listar(a):
    for x in cargar()["enmiendas"]:
        if a.aplica and x["aplica_en"] != a.aplica:
            continue
        marca = "·" if x["estado"] == "activa" else "×"
        print(f"{marca} {x['id']:<26} [{x['aplica_en']:<11}] {x['fecha']} · {x['origen']}")
        print(f"    {x['regla']}")
        if a.verboso:
            print(f"    porque: {x['evidencia']}")
        print()


def cmd_anadir(a):
    d = cargar()
    if any(x["id"] == a.id for x in d["enmiendas"]):
        raise SystemExit(f"ya existe una enmienda con id «{a.id}»")
    if a.aplica not in AMBITOS:
        raise SystemExit(f"ámbito desconocido: {a.aplica} (hay: {', '.join(AMBITOS)})")
    avisar_si_no_es_general(a.regla)
    d["enmiendas"].append({
        "id": a.id, "fecha": date.today().isoformat(), "origen": a.origen,
        "evidencia": a.evidencia, "aplica_en": a.aplica, "regla": a.regla,
        "estado": "activa"})
    guardar(d)
    print(f"añadida «{a.id}» · la siguiente tirada ya la lleva")


def cmd_retirar(a):
    d = cargar()
    for x in d["enmiendas"]:
        if x["id"] == a.id:
            x["estado"] = "retirada"
            x["retirada_porque"] = a.porque
            x["retirada_el"] = date.today().isoformat()
            guardar(d)
            print(f"retirada «{a.id}» — se queda escrita, deja de aplicarse")
            return
    raise SystemExit(f"no existe «{a.id}»")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    l = sub.add_parser("listar"); l.add_argument("--aplica"); l.add_argument("--verboso", action="store_true")
    l.set_defaults(f=cmd_listar)

    n = sub.add_parser("anadir")
    for arg in ("--id", "--origen", "--evidencia", "--aplica", "--regla"):
        n.add_argument(arg, required=True)
    n.set_defaults(f=cmd_anadir)

    r = sub.add_parser("retirar"); r.add_argument("id"); r.add_argument("--porque", required=True)
    r.set_defaults(f=cmd_retirar)

    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()

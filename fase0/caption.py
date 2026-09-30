#!/usr/bin/env python3
"""El caption, con la referencia delante — para superarla, no para copiarla.

El reel de referencia que funcionó pedía algo explícitamente. El nuestro del
run 02 no pedía nada y se llevó 0 comentarios en las tres plataformas. Esto
arma el borrador con la estructura que sacamos de ahí y luego lo mide contra
la referencia antes de que salga.

    python3 caption.py borrador lemon_art_negro
    python3 caption.py revisar lemon_art_negro "Turn any empty bottle..."
"""

import argparse
import difflib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIMITES = {"instagram": 2200, "facebook": 2200, "tiktok": 2200, "youtube": 5000}
GENERICOS = {"#love", "#instagood", "#photooftheday", "#follow", "#like", "#viral", "#fyp"}


def cargar(p):
    return json.loads(Path(p).read_text())


def caption_referencia(ident):
    vids = cargar(REPO / "assets" / "videos.json")
    lista = vids if isinstance(vids, list) else vids.get("videos", [])
    for v in lista:
        if v.get("id") == ident:
            return v.get("caption_original") or ""
    return ""


def regla_caption():
    e = cargar(REPO / "fase0" / "enmiendas.json")["enmiendas"]
    for x in e:
        if x["aplica_en"] == "caption" and x["estado"] == "activa":
            return x["regla"]
    return ""


def cmd_borrador(a):
    """El esqueleto sale de contexto.json, no de un texto escrito a mano: si el
    producto cambia, cambia el borrador. Lo que no sale del contexto se marca
    como hueco en vez de inventarse."""
    ctx = cargar(REPO / "contexto.json")
    prod = ctx["producto"]
    obj = prod.get("objeciones_que_el_clip_debe_resolver", [])
    etiquetas = (ctx.get("publicacion") or {}).get("hashtags") or []
    ref = caption_referencia(a.referencia)

    print(f"REFERENCIA (no se copia, se supera)\n  {ref or '—'}\n")
    print(f"REGLA EN VIGOR\n  {regla_caption()}\n")
    print("ESQUELETO — cada línea sale del contexto del producto")
    print(f"  1 · gancho     el resultado que promete: «{prod.get('propuesta', '—')}»")
    if obj:
        for o in obj:
            izq = o.split("->")[0].strip()
            der = o.split("->")[1].strip() if "->" in o else ""
            print(f"  2 · objeción   {izq}" + (f"  (se ve así: {der})" if der else ""))
    else:
        print("  2 · objeción   HUECO: contexto.json no declara objeciones a resolver")
    print( "  3 · petición   una pregunta concreta y contestable, no «¿qué te parece?»")
    if etiquetas:
        print(f"  4 · hashtags   {' '.join(etiquetas)}")
    else:
        print("  4 · hashtags   HUECO: añade publicacion.hashtags al contexto; "
              "los genéricos no traen a nadie")
    print("\nLa redacción es tuya o mía, pero con esta estructura y sin copiar la referencia.")


def cmd_revisar(a):
    ref = caption_referencia(a.referencia)
    texto = a.texto
    fallos, avisos = [], []

    parecido = difflib.SequenceMatcher(None, texto.lower(), ref.lower()).ratio() if ref else 0.0
    if parecido >= 0.40:
        fallos.append(f"se parece demasiado al de la referencia ({parecido:.2f}); reescríbelo")

    if "?" not in texto:
        fallos.append("no pide nada: sin pregunta ni petición, no hay comentarios")

    etiquetas = [p for p in texto.split() if p.startswith("#")]
    if not etiquetas:
        avisos.append("sin hashtags")
    genericos = [h for h in etiquetas if h.lower() in GENERICOS]
    if genericos:
        avisos.append(f"hashtags genéricos que no traen a nadie: {', '.join(genericos)}")

    for plat, tope in LIMITES.items():
        if len(texto) > tope:
            fallos.append(f"{len(texto)} caracteres: pasa del tope de {plat} ({tope})")

    print(f"parecido con la referencia   {parecido:.2f}   {'FALLO' if parecido >= 0.40 else 'OK'}")
    print(f"pide algo                    {'sí' if '?' in texto else 'NO'}")
    print(f"longitud                     {len(texto)} caracteres")
    print(f"hashtags                     {len(etiquetas)}")
    for f in fallos:
        print(f"  FALLO · {f}")
    for w in avisos:
        print(f"  aviso · {w}")
    print("\nCAPTION: " + ("FALLO" if fallos else "OK"))
    raise SystemExit(1 if fallos else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("borrador"); b.add_argument("referencia"); b.set_defaults(f=cmd_borrador)
    r = sub.add_parser("revisar"); r.add_argument("referencia"); r.add_argument("texto")
    r.set_defaults(f=cmd_revisar)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()

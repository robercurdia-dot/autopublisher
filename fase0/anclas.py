#!/usr/bin/env python3
"""Qué le toca anclar a cada referencia que entra en la generación.

El error de fondo del run 05 fue tratar la referencia como documentación: leerla,
comprimirla a texto y generar a ciegas. El modelo nunca la vio. La referencia es
ENTRADA del modelo; el prompt es la capa de ajuste encima, y su trabajo es decir
QUÉ SE TOMA DE CADA UNA.

Eso solo se puede decir si cada referencia declara su papel, porque no todas
pueden anclar lo mismo: una referencia cuyo producto original es otro no puede
anclar el producto por mucho que el montaje sea perfecto. Sin esta declaración
el prompt tiene que describirlo todo en prosa, y la prosa fija formas pero no
cotas.

Los papeles son genéricos a propósito: valen para un producto físico, para un
servicio o para una pieza con actor, porque describen QUÉ CAPA aporta la
referencia, no de qué va el negocio.
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Qué está autorizada a anclar cada clase de referencia, y qué tiene prohibido
# aportar. Lo prohibido importa tanto como lo permitido: una referencia entra
# entera en el modelo, así que lo que no se le acota, lo aporta igual.
PAPELES = {
    "directa": {
        "ancla": "the shot structure, the cutting rhythm, the camera framing, "
                 "the hand choreography and the product itself",
        "veta": "the set decor, the printed text, the on-screen captions",
        "explica": "misma familia de producto y mismo acabado: puede anclarlo todo",
    },
    "estructura": {
        "ancla": "the shot structure, the cutting rhythm, the camera framing and "
                 "the hand choreography",
        "veta": "the product, its finish, its proportions, the set decor, the "
                "printed text, the on-screen captions",
        "explica": "producto o acabado distintos: monta como ella, pero el producto NO sale de aquí",
    },
    "plano": {
        "ancla": "the camera framing, the lens feel and the camera movement",
        "veta": "the product, the set decor, the pacing, the printed text",
        "explica": "solo encuadre y movimiento de cámara",
    },
    "interpretacion": {
        "ancla": "the performer's energy, gestures, delivery and eyeline",
        "veta": "the product, the set decor, the printed text, the wardrobe",
        "explica": "la persona: cómo actúa. Nunca el producto ni la escena",
    },
}

# El producto no es una referencia más: es la única que fija las cotas. Va
# siempre, en toda generación, y se nombra aparte para que no compita con el
# resto por atención.
ANCLA_PRODUCTO = (
    "is the PRODUCT itself. Its silhouette, its proportions, the length of every "
    "part and the relation between them are defined HERE and nowhere else. Every "
    "single shot must match it. Where the reference video and this image disagree "
    "about the product, this image wins.")


def catalogo():
    return {v["id"]: v for v in json.loads((REPO / "assets" / "videos.json").read_text())["videos"]}


def papel_de(ident, variante=None, cat=None):
    """El papel declarado, degradado si la variante pedida no es la de la referencia.

    Una referencia «directa» deja de serlo en cuanto pedimos un acabado que ella
    no tiene: sigue sirviendo para montar, pero ya no puede decir cómo es el
    producto. Degradar esto solo es justo el fallo del run 05 al revés.
    """
    v = (cat or catalogo())[ident]
    papel = v.get("papel", "estructura")
    motivo = None
    if papel == "directa" and variante and v.get("acabado_topper") not in (None, variante):
        papel, motivo = "estructura", (
            f"la referencia es {v['acabado_topper']} y la tirada es {variante}")
    return papel, motivo


def bloque(entradas):
    """El bloque ANCHORS del prompt.

    `entradas` es la lista en el MISMO orden en que se adjuntan al proveedor,
    porque los anclajes se citan por posición (@Video1, @Image1). Si el orden
    del payload y el del prompt se separan, el prompt ancla a la referencia
    equivocada y no hay forma de notarlo mirando el resultado.
    """
    lineas = ["ANCHORS — what each attached reference is for:"]
    nv = ni = 0
    for e in entradas:
        if e["clase"] == "video":
            nv += 1
            p = PAPELES[e["papel"]]
            lineas.append(f"  @Video{nv} — take from it ONLY: {p['ancla']}.")
            lineas.append(f"  @Video{nv} — do NOT take from it: {p['veta']}.")
        else:
            ni += 1
            if e["papel"] == "producto":
                lineas.append(f"  @Image{ni} — {ANCLA_PRODUCTO}")
            else:
                p = PAPELES[e["papel"]]
                lineas.append(f"  @Image{ni} — take from it ONLY: {p['ancla']}.")
    return "\n".join(lineas)


if __name__ == "__main__":
    cat = catalogo()
    print(f"{'referencia':<26}{'papel':<16}nota")
    for ident, v in cat.items():
        p, motivo = papel_de(ident, cat=cat)
        print(f"{ident:<26}{p:<16}{PAPELES[p]['explica']}")

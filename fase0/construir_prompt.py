#!/usr/bin/env python3
"""Construye el prompt a partir de la ficha de la referencia. No sabe qué vendemos.

Tres fuentes, cada una con su papel:

  ficha de la referencia  ->  QUÉ acción vertebra el vídeo, en cuántos planos y
                              sobre cuántas unidades de atrezzo
  contexto.json           ->  QUÉ producto es el nuestro y qué no queremos ver
  marcas/brands.json      ->  QUÉ atrezzo concreto toca esta vez

Nada de esto está escrito para una lámpara. Si mañana vendemos otra cosa, se
cambia contexto.json; si la referencia es otra, la ficha manda otra estructura.

Dos reglas que salen de la propia referencia y no se negocian:
  1. Tantas unidades de atrezzo como tenga la referencia — la variedad ES el
     argumento de venta, no decoración.
  2. La acción se completa en pantalla. El estado final de la ficha se repite al
     final del prompt para que el modelo no se quede a medias.

Uso:
    python3 construir_prompt.py lemon_art_negro
    python3 construir_prompt.py lemon_art_negro --variante cobre --semilla 3
    python3 construir_prompt.py lemon_art_negro --guardar
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FICHAS = REPO / "assets" / "informes" / "fichas"
PROMPTS = REPO / "fase0" / "prompts"


import anclas  # noqa: E402


def cargar(p):
    return json.loads(Path(p).read_text())


def enmiendas_activas(aplica=None):
    """Lo aprendido publicando. Vive en fase0/enmiendas.json y se lee SIEMPRE:
    el constructor no debe depender de que alguien recuerde una corrección."""
    ruta = REPO / "fase0" / "enmiendas.json"
    if not ruta.exists():
        return []
    e = [x for x in cargar(ruta).get("enmiendas", []) if x.get("estado") == "activa"]
    return [x for x in e if not aplica or x["aplica_en"] == aplica]


def aplica_a(enmienda, lectura):
    """Una corrección sacada de piezas sin cara no tiene por qué valer en una con
    cara: la de «entrada corta» salió midiendo clips donde el gancho era el
    producto, y aquí el gancho es la persona."""
    cond = enmienda.get("aplica_si")
    if not cond:
        return True
    for campo, permitidos in cond.items():
        if lectura.get(campo) not in permitidos:
            return False
    return True


def historial(cuantas=3):
    """Qué atrezzo y qué escena llevaron las últimas piezas. Dos clips seguidos
    con las mismas botellas se leen como el mismo clip, que es exactamente lo
    que penaliza la norma de contenido no original."""
    metas = sorted(PROMPTS.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    atrezzo, escenas = [], []
    for f in metas[:cuantas]:
        try:
            d = cargar(f)
        except json.JSONDecodeError:
            continue
        atrezzo += d.get("atrezzo", [])
        if d.get("escena"):
            escenas.append(d["escena"])
    return {"atrezzo": atrezzo, "escenas": escenas}


# Los bloques de marcas/brands.json se escribieron para prompts de UNA botella
# ("Change the bottles: every bottle that receives..."). Aquí hay varias y cada
# una es distinta, así que se les quita el mandato y se deja la descripción.
_PREFIJO = re.compile(r"^.*?\bis a real\b", re.I | re.S)


# Run 02: pedir "sharp and legible" en una etiqueta no la hace legible, la hace
# INVENTADA con aplomo — salió "BOMBAY SAPPAIRE" y "HENDRICK'S GII". Se quita la
# exigencia del bloque y se sustituye por una regla honesta en el prompt.
_LEGIBLE = re.compile(r",?\s*(?:the [a-z ]+ must stay |and )?sharp and legible\.?", re.I)


def limpiar_bloque(t, con_imagen=False):
    t = _PREFIJO.sub("A real", t.strip(), count=1)
    t = _LEGIBLE.sub(".", t)
    # "exactly as in the reference image" solo vale si esa imagen va de verdad en
    # la generacion. Si no, el modelo busca algo que no le hemos dado.
    if not con_imagen:
        t = re.sub(r",?\s*exactly as in the [^-,.]*image\s*", " ", t, flags=re.I)
        t = re.sub(r"^\s*-\s*", "", t)
    return re.sub(r"\s+", " ", t).replace(" -", " —", 1).strip()


PERSONAS = {
    "ninguna": "no people at all",
    "manos": "hands only, no face in frame",
    "cuerpo": "a person's body, no face in frame",
    # Cuando hay cara, la cara es la de la foto de referencia y no se negocia: es
    # el mismo principio que el producto, una identidad que no puede derivar.
    "cara visible": ("the person from the reference photo and nobody else — keep their face, "
                     "hair, build and skin exactly as in that photo, in every frame"),
}


def proporcion(txt):
    """720:1280 -> 9:16."""
    try:
        a, b = (int(x) for x in str(txt).split(":"))
    except (ValueError, AttributeError):
        return txt
    from math import gcd
    g = gcd(a, b) or 1
    return f"{a // g}:{b // g}"


def elegir_atrezzo(cuantas, semilla, excluir=(), biblioteca=None):
    marcas = cargar(REPO / (biblioteca or "marcas/brands.json"))
    marcas = marcas if isinstance(marcas, list) else marcas.get("marcas", [])
    # «bloque» es el nombre bueno; «bloque_botella» se acepta por las bibliotecas
    # viejas. El motor no debe saber que lo que hay dentro son botellas.
    validas = [m for m in marcas
               if (m.get("bloque") or m.get("bloque_botella")) and m["id"] not in excluir]
    if len(validas) < cuantas:
        raise SystemExit(f"la referencia pide {cuantas} unidades y solo hay {len(validas)}")
    return random.Random(semilla).sample(validas, cuantas)


def construir(ident, variante=None, semilla=0, excluir=(), duracion=None):
    ficha = cargar(FICHAS / f"{ident}.json")
    if not ficha.get("lectura"):
        raise SystemExit(f"la ficha de «{ident}» no tiene lectura: "
                         f"pásala por un modelo de visión (fichar_referencia.py --esquema)")
    ctx = cargar(REPO / "contexto.json")
    L = ficha["lectura"]

    variantes = ctx["producto"]["variantes"]
    # La variante por defecto se declara, no se deduce. Salía por orden
    # alfabético, y eso metió el run 05 en cobre -la única sin foto de producto-
    # sin que nadie lo decidiera.
    variante = variante or ctx["producto"].get("variante_por_defecto") or sorted(variantes)[0]
    if variante not in variantes:
        raise SystemExit(f"variante desconocida: {variante} (hay: {', '.join(variantes)})")

    # Lo que el producto toca es lo que se varía. El tipo lo dicta la referencia
    # (botella, taza, lo que sea) y la biblioteca de dónde sacarlo, contexto.json.
    # Si no cuadran, no se inventa: el clip iría de otra cosa.
    interactua = next((o for o in L["objetos"] if o["papel"] == "interactua"), None)
    atz = ctx.get("atrezzo") or {}
    tipo_ctx = atz.get("tipo")

    # Un servicio no tiene objeto que intercambiar: se vende una acción, no una
    # cosa. En ese caso la variedad sale del escenario y del encuadre, y el
    # bloque de soportes no existe. Que el motor lo exija sería atarlo a
    # productos físicos, que es justo lo que no queremos.
    servicio = not tipo_ctx
    if servicio:
        if interactua:
            print(f"aviso: la referencia interactúa con «{interactua['tipo']}» pero el contexto "
                  f"no tiene biblioteca; se varía solo el escenario", file=sys.stderr)
        unidades = 0
        atrezzo = []
    else:
        if not interactua:
            raise SystemExit(
                f"la lectura de «{ident}» no marca ningún elemento con papel «interactua»\n"
                f"  y contexto.json sí tiene biblioteca de «{tipo_ctx}»: o falta la lectura,\n"
                f"  o esta referencia no sirve para este producto.")
        if interactua["tipo"] != tipo_ctx:
            raise SystemExit(
                f"la referencia interactúa con «{interactua['tipo']}» y contexto.json tiene\n"
                f"  biblioteca de «{tipo_ctx}». O la referencia no vale para este producto,\n"
                f"  o hay que darle a contexto.json una biblioteca de «{interactua['tipo']}».")
        unidades = interactua["cantidad"]
    reglas = [x for x in enmiendas_activas() if aplica_a(x, L)]
    # Una enmienda se aplica por su EFECTO declarado, no porque el código
    # reconozca su id. Así una regla nueva funciona sin tocar el motor.
    efectos = {}
    for x in reglas:
        efectos.update(x.get("efecto") or {})
    previo = historial()

    if not servicio:
        unidades += int(efectos.get("unidades_extra", 0))
        # El guion manda: describir soportes que ningún plano usa es ruido que el
        # modelo acaba metiendo por su cuenta.
        usadas = {g["unidad"] for g in L["guion"] if g.get("unidad") is not None}
        if usadas:
            unidades = min(unidades, max(len(usadas), max(usadas) + 1))
    if efectos.get("no_repetir"):
        excluir = tuple(set(excluir) | set(previo["atrezzo"]))

    try:
        if not servicio:
            atrezzo = elegir_atrezzo(unidades, semilla, excluir, atz.get("biblioteca"))
    except SystemExit:
        # El catálogo manda sobre las enmiendas: antes repetir una botella que
        # quedarse sin pieza. Se afloja primero la exclusión, luego el aumento.
        try:
            atrezzo = elegir_atrezzo(unidades, semilla, (), atz.get("biblioteca"))
        except SystemExit:
            unidades -= 1
            atrezzo = elegir_atrezzo(unidades, semilla, (), atz.get("biblioteca"))
    fases = L["accion"]["fases"]

    lineas = []
    dur = duracion or ficha["duracion"]
    lineas.append(f"{dur:.0f} second vertical {proporcion(ficha.get('proporcion', '9:16'))} "
                  f"product video, {len(ficha['planos'])} shots, no on-screen text.")
    lineas.append("")

    # Las referencias ENTRAN en la generación; el prompt solo dice qué se toma de
    # cada una. Va lo primero porque el modelo debe saber para qué son los
    # adjuntos antes de leer nada más. El orden de esta lista es el orden exacto
    # en que hay que adjuntarlas al proveedor: los anclajes se citan por posición.
    papel_ref, degradado = anclas.papel_de(ident, variante)
    entradas = [{"clase": "video", "papel": papel_ref, "ref": ident,
                 "archivo": f"assets/{cargar(REPO / 'assets' / 'videos.json')['videos'][0]['archivo']}"}]
    entradas[0]["archivo"] = "assets/" + next(
        v["archivo"] for v in cargar(REPO / "assets" / "videos.json")["videos"] if v["id"] == ident)
    foto = (ctx["producto"].get("fotos") or {}).get(variante)
    if not foto:
        raise SystemExit(
            f"contexto.json no tiene foto del producto para la variante «{variante}».\n"
            f"  La enmienda «foto_de_producto_obligatoria» la exige: la prosa fija la forma\n"
            f"  general pero no las cotas. Añádela en producto.fotos.{variante}")
    entradas.append({"clase": "imagen", "papel": "producto", "archivo": foto})
    if degradado:
        print(f"aviso: «{ident}» baja de directa a estructura ({degradado}): "
              f"el producto lo ancla solo la foto", file=sys.stderr)
    lineas.append(anclas.bloque(entradas))
    lineas.append("")
    lineas.append("PRODUCT — identical in every single shot, this is what is being sold:")
    lineas.append(variantes[variante])
    lineas.append("")
    if atrezzo:
        tipo_en = atz.get("tipo_en", "object")
        plural = "s" if unidades != 1 else ""
        cabecera = (f"SUPPORT — one {tipo_en}:" if unidades == 1 else
                    f"SUPPORTS — {unidades} different {tipo_en}{plural}, one per cycle. "
                    f"Each must be clearly distinct from the others:")
        lineas.append(cabecera)
        for i, m in enumerate(atrezzo):
            bloque = m.get("bloque") or m.get("bloque_botella")
            lineas.append(f"  [{i + 1}] {limpiar_bloque(bloque)}")
        lineas.append("")
    lineas.append("ACTION — the point of the video, and it MUST be completed on screen:")
    lineas.append(f"  {L['accion']['verbo']}. It starts with {L['accion']['estado_inicial']} "
                  f"and is only finished when {L['accion']['estado_final']}.")
    lineas.append("")
    # Una enmienda que contradice al guion no sirve de nada: si «entrada_corta»
    # está activa, la presentación se comprime y el resto se reparte el tiempo
    # que queda. Antes salía un prompt que pedía el soporte antes del segundo 2
    # y a la vez listaba tres segundos de presentación.
    tiempos = {x["plano"]: (x["desde"], x["hasta"]) for x in ficha["planos"]}
    tope_entrada = 1.5 if any(x["id"] == "entrada_corta" for x in reglas) else None
    if tope_entrada:
        previos = [g["plano"] for g in L["guion"] if g.get("unidad") is None]
        resto = [g["plano"] for g in L["guion"] if g.get("unidad") is not None]
        if previos and resto:
            corte = tope_entrada / max(len(previos), 1)
            t = 0.0
            for i, n in enumerate(previos):
                tiempos[n] = (round(t, 2), round(t + corte, 2)); t += corte
            largo_viejo = sum(tiempos[n][1] - tiempos[n][0] for n in resto) or 1
            escala = (dur - tope_entrada) / largo_viejo
            for n in resto:
                d = (tiempos[n][1] - tiempos[n][0]) * escala
                tiempos[n] = (round(t, 2), round(t + d, 2)); t += d

    lineas.append("SHOTS:")
    for g in L["guion"]:
        p = next((x for x in ficha["planos"] if x["plano"] == g["plano"]), None)
        if not p:
            continue
        p = dict(p)
        p["desde"], p["hasta"] = tiempos[g["plano"]]
        texto = fases.get(g["fase"], L["accion"]["fases"].get("cierre")) or \
            f"hold on the finished state: {L['accion']['estado_final']}"
        # Una enmienda puede reemplazar lo que se ve en la entrada, no solo cuanto
        # dura. Abrir con el producto en la mano es enseñar la respuesta antes de
        # que nadie se haya hecho la pregunta; se abre por el estado que el
        # espectador ya reconoce en su casa.
        if efectos.get("abrir_con") == "estado_inicial" and g.get("unidad") is None:
            texto = (f"open on the situation the viewer already recognises as their own: "
                     f"{L['accion']['estado_inicial']}. What is being sold is NOT in frame yet")
        soporte = f" — support [{g['unidad'] + 1}]" if g.get("unidad") is not None else ""
        lineas.append(f"  {g['plano'] + 1}. ({p['desde']:.2f}–{p['hasta']:.2f}s, "
                      f"{g.get('encuadre', 'medium')}) {texto}{soporte}")
    lineas.append("")
    escena = L["escenario"]
    cambio = None
    variantes_escena = ctx.get("variacion_escena") or []
    if variantes_escena:
        # Run 02: copiar la escena de la referencia subió el parecido visual de
        # 0,588 a 0,667, a un pelo del umbral. Se ancla el TIPO de sitio y se
        # cambian los objetos, que es lo que identifica al clip ajeno.
        libres = ([v for v in variantes_escena if v not in previo["escenas"]]
                  if efectos.get("no_repetir") else variantes_escena) or variantes_escena
        cambio = random.Random(semilla + 101).choice(libres)
        # El tipo de sitio se hereda; los objetos concretos de la referencia NO se
        # nombran, o el modelo los reproduce y volvemos a parecernos a ella.
        # Nombrar el decorado de la referencia, aunque sea para prohibirlo, es
        # pedirle al modelo que lo piense. No se nombra.
        lineas.append(f"SETTING: {cambio}. Do not reuse the decor of the reference video.")
    else:
        lineas.append(f"SETTING: {escena}.")
    lineas.append(f"LIGHT: {L['iluminacion']}.")
    lineas.append(f"PEOPLE: {PERSONAS.get(L['personas'], L['personas'])}.")
    de_prompt = [x for x in reglas if x["aplica_en"] == "prompt"]
    if de_prompt:
        lineas.append("")
        lineas.append("CORRECTIONS — learned from what we have already published:")
        for x in de_prompt:
            lineas.append(f"  {x['regla']}")
    lineas.append("")
    lineas.append(f"END STATE, non negotiable: {L['accion']['estado_final']}.")
    lineas.append("")
    lineas.append("NEGATIVE: " + "; ".join(ctx["negativos"]) + ".")

    return "\n".join(lineas), {
        "referencia": ident, "variante": variante, "semilla": semilla,
        "unidades": unidades, "atrezzo": [m["id"] for m in atrezzo],
        "escena": cambio if variantes_escena else None,
        "planos": len(ficha["planos"]),
        "duracion": round(dur, 2),
        "duracion_referencia": ficha["duracion"],
        "enmiendas": [x["id"] for x in reglas],
        "entradas": entradas,
        "papel_referencia": papel_ref,
        "evitado": {"atrezzo": previo["atrezzo"], "escenas": previo["escenas"]},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("referencia")
    ap.add_argument("--variante", help="variante del producto (contexto.json)")
    ap.add_argument("--semilla", type=int, default=0, help="cambia el atrezzo sin tocar nada más")
    ap.add_argument("--excluir", default="", help="ids de marcas a evitar, separados por coma")
    ap.add_argument("--duracion", type=float,
                    help="segundos de la pieza; por defecto los de la referencia. "
                         "Queda escrito en el plan para poder verificarlo después.")
    ap.add_argument("--guardar", action="store_true")
    a = ap.parse_args()

    excluir = tuple(x.strip() for x in a.excluir.split(",") if x.strip())
    texto, meta = construir(a.referencia, a.variante, a.semilla, excluir, a.duracion)
    print(texto)
    if a.guardar:
        PROMPTS.mkdir(parents=True, exist_ok=True)
        nombre = f"{a.referencia}_{meta['variante']}_s{a.semilla}"
        (PROMPTS / f"{nombre}.txt").write_text(texto + "\n")
        (PROMPTS / f"{nombre}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        print(f"\n--- guardado en fase0/prompts/{nombre}.txt")


if __name__ == "__main__":
    main()

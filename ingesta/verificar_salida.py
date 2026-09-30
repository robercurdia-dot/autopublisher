#!/usr/bin/env python3
"""¿El clip generado hizo lo que el prompt pedía? Medido, no mirado.

Pagamos por cada tirada y luego comprobamos el resultado a ojo. Esto compara lo
que la ficha del prompt PIDIÓ con lo que el vídeo ENTREGÓ, en lo que se puede
medir sin opinión: duración, número de planos, longitud de la entrada y cuántos
soportes distintos aparecen — esto último no se puede contar solo, así que se
pregunta y se registra.

    python3 verificar_salida.py salida.mp4 --plan lemon_art_negro_negro_mate_s7
    python3 verificar_salida.py salida.mp4 --plan ref_tom_montada_negro_mate_s3 --json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
REPO = RAIZ.parent
sys.path.insert(0, str(RAIZ))
from analizar_referencia import cortes, datos_video  # noqa: E402

# Cuánto puede desviarse cada cosa antes de considerarlo incumplido. No son
# caprichos: la duración la fija el modelo y siempre baila unas décimas; el
# número de planos depende del detector de cortes y admite uno de margen.
TOLERANCIA = {"duracion_s": 0.6, "planos": 1}

# La silueta del producto es lo único que no puede derivar entre planos, y es
# justo lo que no se mide solo. En el run 05 el producto cambió de forma cuatro
# veces dentro del mismo clip y se dio por bueno porque nadie lo miró plano a
# plano. Así que el verificador no pregunta: monta la tira y obliga a mirarla.
# La banda es la zona de pantalla donde vive el producto, declarada en
# contexto.json; sin declarar, se usa el fotograma entero.
BANDAS = {"superior": "iw:ih/2:0:0", "centro": "iw:ih/2:0:ih/4",
          "inferior": "iw:ih/2:0:ih/2", "completo": None}


def tira_producto(salida, ts, duracion, destino, zona="completo"):
    """Un fotograma por plano, recortado a donde vive el producto, en mosaico.

    Mirar el clip entero no sirve: la deriva se ve comparando los planos entre
    sí, no viéndolos pasar. El mosaico los pone uno al lado del otro.
    """
    medios = [(a + b) / 2 for a, b in zip([0.0] + list(ts), list(ts) + [duracion])]
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.parent / "_planos"
    tmp.mkdir(exist_ok=True)
    for viejo in tmp.glob("*.jpg"):
        viejo.unlink()

    crop = BANDAS.get(zona)
    for i, t in enumerate(medios):
        vf = f"crop={crop},scale=480:-1" if crop else "scale=480:-1"
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-ss", f"{t:.2f}", "-i", str(salida),
                        "-frames:v", "1", "-vf", vf, str(tmp / f"{i:02d}.jpg")],
                       check=True, capture_output=True)

    cols = min(3, len(medios))
    filas = -(-len(medios) // cols)
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", str(tmp / "%02d.jpg"),
                    "-vf", f"tile={cols}x{filas}:padding=6:color=white", "-frames:v", "1",
                    str(destino)], check=True, capture_output=True)
    return destino, len(medios)


def cargar(p):
    return json.loads(Path(p).read_text())


def verificar(salida, plan_id):
    meta = cargar(REPO / "fase0" / "prompts" / f"{plan_id}.json")
    ficha = cargar(REPO / "assets" / "informes" / "fichas" / f"{meta['referencia']}.json")
    L = ficha.get("lectura") or {}

    info = datos_video(salida)
    ts = cortes(salida)
    planos = len(ts) + 1
    entrada = ts[0] if ts else info["duracion"]

    pedido = {
        "duracion_s": meta.get("duracion"),
        "planos": meta.get("planos"),
        "unidades": meta.get("unidades"),
        "entrada_max_s": None,
    }
    # Si estaba activa la enmienda de entrada corta, el plano 0 tiene un tope.
    if "entrada_corta" in (meta.get("enmiendas") or []):
        pedido["entrada_max_s"] = 1.5

    entregado = {"duracion_s": round(info["duracion"], 2), "planos": planos,
                 "entrada_s": round(entrada, 2)}

    ctx = cargar(REPO / "contexto.json")
    tira = REPO / "assets" / "informes" / "planos" / plan_id / "producto.jpg"
    tira_producto(salida, ts, info["duracion"], tira,
                  ctx.get("zona_producto", "completo"))

    filas = []

    d_ok = abs(entregado["duracion_s"] - (pedido["duracion_s"] or 0)) <= TOLERANCIA["duracion_s"]
    filas.append(("duración", f"{pedido['duracion_s']} s", f"{entregado['duracion_s']} s", d_ok))

    p_ok = abs(planos - (pedido["planos"] or 0)) <= TOLERANCIA["planos"]
    filas.append(("planos", pedido["planos"], planos, p_ok))

    if pedido["entrada_max_s"]:
        e_ok = entregado["entrada_s"] <= pedido["entrada_max_s"] + 0.3
        filas.append(("entrada", f"≤{pedido['entrada_max_s']} s", f"{entregado['entrada_s']} s", e_ok))

    # Lo que no se mide solo se deja escrito para que lo mire una persona, en vez
    # de dar por bueno lo que nadie ha comprobado.
    a_ojo = [
        f"LA SILUETA DEL PRODUCTO, plano a plano: {tira.relative_to(REPO)}",
        (f"¿aparece 1 soporte?" if pedido.get("unidades") == 1 else
         f"¿aparecen {pedido['unidades']} soportes distintos?") if pedido.get("unidades") else None,
        f"¿la acción se cierra? debe acabar con: {L.get('accion', {}).get('estado_final', '—')}",
        "¿hay texto impreso inventado en cuadro?",
    ]
    return filas, [x for x in a_ojo if x], {"pedido": pedido, "entregado": entregado}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("salida")
    ap.add_argument("--plan", required=True, help="id del prompt en fase0/prompts")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    filas, a_ojo, crudo = verificar(Path(a.salida), a.plan)
    if a.json:
        print(json.dumps({"medido": [{"que": f[0], "pedido": f[1], "entregado": f[2], "ok": f[3]}
                                     for f in filas], "a_ojo": a_ojo, **crudo},
                         indent=2, ensure_ascii=False, default=str))
        raise SystemExit(0 if all(f[3] for f in filas) else 1)

    print(f"{'qué':<12}{'pedido':>12}{'entregado':>14}   veredicto")
    for que, ped, ent, ok in filas:
        print(f"{que:<12}{str(ped):>12}{str(ent):>14}   {'OK' if ok else 'INCUMPLE'}")
    print("\nA ojo, esto no lo mide nadie:")
    for x in a_ojo:
        print(f"  · {x}")
    todo = all(f[3] for f in filas)
    print(f"\nLO MEDIBLE: {'OK' if todo else 'INCUMPLE'}")
    raise SystemExit(0 if todo else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Busca, entre los sonidos disponibles, el más parecido al de una referencia.

El generador devuelve vídeo mudo siempre. Este nodo decide QUÉ sonido le ponemos:
mide el de la referencia (perfil_musical.py), mide cada candidato del catálogo y
los ordena por parecido. La elección final la aprueba una persona.

El catálogo es assets/musica/catalogo.json: una lista de entradas con el fichero
de audio en disco y de dónde sale (Colección de sonidos de Meta, o un sonido de
Instagram cuya vista previa se ha capturado). Ver assets/musica/LEEME.md.

Uso:
    python3 buscar_sonido.py lemon_art_negro
    python3 buscar_sonido.py lemon_art_negro --top 5 --json
"""

import argparse
import json
from pathlib import Path

import numpy as np

from perfil_musical import AUDIO, INFORMES, REPO, descripcion, perfil

MUSICA = REPO / "assets" / "musica"
CATALOGO = MUSICA / "catalogo.json"
INDICE = MUSICA / "indice.json"

# Cuánto pesa cada rasgo. El tempo manda porque es lo que decide si el montaje
# se puede alinear; el timbre va detrás porque es lo que hace que "suene igual".
PESOS = {"tempo": 0.35, "timbre": 0.30, "brillo": 0.15, "golpes": 0.10, "dinamica": 0.10}


def dist_tempo(a, b):
    """Tolerante a la octava: 60 y 120 BPM son el mismo pulso contado distinto."""
    if not a or not b:
        return 1.0
    d = min(abs(np.log2((b * m) / a)) for m in (0.5, 1, 2))
    return float(min(d / 0.25, 1.0))          # 0,25 octavas ≈ 19 % de tempo


def dist_timbre(a, b):
    a, b = np.array(a), np.array(b)
    cos = float(a @ b / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1))
    return float(min(max(1 - cos, 0.0) / 0.15, 1.0))


def dist_rel(a, b, escala):
    if not a or not b:
        return 1.0
    return float(min(abs(np.log2(b / a)) / escala, 1.0))


def parecido(ref, cand):
    d = {
        "tempo": dist_tempo(ref["bpm"], cand["bpm"]),
        "timbre": dist_timbre(ref["bandas"], cand["bandas"]),
        "brillo": dist_rel(ref["brillo_hz"], cand["brillo_hz"], 1.0),
        "golpes": dist_rel(ref["golpes_por_s"], cand["golpes_por_s"], 1.0),
        "dinamica": float(min(abs(ref["dinamica"] - cand["dinamica"]) / 0.5, 1.0)),
    }
    total = sum(PESOS[k] * v for k, v in d.items())
    return round((1 - total) * 100, 1), {k: round(v, 3) for k, v in d.items()}


def usadas(cuantas=3):
    """Pistas de las últimas piezas publicadas. Repetir música es repetir pieza
    a oídos de cualquiera que nos siga, y a efectos de contenido no original."""
    bd = REPO / "db" / "jobs.db"
    if not bd.exists():
        return []
    import sqlite3
    con = sqlite3.connect(bd)
    filas = con.execute(
        "SELECT DISTINCT audio_fuente FROM publicaciones WHERE audio_fuente IS NOT NULL"
        " ORDER BY id DESC LIMIT ?", (cuantas * 2,)).fetchall()
    con.close()
    return [f[0] for f in filas]


def catalogo(ruta=None):
    ruta = Path(ruta) if ruta else CATALOGO
    if not ruta.exists():
        return []
    return json.loads(ruta.read_text())


def indice(entradas, refrescar=False):
    """Perfil de cada candidato, cacheado por fecha de modificación."""
    cache = json.loads(INDICE.read_text()) if INDICE.exists() and not refrescar else {}
    for e in entradas:
        ruta = (MUSICA / e["archivo"]) if not Path(e["archivo"]).is_absolute() else Path(e["archivo"])
        if not ruta.exists():
            e["error"] = "falta el archivo"
            continue
        sello = f'{ruta.stat().st_mtime_ns}'
        guardado = cache.get(e["id"])
        if guardado and guardado.get("sello") == sello:
            e["perfil"] = guardado["perfil"]
            continue
        p = perfil(ruta)
        e["perfil"] = p
        cache[e["id"]] = {"sello": sello, "perfil": p}
    INDICE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
    return entradas


def perfil_referencia(ident):
    guardado = INFORMES / f"{ident}.json"
    if guardado.exists():
        return json.loads(guardado.read_text())
    audio = AUDIO / f"{ident}.m4a"
    if not audio.exists():
        raise SystemExit(f"no encuentro ni el perfil ni el audio de «{ident}»")
    p = perfil(audio)
    p["terminos"] = descripcion(p)
    INFORMES.mkdir(parents=True, exist_ok=True)
    guardado.write_text(json.dumps(p, indent=2, ensure_ascii=False))
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("referencia", help="id de la referencia, p. ej. lemon_art_negro")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--refrescar", action="store_true", help="reanaliza el catálogo entero")
    ap.add_argument("--catalogo", help="otro catálogo (pruebas de control)")
    ap.add_argument("--repetir", action="store_true",
                    help="permite volver a usar una pista ya publicada")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    ref = perfil_referencia(a.referencia)
    ref.setdefault("terminos", descripcion(ref))
    consulta = {
        "bpm_objetivo": ref["bpm"],
        "bpm_margen": [round(ref["bpm"] * 0.92, 1), round(ref["bpm"] * 1.08, 1)],
        "duracion_min_s": ref["duracion"],
        "terminos": ref["terminos"],
    }

    entradas = indice(catalogo(a.catalogo), a.refrescar)
    validos = [e for e in entradas if e.get("perfil")]
    ya = usadas() if not a.repetir else []
    frescos = [e for e in validos if e["id"] not in ya]
    if ya and frescos:
        validos = frescos       # si el catálogo da de sí, ni una repetición
    clasificados = []
    for e in validos:
        nota, desglose = parecido(ref, e["perfil"])
        clasificados.append({**{k: v for k, v in e.items() if k != "perfil"},
                             "nota": nota, "desglose": desglose,
                             "bpm": e["perfil"]["bpm"],
                             "duracion": e["perfil"]["duracion"]})
    clasificados.sort(key=lambda c: -c["nota"])
    mejores = clasificados[: a.top]

    if a.json:
        print(json.dumps({"referencia": a.referencia, "perfil": ref,
                          "consulta": consulta, "candidatos": mejores,
                          "catalogo_total": len(validos)}, indent=2, ensure_ascii=False))
        return

    print(f"REFERENCIA  {a.referencia}")
    print(f"  {ref['bpm']} BPM · {ref['duracion']} s · {', '.join(ref['terminos'])}")
    print(f"\nQUÉ BUSCAR EN LA APP")
    print(f"  tempo {consulta['bpm_margen'][0]}–{consulta['bpm_margen'][1]} BPM · "
          f"al menos {consulta['duracion_min_s']} s · {', '.join(consulta['terminos'])}")

    if not validos:
        print(f"\nCATÁLOGO VACÍO — no hay nada que puntuar.")
        print(f"  Mete pistas en {CATALOGO.relative_to(REPO)} (ver assets/musica/LEEME.md)")
        raise SystemExit(0)

    print(f"\nCANDIDATOS  ({len(validos)} en catálogo)")
    for i, c in enumerate(mejores, 1):
        d = c["desglose"]
        print(f"  {i}. {c['nota']:5.1f}  {c.get('nombre', c['id'])}  "
              f"[{c.get('origen', '?')}]  {c['bpm']} BPM · {c['duracion']} s")
        print(f"       tempo {1 - d['tempo']:.0%} · timbre {1 - d['timbre']:.0%} · "
              f"brillo {1 - d['brillo']:.0%} · golpes {1 - d['golpes']:.0%} · "
              f"dinámica {1 - d['dinamica']:.0%}")
        if c.get("url"):
            print(f"       {c['url']}")
    print(f"\nLa elección la aprueba una persona: esto ordena, no decide.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Convierte lo medido en enmiendas en borrador. No las aplica: las propone.

Hasta ahora el bucle estaba abierto — la analítica medía y era una persona quien
leía los números y escribía la regla. Esto hace la primera mitad: detecta en los
datos los patrones que ya sabemos leer y redacta el borrador con su evidencia
numérica dentro. Aprobarlo sigue siendo humano, y debe seguir siéndolo: una
correlación con dos piezas no es una lección.

    python3 proponer.py
    python3 proponer.py --json
"""

import argparse
import json
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BD = REPO / "db" / "jobs.db"
PROMPTS = REPO / "fase0" / "prompts"

# Cuánto tiene que moverse algo para molestarse en proponer una regla.
UMBRAL_RETENCION = 10.0     # puntos porcentuales
UMBRAL_INTERACCION = 1.0    # % sobre alcance
FACTOR_PLATAFORMA = 2.0     # una plataforma rinde el doble que otra


def conectar():
    con = sqlite3.connect(BD)
    con.row_factory = sqlite3.Row
    return con


def duracion_de(job):
    """La duración pedida vive en el plan del prompt, no en la tabla."""
    f = PROMPTS / f"{job['prompt_version']}.json"
    if f.exists():
        try:
            return json.loads(f.read_text()).get("duracion")
        except json.JSONDecodeError:
            pass
    return None


def ultima_lectura(con, job_id, plataforma):
    return con.execute(
        "SELECT m.* FROM metricas m JOIN publicaciones p ON p.id = m.publicacion_id"
        " WHERE p.job_id = ? AND p.plataforma = ? ORDER BY m.horas DESC LIMIT 1",
        (job_id, plataforma)).fetchone()


def detectar_retencion(con, jobs):
    """Dos piezas seguidas: si la nueva retiene mucho menos, hay algo que contar."""
    lecturas = []
    for j in jobs:
        m = ultima_lectura(con, j["id"], "instagram")
        dur = duracion_de(j)
        if m and m["retencion_s"] and dur:
            lecturas.append((j, round(m["retencion_s"] / dur * 100, 1), m["retencion_s"], dur))
    if len(lecturas) < 2:
        return None
    (jn, pn, sn, dn), (jv, pv, sv, dv) = lecturas[0], lecturas[1]
    if pv - pn < UMBRAL_RETENCION:
        return None
    return {
        "id_sugerido": f"retencion_job{jn['id']}",
        "aplica": "prompt",
        "evidencia": (f"El job {jn['id']} ({jn['referencia']}) retiene {pn}% "
                      f"({sn} s de {dn}) frente al {pv}% del job {jv['id']} "
                      f"({sv} s de {dv}). Son {pv - pn:.1f} puntos de caída."),
        "regla_pendiente": ("QUÉ CAMBIÓ ENTRE LAS DOS PIEZAS: escribe aquí la regla. "
                            "El sistema ve la caída, no la causa."),
    }


def detectar_interaccion(con, jobs):
    for j in jobs:
        total_alcance = total_inter = comentarios = 0
        for plat in ("instagram", "facebook", "tiktok"):
            m = ultima_lectura(con, j["id"], plat)
            if not m:
                continue
            total_alcance += (m["alcance"] or m["visionados"] or 0)
            total_inter += (m["interacciones"] or 0)
            comentarios += (m["comentarios"] or 0)
        if total_alcance < 50:
            continue
        pct = total_inter / total_alcance * 100
        if pct < UMBRAL_INTERACCION and comentarios == 0:
            return {
                "id_sugerido": f"conversion_job{j['id']}",
                "aplica": "caption",
                "evidencia": (f"El job {j['id']} lleva {total_alcance} de alcance sumando "
                              f"plataformas y {total_inter} interacciones ({pct:.1f}%), "
                              f"con 0 comentarios."),
                "regla_pendiente": ("El caption ya pide algo y aun así nadie contesta. "
                                    "Prueba a pedir algo más fácil de contestar, o a pedirlo "
                                    "dentro del vídeo y no solo en el texto."),
            }
    return None


def detectar_plataforma(con):
    """Vistas por día de vida, que es lo único comparable entre piezas de distinta edad."""
    ritmos = {}
    for p in con.execute("SELECT * FROM publicaciones WHERE estado = 'publicado'"):
        m = ultima_lectura(con, p["job_id"], p["plataforma"])
        if not m or not m["horas"] or not m["visionados"]:
            continue
        dias = max(m["horas"] / 24, 0.3)
        ritmos.setdefault(p["plataforma"], []).append(m["visionados"] / dias)
    medias = {k: sum(v) / len(v) for k, v in ritmos.items() if v}
    if len(medias) < 2:
        return None
    orden = sorted(medias.items(), key=lambda x: -x[1])
    mejor, peor = orden[0], orden[-1]
    if mejor[1] < peor[1] * FACTOR_PLATAFORMA:
        return None
    return {
        "id_sugerido": "orden_de_publicacion",
        "aplica": "publicacion",
        "evidencia": ("Reproducciones por día de vida: " +
                      " · ".join(f"{k} {v:.0f}" for k, v in orden) +
                      f". {mejor[0]} rinde {mejor[1] / peor[1]:.1f} veces más que {peor[0]}."),
        "regla_pendiente": f"Publicar primero en {mejor[0]} y tratarla como plataforma principal.",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    con = conectar()
    jobs = con.execute(
        "SELECT * FROM jobs WHERE estado = 'published' ORDER BY id DESC").fetchall()

    propuestas = [p for p in (detectar_retencion(con, jobs),
                              detectar_interaccion(con, jobs),
                              detectar_plataforma(con)) if p]

    if a.json:
        print(json.dumps(propuestas, indent=2, ensure_ascii=False))
        return
    if not propuestas:
        print("nada que proponer: ningún patrón cruza los umbrales")
        return
    for p in propuestas:
        print(f"\n── {p['id_sugerido']}  [{p['aplica']}]")
        print(f"   evidencia: {p['evidencia']}")
        print(f"   pendiente: {p['regla_pendiente']}")
        print(f"\n   python3 fase0/enmiendas.py anadir --id {p['id_sugerido']} \\")
        print(f"     --origen analitica --aplica {p['aplica']} \\")
        print(f"     --evidencia \"{p['evidencia']}\" \\")
        print(f"     --regla \"ESCRIBE AQUÍ LA REGLA\"")
    print(f"\n{len(propuestas)} propuestas. Ninguna se aplica hasta que la apruebes.")


if __name__ == "__main__":
    main()

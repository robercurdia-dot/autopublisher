#!/usr/bin/env python3
"""Acceso a la tabla de estado.

Cada función mueve el job de un estado concreto al siguiente y falla si la fila no
estaba donde tocaba. Eso es la regla de "cada parte toca solo sus transiciones"
puesta en código, no en un comentario: no se puede publicar algo sin aprobar,
ni aprobar algo que aún se está generando.

    python3 jobs.py listar
    python3 jobs.py aprobar 3
    python3 jobs.py gasto
"""

import json
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
BD = RAIZ / "jobs.db"


def conectar():
    con = sqlite3.connect(BD)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _mover(con, job_id, desde, hasta, **campos):
    """Transición con guarda: solo si la fila está en 'desde'."""
    sets = ", ".join(["estado = ?"] + ["%s = ?" % k for k in campos])
    vals = [hasta] + list(campos.values()) + [job_id, desde]
    cur = con.execute(
        "UPDATE jobs SET %s WHERE id = ? AND estado = ?" % sets, vals)
    if cur.rowcount == 0:
        actual = con.execute("SELECT estado FROM jobs WHERE id = ?", (job_id,)).fetchone()
        raise RuntimeError(
            "job %s: se esperaba '%s' y está en '%s'" %
            (job_id, desde, actual["estado"] if actual else "no existe"))
    con.commit()


def evento(con, job_id, fase, estado, coste=None, error=None, payload=None):
    con.execute(
        "INSERT INTO job_events(job_id, fase, estado, acabado_en, coste_usd, error_texto, payload)"
        " VALUES(?,?,?,datetime('now'),?,?,?)",
        (job_id, fase, estado, coste, error,
         json.dumps(payload, ensure_ascii=False) if payload is not None else None))
    con.commit()


# ---------- las transiciones, en orden ----------

def crear(con, modo, referencia, prompt_version, proveedor, atrezzo=None):
    cur = con.execute(
        "INSERT INTO jobs(modo, referencia, atrezzo, prompt_version, proveedor)"
        " VALUES(?,?,?,?,?)", (modo, referencia, atrezzo, prompt_version, proveedor))
    con.commit()
    evento(con, cur.lastrowid, "crear", "ok")
    return cur.lastrowid


def generando(con, job_id, job_proveedor, coste_estimado):
    _mover(con, job_id, "pending", "generating",
           job_proveedor=job_proveedor, coste_estimado_usd=coste_estimado)
    evento(con, job_id, "generar", "running", payload={"job_proveedor": job_proveedor})


def generado(con, job_id, output_url, coste_real, audio_ref=None, etiqueta_ia=False):
    _mover(con, job_id, "generating", "generated",
           output_url=output_url, coste_usd=coste_real, audio_ref=audio_ref,
           etiqueta_ia=1 if etiqueta_ia else 0)
    evento(con, job_id, "generar", "ok", coste=coste_real)


def aprobar(con, job_id, caption=None, hashtags=None):
    """La única transición que no hace un proceso. Rechaza si el clip va mudo:
    el run 01 se publicó en silencio y esa puerta ya no se vuelve a cruzar."""
    fila = con.execute("SELECT audio_ref, etiqueta_ia, vertiente, qa_producto, estado"
                       " FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if fila and fila["audio_ref"] is None:
        raise RuntimeError(
            "job %s no tiene audio_ref: el clip va mudo. Móntalo antes de aprobar." % job_id)
    # Ya no se exige etiqueta quemada en ninguna pieza — enmienda «etiqueta_solo_nativa»,
    # 27 sep 2026. La declaración de IA va por el mecanismo de cada red y la hace el
    # publisher: is_ai_generated en Instagram, etiqueta de IA en Facebook, AIGC en TikTok.
    # La columna etiqueta_ia se queda para leer el histórico de los que sí la llevaron.
    # La silueta del producto es lo unico que no puede derivar, y no se mide sola.
    # El run 05 se publicó camino de aprobarse con el cono invertido entre planos.
    # Desde aquí, aprobar exige haber mirado el producto plano a plano.
    if fila and not fila["qa_producto"]:
        raise RuntimeError(
            "job %s sin QA de producto. Mira assets/informes/planos/<id>/producto.jpg y,\n"
            "  si la silueta aguanta en todos los planos:\n"
            "  UPDATE jobs SET qa_producto=1 WHERE id=%s" % (job_id, job_id))

    extra = {}
    if caption is not None:
        extra["caption"] = caption
    if hashtags is not None:
        extra["hashtags"] = hashtags
    _mover(con, job_id, "generated", "approved", **extra)
    evento(con, job_id, "revision", "ok")


def reclamar(con):
    """Reclamación atómica. Dos publishers a la vez no pueden coger la misma fila."""
    fila = con.execute("""
        UPDATE jobs SET estado = 'publishing', intentos = intentos + 1
         WHERE id = (SELECT id FROM jobs WHERE estado = 'approved'
                      ORDER BY creado_en LIMIT 1)
        RETURNING *
    """).fetchone()
    con.commit()
    if fila:
        evento(con, fila["id"], "publicar", "running")
    return fila


def publicado(con, job_id, plataforma, post_id, post_url):
    _mover(con, job_id, "publishing", "published",
           plataforma=plataforma, post_id=post_id, post_url=post_url)
    evento(con, job_id, "publicar", "ok", payload={"post_id": post_id, "post_url": post_url})


def fallar(con, job_id, fase, error):
    con.execute("UPDATE jobs SET estado='failed', error=? WHERE id=?", (str(error), job_id))
    con.commit()
    evento(con, job_id, fase, "error", error=str(error))


# ---------- consola ----------

def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    orden = sys.argv[1]
    con = conectar()

    if orden == "listar":
        filas = con.execute(
            "SELECT id, estado, modo, referencia, atrezzo, coste_usd, audio_ref, post_url"
            " FROM jobs ORDER BY id").fetchall()
        if not filas:
            print("Vacía."); return
        print("%-3s %-11s %-8s %-22s %-14s %6s %-8s" %
              ("id", "estado", "modo", "referencia", "atrezzo", "$", "audio"))
        for f in filas:
            print("%-3s %-11s %-8s %-22s %-14s %6s %-8s" % (
                f["id"], f["estado"], f["modo"], f["referencia"],
                f["atrezzo"] or "—", ("%.2f" % f["coste_usd"]) if f["coste_usd"] else "—",
                f["audio_ref"] or "MUDO"))

    elif orden == "gasto":
        for f in con.execute("SELECT * FROM gasto"):
            print("%-12s %d tiradas · estimado $%.2f · real $%.2f · ratio %.3f" % (
                f["proveedor"], f["tiradas"], f["estimado"], f["real"], f["ratio"]))

    elif orden == "aprobar":
        aprobar(con, int(sys.argv[2]))
        print("job %s aprobado" % sys.argv[2])

    elif orden == "pendientes":
        for f in con.execute("SELECT * FROM pendientes_de_aprobar"):
            print(dict(f))

    else:
        sys.exit("No conozco '%s'." % orden)


if __name__ == "__main__":
    main()

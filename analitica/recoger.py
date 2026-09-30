#!/usr/bin/env python3
"""Último nodo: a las 6 horas, mira qué ha pasado con lo que publicamos.

Seis horas es el punto donde una pieza ya ha enseñado si arranca: si a esa altura
no la están recomendando, no lo van a hacer luego. Y sin esa primera lectura no
hay serie — el run 02 estaba a 0 a las 2 h y a 124 a las 48 h, y sin las dos
lecturas esa diferencia no se ve.

Lee de la API lo que la API dé, y dice con nombre y apellidos lo que hay que
recoger a mano. No inventa un número que no ha medido.

    python3 recoger.py pendientes          # qué toca medir ya
    python3 recoger.py recoger             # mide todo lo que toque
    python3 recoger.py serie 3             # la evolución de un job
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BD = REPO / "db" / "jobs.db"
VENTANA = 6.0          # horas: el corte que pediste
MARGEN = 0.75          # se da por hecha una lectura si cae a menos de esto de la ventana


def conectar():
    con = sqlite3.connect(BD)
    con.row_factory = sqlite3.Row
    return con


def credenciales():
    ruta = os.environ.get("CRED_FILE")
    if not ruta or not Path(ruta).exists():
        return None
    d = {}
    for linea in Path(ruta).read_text().splitlines():
        if "=" in linea and not linea.strip().startswith("#"):
            k, v = linea.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def horas_desde(iso):
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


def pendientes(con):
    """Publicaciones que ya pasaron la ventana y no tienen lectura de esa ventana."""
    out = []
    for p in con.execute("SELECT * FROM publicaciones WHERE estado = 'publicado'"):
        if not p["publicada_en"]:
            continue
        h = horas_desde(p["publicada_en"])
        if h < VENTANA:
            continue
        ya = con.execute(
            "SELECT 1 FROM metricas WHERE publicacion_id = ? AND abs(horas - ?) < ?",
            (p["id"], VENTANA, MARGEN)).fetchone()
        if not ya:
            out.append((p, h))
    return out


def medir_instagram(post_id, cred):
    """Graph API. Es la única de las tres que mide sin navegador."""
    campos = ("reach,views,likes,comments,shares,saved,total_interactions,"
              "ig_reels_avg_watch_time")
    url = (f"https://graph.instagram.com/v25.0/{post_id}/insights"
           f"?metric={campos}&access_token={cred['ACCESS_TOKEN']}")
    crudo = subprocess.check_output(["curl", "-s", "--max-time", "30", url]).decode()
    d = json.loads(crudo)
    if "error" in d:
        raise RuntimeError(d["error"].get("message", "error de la API"))
    v = {m["name"]: m["values"][0]["value"] for m in d.get("data", [])}
    return {
        "alcance": v.get("reach"), "visionados": v.get("views"),
        "interacciones": v.get("total_interactions"), "guardados": v.get("saved"),
        "compartidos": v.get("shares"), "comentarios": v.get("comments"),
        "retencion_s": round(v["ig_reels_avg_watch_time"] / 1000, 2)
                       if v.get("ig_reels_avg_watch_time") else None,
        "crudo": crudo, "fuente": "api",
    }


# Facebook necesita un token de página (pages_read_engagement) que no tenemos, y
# TikTok no expone métricas sin su API de socios. Las dos se leen conduciendo el
# navegador, que es una sesión de Roberto, no un script desatendido.
A_MANO = {
    "facebook": "Panel para profesionales de la página → Insights",
    "tiktok": "TikTok Studio → Estadísticas",
}


def guardar(con, pub_id, horas, m):
    con.execute(
        "INSERT INTO metricas(publicacion_id, horas, alcance, visionados, interacciones,"
        " guardados, compartidos, comentarios, retencion_s, crudo, fuente)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (pub_id, round(horas, 2), m.get("alcance"), m.get("visionados"),
         m.get("interacciones"), m.get("guardados"), m.get("compartidos"),
         m.get("comentarios"), m.get("retencion_s"), m.get("crudo"), m.get("fuente", "api")))
    con.commit()


def cmd_pendientes(a, con):
    ps = pendientes(con)
    if not ps:
        print(f"nada que medir: ninguna publicación ha cruzado las {VENTANA:.0f} h sin lectura")
        return
    for p, h in ps:
        via = "api" if p["plataforma"] == "instagram" else f"a mano — {A_MANO.get(p['plataforma'], '?')}"
        print(f"job {p['job_id']} · {p['plataforma']:<10} {h:6.1f} h  · {via}")


def cmd_recoger(a, con):
    cred = credenciales()
    ps = pendientes(con)
    if not ps:
        print(f"nada que medir")
        return
    for p, h in ps:
        if p["plataforma"] == "instagram":
            if not cred:
                print(f"job {p['job_id']} · instagram: falta CRED_FILE, no mido a ciegas")
                continue
            try:
                m = medir_instagram(p["post_id"], cred)
            except Exception as e:                       # noqa: BLE001
                # Un post borrado no vuelve: se marca omitida y deja de dar la lata
                # en cada pasada. Roberto borró a mano los dos primeros.
                if "does not exist" in str(e):
                    con.execute("UPDATE publicaciones SET estado = 'omitida',"
                                " error = 'el post ya no existe' WHERE id = ?", (p["id"],))
                    con.commit()
                    print(f"job {p['job_id']} · instagram: el post ya no existe → omitida")
                else:
                    print(f"job {p['job_id']} · instagram: {e}")
                continue
            guardar(con, p["id"], h, m)
            print(f"job {p['job_id']} · instagram {h:.1f} h → alcance {m['alcance']} · "
                  f"visionados {m['visionados']} · interacciones {m['interacciones']} · "
                  f"retención {m['retencion_s']} s")
        else:
            print(f"job {p['job_id']} · {p['plataforma']}: se lee a mano en "
                  f"{A_MANO.get(p['plataforma'], '?')} — el agente puede sacarlo por navegador")


def cmd_serie(a, con):
    filas = con.execute(
        "SELECT p.plataforma, m.horas, m.alcance, m.visionados, m.interacciones, m.retencion_s"
        " FROM metricas m JOIN publicaciones p ON p.id = m.publicacion_id"
        " WHERE p.job_id = ? ORDER BY p.plataforma, m.horas", (a.job,)).fetchall()
    if not filas:
        print(f"el job {a.job} no tiene ninguna lectura todavía")
        return
    print(f"{'plataforma':<11}{'horas':>7}{'alcance':>9}{'vis.':>7}{'inter.':>8}{'ret.':>7}")
    for f in filas:
        print(f"{f['plataforma']:<11}{f['horas']:7.1f}{(f['alcance'] or 0):9}"
              f"{(f['visionados'] or 0):7}{(f['interacciones'] or 0):8}"
              f"{(f['retencion_s'] or 0):7.1f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pendientes").set_defaults(f=cmd_pendientes)
    sub.add_parser("recoger").set_defaults(f=cmd_recoger)
    s = sub.add_parser("serie"); s.add_argument("job", type=int); s.set_defaults(f=cmd_serie)
    a = ap.parse_args()
    with conectar() as con:
        a.f(a, con)


if __name__ == "__main__":
    main()

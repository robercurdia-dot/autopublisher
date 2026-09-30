#!/usr/bin/env python3
"""Una pieza, varias plataformas. Reparte y lleva la cuenta de qué cayó dónde.

No publica por su cuenta: cada plataforma tiene su vía y sus condiciones, y salvo
Instagram todas pasan hoy por el navegador con la sesión de Roberto, parando en la
pantalla de publicar para que confirme él (ver `estado`). Lo que sí
hace siempre es dejar la fila en `publicaciones` antes de intentar nada, para que
un fallo a mitad no deje una publicación fantasma ni permita repetirla.

    python3 red.py estado                 # qué plataformas están listas y por qué no
    python3 red.py plan 3                 # qué se publicaría del job 3, y dónde
    python3 red.py publicar 3 --en instagram
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "db"))
import jobs  # noqa: E402

# Lo que cada plataforma exige. Esto no es burocracia: cada casilla nos costó
# una comprobación, y la que está a False tumba la publicación entera.
PLATAFORMAS = {
    "instagram": {
        "titulo": "Instagram",
        "declaracion_ia": "is_ai_generated=true en el contenedor",
        "audio": "meta",          # qué licencias de música admite
        "caption_max": 2200,
        "via": "graph api propia · publicar/publicar_clip.sh",
        "listo": True,
        "falta": None,
    },
    "facebook": {
        "titulo": "Facebook (página)",
        "declaracion_ia": "misma etiqueta de IA de Meta",
        "audio": "meta",
        "caption_max": 2200,
        "via": "navegador · Meta Business Suite (o API de páginas si algún día compensa)",
        "listo": False,
        "falta": "no hay página creada",
    },
    "tiktok": {
        "titulo": "TikTok",
        "declaracion_ia": "interruptor «contenido generado por IA» en el formulario de subida",
        "audio": "tiktok",        # su propia biblioteca comercial, no la de Meta
        "caption_max": 2200,      # en el formulario web, no los 150 de la API
        "via": "navegador · tiktok.com/tiktokstudio/upload con la sesión de Roberto",
        "listo": False,
        "falta": "falta comprobar que hay cuenta y sesión iniciada en Chrome",
    },
    "youtube": {
        "titulo": "YouTube Shorts",
        "declaracion_ia": "casilla de contenido alterado o sintético en Studio",
        "audio": "neutro",
        "caption_max": 5000,
        "via": "navegador · studio.youtube.com con la sesión de Roberto",
        "listo": False,
        "falta": "falta comprobar canal y sesión iniciada en Chrome",
    },
}

# La música NO viaja entre plataformas. La Colección de sonidos de Meta está
# licenciada para productos de Meta; ponerla en TikTok o YouTube es meter una
# pista sin licencia en un sistema que sabe escuchar. Por eso cada plataforma
# declara qué fuentes admite y la red se niega a cruzarlas.
AUDIO_POR_FUENTE = {
    "coleccion_meta": {"meta"},
    "tiktok_cml": {"tiktok"},
    "neutro": {"meta", "facebook", "tiktok", "youtube", "neutro"},
}


def cuentas():
    """El estado real de cada cuenta vive en cuentas.json, no en esta tabla.
    Tenerlo duplicado ya nos mintió una vez: la red decía «no hay página» con la
    página creada y publicando."""
    f = REPO / "cuentas.json"
    return json.loads(f.read_text()).get("cuentas", {}) if f.exists() else {}


def con_estado():
    """Funde lo que la plataforma EXIGE (aquí) con lo que la cuenta TIENE (allí)."""
    reg = cuentas()
    out = {}
    for k, p in PLATAFORMAS.items():
        c = reg.get(k, {})
        p = dict(p)
        activa = c.get("estado") == "activa"
        p["cuenta"] = c.get("usuario") or c.get("pagina")
        p["listo"] = p["listo"] or activa
        p["desatendido"] = p["via"].startswith("graph api")
        if activa and not p["desatendido"]:
            p["falta"] = "publica, pero conduciendo el navegador: no corre si no hay sesión"
        elif activa:
            p["falta"] = None
        out[k] = p
    return out


def conectar():
    con = sqlite3.connect(REPO / "db" / "jobs.db")
    con.row_factory = sqlite3.Row
    return con


def audio_compatible(fuente, plataforma):
    admitidas = AUDIO_POR_FUENTE.get(fuente, set())
    return PLATAFORMAS[plataforma]["audio"] in admitidas


def cmd_estado(_):
    for k, p in con_estado().items():
        marca = "auto" if (p["listo"] and p["desatendido"]) else ("manos" if p["listo"] else "FALTA")
        cuenta = f" · {p['cuenta']}" if p.get("cuenta") else ""
        print(f"{marca:>5}  {p['titulo']:<20} {p['via']}{cuenta}")
        if p["falta"]:
            print(f"         {p['falta']}")
        print(f"         IA: {p['declaracion_ia']}")
        print(f"         audio admitido: {p['audio']} · caption {p['caption_max']} car.")
        print()


def cmd_plan(a):
    con = conectar()
    job = con.execute("SELECT * FROM jobs WHERE id = ?", (a.job,)).fetchone()
    if not job:
        raise SystemExit(f"no existe el job {a.job}")
    fuente = job["audio_ref"] or ""
    fuente = "coleccion_meta" if fuente.startswith("meta_") else fuente or "desconocida"
    print(f"job {job['id']} · {job['referencia']} · audio {fuente}")
    ya = {r["plataforma"]: r for r in
          con.execute("SELECT * FROM publicaciones WHERE job_id = ?", (a.job,))}
    for k, p in con_estado().items():
        if k in ya:
            print(f"  {p['titulo']:<20} ya {ya[k]['estado']}")
            continue
        if not p["listo"]:
            print(f"  {p['titulo']:<20} no disponible — {p['falta']}")
            continue
        if not audio_compatible(fuente, k):
            print(f"  {p['titulo']:<20} BLOQUEADO — el audio «{fuente}» no tiene licencia aquí; "
                  f"hace falta una pista {p['audio']}")
            continue
        print(f"  {p['titulo']:<20} publicable")


# Qué hay que mirar en cada sitio DESPUÉS de publicar. Cada línea es un fallo
# que ya nos ha pasado, no una precaución teórica.
COMPROBAR = {
    "instagram": "la API lo confirma sola: existe, es REELS y lleva is_ai_generated",
    "facebook":  "que el reel aparezca en la pestaña Reels de la página — el 27 sep "
                 "el subidor se quedó al 0% y el formulario no avisó",
    "tiktok":    "que la privacidad sea «Todo el mundo» — el 27 sep salió en «Solo yo» "
                 "por defecto, y en revisión no deja cambiarla",
    "youtube":   "que el vídeo esté público y con la casilla de contenido sintético",
}


def cmd_auditar(a, con):
    """Publicaciones cuyo estado no cuadra con las pruebas que tenemos."""
    sospechosas = []
    for p in con.execute("SELECT * FROM publicaciones ORDER BY job_id, plataforma"):
        motivos = []
        if p["estado"] == "publicado":
            if not p["post_url"]:
                motivos.append("sin enlace: nadie ha visto dónde cayó")
            if not p["confirmada_en"]:
                motivos.append(f"sin confirmar · {COMPROBAR.get(p['plataforma'], '?')}")
            m = con.execute("SELECT count(*) n FROM metricas WHERE publicacion_id = ?",
                            (p["id"],)).fetchone()["n"]
            if m == 0 and p["publicada_en"]:
                motivos.append("sin ninguna métrica recogida")
        elif p["estado"] == "fallida":
            motivos.append(f"fallida y sin reintentar — {p['error'] or 'sin motivo anotado'}")
        elif p["estado"] in ("publicando", "pendiente"):
            motivos.append("se quedó a medias")
        if motivos:
            sospechosas.append((p, motivos))

    if not sospechosas:
        print("todo cuadra: cada publicación tiene enlace, confirmación y métricas")
        return
    for p, motivos in sospechosas:
        print(f"job {p['job_id']} · {p['plataforma']:<10} [{p['estado']}]")
        for m in motivos:
            print(f"    {m}")
    print(f"\n{len(sospechosas)} publicaciones que no se pueden dar por buenas.")
    print("Confirmar una: python3 publicar/red.py confirmar <job> --en <plataforma> "
          "--url <enlace> --nota \"lo que has comprobado\"")


def cmd_confirmar(a, con):
    cur = con.execute(
        "UPDATE publicaciones SET confirmada_en = datetime('now'), verificacion = ?,"
        " post_url = COALESCE(?, post_url) WHERE job_id = ? AND plataforma = ?",
        (a.nota, a.url, a.job, a.en))
    con.commit()
    if not cur.rowcount:
        raise SystemExit(f"no hay publicación del job {a.job} en {a.en}")
    print(f"job {a.job} · {a.en}: confirmada")


def cmd_publicar(a):
    p = con_estado().get(a.en)
    if not p:
        raise SystemExit(f"plataforma desconocida: {a.en}")
    if not p["listo"]:
        raise SystemExit(f"{p['titulo']} no está disponible todavía: {p['falta']}")
    raise SystemExit(
        "publicar en Instagram sigue siendo publicar/publicar_clip.sh, que ya hace\n"
        "montaje, etiqueta, originalidad, alojamiento y la puerta de confirmación.\n"
        "La red lleva el registro; el disparo real no se duplica aquí.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("estado").set_defaults(f=cmd_estado)
    pp = sub.add_parser("plan"); pp.add_argument("job", type=int); pp.set_defaults(f=cmd_plan)
    pu = sub.add_parser("publicar"); pu.add_argument("job", type=int)
    pu.add_argument("--en", required=True); pu.set_defaults(f=cmd_publicar)
    au = sub.add_parser("auditar"); au.set_defaults(f=cmd_auditar)
    cf = sub.add_parser("confirmar"); cf.add_argument("job", type=int)
    cf.add_argument("--en", required=True); cf.add_argument("--url")
    cf.add_argument("--nota", required=True); cf.set_defaults(f=cmd_confirmar)
    a = ap.parse_args()
    if a.f in (cmd_auditar, cmd_confirmar):
        with conectar() as con:
            a.f(a, con)
    else:
        a.f(a)


if __name__ == "__main__":
    main()

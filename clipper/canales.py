#!/usr/bin/env python3
"""¿De qué canales de YouTube merece la pena sacar clips ESTA semana?

Un ranking de suscriptores dice quién es grande, no quién está caliente. Lo que
importa para clipear es otra cosa: que el canal haya subido material largo en
los últimos días -materia prima- y que ese material esté rindiendo por encima
de lo que le corresponde por tamaño.

Para cada canal se cruzan dos fuentes, porque ninguna basta sola:
  - la pestaña /videos (vía yt-dlp): solo vídeos largos, con duración y vistas
  - el feed RSS del canal: trae la fecha de publicación, que yt-dlp no da

    python3 canales.py @TheWildProject @auronplay @ibai
    python3 canales.py --lista clipper/canales_es.txt --dias 7
    python3 canales.py @ibai --json
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

NS = {"a": "http://www.w3.org/2005/Atom", "m": "http://search.yahoo.com/mrss/",
      "yt": "http://www.youtube.com/xml/schemas/2015"}


def largos(handle, cuantos=15):
    """Vídeos largos recientes del canal: id, vistas, duración."""
    url = f"https://www.youtube.com/{handle}/videos"
    r = subprocess.run(["yt-dlp", "--flat-playlist", "--playlist-end", str(cuantos),
                        "-J", url], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    d = json.loads(r.stdout)
    return {"canal": d.get("channel"), "id_canal": d.get("channel_id"),
            "seguidores": d.get("channel_follower_count") or 0,
            "videos": {e["id"]: {"vistas": e.get("view_count") or 0,
                                 "duracion": e.get("duration") or 0}
                       for e in d.get("entries") or [] if e.get("id")}}


def fechas(id_canal):
    """Fecha de publicación de las últimas subidas, desde el RSS."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={id_canal}"
    try:
        raiz = ET.fromstring(urllib.request.urlopen(url, timeout=20).read())
    except Exception:
        return {}
    out = {}
    for e in raiz.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", namespaces=NS)
        pub = e.findtext("a:published", namespaces=NS)
        if vid and pub:
            out[vid] = datetime.fromisoformat(pub.replace("Z", "+00:00"))
    return out


def medir(handle, dias):
    l = largos(handle)
    if not l:
        return {"handle": handle, "error": "no se pudo leer el canal (¿handle mal escrito?)"}
    f = fechas(l["id_canal"])
    corte = datetime.now(timezone.utc) - timedelta(days=dias)
    semana = [dict(v, id=k, fecha=f[k]) for k, v in l["videos"].items()
              if k in f and f[k] >= corte]
    vistas = sorted(v["vistas"] for v in semana)
    mediana = vistas[len(vistas) // 2] if vistas else 0
    seg = l["seguidores"] or 1
    return {
        "handle": handle, "canal": l["canal"], "seguidores": l["seguidores"],
        "largos_semana": len(semana),
        # Minutos de materia prima: lo que hay para clipear.
        "minutos_semana": round(sum(v["duracion"] for v in semana) / 60),
        "vistas_mediana": mediana,
        "vistas_max": vistas[-1] if vistas else 0,
        # Vistas de la semana por cada mil seguidores: separa al canal que está
        # caliente del que solo es grande.
        "por_mil_seguidores": round(mediana / seg * 1000, 1),
        "mejor": max(semana, key=lambda v: v["vistas"])["id"] if semana else None,
        "rss_ok": bool(f),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("handles", nargs="*")
    ap.add_argument("--lista", help="fichero con un handle por línea")
    ap.add_argument("--dias", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    hs = list(a.handles)
    if a.lista:
        hs += [l.split("#")[0].strip() for l in Path(a.lista).read_text().splitlines()
               if l.split("#")[0].strip()]
    hs = [h if h.startswith("@") else "@" + h for h in hs]
    if not hs:
        raise SystemExit("pasa al menos un handle, o --lista")

    filas = []
    for h in hs:
        print(f"  midiendo {h} …", file=sys.stderr)
        filas.append(medir(h, a.dias))

    ok = sorted([f for f in filas if "error" not in f],
                key=lambda f: (-f["largos_semana"] > 0, -f["vistas_mediana"]))
    ok.sort(key=lambda f: (f["largos_semana"] == 0, -f["vistas_mediana"]))
    if a.json:
        print(json.dumps({"dias": a.dias, "canales": ok,
                          "fallidos": [f for f in filas if "error" in f]},
                         indent=2, ensure_ascii=False, default=str))
        return
    print(f"\n{'canal':<26}{'seguid.':>9}{'largos':>8}{'min':>6}{'mediana':>10}{'máx':>10}{'/mil seg':>10}")
    for f in ok:
        print(f"{(f['canal'] or f['handle'])[:25]:<26}{f['seguidores']/1e6:>8.1f}M{f['largos_semana']:>8}"
              f"{f['minutos_semana']:>6}{f['vistas_mediana']:>10,}{f['vistas_max']:>10,}{f['por_mil_seguidores']:>10}")
    for f in filas:
        if "error" in f:
            print(f"  ✗ {f['handle']}: {f['error']}")


if __name__ == "__main__":
    main()

"""La suite como web: el motor detrás de HTTP para usuarios externos.

Solo expone lo que necesita quien la usa: analizar un enlace, que Claude elija los
momentos, cortarlos y descargar cada clip con su título y descripción. El usuario los
sube a mano a su canal. Nada de cola de publicación, abrir en el Mac ni rutas
arbitrarias: cada sesión ve únicamente sus propios trabajos.

    motor/.venv/bin/python motor/servidor_web.py [--puerto 8787]

Lee de fase0/.env: SUITE_CLAVE (la contraseña de la beta) y ANTHROPIC_API_KEY.
Escucha solo en 127.0.0.1: desde fuera se llega por el túnel de Cloudflare.
"""

import argparse
import hmac
import json
import os
import re
import secrets
import sys
import threading
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import servidor_mcp as m  # noqa: E402

AQUI = Path(__file__).resolve().parent
WEB = AQUI / "web"
SUITE_JS = AQUI / "suite" / "suite.js"
ENV = m.REPO / "fase0" / ".env"
MODELO = "claude-opus-5-5"
# El Mac transcribe y corta de uno en uno; más de dos trabajos a la vez lo atascan.
MAX_EN_CURSO = 2
MAX_MOMENTOS = 8

ESQUEMA = {
    "type": "object",
    "properties": {"momentos": {"type": "array", "items": {
        "type": "object",
        "properties": {k: {"type": "string"} for k in
                       ("ini", "fin", "gancho", "por_que", "titulo", "descripcion", "hashtags")},
        "required": ["ini", "fin", "gancho", "por_que", "titulo", "descripcion", "hashtags"],
        "additionalProperties": False}}},
    "required": ["momentos"],
    "additionalProperties": False,
}

SESIONES = {}            # token -> ids de trabajos de esa sesión
CANDADO = threading.Lock()


def _env(nombre):
    if os.environ.get(nombre):
        return os.environ[nombre]
    if ENV.exists():
        for linea in ENV.read_text().splitlines():
            k, _, v = linea.partition("=")
            if k.strip() == nombre:
                return v.strip().strip('"').strip("'")
    return None


def reglas():
    """Las reglas para elegir momentos, las mismas que usa la suite: una sola fuente."""
    js = SUITE_JS.read_text()
    m_ = re.search(r"var REGLAS = \[(.*?)\]\.join\(", js, re.S)
    return "\n".join(json.loads("[" + m_.group(1) + "]"))


def proponer(analisis, n=5):
    """Claude lee la transcripción entera y devuelve los n mejores momentos."""
    clave = _env("ANTHROPIC_API_KEY")
    if not clave:
        raise ValueError("falta ANTHROPIC_API_KEY en fase0/.env: sin ella Claude no puede elegir momentos")
    import anthropic

    n = max(1, min(int(n), MAX_MOMENTOS))
    tr = m.transcripcion(analisis)
    dur = int(tr.get("duracion") or 0)
    prompt = (reglas().replace("los N mejores", f"los {n} mejores")
              + f"\n\nVídeo: «{tr.get('titulo') or ''}» de {tr.get('canal') or ''} ({dur // 60:02d}:{dur % 60:02d})"
              + "\n\nTRANSCRIPCIÓN\n" + tr["texto"])
    r = anthropic.Anthropic(api_key=clave).beta.messages.create(
        model=MODELO, max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": ESQUEMA}},
        messages=[{"role": "user", "content": prompt}])
    if r.stop_reason == "refusal":
        raise ValueError("Claude no ha querido elegir momentos de este vídeo")
    if r.stop_reason == "max_tokens":
        raise ValueError("la respuesta de Claude se cortó; prueba con menos momentos")
    texto = next(b.text for b in r.content if b.type == "text")
    return {"momentos": json.loads(texto)["momentos"][:n]}


def _segundos(t):
    p = [float(x) for x in str(t).strip().split(":")]
    return p[0] * 60 + p[1] if len(p) == 2 else p[0]


def tramos_de(momentos):
    """«mm:ss» de cada momento → «ini-fin,ini-fin» en segundos, validado."""
    partes = []
    for x in momentos[:MAX_MOMENTOS]:
        a, b = _segundos(x["ini"]), _segundos(x["fin"])
        if not 5 <= b - a <= 90:
            raise ValueError(f"momento {x['ini']}-{x['fin']}: tiene que durar entre 5 y 90 s")
        partes.append(f"{a:g}-{b:g}")
    if not partes:
        raise ValueError("no hay momentos que cortar")
    return ",".join(partes)


def en_curso():
    return sum(1 for t in m.trabajos(50)["trabajos"] if t["estado"] == "en_curso")


def vista(tid):
    """Lo que el usuario puede ver de un trabajo suyo: sin rutas del Mac."""
    d = m._leer(tid)
    out = {"id": tid, "tipo": d["tipo"], "estado": d["estado"],
           "paso": (d["registro"] or [""])[-1][:160], "motivo": d.get("motivo"), "fuente": d.get("fuente")}
    out["clips"] = [{"n": c["n"], "duracion": round(c["fin"] - c["ini"]),
                     "titulo": (c["propuesta"] or {}).get("titulo", ""),
                     "descripcion": (c["propuesta"] or {}).get("descripcion", ""),
                     "hashtags": (c["propuesta"] or {}).get("hashtags", "")}
                    for c in d["clips"]]
    return out


def archivo_clip(tid, n):
    d = m._leer(tid)
    clip = next((c for c in d["clips"] if c["n"] == int(n)), None)
    if not clip or not clip["archivos"]:
        raise ValueError("ese clip no existe")
    return m._permitida(clip["archivos"][0])


class Manejador(BaseHTTPRequestHandler):
    server_version = "suite"

    def log_message(self, *a):
        pass

    # ---------------------------------------------------------------- respuestas
    def _json(self, codigo, datos, extra=None):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(cuerpo)

    def _fichero(self, ruta, tipo, descarga=None):
        tam = ruta.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(tam))
        if descarga:
            self.send_header("Content-Disposition", f'attachment; filename="{descarga}"')
        self.end_headers()
        with open(ruta, "rb") as f:
            while bloque := f.read(1 << 16):
                self.wfile.write(bloque)

    def _cuerpo(self):
        largo = int(self.headers.get("Content-Length") or 0)
        if largo > 200_000:
            raise ValueError("petición demasiado grande")
        return json.loads(self.rfile.read(largo) or b"{}")

    def _sesion(self):
        c = cookies.SimpleCookie(self.headers.get("Cookie") or "")
        tok = c["sesion"].value if "sesion" in c else None
        return tok if tok in SESIONES else None

    def _mio(self, tok, tid):
        if not re.fullmatch(r"[0-9a-f]{8}", tid or "") or tid not in SESIONES[tok]:
            raise PermissionError("ese trabajo no es tuyo")

    # ------------------------------------------------------------------- rutas
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            return self._fichero(WEB / "index.html", "text/html; charset=utf-8")
        tok = self._sesion()
        if u.path == "/api/yo":
            return self._json(200 if tok else 401, {"dentro": bool(tok)})
        if not tok:
            return self._json(401, {"error": "entra con la clave de la beta"})
        try:
            if u.path == "/api/trabajo":
                self._mio(tok, q.get("id"))
                return self._json(200, vista(q["id"]))
            if u.path == "/api/clip":
                self._mio(tok, q.get("id"))
                ruta = archivo_clip(q["id"], q.get("n", 0))
                return self._fichero(ruta, "video/mp4",
                                     descarga=f"clip{int(q['n'])}.mp4" if q.get("descargar") else None)
            return self._json(404, {"error": "no existe"})
        except PermissionError as e:
            return self._json(403, {"error": str(e)})
        except (ValueError, KeyError) as e:
            return self._json(400, {"error": str(e)})

    def do_POST(self):
        u = urlparse(self.path)
        try:
            datos = self._cuerpo()
            if u.path == "/api/entrar":
                clave = _env("SUITE_CLAVE")
                if not clave or not hmac.compare_digest(str(datos.get("clave", "")), clave):
                    return self._json(403, {"error": "clave incorrecta"})
                tok = secrets.token_urlsafe(32)
                with CANDADO:
                    SESIONES[tok] = set()
                seguro = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
                return self._json(200, {"dentro": True}, {
                    "Set-Cookie": f"sesion={tok}; HttpOnly; SameSite=Strict; Path=/{seguro}"})
            tok = self._sesion()
            if not tok:
                return self._json(401, {"error": "entra con la clave de la beta"})
            if u.path == "/api/analizar":
                if en_curso() >= MAX_EN_CURSO:
                    return self._json(429, {"error": "hay otros vídeos procesándose; prueba en unos minutos"})
                r = m.analizar(str(datos.get("url", ""))[:500])
            elif u.path == "/api/proponer":
                self._mio(tok, datos.get("id"))
                return self._json(200, proponer(datos["id"], datos.get("n", 5)))
            elif u.path == "/api/clipear":
                self._mio(tok, datos.get("id"))
                if en_curso() >= MAX_EN_CURSO:
                    return self._json(429, {"error": "hay otros vídeos procesándose; prueba en unos minutos"})
                momentos = datos.get("momentos") or []
                r = m.clipear(analisis=datos["id"], tramos=tramos_de(momentos), propuestas=momentos)
            else:
                return self._json(404, {"error": "no existe"})
            with CANDADO:
                SESIONES[tok].add(r["id"])
            return self._json(200, r)
        except PermissionError as e:
            return self._json(403, {"error": str(e)})
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            return self._json(400, {"error": str(e)})


def servidor(puerto=8787):
    return ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--puerto", type=int, default=8787)
    s = servidor(a.parse_args().puerto)
    print(f"suite en http://127.0.0.1:{s.server_port}", flush=True)
    s.serve_forever()

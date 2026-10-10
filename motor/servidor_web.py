"""La suite como web: el motor detrás de HTTP para usuarios externos, con planes y tokens.

Solo expone lo que necesita quien la usa: analizar un enlace, que Claude elija los
momentos, cortarlos y descargar cada clip con su título y descripción. Cada acción
cuesta tokens (motor/planes.json): se cobran antes de lanzarla y se devuelven solos
si el trabajo falla. Nada de cola de publicación, abrir en el Mac ni rutas
arbitrarias: cada cuenta ve únicamente sus propios trabajos.

    motor/.venv/bin/python motor/servidor_web.py [--puerto 8787]

Cuentas con email y contraseña (motor/cuentas.py); privada o abierta según
motor/acceso.json. Lee de fase0/.env: ANTHROPIC_API_KEY y, para recuperar
contraseñas por correo, SMTP_HOST, SMTP_PUERTO, SMTP_USUARIO, SMTP_CLAVE, SMTP_REMITENTE.
Escucha solo en 127.0.0.1: desde fuera se llega por el túnel de Cloudflare.
"""

import argparse
import json
import os
import re
import secrets
import sys
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "clipper"))
import cuentas  # noqa: E402
import servidor_mcp as m  # noqa: E402
import tokens  # noqa: E402

AQUI = Path(__file__).resolve().parent
WEB = AQUI / "web"
SUITE_JS = AQUI / "suite" / "suite.js"
ENV = m.REPO / "fase0" / ".env"
MODELO = "claude-opus-5-5"
# El Mac transcribe y corta de uno en uno; más trabajos a la vez lo atascan.
MAX_EN_CURSO = 3
MAX_MOMENTOS = 8
MAX_MINUTOS = 240

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


def duracion_minutos(url):
    """Lo que dura el vídeo según la plataforma, para cobrar antes de bajarlo."""
    import descargar
    d = descargar.metadatos(url) or {}
    if not d.get("duration"):
        raise ValueError("no he podido leer ese vídeo; revisa el enlace")
    minutos = d["duration"] / 60
    if minutos > MAX_MINUTOS:
        raise ValueError(f"el vídeo dura {minutos:.0f} min; el máximo es {MAX_MINUTOS}")
    return minutos


def _ficha(tid):
    return json.loads(m._ruta_trabajo(tid).read_text())


def _anotar(tid, **datos):
    """Guarda en la ficha del trabajo de quién es y qué se cobró por él."""
    f = _ficha(tid)
    f.update(datos)
    m._ruta_trabajo(tid).write_text(json.dumps(f, ensure_ascii=False))


def de_quien(tid):
    if not re.fullmatch(r"[0-9a-f]{8}", tid or "") or not m._ruta_trabajo(tid).exists():
        return None
    return _ficha(tid).get("email")


def en_curso(email=None):
    return sum(1 for t in m.trabajos(60)["trabajos"]
               if t["estado"] == "en_curso" and (email is None or t.get("email") == email))


def vista(tid):
    """Lo que el usuario puede ver de un trabajo suyo: sin rutas del Mac. Si falló,
    le devuelve los tokens (una sola vez)."""
    d = m._leer(tid)
    devuelto = False
    if d["estado"] == "fallido" and d.get("email") and d.get("cobro"):
        devuelto = tokens.devolver(d["email"], d["cobro"])
    out = {"id": tid, "tipo": d["tipo"], "estado": d["estado"],
           "paso": (d["registro"] or [""])[-1][:160], "motivo": d.get("motivo"), "fuente": d.get("fuente"),
           "devuelto": devuelto}
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


def planes_publicos():
    c = tokens.config()
    return {"planes": c["planes"], "packs": c["packs"], "costes": c["costes"]}


def lanzar_cobrando(email, coste, concepto, lanzar):
    """Cobra, lanza y apunta el cobro en el trabajo; si no se llega a lanzar, devuelve."""
    ref = "c" + secrets.token_hex(6)
    tokens.cobrar(email, coste, concepto, ref)
    try:
        r = lanzar()
    except Exception:
        tokens.devolver(email, ref)
        raise
    _anotar(r["id"], email=email, cobro=ref)
    return {**r, "coste": coste, "saldo": tokens.saldo(email)["tokens"]}


ESTATICOS = {"/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"),
             "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/app.css": ("app.css", "text/css; charset=utf-8")}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
COOKIE = "sesion"


class Manejador(BaseHTTPRequestHandler):
    server_version = "suite"
    sys_version = ""

    def log_message(self, *a):
        pass

    # ---------------------------------------------------------------- respuestas
    def _https(self):
        return self.headers.get("X-Forwarded-Proto") == "https"

    def _seguridad(self):
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if self._https():
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    def _json(self, codigo, datos, extra=None):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self._seguridad()
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(cuerpo)

    def _fichero(self, ruta, tipo, descarga=None):
        tam = ruta.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(tam))
        self.send_header("Cache-Control", "no-cache" if tipo.startswith("text/") else "private, max-age=3600")
        self._seguridad()
        if descarga:
            self.send_header("Content-Disposition", f'attachment; filename="{descarga}"')
        self.end_headers()
        with open(ruta, "rb") as f:
            while bloque := f.read(1 << 16):
                self.wfile.write(bloque)

    def _galleta(self, token):
        """La cookie de sesión: solo para este sitio, sin acceso desde JavaScript."""
        seguro = "; Secure" if self._https() else ""
        if token:
            return {"Set-Cookie": f"{COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/; "
                                  f"Max-Age={cuentas.DURACION_SESION}{seguro}"}
        return {"Set-Cookie": f"{COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0{seguro}"}

    def _cuerpo(self):
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise ValueError("se espera JSON")
        largo = int(self.headers.get("Content-Length") or 0)
        if largo > 200_000:
            raise ValueError("petición demasiado grande")
        return json.loads(self.rfile.read(largo) or b"{}")

    def _token(self):
        c = cookies.SimpleCookie(self.headers.get("Cookie") or "")
        return c[COOKIE].value if COOKIE in c else None

    def _email(self):
        return cuentas.sesion(self._token())

    def _ip(self):
        return (self.headers.get("CF-Connecting-IP") or self.client_address[0])[:64]

    def _mismo_origen(self):
        """Contra CSRF: un navegador siempre manda Origin en un POST; tiene que ser este sitio."""
        origen = self.headers.get("Origin")
        if not origen:
            return True
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or ""
        return urlparse(origen).netloc == host

    def _base(self):
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "127.0.0.1"
        return ("https://" if self._https() else "http://") + host

    def _mio(self, email, tid):
        if de_quien(tid) != email:
            raise PermissionError("ese trabajo no es tuyo")

    def _ocupado(self, email):
        if en_curso() >= MAX_EN_CURSO:
            return "hay muchos vídeos procesándose; prueba en unos minutos"
        if en_curso(email) >= tokens.saldo(email)["trabajos_a_la_vez"]:
            return "ya tienes el máximo de trabajos a la vez de tu plan; espera a que acabe alguno"
        return None

    # ------------------------------------------------------------------- rutas
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ESTATICOS:
            nombre, tipo = ESTATICOS[u.path]
            return self._fichero(WEB / nombre, tipo)
        if u.path == "/api/planes":
            return self._json(200, planes_publicos())
        email = self._email()
        if u.path == "/api/yo":
            return self._json(200 if email else 401, {"dentro": bool(email), "email": email,
                                                      "registro": cuentas.acceso().get("registro")})
        if not email:
            return self._json(401, {"error": "entra en tu cuenta"})
        try:
            if u.path == "/api/cuenta":
                return self._json(200, {**tokens.saldo(email), "movimientos": tokens.movimientos(email)})
            if u.path == "/api/trabajo":
                self._mio(email, q.get("id"))
                return self._json(200, vista(q["id"]))
            if u.path == "/api/clip":
                self._mio(email, q.get("id"))
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
        if not self._mismo_origen():
            return self._json(403, {"error": "origen no permitido"})
        try:
            datos = self._cuerpo()
            # ---------------------------------------------------------- cuenta
            if u.path == "/api/registro":
                tok = cuentas.registrar(datos.get("email"), str(datos.get("clave", "")))
                return self._json(200, {"dentro": True}, self._galleta(tok))
            if u.path == "/api/entrar":
                tok = cuentas.entrar(datos.get("email"), str(datos.get("clave", "")), self._ip())
                return self._json(200, {"dentro": True}, self._galleta(tok))
            if u.path == "/api/olvide":
                try:
                    cuentas.pedir_reset(datos.get("email"), self._base(), _env)
                except RuntimeError as e:
                    return self._json(503, {"error": str(e)})
                return self._json(200, {"enviado": True})
            if u.path == "/api/restablecer":
                tok = cuentas.restablecer(str(datos.get("token", "")), str(datos.get("clave", "")))
                return self._json(200, {"dentro": True}, self._galleta(tok))
            if u.path == "/api/salir":
                cuentas.salir(self._token())
                return self._json(200, {"dentro": False}, self._galleta(None))
            email = self._email()
            if not email:
                return self._json(401, {"error": "entra en tu cuenta"})
            if u.path == "/api/clave":
                tok = cuentas.cambiar_clave(email, str(datos.get("actual", "")), str(datos.get("nueva", "")))
                return self._json(200, {"cambiada": True}, self._galleta(tok))
            # ---------------------------------------------------------- clipper
            if u.path == "/api/analizar":
                if (motivo := self._ocupado(email)):
                    return self._json(429, {"error": motivo})
                url = str(datos.get("url", ""))[:500]
                coste = tokens.coste_analizar(duracion_minutos(url))
                return self._json(200, lanzar_cobrando(email, coste, "analizar vídeo", lambda: m.analizar(url)))
            if u.path == "/api/proponer":
                self._mio(email, datos.get("id"))
                ref = "c" + secrets.token_hex(6)
                tokens.cobrar(email, tokens.coste_proponer(), "elegir momentos", ref)
                try:
                    return self._json(200, {**proponer(datos["id"], datos.get("n", 5)),
                                            "saldo": tokens.saldo(email)["tokens"]})
                except Exception:
                    tokens.devolver(email, ref)
                    raise
            if u.path == "/api/clipear":
                self._mio(email, datos.get("id"))
                if (motivo := self._ocupado(email)):
                    return self._json(429, {"error": motivo})
                momentos = (datos.get("momentos") or [])[:MAX_MOMENTOS]
                tramos = tramos_de(momentos)
                return self._json(200, lanzar_cobrando(
                    email, tokens.coste_clips(len(momentos)), f"cortar {len(momentos)} clips",
                    lambda: m.clipear(analisis=datos["id"], tramos=tramos, propuestas=momentos)))
            return self._json(404, {"error": "no existe"})
        except tokens.SinSaldo as e:
            return self._json(402, {"error": f"no te quedan tokens suficientes: {e}"})
        except cuentas.Bloqueado as e:
            return self._json(429, {"error": str(e)})
        except (PermissionError, cuentas.NoPermitido) as e:
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

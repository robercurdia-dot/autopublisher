"""Cuentas de la suite: registro, entrada, sesiones y recuperación de contraseña.

- Contraseñas con scrypt y sal propia; nunca se guardan ni se registran en claro.
- Sesiones en la base de datos: el navegador guarda un token aleatorio y aquí solo se
  guarda su hash, así que una copia de la base no sirve para entrar. Caducan a los
  30 días sin uso.
- Acceso privado o abierto (motor/acceso.json): mientras sea privado, solo los emails
  de «permitidos» pueden registrarse y entrar. Para liberar la web: "registro": "abierto".
- Límite de intentos: tras 8 fallos en 15 min para un email o una IP, se bloquea un rato.
"""

import hashlib
import hmac
import json
import secrets
import smtplib
import sqlite3
import threading
import time
from email.message import EmailMessage
from pathlib import Path

import tokens

AQUI = Path(__file__).resolve().parent
ACCESO = AQUI / "acceso.json"
DURACION_SESION = 30 * 86400
DURACION_RESET = 3600
MIN_CLAVE = 10
MAX_FALLOS, VENTANA_FALLOS = 8, 15 * 60
_fallos = {}
_candado = threading.Lock()


class NoPermitido(Exception):
    pass


class Bloqueado(Exception):
    pass


def acceso():
    if not ACCESO.exists():
        return {"registro": "privado", "permitidos": []}
    return json.loads(ACCESO.read_text())


def puede_entrar(email):
    a = acceso()
    return a.get("registro") == "abierto" or email in [e.lower() for e in a.get("permitidos", [])]


def _con():
    c = sqlite3.connect(tokens.BD, isolation_level=None, timeout=10)
    c.execute("""CREATE TABLE IF NOT EXISTS cuentas (
        email TEXT PRIMARY KEY, hash TEXT NOT NULL, creada REAL NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sesiones (
        token_hash TEXT PRIMARY KEY, email TEXT NOT NULL, creada REAL NOT NULL, ultimo REAL NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS restablecer (
        token_hash TEXT PRIMARY KEY, email TEXT NOT NULL, expira REAL NOT NULL)""")
    return c


def _h(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _hash_clave(clave, sal=None):
    sal = sal or secrets.token_bytes(16)
    d = hashlib.scrypt(clave.encode(), salt=sal, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${sal.hex()}${d.hex()}"


def _clave_ok(clave, guardado):
    _, sal, d = guardado.split("$")
    return hmac.compare_digest(_hash_clave(clave, bytes.fromhex(sal)).split("$")[2], d)


def _validar_clave(clave):
    if len(clave or "") < MIN_CLAVE:
        raise ValueError(f"la contraseña tiene que tener al menos {MIN_CLAVE} caracteres")
    if len(clave) > 200:
        raise ValueError("contraseña demasiado larga")


def _fallo(*claves):
    ahora = time.time()
    with _candado:
        for k in claves:
            _fallos[k] = [t for t in _fallos.get(k, []) if ahora - t < VENTANA_FALLOS] + [ahora]


def _bloqueado(*claves):
    ahora = time.time()
    with _candado:
        return any(len([t for t in _fallos.get(k, []) if ahora - t < VENTANA_FALLOS]) >= MAX_FALLOS
                   for k in claves)


def _nueva_sesion(c, email):
    token = secrets.token_urlsafe(32)
    ahora = time.time()
    c.execute("INSERT INTO sesiones VALUES (?,?,?,?)", (_h(token), email, ahora, ahora))
    return token


def registrar(email, clave):
    email = tokens._normal(email)
    if not puede_entrar(email):
        raise NoPermitido("de momento el registro es solo por invitación")
    _validar_clave(clave)
    c = _con()
    try:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT 1 FROM cuentas WHERE email=?", (email,)).fetchone():
            c.execute("ROLLBACK")
            raise ValueError("ya hay una cuenta con ese email; entra o recupera la contraseña")
        c.execute("INSERT INTO cuentas VALUES (?,?,?)", (email, _hash_clave(clave), time.time()))
        token = _nueva_sesion(c, email)
        c.execute("COMMIT")
    finally:
        c.close()
    tokens.saldo(email)          # alta en el plan Gratis
    return token


def entrar(email, clave, ip=""):
    email = tokens._normal(email)
    if _bloqueado("e:" + email, "i:" + ip):
        raise Bloqueado("demasiados intentos; espera unos minutos")
    c = _con()
    try:
        f = c.execute("SELECT hash FROM cuentas WHERE email=?", (email,)).fetchone()
        # Se calcula el hash aunque la cuenta no exista: así no se distingue por el tiempo.
        ok = _clave_ok(clave or "", f[0]) if f else (_hash_clave(clave or "x") and False)
        if not ok or not puede_entrar(email):
            _fallo("e:" + email, "i:" + ip)
            raise PermissionError("email o contraseña incorrectos")
        return _nueva_sesion(c, email)
    finally:
        c.close()


def sesion(token):
    """El email de una sesión válida (y renueva su caducidad), o None."""
    if not token or len(token) > 100:
        return None
    c = _con()
    try:
        f = c.execute("SELECT email, ultimo FROM sesiones WHERE token_hash=?", (_h(token),)).fetchone()
        if not f:
            return None
        email, ultimo = f
        if time.time() - ultimo > DURACION_SESION or not puede_entrar(email):
            c.execute("DELETE FROM sesiones WHERE token_hash=?", (_h(token),))
            return None
        if time.time() - ultimo > 3600:
            c.execute("UPDATE sesiones SET ultimo=? WHERE token_hash=?", (time.time(), _h(token)))
        return email
    finally:
        c.close()


def salir(token):
    c = _con()
    try:
        c.execute("DELETE FROM sesiones WHERE token_hash=?", (_h(token or ""),))
    finally:
        c.close()


def cambiar_clave(email, actual, nueva):
    c = _con()
    try:
        f = c.execute("SELECT hash FROM cuentas WHERE email=?", (email,)).fetchone()
        if not f or not _clave_ok(actual or "", f[0]):
            raise PermissionError("la contraseña actual no es correcta")
        _validar_clave(nueva)
        c.execute("UPDATE cuentas SET hash=? WHERE email=?", (_hash_clave(nueva), email))
        c.execute("DELETE FROM sesiones WHERE email=?", (email,))   # cierra las demás sesiones
        return _nueva_sesion(c, email)
    finally:
        c.close()


# ------------------------------------------------------- recuperar contraseña

def correo_configurado(env):
    return all(env(k) for k in ("SMTP_HOST", "SMTP_USUARIO", "SMTP_CLAVE", "SMTP_REMITENTE"))


def pedir_reset(email, base_url, env):
    """Envía un enlace para poner contraseña nueva. Responde igual exista o no la
    cuenta, para que no sirva para averiguar quién está registrado."""
    email = tokens._normal(email)
    if not correo_configurado(env):
        raise RuntimeError("la recuperación por correo aún no está configurada")
    c = _con()
    try:
        if not c.execute("SELECT 1 FROM cuentas WHERE email=?", (email,)).fetchone():
            return
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO restablecer VALUES (?,?,?)", (_h(token), email, time.time() + DURACION_RESET))
    finally:
        c.close()
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = "Recupera tu contraseña", env("SMTP_REMITENTE"), email
    msg.set_content(f"Para poner una contraseña nueva entra aquí (caduca en una hora):\n\n"
                    f"{base_url}/?restablecer={token}\n\nSi no lo has pedido tú, ignora este correo.")
    with smtplib.SMTP(env("SMTP_HOST"), int(env("SMTP_PUERTO") or 587), timeout=20) as s:
        s.starttls()
        s.login(env("SMTP_USUARIO"), env("SMTP_CLAVE"))
        s.send_message(msg)


def restablecer(token, nueva):
    _validar_clave(nueva)
    c = _con()
    try:
        c.execute("BEGIN IMMEDIATE")
        f = c.execute("SELECT email, expira FROM restablecer WHERE token_hash=?", (_h(token or ""),)).fetchone()
        c.execute("DELETE FROM restablecer WHERE token_hash=?", (_h(token or ""),))
        if not f or f[1] < time.time():
            c.execute("COMMIT")
            raise PermissionError("el enlace no es válido o ha caducado")
        email = f[0]
        c.execute("UPDATE cuentas SET hash=? WHERE email=?", (_hash_clave(nueva), email))
        c.execute("DELETE FROM sesiones WHERE email=?", (email,))
        token_sesion = _nueva_sesion(c, email)
        c.execute("COMMIT")
    finally:
        c.close()
    return token_sesion

"""Planes y tokens de la suite: quién tiene qué plan y cuántos tokens le quedan.

Dos bolsas por usuario:
- plan: los tokens del mes de su plan. Se renuevan al empezar cada mes y no se acumulan.
- extra: tokens de packs comprados. No caducan. Se gastan después de los del plan.

Cada gasto o ingreso es un movimiento (para poder enseñar el historial y devolver lo
cobrado si un trabajo falla). Todo cobro comprueba el saldo dentro de la misma
transacción: dos peticiones a la vez no pueden gastar el mismo token.
"""

import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PLANES = AQUI / "planes.json"
BD = AQUI / "cuentas.db"
_candado = threading.Lock()


class SinSaldo(Exception):
    pass


def config():
    return json.loads(PLANES.read_text())


def _con():
    c = sqlite3.connect(BD, isolation_level=None, timeout=10)
    c.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        email TEXT PRIMARY KEY, plan TEXT NOT NULL, periodo TEXT NOT NULL,
        plan_tokens INTEGER NOT NULL, extra_tokens INTEGER NOT NULL, alta REAL NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, fecha REAL NOT NULL,
        tokens INTEGER NOT NULL, de_plan INTEGER NOT NULL, de_extra INTEGER NOT NULL,
        concepto TEXT NOT NULL, ref TEXT, devuelto INTEGER NOT NULL DEFAULT 0)""")
    return c


def _periodo():
    return datetime.now().strftime("%Y-%m")


def _normal(email):
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 200:
        raise ValueError("email no válido")
    return email


def _fila(c, email):
    """El usuario, dado de alta en Gratis si es nuevo y con el mes renovado si toca."""
    planes = config()["planes"]
    f = c.execute("SELECT plan, periodo, plan_tokens, extra_tokens FROM usuarios WHERE email=?",
                  (email,)).fetchone()
    if not f:
        c.execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)",
                  (email, "gratis", _periodo(), planes["gratis"]["tokens_mes"], 0, time.time()))
        return {"plan": "gratis", "plan_tokens": planes["gratis"]["tokens_mes"], "extra_tokens": 0}
    plan, periodo, pt, et = f
    if periodo != _periodo():
        pt = planes.get(plan, planes["gratis"])["tokens_mes"]
        c.execute("UPDATE usuarios SET periodo=?, plan_tokens=? WHERE email=?", (_periodo(), pt, email))
    return {"plan": plan, "plan_tokens": pt, "extra_tokens": et}


def saldo(email):
    email = _normal(email)
    with _candado:
        c = _con()
        try:
            c.execute("BEGIN IMMEDIATE")
            f = _fila(c, email)
            c.execute("COMMIT")
        finally:
            c.close()
    p = config()["planes"][f["plan"]]
    return {"email": email, "plan": f["plan"], "plan_nombre": p["nombre"],
            "tokens": f["plan_tokens"] + f["extra_tokens"],
            "del_plan": f["plan_tokens"], "extra": f["extra_tokens"],
            "trabajos_a_la_vez": p["trabajos_a_la_vez"]}


def cobrar(email, tokens, concepto, ref=None):
    """Descuenta tokens (primero los del plan) o lanza SinSaldo sin tocar nada."""
    email, tokens = _normal(email), int(tokens)
    if tokens <= 0:
        raise ValueError("cantidad no válida")
    with _candado:
        c = _con()
        try:
            c.execute("BEGIN IMMEDIATE")
            f = _fila(c, email)
            if f["plan_tokens"] + f["extra_tokens"] < tokens:
                c.execute("COMMIT")
                raise SinSaldo(f"hacen falta {tokens} tokens y te quedan "
                               f"{f['plan_tokens'] + f['extra_tokens']}")
            de_plan = min(tokens, f["plan_tokens"])
            de_extra = tokens - de_plan
            c.execute("UPDATE usuarios SET plan_tokens=plan_tokens-?, extra_tokens=extra_tokens-? WHERE email=?",
                      (de_plan, de_extra, email))
            c.execute("INSERT INTO movimientos (email, fecha, tokens, de_plan, de_extra, concepto, ref) "
                      "VALUES (?,?,?,?,?,?,?)", (email, time.time(), -tokens, de_plan, de_extra, concepto, ref))
            c.execute("COMMIT")
        finally:
            c.close()
    return saldo(email)


def devolver(email, ref):
    """Devuelve lo cobrado con esa referencia (un trabajo que falló), una sola vez."""
    email = _normal(email)
    with _candado:
        c = _con()
        try:
            c.execute("BEGIN IMMEDIATE")
            _fila(c, email)
            filas = c.execute("SELECT id, de_plan, de_extra FROM movimientos "
                              "WHERE email=? AND ref=? AND tokens<0 AND devuelto=0", (email, ref)).fetchall()
            for mid, de_plan, de_extra in filas:
                c.execute("UPDATE usuarios SET plan_tokens=plan_tokens+?, extra_tokens=extra_tokens+? WHERE email=?",
                          (de_plan, de_extra, email))
                c.execute("UPDATE movimientos SET devuelto=1 WHERE id=?", (mid,))
                c.execute("INSERT INTO movimientos (email, fecha, tokens, de_plan, de_extra, concepto, ref) "
                          "VALUES (?,?,?,?,?,?,?)",
                          (email, time.time(), de_plan + de_extra, de_plan, de_extra, "devolución", ref))
            c.execute("COMMIT")
        finally:
            c.close()
    return len(filas) > 0


def poner_plan(email, plan):
    """Cambia el plan y le da ya los tokens del mes del plan nuevo (alta o mejora)."""
    email, planes = _normal(email), config()["planes"]
    if plan not in planes:
        raise ValueError(f"plan desconocido: {plan}")
    with _candado:
        c = _con()
        try:
            c.execute("BEGIN IMMEDIATE")
            _fila(c, email)
            c.execute("UPDATE usuarios SET plan=?, periodo=?, plan_tokens=? WHERE email=?",
                      (plan, _periodo(), planes[plan]["tokens_mes"], email))
            c.execute("INSERT INTO movimientos (email, fecha, tokens, de_plan, de_extra, concepto, ref) "
                      "VALUES (?,?,?,?,?,?,?)",
                      (email, time.time(), planes[plan]["tokens_mes"], planes[plan]["tokens_mes"], 0,
                       f"plan {plan}", None))
            c.execute("COMMIT")
        finally:
            c.close()
    return saldo(email)


def sumar_pack(email, pack):
    email, packs = _normal(email), config()["packs"]
    if pack not in packs:
        raise ValueError(f"pack desconocido: {pack}")
    n = packs[pack]["tokens"]
    with _candado:
        c = _con()
        try:
            c.execute("BEGIN IMMEDIATE")
            _fila(c, email)
            c.execute("UPDATE usuarios SET extra_tokens=extra_tokens+? WHERE email=?", (n, email))
            c.execute("INSERT INTO movimientos (email, fecha, tokens, de_plan, de_extra, concepto, ref) "
                      "VALUES (?,?,?,?,?,?,?)", (email, time.time(), n, 0, n, f"pack {pack}", None))
            c.execute("COMMIT")
        finally:
            c.close()
    return saldo(email)


def movimientos(email, limite=30):
    email = _normal(email)
    c = _con()
    try:
        filas = c.execute("SELECT fecha, tokens, concepto FROM movimientos WHERE email=? "
                          "ORDER BY id DESC LIMIT ?", (email, int(limite))).fetchall()
    finally:
        c.close()
    return [{"fecha": datetime.fromtimestamp(f).strftime("%Y-%m-%d %H:%M"), "tokens": t, "concepto": k}
            for f, t, k in filas]


# --------------------------------------------------------------- precios

def coste_analizar(minutos):
    k = config()["costes"]
    return max(k["analizar_minimo"], int(round(minutos * k["analizar_por_minuto"])))


def coste_proponer():
    return config()["costes"]["proponer"]


def coste_clips(n):
    return config()["costes"]["clip"] * int(n)


def coste_fal(usd):
    """Una generación de fal: su precio real × factor, en tokens (1 token = 0,01 €)."""
    return max(1, int(round(float(usd) * config()["factor_fal"] * 100)))


if __name__ == "__main__":
    # Mientras no haya pagos: asignar planes y packs a mano.
    #   python3 motor/tokens.py saldo ana@x.com
    #   python3 motor/tokens.py plan ana@x.com creador
    #   python3 motor/tokens.py pack ana@x.com p500
    import sys
    orden, email, *resto = sys.argv[1:] + [None]
    hacer = {"saldo": lambda: saldo(email), "plan": lambda: poner_plan(email, resto[0]),
             "pack": lambda: sumar_pack(email, resto[0])}
    print(json.dumps(hacer[orden](), ensure_ascii=False, indent=1))

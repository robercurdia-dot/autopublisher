"""Cuentas: registro privado o abierto, contraseñas con hash, bloqueo por intentos y sesiones.

    motor/.venv/bin/python -m unittest tests.test_cuentas -v
"""

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "motor"))
import cuentas  # noqa: E402
import tokens  # noqa: E402


class TestCuentas(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.orig = (tokens.BD, cuentas.ACCESO)
        tokens.BD, cuentas.ACCESO = d / "cuentas.db", d / "acceso.json"
        self.acceso("privado", ["yo@x.com"])
        cuentas._fallos.clear()

    def tearDown(self):
        tokens.BD, cuentas.ACCESO = self.orig
        self.tmp.cleanup()

    def acceso(self, registro, permitidos):
        cuentas.ACCESO.write_text(json.dumps({"registro": registro, "permitidos": permitidos}))

    def test_privada_solo_entra_quien_esta_en_la_lista(self):
        with self.assertRaises(cuentas.NoPermitido):
            cuentas.registrar("otro@x.com", "una-clave-larga")
        tok = cuentas.registrar("Yo@X.com", "una-clave-larga")
        self.assertEqual(cuentas.sesion(tok), "yo@x.com")
        self.assertEqual(tokens.saldo("yo@x.com")["plan"], "gratis", "el registro da de alta en Gratis")

    def test_abrirla_es_cambiar_una_linea(self):
        self.acceso("abierto", [])
        self.assertTrue(cuentas.sesion(cuentas.registrar("otro@x.com", "una-clave-larga")))

    def test_quitar_a_alguien_de_la_lista_le_cierra_la_sesion(self):
        tok = cuentas.registrar("yo@x.com", "una-clave-larga")
        self.acceso("privado", [])
        self.assertIsNone(cuentas.sesion(tok))

    def test_contrasenas(self):
        with self.assertRaises(ValueError):
            cuentas.registrar("yo@x.com", "corta")
        cuentas.registrar("yo@x.com", "una-clave-larga")
        with self.assertRaises(ValueError):
            cuentas.registrar("yo@x.com", "otra-clave-larga")
        guardado = sqlite3.connect(tokens.BD).execute("SELECT hash FROM cuentas").fetchone()[0]
        self.assertTrue(guardado.startswith("scrypt$"))
        self.assertNotIn("una-clave-larga", guardado)
        with self.assertRaises(PermissionError):
            cuentas.entrar("yo@x.com", "mala-clave-larga")
        self.assertTrue(cuentas.entrar("yo@x.com", "una-clave-larga"))

    def test_mismo_error_exista_o_no_la_cuenta(self):
        with self.assertRaises(PermissionError) as a:
            cuentas.entrar("nadie@x.com", "lo-que-sea-largo")
        cuentas.registrar("yo@x.com", "una-clave-larga")
        with self.assertRaises(PermissionError) as b:
            cuentas.entrar("yo@x.com", "lo-que-sea-largo")
        self.assertEqual(str(a.exception), str(b.exception))

    def test_bloqueo_por_intentos(self):
        cuentas.registrar("yo@x.com", "una-clave-larga")
        for _ in range(cuentas.MAX_FALLOS):
            with self.assertRaises(PermissionError):
                cuentas.entrar("yo@x.com", "mala-clave-larga", "1.2.3.4")
        with self.assertRaises(cuentas.Bloqueado):
            cuentas.entrar("yo@x.com", "una-clave-larga", "1.2.3.4")

    def test_las_sesiones_se_guardan_como_hash_y_caducan(self):
        tok = cuentas.registrar("yo@x.com", "una-clave-larga")
        c = sqlite3.connect(tokens.BD)
        self.assertIsNone(c.execute("SELECT 1 FROM sesiones WHERE token_hash=?", (tok,)).fetchone())
        c.execute("UPDATE sesiones SET ultimo=?", (time.time() - cuentas.DURACION_SESION - 1,))
        c.commit()
        self.assertIsNone(cuentas.sesion(tok))

    def test_salir_y_cambiar_clave_cierran_sesiones(self):
        t1 = cuentas.registrar("yo@x.com", "una-clave-larga")
        t2 = cuentas.entrar("yo@x.com", "una-clave-larga")
        cuentas.salir(t1)
        self.assertIsNone(cuentas.sesion(t1))
        t3 = cuentas.cambiar_clave("yo@x.com", "una-clave-larga", "otra-clave-larga")
        self.assertIsNone(cuentas.sesion(t2))
        self.assertEqual(cuentas.sesion(t3), "yo@x.com")

    def test_restablecer_una_sola_vez(self):
        cuentas.registrar("yo@x.com", "una-clave-larga")
        enviados = []
        env = {"SMTP_HOST": "h", "SMTP_USUARIO": "u", "SMTP_CLAVE": "c", "SMTP_REMITENTE": "r@x.com"}.get

        class SMTPFalso:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def starttls(self): pass
            def login(self, *a): pass
            def send_message(self, msg): enviados.append(msg.get_content())

        orig = cuentas.smtplib.SMTP
        cuentas.smtplib.SMTP = SMTPFalso
        try:
            cuentas.pedir_reset("nadie@x.com", "https://web", env)
            self.assertEqual(enviados, [], "a quien no existe no se le envía nada")
            cuentas.pedir_reset("yo@x.com", "https://web", env)
        finally:
            cuentas.smtplib.SMTP = orig
        token = enviados[0].split("restablecer=")[1].split()[0]
        self.assertTrue(cuentas.restablecer(token, "nueva-clave-larga"))
        with self.assertRaises(PermissionError):
            cuentas.restablecer(token, "otra-clave-larga")
        self.assertTrue(cuentas.entrar("yo@x.com", "nueva-clave-larga"))

    def test_sin_correo_configurado_lo_dice(self):
        with self.assertRaises(RuntimeError):
            cuentas.pedir_reset("yo@x.com", "https://web", lambda k: None)


if __name__ == "__main__":
    unittest.main()

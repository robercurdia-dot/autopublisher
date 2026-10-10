"""La suite como web: acceso con clave, cada sesión solo ve lo suyo, y nada de rutas del Mac.

    motor/.venv/bin/python -m unittest tests.test_web -v
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "motor"))
import servidor_mcp as m  # noqa: E402
import servidor_web as w  # noqa: E402


class TestWeb(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.orig = (m.TRABAJOS, w.ENV, os.environ.get("SUITE_CLAVE"), os.environ.get("ANTHROPIC_API_KEY"))
        m.TRABAJOS, w.ENV = d / "trabajos", d / ".env"
        m.TRABAJOS.mkdir()
        os.environ["SUITE_CLAVE"] = "clave-de-prueba"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        # Un análisis ajeno, ya terminado.
        fuente = d / "fuente"
        fuente.mkdir()
        (fuente / "transcripcion.json").write_text(json.dumps(
            {"duracion": 60, "titulo": "t", "canal": "c", "segmentos": [{"ini": 1, "fin": 2, "t": "Hola."}]}))
        (m.TRABAJOS / "aaaaaaaa.json").write_text(json.dumps(
            {"id": "aaaaaaaa", "tipo": "analisis", "pid": None, "creado": 0, "carpeta": str(fuente)}))
        self.srv = w.servidor(0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
        self.galleta = None

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        m.TRABAJOS, w.ENV = self.orig[0], self.orig[1]
        for k, v in (("SUITE_CLAVE", self.orig[2]), ("ANTHROPIC_API_KEY", self.orig[3])):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        w.SESIONES.clear()
        self.tmp.cleanup()

    def pedir(self, ruta, datos=None):
        req = urllib.request.Request(self.base + ruta, data=json.dumps(datos).encode() if datos is not None else None,
                                     headers={"Content-Type": "application/json"})
        if self.galleta:
            req.add_header("Cookie", self.galleta)
        try:
            with urllib.request.urlopen(req) as r:
                if r.headers.get("Set-Cookie"):
                    self.galleta = r.headers["Set-Cookie"].split(";")[0]
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_la_pagina_carga_sin_sesion(self):
        codigo, cuerpo = self.pedir("/")
        self.assertEqual(codigo, 200)
        self.assertIn(b"Clipper", cuerpo)

    def test_sin_clave_no_se_entra(self):
        self.assertEqual(self.pedir("/api/yo")[0], 401)
        self.assertEqual(self.pedir("/api/analizar", {"url": "https://x.com/a"})[0], 401)
        self.assertEqual(self.pedir("/api/entrar", {"clave": "otra"})[0], 403)
        self.assertEqual(self.pedir("/api/entrar", {"clave": "clave-de-prueba"})[0], 200)
        self.assertEqual(self.pedir("/api/yo")[0], 200)

    def test_cada_sesion_solo_ve_lo_suyo(self):
        self.pedir("/api/entrar", {"clave": "clave-de-prueba"})
        self.assertEqual(self.pedir("/api/trabajo?id=aaaaaaaa")[0], 403)
        self.assertEqual(self.pedir("/api/clip?id=aaaaaaaa&n=1")[0], 403)
        self.assertEqual(self.pedir("/api/trabajo?id=../../etc")[0], 403)
        w.SESIONES[self.galleta.split("=", 1)[1]].add("aaaaaaaa")
        codigo, cuerpo = self.pedir("/api/trabajo?id=aaaaaaaa")
        self.assertEqual(codigo, 200)
        self.assertNotIn(self.tmp.name, cuerpo.decode(), "no enseña rutas del Mac")

    def test_sin_clave_de_anthropic_lo_dice(self):
        self.pedir("/api/entrar", {"clave": "clave-de-prueba"})
        w.SESIONES[self.galleta.split("=", 1)[1]].add("aaaaaaaa")
        codigo, cuerpo = self.pedir("/api/proponer", {"id": "aaaaaaaa"})
        self.assertEqual(codigo, 400)
        self.assertIn("ANTHROPIC_API_KEY", json.loads(cuerpo)["error"])

    def test_reglas_de_la_suite(self):
        r = w.reglas()
        self.assertIn("CONFLICTO", r)
        self.assertIn("Responde SOLO con JSON", r)

    def test_tramos_de_los_momentos(self):
        self.assertEqual(w.tramos_de([{"ini": "01:05", "fin": "01:35"}, {"ini": "2:00", "fin": "2:30"}]),
                         "65-95,120-150")
        with self.assertRaises(ValueError):
            w.tramos_de([{"ini": "01:05", "fin": "01:06"}])
        with self.assertRaises(ValueError):
            w.tramos_de([])


if __name__ == "__main__":
    unittest.main()

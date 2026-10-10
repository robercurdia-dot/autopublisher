"""La suite como web: acceso con clave, cada cuenta solo ve lo suyo, cobro en tokens.

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
import tokens  # noqa: E402


class TestWeb(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.orig = (m.TRABAJOS, w.ENV, tokens.BD, w.duracion_minutos, m.analizar,
                     os.environ.get("SUITE_CLAVE"), os.environ.get("ANTHROPIC_API_KEY"))
        m.TRABAJOS, w.ENV, tokens.BD = d / "trabajos", d / ".env", d / "cuentas.db"
        m.TRABAJOS.mkdir()
        os.environ["SUITE_CLAVE"] = "clave-de-prueba"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        # Un análisis ya terminado, de otra persona.
        self.fuente = d / "fuente"
        self.fuente.mkdir()
        (self.fuente / "transcripcion.json").write_text(json.dumps(
            {"duracion": 60, "titulo": "t", "canal": "c", "segmentos": [{"ini": 1, "fin": 2, "t": "Hola."}]}))
        (m.TRABAJOS / "aaaaaaaa.json").write_text(json.dumps(
            {"id": "aaaaaaaa", "tipo": "analisis", "pid": None, "creado": 0, "carpeta": str(self.fuente),
             "email": "otra@x.com"}))
        self.srv = w.servidor(0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
        self.galleta = None

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        m.TRABAJOS, w.ENV, tokens.BD, w.duracion_minutos, m.analizar = self.orig[:5]
        for k, v in (("SUITE_CLAVE", self.orig[5]), ("ANTHROPIC_API_KEY", self.orig[6])):
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
                return r.status, json.loads(r.read() or b"null") if "json" in r.headers.get("Content-Type", "") else r.read()
        except urllib.error.HTTPError as e:
            cuerpo = e.read()
            e.close()
            return e.code, json.loads(cuerpo or b"null")

    def entrar(self, email="yo@x.com"):
        return self.pedir("/api/entrar", {"email": email, "clave": "clave-de-prueba"})

    def test_la_pagina_y_los_planes_sin_sesion(self):
        codigo, cuerpo = self.pedir("/")
        self.assertEqual(codigo, 200)
        self.assertIn(b"Clipper", cuerpo)
        codigo, planes = self.pedir("/api/planes")
        self.assertEqual(set(planes["planes"]), {"gratis", "creador", "pro", "agencia"})

    def test_sin_clave_no_se_entra(self):
        self.assertEqual(self.pedir("/api/yo")[0], 401)
        self.assertEqual(self.pedir("/api/analizar", {"url": "https://x.com/a"})[0], 401)
        self.assertEqual(self.pedir("/api/entrar", {"email": "yo@x.com", "clave": "otra"})[0], 403)
        self.assertEqual(self.pedir("/api/entrar", {"email": "sin-arroba", "clave": "clave-de-prueba"})[0], 400)
        self.assertEqual(self.entrar()[0], 200)
        codigo, cuenta = self.pedir("/api/cuenta")
        self.assertEqual((codigo, cuenta["plan"], cuenta["tokens"]), (200, "gratis", 150))

    def test_cada_cuenta_solo_ve_lo_suyo(self):
        self.entrar()
        self.assertEqual(self.pedir("/api/trabajo?id=aaaaaaaa")[0], 403)
        self.assertEqual(self.pedir("/api/clip?id=aaaaaaaa&n=1")[0], 403)
        self.assertEqual(self.pedir("/api/trabajo?id=../../etc")[0], 403)
        self.galleta = None
        self.entrar("otra@x.com")
        codigo, t = self.pedir("/api/trabajo?id=aaaaaaaa")
        self.assertEqual(codigo, 200)
        self.assertNotIn(self.tmp.name, json.dumps(t), "no enseña rutas del Mac")

    def test_analizar_cobra_y_si_falla_devuelve(self):
        w.duracion_minutos = lambda url: 40
        m.analizar = lambda url: m._lanzar([sys.executable, "-c", "raise SystemExit('Error: falló')"],
                                           {"tipo": "analisis", "url": url})
        self.entrar()
        codigo, r = self.pedir("/api/analizar", {"url": "https://www.youtube.com/watch?v=x"})
        self.assertEqual((codigo, r["coste"], r["saldo"]), (200, 40, 110))
        import time
        for _ in range(50):
            codigo, t = self.pedir(f"/api/trabajo?id={r['id']}")
            if t["estado"] != "en_curso":
                break
            time.sleep(0.1)
        self.assertEqual((t["estado"], t["devuelto"]), ("fallido", True))
        self.assertEqual(self.pedir("/api/cuenta")[1]["tokens"], 150)
        self.assertFalse(self.pedir(f"/api/trabajo?id={r['id']}")[1]["devuelto"], "solo se devuelve una vez")

    def test_sin_saldo_no_se_lanza(self):
        w.duracion_minutos = lambda url: 200
        lanzados = []
        m.analizar = lambda url: lanzados.append(url)
        self.entrar()
        codigo, r = self.pedir("/api/analizar", {"url": "https://www.youtube.com/watch?v=x"})
        self.assertEqual(codigo, 402)
        self.assertEqual(lanzados, [])

    def test_sin_clave_de_anthropic_lo_dice_y_no_cobra(self):
        self.entrar("otra@x.com")
        codigo, r = self.pedir("/api/proponer", {"id": "aaaaaaaa"})
        self.assertEqual(codigo, 400)
        self.assertIn("ANTHROPIC_API_KEY", r["error"])
        self.assertEqual(self.pedir("/api/cuenta")[1]["tokens"], 150)

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

"""Planes y tokens: altas en Gratis, cobros sin saldo negativo, devoluciones y renovación.

    python3 -m unittest tests.test_planes -v
"""

import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "motor"))
import tokens as t  # noqa: E402


class TestTokens(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = t.BD
        t.BD = Path(self.tmp.name) / "cuentas.db"

    def tearDown(self):
        t.BD = self.orig
        self.tmp.cleanup()

    def test_alta_en_gratis(self):
        s = t.saldo("Ana@Ejemplo.com")
        self.assertEqual((s["email"], s["plan"], s["tokens"]), ("ana@ejemplo.com", "gratis", 150))

    def test_cobro_y_sin_saldo(self):
        t.cobrar("a@b.c", 100, "análisis", "x1")
        with self.assertRaises(t.SinSaldo):
            t.cobrar("a@b.c", 51, "momentos")
        self.assertEqual(t.saldo("a@b.c")["tokens"], 50, "un cobro rechazado no toca el saldo")

    def test_primero_los_del_plan_luego_los_extra(self):
        t.sumar_pack("a@b.c", "p500")
        s = t.cobrar("a@b.c", 200, "clips")
        self.assertEqual((s["del_plan"], s["extra"]), (0, 450))

    def test_devolucion_una_sola_vez(self):
        t.sumar_pack("a@b.c", "p500")
        t.cobrar("a@b.c", 300, "clips", "trabajo1")
        self.assertTrue(t.devolver("a@b.c", "trabajo1"))
        self.assertFalse(t.devolver("a@b.c", "trabajo1"))
        s = t.saldo("a@b.c")
        self.assertEqual((s["del_plan"], s["extra"]), (150, 500), "vuelve a cada bolsa lo que salió de ella")

    def test_el_mes_nuevo_renueva_el_plan_sin_acumular(self):
        t.poner_plan("a@b.c", "creador")
        t.sumar_pack("a@b.c", "p500")
        t.cobrar("a@b.c", 1000, "generación")
        c = sqlite3.connect(t.BD)
        c.execute("UPDATE usuarios SET periodo='2000-01'")
        c.commit()
        c.close()
        s = t.saldo("a@b.c")
        self.assertEqual((s["del_plan"], s["extra"]), (1200, 500))

    def test_dos_cobros_a_la_vez_no_gastan_el_mismo_token(self):
        t.saldo("a@b.c")
        resultados = []

        def gastar():
            try:
                t.cobrar("a@b.c", 100, "carrera")
                resultados.append("ok")
            except t.SinSaldo:
                resultados.append("sin saldo")

        hilos = [threading.Thread(target=gastar) for _ in range(4)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        self.assertEqual(resultados.count("ok"), 1)
        self.assertEqual(t.saldo("a@b.c")["tokens"], 50)

    def test_precios(self):
        self.assertEqual(t.coste_analizar(2), 5, "mínimo")
        self.assertEqual(t.coste_analizar(77), 77)
        self.assertEqual(t.coste_clips(4), 20)
        self.assertEqual(t.coste_fal(2.9), 580, "Recast de 6,5 s a 1080p")

    def test_plan_y_pack_desconocidos(self):
        with self.assertRaises(ValueError):
            t.poner_plan("a@b.c", "oro")
        with self.assertRaises(ValueError):
            t.sumar_pack("a@b.c", "p9")
        with self.assertRaises(ValueError):
            t.saldo("sin-arroba")


if __name__ == "__main__":
    unittest.main()

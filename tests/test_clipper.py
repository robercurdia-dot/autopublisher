"""Cada test reproduce un error de clipper/errores.json y comprueba que no vuelve.

Se trabaja sobre vídeos sintéticos generados con ffmpeg, no sobre vídeos
reales: así se sabe exactamente dónde está la intro, dónde el pico de audio y
qué hay en los laterales, y el resultado no depende de la red.

    python3 -m unittest tests.test_clipper -v
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "clipper"))
import autoclipper as ac  # noqa: E402

ERRORES = json.loads((REPO / "clipper" / "errores.json").read_text())["errores"]

# Vídeo largo de prueba: 240 s.
#   0-30 s    intro: alterna oscuro y claro cada medio segundo (muy montada)
#   30-240 s  contenido: un nivel de gris que cambia cada 25 s y un cuadrado
#             que se mueve
#   audio     tono bajo todo el rato, y un pico fuerte entre 150 y 156 s
PICO = (150.0, 156.0)
LUM = ("clip(if(lt(T,30), 40+180*mod(floor(T*2),2),"
       " 90+40*mod(floor(T/25),3)"
       " + 120*between(X,mod(T*12,160)-8,mod(T*12,160)+8)*between(Y,35,55)),0,255)")
AUDIO = (f"if(between(t,{PICO[0]},{PICO[1]}),0.9,0.03)*sin(2*PI*440*t)")


def generar(destino, segundos, lum, audio=None, tam="160x90"):
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y",
           "-f", "lavfi", "-i", f"color=c=gray:s={tam}:r=10:d={segundos},format=gray,"
                               f"geq=lum='{lum}',format=yuv420p"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"aevalsrc='{audio}':s=8000:d={segundos}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    subprocess.run(cmd + [str(destino)], check=True)
    return destino


class TestClipper(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.largo = generar(d / "largo.mp4", 240, LUM, AUDIO)
        cls.corto = generar(d / "corto.mp4", 20, "90+60*between(X,mod(T*20,160)-8,mod(T*20,160)+8)",
                            "0.2*sin(2*PI*440*t)")
        cls.r = ac.analizar(cls.largo, cuantos=3, todas=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_cada_error_tiene_su_test(self):
        """Un error sin test no está arreglado, solo anotado."""
        definidos = {n for n in dir(self) if n.startswith("test_")}
        for e in ERRORES:
            self.assertIn(e["test"], definidos, f"el error «{e['id']}» no tiene test")

    def test_criterios_relativos_al_video(self):
        """No quedan constantes de otro nicho y las señales son percentiles."""
        self.assertFalse(hasattr(ac, "RITMO_OBJETIVO"),
                         "vuelve a haber un ritmo objetivo absoluto")
        v = ac.percentil([5, 1, 3, 3, 9])
        self.assertEqual(v.min(), 0.0)
        self.assertEqual(v.max(), 1.0)
        self.assertEqual(v[2], v[3], "los empates deben compartir percentil")
        for c in self.r["todas"]:
            for k in ac.PESOS:
                self.assertTrue(0.0 <= c[k] <= 1.0)

    def test_no_elige_la_intro(self):
        self.assertGreaterEqual(self.r["margen"], 30.0)
        for c in self.r["clips"]:
            self.assertGreaterEqual(c["ini"], self.r["margen"],
                                    f"clip en la intro: {c['ini']}-{c['fin']}")
            self.assertLessEqual(c["fin"], self.r["duracion_fuente"] - self.r["margen"],
                                 f"clip en el cierre: {c['ini']}-{c['fin']}")

    def test_clips_sin_solape_y_separados(self):
        cs = sorted(self.r["clips"], key=lambda c: c["ini"])
        self.assertGreaterEqual(len(cs), 2, "con 240 s debe haber sitio para varios clips")
        hueco = self.r["duracion_clip"] / 2
        for a, b in zip(cs, cs[1:]):
            self.assertGreaterEqual(b["ini"] - a["fin"], hueco - 0.01,
                                    f"clips demasiado juntos: {a['ini']}-{a['fin']} y {b['ini']}-{b['fin']}")

    def test_encuentra_el_pico_de_audio(self):
        self.assertTrue(self.r["con_audio"])
        mejor = max(self.r["clips"], key=lambda c: c["puntos"])
        self.assertTrue(mejor["ini"] <= PICO[0] and mejor["fin"] >= PICO[1],
                        f"el mejor clip ({mejor['ini']}-{mejor['fin']}) no contiene el pico {PICO}")

    def test_arco_no_satura(self):
        arcos = [c["arco"] for c in self.r["todas"]]
        self.assertGreater(np.std(arcos), 0.1, "el arco no discrimina entre ventanas")
        self.assertFalse(all(c["arco"] == 1.0 for c in self.r["clips"]),
                         "todos los clips elegidos tienen el arco al máximo")

    def test_recorte_detecta_detalle_en_los_laterales(self):
        h, w = 180, 320
        liso = np.full((h, w), 100.0)
        liso[:, 110:210] = np.tile([0.0, 255.0], (h, 50))      # detalle solo en el centro
        con_rotulo = liso.copy()
        con_rotulo[20:50, :] = np.tile([0.0, 255.0], (30, w // 2))  # rótulo de lado a lado
        self.assertLess(ac.detalle_laterales(liso), ac.UMBRAL_LATERALES,
                        "laterales lisos no deberían pedir encuadre completo")
        self.assertGreaterEqual(ac.detalle_laterales(con_rotulo), ac.UMBRAL_LATERALES,
                                "un rótulo de lado a lado debe pedir encuadre completo")

    def test_ningun_criterio_es_constante(self):
        self.assertNotIn("duracion", ac.PESOS, "la duración vuelve a ser criterio")
        for k, peso in self.r["pesos"].items():
            if peso > 0:
                self.assertGreater(np.std([c[k] for c in self.r["todas"]]), 0,
                                   f"el criterio «{k}» vale lo mismo en todas las ventanas")

    def test_duracion_segun_la_fuente(self):
        self.assertEqual(self.r["duracion_clip"], ac.DURACION_LARGA)
        self.assertEqual(ac.analizar(self.corto, cuantos=1)["duracion_clip"], ac.DURACION_CORTA)


if __name__ == "__main__":
    unittest.main()

"""Cada test reproduce un error de clipper/errores.json y comprueba que no vuelve.

Se trabaja sobre vídeos sintéticos generados con ffmpeg, no sobre vídeos
reales: así se sabe exactamente dónde está la intro, dónde el pico de audio y
qué hay en los laterales, y el resultado no depende de la red.

    python3 -m unittest tests.test_clipper -v
"""

import json
import re
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
        # En cualquier fichero de tests: los de subtítulos viven en test_subtitulos.py.
        fuentes = " ".join(f.read_text() for f in (REPO / "tests").glob("test_*.py"))
        definidos = set(re.findall(r"def (test_\w+)\(", fuentes))
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

    def test_a_camara_se_recorta_sobre_la_cara(self):
        # Medidas reales del Xokas: a cámara la cara ocupa 0,54-0,60 del alto;
        # su webcam en la esquina de un tuit, 0,20.
        self.assertTrue(ac.es_a_camara([(0.59, 0.60), (0.56, 0.54), (0.52, 0.56), (0.53, 0.6), (0.5, 0.58)]))
        self.assertFalse(ac.es_a_camara([(0.85, 0.22), (0.81, 0.20), (0.84, 0.21)]))
        self.assertFalse(ac.es_a_camara([(0.5, 0.6)]), "una cara suelta no es alguien hablando")
        # El recorte sigue a la cara y nunca se sale del plano.
        self.assertEqual(ac.x_recorte(0.5, 1920, 1080), int(960 - 1080 * 9 / 32))
        self.assertEqual(ac.x_recorte(0.0, 1920, 1080), 0)
        self.assertEqual(ac.x_recorte(1.0, 1920, 1080), int(1920 - 1080 * 9 / 16))

    def test_el_origen_sobrevive_al_reprocesar(self):
        d = Path(self.tmp.name) / "con_origen"
        d.mkdir(exist_ok=True)
        video = d / "original.mp4"
        video.write_bytes(b"")
        self.assertEqual(ac.leer_origen(video), {})
        ac.guardar_origen(video, {"webpage_url": "https://youtu.be/x", "uploader": "alguien"})
        self.assertEqual(ac.leer_origen(video)["uploader"], "alguien")

    def test_metadatos_avisan_si_fallan(self):
        from descargar import metadatos
        with self.assertWarns(UserWarning):
            self.assertEqual(metadatos("https://no-existe.invalid/video"), {})

    def test_reaccion_webcam_arriba_y_una_sola_vez(self):
        # Medidas reales del clip 3 del Xokas: webcam abajo a la derecha (0,19 de
        # alto) en 4 de 5 fotogramas y un plano a cámara (0,53) en medio.
        xokas = [(0.84, 0.20, 0.75, 0.09), (0.54, 0.53, 0.50, 0.22), (0.78, 0.18, 0.74, 0.08),
                 (0.87, 0.18, 0.75, 0.08), (0.82, 0.20, 0.76, 0.09)]
        caja = ac.webcam(xokas)
        self.assertIsNotNone(caja)
        self.assertFalse(ac.es_a_camara(xokas))
        # Webcam diminuta (0,078) arriba a la derecha mientras el vídeo enseña
        # caras grandes: reacción a la casa de Grefg.
        grefg = [[(0.908, 0.084, 0.196, 0.037)], [(0.91, 0.078, 0.195, 0.035)],
                 [(0.473, 0.518, 0.541, 0.2), (0.909, 0.08, 0.194, 0.036)],
                 [(0.907, 0.073, 0.191, 0.034)], [(0.561, 0.574, 0.553, 0.233)]]
        self.assertIsNotNone(ac.webcam(grefg))
        # Gente del tour por el centro de la imagen: no es una webcam.
        tour = [[(0.479, 0.446, 0.591, 0.186)], [(0.414, 0.15, 0.276, 0.061)],
                [(0.453, 0.081, 0.354, 0.037)], [(0.443, 0.156, 0.317, 0.072)], [(0.45, 0.13, 0.30, 0.07)]]
        self.assertIsNone(ac.webcam(tour))
        # El Xokas entrando en el plano por arriba: cara cortada por el borde.
        entrando = [[], [], [(0.3, 0.13, 0.07, 0.09)], [(0.28, 0.15, 0.08, 0.1)],
                    [(0.29, 0.15, 0.08, 0.11)], [(0.3, 0.16, 0.08, 0.1)], [(0.31, 0.16, 0.08, 0.1)]]
        self.assertIsNone(ac.webcam(entrando))
        # Una cara pequeña que salta de sitio no es una webcam fija.
        self.assertIsNone(ac.webcam([(0.2, 0.2, 0.3, 0.1), (0.8, 0.2, 0.7, 0.1), (0.5, 0.2, 0.2, 0.1)]))
        x, y, cw, ch = ac.recorte_webcam(caja, 1920, 1080)
        self.assertTrue(0 <= x and x + cw <= 1920 and 0 <= y and y + ch <= 1080)
        self.assertLessEqual(x, caja[0] * 1920 - caja[2] * 1920 / 2, "la cara no entra entera")
        # La pantalla de abajo deja fuera la columna de la webcam.
        px, pw = ac.pantalla_sin_webcam(caja, x, cw, 1920)
        self.assertLessEqual(px + pw, x)
        d = Path(self.tmp.name)
        sal = d / "reaccion.mp4"
        ac.cortar(self.largo, 60, 64, sal, "reaccion", caja=caja)
        self.assertEqual(ac.medidas(sal), (1080, 1920))

    def test_tramos_elegidos_a_mano(self):
        r = ac.tramos_fijos(self.largo, "10-20, 1:00-1:30")
        self.assertEqual([(c["ini"], c["fin"]) for c in r["clips"]], [(10.0, 20.0), (60.0, 90.0)])
        self.assertTrue(r["con_audio"])
        with self.assertRaises(SystemExit):
            ac.tramos_fijos(self.largo, "230-300")

    def test_encuadre_por_plano(self):
        # Cambios de plano a 5, 6 y 20 s: el de 6 está a 1 s del anterior y se suma.
        self.assertEqual(ac.planos([5, 6, 20], 0, 30), [(0, 5), (5, 20), (20, 30)])
        lista = [{"ini": 0, "fin": 5, "encuadre": "reaccion", "extra": (0.85, 0.15, 0.07, 0.16)},
                 {"ini": 5, "fin": 12, "encuadre": "cara", "extra": 0.50},
                 {"ini": 12, "fin": 20, "encuadre": "cara", "extra": 0.53},
                 {"ini": 20, "fin": 30, "encuadre": "cara", "extra": 0.80}]
        unidos = ac.unir_planos(lista)
        self.assertEqual([(p["ini"], p["fin"], p["encuadre"]) for p in unidos],
                         [(0, 5, "reaccion"), (5, 20, "cara"), (20, 30, "cara")])
        # Un clip con dos encuadres sale entero, vertical y con su audio.
        sal = Path(self.tmp.name) / "planos.mp4"
        ac.cortar_planos(self.largo, 60, 66, sal,
                         [{"ini": 60, "fin": 63, "encuadre": "completo", "extra": None},
                          {"ini": 63, "fin": 66, "encuadre": "recorte", "extra": None}])
        self.assertEqual(ac.medidas(sal), (1080, 1920))
        self.assertAlmostEqual(ac.datos_video(sal)["duracion"], 6.0, delta=0.3)
        flujos = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                                 "-of", "csv=p=0", str(sal)], capture_output=True, text=True).stdout
        self.assertIn("audio", flujos)

    def test_pantalla_partida_mitades(self):
        d = Path(self.tmp.name)
        rojo = d / "fondo_rojo.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=red:s=320x180:r=10:d=5", "-c:v", "libx264", "-pix_fmt",
                        "yuv420p", str(rojo)], check=True)
        sal = d / "partido.mp4"
        ac.cortar(self.largo, 60, 66, sal, "completo", fondo=rojo)
        self.assertEqual(ac.medidas(sal), (1080, 1920))
        r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", "2", "-i", str(sal),
                            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True, check=True)
        img = np.frombuffer(r.stdout, dtype=np.uint8).reshape(1920, 1080, 3).astype(int)
        abajo, arriba = img[1100:1900].mean(axis=(0, 1)), img[100:860].mean(axis=(0, 1))
        self.assertGreater(abajo[0] - abajo[1], 150, "la mitad de abajo no es el fondo")
        self.assertLess(abs(arriba[0] - arriba[1]), 40, "el fondo se ha colado arriba")

    @unittest.skipUnless((REPO / "clipper" / "modelos" / "ggml-large-v3-turbo.bin").exists(),
                         "falta el modelo de whisper")
    def test_alto_del_video_no_se_pisa(self):
        d = Path(self.tmp.name)
        vertical = generar(d / "vertical.mp4", 60, "90+60*between(Y,mod(T*20,320)-8,mod(T*20,320)+8)",
                           "0.2*sin(2*PI*440*t)*(1+between(t,40,44))", "180x320")
        salida = d / "vertical_clips"
        subprocess.run([sys.executable, str(REPO / "clipper" / "autoclipper.py"), str(vertical),
                        "--cuantos", "3", "--duracion", "8", "--salida", str(salida)],
                       check=True, capture_output=True)
        clips = json.loads((salida / "informe.json").read_text())["clips"]
        self.assertGreater(len(clips), 1)
        self.assertEqual({c["encuadre"] for c in clips}, {"original"},
                         "un vídeo vertical se ha reencuadrado")


if __name__ == "__main__":
    unittest.main()

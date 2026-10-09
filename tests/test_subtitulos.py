"""Subtítulos del clipper: frases, cortes en pausas, ASS sin solapes y quemado real.

Los tests de lógica usan palabras inventadas con tiempos conocidos. Los de
integración generan voz en castellano con `say` (macOS), la transcriben con
whisper.cpp y queman el resultado; se saltan si falta el modelo o ffmpeg-full.

    python3 -m unittest tests.test_subtitulos -v
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "clipper"))
import subtitulos as st  # noqa: E402


def pal(*tramos):
    """pal(("hola", 0.0, 0.4), ...) → lista de palabras."""
    return [{"t": t, "ini": a, "fin": b} for t, a, b in tramos]


FRASE = pal(("Esto", 0.0, 0.3), ("es", 0.35, 0.5), ("una", 0.55, 0.8), ("prueba.", 0.85, 1.3),
            ("Ahora", 2.4, 2.8), ("viene", 2.85, 3.1), ("lo", 3.15, 3.25), ("bueno", 3.3, 3.8),
            ("de", 3.85, 3.95), ("verdad,", 4.0, 4.5), ("mira", 4.55, 4.9))


class TestLogica(unittest.TestCase):

    def test_frases_cortas_y_por_pausa(self):
        g = st.frases(FRASE)
        self.assertTrue(all(len(x) <= st.PALABRAS_POR_FRASE for x in g))
        # «prueba.» cierra frase: no se junta con lo que viene después.
        self.assertTrue(any(x[-1]["t"] == "prueba." for x in g))
        # Y no queda huérfana: «Esto es una prueba.» se reparte 2 + 2.
        self.assertEqual([len(x) for x in g[:2]], [2, 2])
        # Tras la coma se corta aunque la frase no esté llena.
        self.assertTrue(any(x[-1]["t"] == "verdad," for x in g))

    def test_ass_sin_solapes_y_una_entrada_por_palabra(self):
        texto = st.ass(FRASE)
        ev = st.eventos(texto)
        self.assertEqual(len(ev), len(FRASE))
        for (a0, b0), (a1, _) in zip(ev, ev[1:]):
            self.assertLess(a0, b0)
            self.assertLessEqual(b0, a1 + 1e-6, "dos rótulos a la vez")
        self.assertEqual(texto.count(st.ESTILO["resalte"]), len(FRASE))

    def test_ass_relativo_al_clip(self):
        movidas = [dict(p, ini=p["ini"] + 100, fin=p["fin"] + 100) for p in FRASE]
        self.assertEqual(st.eventos(st.ass(movidas, desplazamiento=100)), st.eventos(st.ass(FRASE)))

    def test_rotulo_cambia_de_sitio_con_el_plano(self):
        arriba = dict(st.ESTILO, margen_v=1000)
        texto = st.ass(FRASE, 0, por_tramo=[(0, 2.0, arriba), (2.0, 10, st.ESTILO)])
        self.assertEqual(sum(1 for l in texto.splitlines() if l.startswith("Style:")), 2)
        dialogos = [l.split(",")[3] for l in texto.splitlines() if l.startswith("Dialogue")]
        self.assertEqual(dialogos[0], "E0")
        self.assertEqual(dialogos[-1], "E1")

    def test_ass_escapa_llaves(self):
        texto = st.ass(pal(("{\\b1}hola", 0, 0.5)))
        dialogo = [l for l in texto.splitlines() if l.startswith("Dialogue")][0]
        self.assertNotIn("{\\b1}", dialogo)

    def test_corte_cae_en_pausa(self):
        # Cortar en 3.2 parte «lo»; cerca hay una pausa larga tras «prueba.» (1,85).
        ini, fin = st.ajustar_cortes(1.6, 20.0, FRASE)
        self.assertTrue(1.3 <= ini <= 2.4, ini)
        ini, _ = st.ajustar_cortes(3.2, 20.0, FRASE, holgura=0.2)
        habla = [(p["ini"], p["fin"]) for p in FRASE]
        self.assertFalse(any(a < ini < b for a, b in habla), f"corta a media palabra: {ini}")

    def test_corte_tras_el_punto_con_tiempos_pegados(self):
        # Tiempos reales del vídeo de Rubius: whisper los da sin huecos.
        pegadas = pal(("bien.", 752.20, 752.56), ("Este", 752.56, 752.79), ("es", 752.79, 752.87),
                      ("el", 752.87, 752.97), ("número", 752.97, 753.34), ("7.", 753.34, 753.78),
                      ("Esa", 753.78, 753.99), ("carta", 753.99, 754.35), ("está", 754.35, 754.64),
                      ("rota", 754.64, 754.93))
        ini, _ = st.ajustar_cortes(753.48, 800.0, pegadas)
        # Tras «7.» (753.78) o tras «bien.» (752.56); nunca dentro de la frase.
        self.assertIn(round(ini, 2), (752.56, 753.78))
        self.assertEqual(round(ini, 2), 753.78, "el punto más cercano")

    def test_correcciones_y_guiones(self):
        x = pal(("de", 0, 0.2), ("pagos.", 0.2, 0.6), ("al", 0.6, 0.8), ("Bolt", 0.8, 1.0))
        st.corregir(x, "pagos=pavos, bolt=goat")
        self.assertEqual([p["t"] for p in x], ["de", "pavos.", "al", "goat"])
        self.assertEqual(x[1]["ini"], 0.2, "los tiempos no se tocan")

    def test_transcripcion_empieza_lejos_del_clip(self):
        # El desfase del prompt de whisper llegaba hasta ~13 s dentro de la ventana.
        self.assertGreaterEqual(st.ENTRADA_TRANSCRIPCION, 20)
        fuente = (REPO / "clipper" / "autoclipper.py").read_text()
        self.assertIn("c[\"ini\"] - subtitulos.ENTRADA_TRANSCRIPCION", fuente)

    def test_tramo_elegido_casi_no_se_mueve(self):
        # Cirujano 43:31: con la holgura normal retrocede hasta «Dana…».
        x = pal(("contenido.", 2611.9, 2612.5), ("Dana", 2612.6, 2613.0), ("es", 2613.1, 2613.3),
                ("una", 2613.3, 2613.6), ("de", 2613.6, 2613.8), ("ellas.", 2613.8, 2614.5),
                ("Me", 2616.2, 2616.4), ("alegro", 2616.4, 2617.0), ("mucho.", 2617.1, 2617.4),
                ("La", 2617.5, 2617.7), ("gente", 2617.7, 2618.1))
        ini, _ = st.ajustar_cortes(2617.45, 2648.0, x, holgura=0.4, atras_fin=0.4)
        self.assertGreaterEqual(ini, 2617.0)
        self.assertLess(abs(ini - 2617.45), 0.5)

    def test_tramo_elegido_avanza_hasta_el_cierre_de_frase(self):
        # Auron 0:41 (9 oct): el tramo se elige en segundos enteros, redondeados hacia
        # abajo; el cierre quedaba a 0,45 s, fuera del margen, y el clip abría con
        # «disfrutándolo.», la cola de la frase anterior. Hacia delante puede ir más lejos.
        x = pal(("tema,", 40.35, 40.62), ("disfrutándolo.", 40.62, 41.4), ("Sí.", 41.5, 42.5),
                ("Tú", 42.5, 42.58), ("porque", 42.58, 42.83), ("eres", 42.83, 42.99))
        ini, _ = st.ajustar_cortes(41.0, 62.0, x, holgura=st.TRAMO_ADELANTE, atras_fin=st.TRAMO_ATRAS)
        anterior = [p for p in x if p["fin"] <= ini + 0.01][-1]["t"]
        self.assertTrue(anterior.endswith("."), "empieza con la cola de otra frase")
        self.assertLess(ini - 41.0, st.TRAMO_ADELANTE + 0.01)
        fuente = (REPO / "clipper" / "autoclipper.py").read_text()
        self.assertIn("subtitulos.TRAMO_ADELANTE", fuente)

    def test_inicio_en_frase_entera_no_tras_coma(self):
        # Caso «Ceuta a nado»: el corte caía tras una coma, a mitad de idea.
        x = pal(("La", 450.0, 450.2), ("cosa", 450.2, 450.5), ("es", 450.5, 450.6), ("así.", 450.6, 451.0),
                ("Si", 451.0, 451.2), ("vas", 451.2, 451.5), ("en", 451.5, 451.6), ("patera,", 451.6, 452.3),
                ("te", 452.3, 452.4), ("pillan,", 452.4, 452.9), ("te", 452.9, 453.0), ("cogen", 453.0, 453.4))
        ini, _ = st.ajustar_cortes(452.6, 480.0, x)
        self.assertAlmostEqual(ini, 451.0, places=1)
        anterior = [p for p in x if p["fin"] <= ini + 0.01][-1]["t"]
        self.assertTrue(anterior.endswith("."), "no empieza en una frase entera")

    def test_final_en_cierre_de_frase_aunque_este_lejos(self):
        # Caso del Xokas: el remate acaba 7 s antes del corte, luego habla otro
        # y la frase más cercana al corte termina en coma.
        x = pal(("ya", 758.5, 758.8), ("no", 758.8, 759.0), ("se", 759.0, 759.2), ("la", 759.2, 759.4),
                ("coláis.", 759.4, 760.0), ("Tenemos", 761.0, 761.5), ("dos", 761.5, 761.8),
                ("consideraciones", 761.8, 762.6), ("previas,", 762.6, 763.5), ("agradecer", 763.5, 764.2),
                ("la", 764.2, 764.4), ("cooperación", 764.4, 765.5), ("aquí", 765.5, 768.2),
                ("presente,", 768.2, 769.0), ("institucional", 769.0, 770.0))
        _, fin = st.ajustar_cortes(738.0, 768.4, x)
        self.assertAlmostEqual(fin, 760.5, places=1)
        anterior = [p for p in x if p["fin"] <= fin + 0.01][-1]["t"]
        self.assertFalse(anterior.endswith(","), "acaba en coma")

    def test_ninguna_frase_pasa_de_una_linea(self):
        largas = pal(("película", 0, 0.5), ("de", 0.5, 0.6), ("Interestral", 0.6, 1.2),
                     ("extraordinariamente", 1.2, 2.0), ("bien", 2.0, 2.3))
        for g in st.frases(largas):
            texto = " ".join(p["t"] for p in g)
            self.assertTrue(len(g) == 1 or len(texto) <= st.CARACTERES_POR_FRASE, texto)

    def test_los_dos_ffmpeg_arrancan(self):
        for exe, necesita in (("ffmpeg", ["libx264"]), (st.FFMPEG_SUB, ["libx264"])):
            if not shutil.which(exe) and not Path(exe).exists():
                self.skipTest(f"no está {exe}")
            r = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{exe} no arranca: {r.stderr[-300:]}")
            for n in necesita:
                self.assertIn(n, r.stdout, f"{exe} sin {n}")
        if Path(st.FFMPEG_SUB).exists():
            f = subprocess.run([st.FFMPEG_SUB, "-hide_banner", "-filters"], capture_output=True, text=True)
            self.assertRegex(f.stdout, r"\bass\b", "ffmpeg-full sin libass")

    def test_sin_habla_no_toca_el_corte(self):
        self.assertEqual(st.ajustar_cortes(50.0, 80.0, FRASE), (50.0, 80.0))


@unittest.skipUnless(st.MODELO.exists() and shutil.which(st.WHISPER) and shutil.which("say")
                     and Path(st.FFMPEG_SUB).exists(), "falta whisper, el modelo, say o ffmpeg-full")
class TestIntegracion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        aiff = d / "voz.aiff"
        subprocess.run(["say", "-v", "Mónica", "-o", str(aiff),
                        "Hoy abrimos un sobre nuevo. [[slnc 1200]] Y sale una carta increíble."],
                       check=True)
        # Vídeo vertical gris de 1080x1920 con esa voz, dos segundos de cola.
        cls.video = d / "voz.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=0x404040:s=1080x1920:r=25:d=8", "-i", str(aiff),
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(cls.video)], check=True)
        cls.palabras = st.transcribir(cls.video)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_transcribe_castellano(self):
        texto = " ".join(p["t"] for p in self.palabras).lower()
        for w in ("sobre", "carta", "increíble"):
            self.assertIn(w, texto)

    def test_tiempos_ordenados_y_dentro_del_audio(self):
        for a, b in zip(self.palabras, self.palabras[1:]):
            self.assertLessEqual(a["ini"], b["ini"])
        self.assertLess(self.palabras[-1]["fin"], 8.0)

    def test_tramo_en_segundos_absolutos(self):
        tramo = st.transcribir(self.video, ini=2.0)
        self.assertTrue(tramo and all(p["ini"] >= 2.0 for p in tramo))

    def test_quema_y_se_ve(self):
        sal = Path(self.tmp.name) / "sub.mp4"
        st.quemar(self.video, st.ass(self.palabras), sal)
        mitad = (self.palabras[1]["ini"] + self.palabras[1]["fin"]) / 2
        r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{mitad:.2f}", "-i", str(sal),
                            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True, check=True)
        img = np.frombuffer(r.stdout, dtype=np.uint8).reshape(1920, 1080, 3).astype(int)
        amarillo = (img[..., 0] > 200) & (img[..., 1] > 180) & (img[..., 2] < 80)
        filas = np.where(amarillo.any(axis=1))[0]
        self.assertGreater(amarillo.sum(), 500, "no aparece la palabra resaltada")
        # Por encima de la franja de interfaz de Shorts (último ~20 % del alto).
        self.assertLess(filas.max(), 1920 * 0.8)


if __name__ == "__main__":
    unittest.main()

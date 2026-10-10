"""El motor MCP local: protocolo, herramientas y que no se salga de sus carpetas.

    python3 -m unittest tests.test_motor -v
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "motor"))
import servidor_mcp as m  # noqa: E402


def hablar(*mensajes):
    """Arranca el servidor por stdio como lo haría la app y devuelve sus respuestas."""
    entrada = "\n".join(json.dumps(x) for x in mensajes) + "\n"
    r = subprocess.run([sys.executable, str(REPO / "motor" / "servidor_mcp.py")], input=entrada,
                       capture_output=True, text=True, timeout=60)
    return [json.loads(l) for l in r.stdout.splitlines() if l.strip()]


class TestProtocolo(unittest.TestCase):

    def test_proceso_acabado_no_cuenta_como_vivo(self):
        # 9 oct: el análisis acabó pero quedó zombi (hijo sin recoger) y el motor lo
        # daba por «en curso» para siempre, así que no dejaba cortar los clips.
        import time
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        for _ in range(50):
            time.sleep(0.1)
            if subprocess.run(["ps", "-o", "stat=", "-p", str(p.pid)],
                              capture_output=True, text=True).stdout.strip().startswith("Z"):
                break
        self.assertFalse(m._vivo(p.pid))

    def test_saludo_y_lista_por_stdio(self):
        r = hablar({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "test", "version": "0"}}},
                   {"jsonrpc": "2.0", "method": "notifications/initialized"},
                   {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(r), 2, "la notificación no lleva respuesta")
        self.assertEqual(r[0]["result"]["serverInfo"]["name"], "autopublisher")
        nombres = {t["name"] for t in r[1]["result"]["tools"]}
        self.assertEqual(nombres, {"analizar", "transcripcion", "clipear", "trabajos", "miniatura",
                                   "abrir", "programar", "cola", "actualizar_cola", "estado"})
        lectura = {t["name"]: t["annotations"]["readOnlyHint"] for t in r[1]["result"]["tools"]}
        self.assertFalse(lectura["clipear"])
        self.assertTrue(lectura["trabajos"])

    def test_un_fallo_no_tumba_el_servidor(self):
        r = hablar({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "clipear", "arguments": {"url": "no es un enlace"}}},
                   {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "estado", "arguments": {}}})
        self.assertTrue(r[0]["result"]["isError"])
        self.assertIn("enlace", r[0]["result"]["content"][0]["text"])
        self.assertIn("subtitulos", r[1]["result"]["structuredContent"])

    def test_metodo_desconocido(self):
        r = hablar({"jsonrpc": "2.0", "id": 7, "method": "resources/list"})
        self.assertEqual(r[0]["error"]["code"], -32601)


class TestHerramientas(unittest.TestCase):

    def test_no_lee_fuera_de_sus_carpetas(self):
        for ruta in ("/etc/passwd", str(Path.home() / ".ssh" / "id_rsa"), "~/../../etc/hosts"):
            with self.assertRaises(ValueError):
                m.miniatura(ruta)
            with self.assertRaises(ValueError):
                m.abrir(ruta)

    def test_id_de_trabajo_validado(self):
        with self.assertRaises(ValueError):
            m._ruta_trabajo("../../cuentas")

    def test_miniatura_de_un_clip(self):
        with tempfile.TemporaryDirectory(dir=REPO / "motor") as d:
            v = Path(d) / "c.mp4"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc2=s=320x568:d=2", "-pix_fmt", "yuv420p", str(v)], check=True)
            r = m.miniatura(str(v), segundo=1)
            self.assertEqual(r["mime"], "image/jpeg")
            self.assertTrue(r["base64"].startswith("/9j/"), "no es un JPEG")

    def test_trabajo_fallido_dice_por_que(self):
        texto = "ERROR: [youtube] x: Sign in to confirm you’re not a bot."
        self.assertIn("sesión de Chrome", m._motivo(texto))

    def test_estado_cuenta_enmiendas_activas(self):
        e = m.estado()
        enm = json.loads((REPO / "fase0" / "enmiendas.json").read_text())["enmiendas"]
        self.assertEqual(e["enmiendas_activas"],
                         sum(1 for x in enm if x.get("estado", "activa") == "activa"))
        self.assertIn("youtube_clips", e["cuentas"])


class TestFlujoEditor(unittest.TestCase):
    """Análisis → transcripción → tramos → cola de publicación, sin red."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=REPO / "motor")
        d = Path(self.tmp.name)
        self.orig = (m.TRABAJOS, m.COLA, m.SUBIR)
        m.TRABAJOS, m.COLA, m.SUBIR = d / "trabajos", d / "cola.json", d / "subir"
        m.TRABAJOS.mkdir()
        # Un análisis terminado, como lo dejaría transcribir_fuente.py.
        self.fuente = d / "fuente"
        self.fuente.mkdir()
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=3",
                        "-pix_fmt", "yuv420p", str(self.fuente / "original.mp4")], check=True)
        (self.fuente / "transcripcion.json").write_text(json.dumps(
            {"duracion": 75, "titulo": "Prueba", "canal": "alguien", "url": "https://youtu.be/x",
             "segmentos": [{"ini": 1, "fin": 3, "t": "Hola."}, {"ini": 40, "fin": 42, "t": "Adiós."}]}))
        self.aid = "abcd1234"
        (m.TRABAJOS / f"{self.aid}.json").write_text(json.dumps(
            {"id": self.aid, "tipo": "analisis", "pid": None, "creado": 0, "carpeta": str(self.fuente)}))
        (m.TRABAJOS / f"{self.aid}.log").write_text(f"40 frases transcritas en {self.fuente}/\n")

    def tearDown(self):
        m.TRABAJOS, m.COLA, m.SUBIR = self.orig
        self.tmp.cleanup()

    def test_transcripcion_en_bloques(self):
        self.assertEqual(m.transcripcion(self.aid)["texto"].splitlines(), ["00:01 Hola.", "00:40 Adiós."])
        t = m.transcripcion(self.aid, bloque=30)
        self.assertEqual(t["texto"].splitlines(), ["[00:00] Hola.", "[00:30] Adiós."])
        self.assertEqual(m._leer(self.aid)["fuente"]["frases"], 2)

    def test_tramos_mal_escritos_se_rechazan(self):
        with self.assertRaises(ValueError):
            m.clipear(analisis=self.aid, tramos="desde el 3 al 10")

    def test_cola_de_publicacion(self):
        video = self.fuente / "original.mp4"
        with self.assertRaises(ValueError):
            m.programar(str(video), "Título", "", "2020-01-01T09:00")
        with self.assertRaises(ValueError):
            m.programar(str(video), "x" * 101, "", "2099-01-01T09:00")
        with self.assertRaises(ValueError):
            m.programar("/etc/hosts", "Título", "", "2099-01-01T09:00")
        item = m.programar(str(video), "Título", "Desc", "2099-01-01T09:00")
        self.assertTrue(Path(item["subir"]).exists())
        self.assertLessEqual(Path(item["subir"]).stat().st_size, m.MAX_SUBIDA)
        m.actualizar_cola(item["id"], "programado", url="https://youtube.com/shorts/abc")
        c = m.cola()["cola"]
        self.assertEqual((c[0]["estado"], c[0]["url"]), ("programado", "https://youtube.com/shorts/abc"))

    def test_como_mucho_dos_clips_al_dia(self):
        # ClipperZero, 8 y 10 oct: con 5-6 clips el mismo día solo el primero recibió
        # vistas (1358 frente a 115, 52, 36, 26, 22; y 116 frente a 2, 0, 0, 0).
        video = self.fuente / "original.mp4"
        a = m.programar(str(video), "Uno", "", "2099-03-01T09:00")
        m.programar(str(video), "Dos", "", "2099-03-01T19:00")
        with self.assertRaises(ValueError) as e:
            m.programar(str(video), "Tres", "", "2099-03-01T13:00")
        self.assertIn("2099-03-02", str(e.exception))
        m.programar(str(video), "Tres", "", "2099-03-01T13:00", plataforma="tiktok")
        m.actualizar_cola(a["id"], "cancelado")
        m.programar(str(video), "Tres", "", "2099-03-01T13:00")


if __name__ == "__main__":
    unittest.main()

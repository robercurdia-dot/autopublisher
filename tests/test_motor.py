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

    def test_saludo_y_lista_por_stdio(self):
        r = hablar({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "test", "version": "0"}}},
                   {"jsonrpc": "2.0", "method": "notifications/initialized"},
                   {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(r), 2, "la notificación no lleva respuesta")
        self.assertEqual(r[0]["result"]["serverInfo"]["name"], "autopublisher")
        nombres = {t["name"] for t in r[1]["result"]["tools"]}
        self.assertEqual(nombres, {"clipear", "trabajos", "miniatura", "abrir", "estado"})
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


if __name__ == "__main__":
    unittest.main()

#!/opt/homebrew/bin/python3
"""El motor del Autopublisher como servidor MCP local (stdio).

La suite es una página publicada (el artifact Autopublisher); una página no
puede ejecutar nada en este Mac. Este servidor es lo que sí puede: la app de
Claude lo arranca, y la página lo llama como `host:autopublisher` cuando la
abre su dueño dentro de la app. Así la suite funciona sin que haya una
conversación con Claude abierta.

Sin dependencias: el protocolo MCP por stdio es JSON-RPC, una línea por
mensaje. Herramientas:

  clipear      lanza el autoclipper sobre un enlace, en segundo plano
  trabajos     lista los trabajos con su estado, su registro y sus clips
  miniatura    un fotograma de un clip, para verlo en la página
  abrir        abre un clip o su carpeta en este Mac
  estado       lo que la suite necesita saber del motor

Los trabajos sobreviven a que el servidor se reinicie: cada uno es un fichero
en motor/trabajos/ y el clipper corre como proceso aparte.
"""

import base64
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRABAJOS = REPO / "motor" / "trabajos"
CLIPS = Path.home() / "Downloads" / "clips"
PYTHON = sys.executable
PROTOCOLO = "2025-06-18"

# La app de Claude arranca el servidor con un PATH mínimo; sin esto no
# encuentra ffmpeg, yt-dlp ni whisper-cli, y el clipper falla al primer paso.
os.environ["PATH"] = ":".join(["/opt/homebrew/bin", "/usr/local/bin", os.environ.get("PATH", "/usr/bin:/bin")])

# Solo se leen o abren ficheros de aquí: la página no puede pedir cualquier
# ruta del disco.
PERMITIDAS = (CLIPS, REPO)


# ----------------------------------------------------------------- trabajos

def _ruta_trabajo(tid):
    if not re.fullmatch(r"[0-9a-f]{8}", tid or ""):
        raise ValueError("id de trabajo no válido")
    return TRABAJOS / f"{tid}.json"


def _vivo(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, TypeError):
        return False


def clipear(url, cuantos=3, duracion=None, fondo=None, vocabulario=None,
            sesion_chrome=False):
    if not re.match(r"^https?://", url or ""):
        raise ValueError("hace falta un enlace http(s)")
    cuantos = max(1, min(int(cuantos), 10))
    TRABAJOS.mkdir(parents=True, exist_ok=True)
    tid = uuid.uuid4().hex[:8]
    log = TRABAJOS / f"{tid}.log"
    cmd = [PYTHON, str(REPO / "clipper" / "autoclipper.py"), url, "--cuantos", str(cuantos)]
    if duracion:
        cmd += ["--duracion", str(float(duracion))]
    if fondo:
        cmd += ["--fondo", str(_permitida(fondo))]
    if vocabulario:
        cmd += ["--vocabulario", str(vocabulario)[:300]]
    if sesion_chrome:
        cmd += ["--cookies-de", "chrome"]
    with open(log, "w") as f:
        p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=REPO,
                             start_new_session=True, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    datos = {"id": tid, "url": url, "cuantos": cuantos, "duracion": duracion,
             "fondo": fondo, "vocabulario": vocabulario, "sesion_chrome": sesion_chrome,
             "pid": p.pid, "creado": time.time(), "carpeta": None}
    _ruta_trabajo(tid).write_text(json.dumps(datos, ensure_ascii=False))
    return {"id": tid, "estado": "en_curso"}


def _leer(tid):
    d = json.loads(_ruta_trabajo(tid).read_text())
    log = TRABAJOS / f"{tid}.log"
    texto = log.read_text(errors="replace") if log.exists() else ""
    m = re.search(r"clips en (.+?)/?\s*$", texto, re.M)
    if m and not d.get("carpeta"):
        d["carpeta"] = m.group(1)
        _ruta_trabajo(tid).write_text(json.dumps(d, ensure_ascii=False))
    vivo = _vivo(d.get("pid"))
    if d.get("carpeta") and (Path(d["carpeta"]) / "informe.json").exists() and not vivo:
        estado = "terminado"
    elif vivo:
        estado = "en_curso"
    else:
        estado = "fallido"
    d["estado"] = estado
    lineas = [l for l in texto.splitlines() if l.strip()]
    d["registro"] = lineas[-12:]
    if estado == "fallido":
        d["motivo"] = _motivo(texto)
    d["clips"] = _clips(d["carpeta"]) if estado == "terminado" else []
    return d


def _motivo(texto):
    """La causa legible de un fallo, con la salida si la tiene."""
    if "confirm you" in texto and "bot" in texto:
        return ("YouTube pide confirmar que no eres un bot. Vuelve a lanzarlo con "
                "«usar mi sesión de Chrome».")
    errores = [l for l in texto.splitlines() if re.search(r"error|Error|SystemExit|no existe", l)]
    return (errores[-1] if errores else "el proceso terminó sin dejar informe")[:300]


def _clips(carpeta):
    inf = Path(carpeta) / "informe.json"
    if not inf.exists():
        return []
    r = json.loads(inf.read_text())
    out = []
    for i, c in enumerate(r.get("clips", []), 1):
        archivos = c.get("archivos") or ([c["archivo"]] if c.get("archivo") else [])
        out.append({"n": i, "ini": c["ini"], "fin": c["fin"], "puntos": c.get("puntos"),
                    "audio": c.get("audio"), "encuadre": c.get("encuadre"),
                    "texto": c.get("texto", ""), "archivos": archivos,
                    "publicado": c.get("publicado")})
    return out


def trabajos(limite=20):
    if not TRABAJOS.exists():
        return {"trabajos": []}
    fs = sorted(TRABAJOS.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    return {"trabajos": [_leer(f.stem) for f in fs[: int(limite)]]}


# ------------------------------------------------------------------ ficheros

def _permitida(ruta):
    p = Path(ruta).expanduser().resolve()
    if not any(p == b.resolve() or b.resolve() in p.parents for b in PERMITIDAS):
        raise ValueError("ruta fuera de las carpetas del motor")
    if not p.exists():
        raise ValueError(f"no existe: {p.name}")
    return p


def miniatura(ruta, segundo=3.0, ancho=240):
    p = _permitida(ruta)
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{float(segundo):.2f}",
                        "-i", str(p), "-frames:v", "1", "-vf", f"scale={int(ancho)}:-2",
                        "-f", "image2", "-c:v", "mjpeg", "-q:v", "5", "-"],
                       capture_output=True, check=True)
    return {"mime": "image/jpeg", "base64": base64.b64encode(r.stdout).decode()}


def abrir(ruta, carpeta=False):
    p = _permitida(ruta)
    subprocess.run(["open", "-R", str(p)] if carpeta else ["open", str(p)], check=True)
    return {"abierto": p.name}


# -------------------------------------------------------------------- estado

def estado():
    modelo = REPO / "clipper" / "modelos" / "ggml-large-v3-turbo.bin"
    errores = json.loads((REPO / "clipper" / "errores.json").read_text())["errores"]
    enm = json.loads((REPO / "fase0" / "enmiendas.json").read_text())
    activas = [e for e in enm["enmiendas"] if e.get("estado", "activa") == "activa"]
    cuentas = json.loads((REPO / "cuentas.json").read_text())["cuentas"]
    return {
        "motor": "local",
        "subtitulos": modelo.exists() and Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg").exists(),
        "caras": (REPO / "clipper" / "modelos" / "yunet.onnx").exists(),
        "errores_clipper": [{"id": e["id"], "pendiente": bool(e.get("pendiente"))} for e in errores],
        "enmiendas_activas": len(activas),
        "cuentas": {k: {"estado": v.get("estado"), "via": v.get("via"),
                        "nombre": v.get("usuario") or v.get("canal") or v.get("pagina")}
                    for k, v in cuentas.items()},
        "generacion": {"fal": "sin saldo", "flashboards": "sin saldo"},
    }


# ------------------------------------------------------------------ protocolo

def _obj(props, req=()):
    return {"type": "object", "properties": props, "required": list(req),
            "additionalProperties": False}


HERRAMIENTAS = {
    "clipear": (clipear, "Lanza el autoclipper sobre un enlace (YouTube, TikTok, Instagram, X, "
                "Facebook) en segundo plano y devuelve el id del trabajo. Tarda minutos.",
                _obj({"url": {"type": "string"},
                      "cuantos": {"type": "integer", "minimum": 1, "maximum": 10},
                      "duracion": {"type": "number"},
                      "fondo": {"type": "string", "description": "ruta a un vídeo de fondo"},
                      "vocabulario": {"type": "string"},
                      "sesion_chrome": {"type": "boolean"}}, ["url"]), False),
    "trabajos": (trabajos, "Trabajos del clipper, del más reciente al más antiguo, con estado, "
                 "registro y clips.", _obj({"limite": {"type": "integer"}}), True),
    "miniatura": (miniatura, "Un fotograma JPEG en base64 de un clip.",
                  _obj({"ruta": {"type": "string"}, "segundo": {"type": "number"},
                        "ancho": {"type": "integer"}}, ["ruta"]), True),
    "abrir": (abrir, "Abre un clip en el reproductor del Mac, o su carpeta en el Finder.",
              _obj({"ruta": {"type": "string"}, "carpeta": {"type": "boolean"}}, ["ruta"]), False),
    "estado": (estado, "Estado del motor: subtítulos, caras, errores, enmiendas, cuentas y saldos.",
               _obj({}), True),
}


def responder(msg):
    """Una respuesta JSON-RPC para un mensaje, o None si es una notificación."""
    metodo, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    if metodo == "initialize":
        version = (msg.get("params") or {}).get("protocolVersion") or PROTOCOLO
        res = {"protocolVersion": version, "capabilities": {"tools": {}},
               "serverInfo": {"name": "autopublisher", "version": "0.1.0"}}
    elif metodo == "ping":
        res = {}
    elif metodo == "tools/list":
        res = {"tools": [{"name": n, "description": d, "inputSchema": s,
                          "annotations": {"readOnlyHint": ro}}
                         for n, (_, d, s, ro) in HERRAMIENTAS.items()]}
    elif metodo == "tools/call":
        p = msg.get("params") or {}
        if p.get("name") not in HERRAMIENTAS:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": f"herramienta desconocida: {p.get('name')}"}}
        fn = HERRAMIENTAS[p["name"]][0]
        try:
            out = fn(**(p.get("arguments") or {}))
            res = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                   "structuredContent": out}
        except Exception as e:  # el fallo de una herramienta se devuelve, no tumba el servidor
            res = {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                   "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"método no soportado: {metodo}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        try:
            msg = json.loads(linea)
        except json.JSONDecodeError:
            continue
        r = responder(msg)
        if r is not None:
            sys.stdout.write(json.dumps(r, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

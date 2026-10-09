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
from datetime import datetime
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
    # Un hijo que ya acabó sigue «existiendo» como zombi hasta que se recoge: recogerlo aquí.
    try:
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    except (ChildProcessError, TypeError):
        pass
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, TypeError):
        return False


def _lanzar(cmd, datos):
    """Arranca un proceso aparte (sobrevive al servidor) y guarda su ficha."""
    TRABAJOS.mkdir(parents=True, exist_ok=True)
    tid = uuid.uuid4().hex[:8]
    with open(TRABAJOS / f"{tid}.log", "w") as f:
        p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=REPO,
                             start_new_session=True, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    datos = {"id": tid, "pid": p.pid, "creado": time.time(), "carpeta": None, **datos}
    _ruta_trabajo(tid).write_text(json.dumps(datos, ensure_ascii=False))
    return {"id": tid, "estado": "en_curso"}


def analizar(url, vocabulario=None, sesion_chrome=False):
    """Baja el vídeo y lo transcribe entero: primer paso para elegir clips leyendo."""
    if not re.match(r"^https?://", url or ""):
        raise ValueError("hace falta un enlace http(s)")
    cmd = [PYTHON, str(REPO / "clipper" / "transcribir_fuente.py"), url]
    if vocabulario:
        cmd += ["--vocabulario", str(vocabulario)[:300]]
    if sesion_chrome:
        cmd += ["--cookies-de", "chrome"]
    return _lanzar(cmd, {"tipo": "analisis", "url": url, "vocabulario": vocabulario})


def _fuente(trabajo):
    """Carpeta y vídeo original de un análisis terminado."""
    d = _leer(trabajo)
    if d.get("tipo") != "analisis" or d["estado"] != "terminado":
        raise ValueError("ese análisis no ha terminado")
    return Path(d["carpeta"]), Path(d["carpeta"]) / "original.mp4", d


def clipear(url=None, cuantos=3, duracion=None, fondo=None, vocabulario=None,
            sesion_chrome=False, analisis=None, tramos=None, propuestas=None, corregir=None):
    """Corta clips. Dos modos:

    - url: el clipper elige solo (por audio, imagen y ritmo).
    - analisis + tramos: corta los momentos elegidos leyendo la transcripción
      de un análisis («356-386,19:30-20:02»), con sus propuestas de título.
    """
    if analisis:
        carpeta, video, a = _fuente(analisis)
        if not re.fullmatch(r"[\d.:]+-[\d.:]+(\s*,\s*[\d.:]+-[\d.:]+)*", (tramos or "").strip()):
            raise ValueError("tramos no válidos: «356-386,19:30-20:02»")
        salida = carpeta / f"clips_{datetime.now():%Y%m%d-%H%M%S}"
        cmd = [PYTHON, str(REPO / "clipper" / "autoclipper.py"), str(video),
               "--tramos", tramos.strip(), "--salida", str(salida)]
        url = a.get("url")
        vocabulario = vocabulario or a.get("vocabulario")
    else:
        if not re.match(r"^https?://", url or ""):
            raise ValueError("hace falta un enlace http(s)")
        cmd = [PYTHON, str(REPO / "clipper" / "autoclipper.py"), url,
               "--cuantos", str(max(1, min(int(cuantos), 10)))]
        if duracion:
            cmd += ["--duracion", str(float(duracion))]
        if sesion_chrome:
            cmd += ["--cookies-de", "chrome"]
    if fondo:
        cmd += ["--fondo", str(_permitida(fondo))]
    if vocabulario:
        cmd += ["--vocabulario", str(vocabulario)[:300]]
    if corregir:
        cmd += ["--corregir", str(corregir)[:300]]
    return _lanzar(cmd, {"tipo": "clips", "url": url, "analisis": analisis, "tramos": tramos,
                         "propuestas": propuestas or [], "vocabulario": vocabulario})


def _leer(tid):
    d = json.loads(_ruta_trabajo(tid).read_text())
    d.setdefault("tipo", "clips")
    log = TRABAJOS / f"{tid}.log"
    texto = log.read_text(errors="replace") if log.exists() else ""
    m = re.search(r"(?:clips|frases transcritas) en (.+?)/?\s*$", texto, re.M)
    if m and not d.get("carpeta"):
        d["carpeta"] = m.group(1)
        _ruta_trabajo(tid).write_text(json.dumps(d, ensure_ascii=False))
    vivo = _vivo(d.get("pid"))
    hecho = "transcripcion.json" if d["tipo"] == "analisis" else "informe.json"
    if d.get("carpeta") and (Path(d["carpeta"]) / hecho).exists() and not vivo:
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
    d["clips"] = _clips(d["carpeta"], d.get("propuestas")) if estado == "terminado" and d["tipo"] == "clips" else []
    if estado == "terminado" and d["tipo"] == "analisis":
        t = json.loads((Path(d["carpeta"]) / "transcripcion.json").read_text())
        d["fuente"] = {"titulo": t.get("titulo"), "canal": t.get("canal"),
                       "duracion": t.get("duracion"), "frases": len(t.get("segmentos", []))}
    return d


def _motivo(texto):
    """La causa legible de un fallo, con la salida si la tiene."""
    if "confirm you" in texto and "bot" in texto:
        return ("YouTube pide confirmar que no eres un bot. Vuelve a lanzarlo con "
                "«usar mi sesión de Chrome».")
    errores = [l for l in texto.splitlines() if re.search(r"error|Error|SystemExit|no existe", l)]
    return (errores[-1] if errores else "el proceso terminó sin dejar informe")[:300]


def _clips(carpeta, propuestas=None):
    inf = Path(carpeta) / "informe.json"
    if not inf.exists():
        return []
    r = json.loads(inf.read_text())
    origen = r.get("origen") or {}
    out = []
    for i, c in enumerate(r.get("clips", []), 1):
        archivos = c.get("archivos") or ([c["archivo"]] if c.get("archivo") else [])
        prop = (propuestas or [])[i - 1] if propuestas and i <= len(propuestas) else None
        out.append({"n": i, "ini": c["ini"], "fin": c["fin"], "puntos": c.get("puntos"),
                    "audio": c.get("audio"), "encuadre": c.get("encuadre"),
                    "texto": c.get("texto", ""), "archivos": archivos,
                    "publicado": c.get("publicado"), "propuesta": prop,
                    "origen": {"url": origen.get("webpage_url"), "canal": origen.get("uploader")}})
    return out


def trabajos(limite=20):
    if not TRABAJOS.exists():
        return {"trabajos": []}
    fs = sorted(TRABAJOS.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    return {"trabajos": [_leer(f.stem) for f in fs[: int(limite)]]}


def transcripcion(analisis, bloque=0):
    """La transcripción de un análisis: frase a frase («mm:ss texto») o, con
    `bloque`, agrupada en bloques de tantos segundos («[mm:ss] texto»)."""
    carpeta, _, _ = _fuente(analisis)
    t = json.loads((carpeta / "transcripcion.json").read_text())
    if not bloque:
        # Frase a frase, con su segundo exacto: para que quien elige los cortes
        # pueda empezar justo donde arranca una frase.
        texto = "\n".join(f"{int(x['ini']) // 60:02d}:{int(x['ini']) % 60:02d} {x['t']}"
                          for x in t["segmentos"])
    else:
        grupos = {}
        for x in t["segmentos"]:
            grupos.setdefault(int(x["ini"] // bloque) * bloque, []).append(x["t"])
        texto = "\n".join(f"[{k // 60:02d}:{k % 60:02d}] " + " ".join(v) for k, v in sorted(grupos.items()))
    return {"titulo": t.get("titulo"), "canal": t.get("canal"), "url": t.get("url"),
            "duracion": t.get("duracion"), "texto": texto}


# -------------------------------------------------------------- publicación

COLA = REPO / "motor" / "cola_publicacion.json"
SUBIR = CLIPS / "subir"
# La subida por Chrome admite como mucho 10 MB por fichero: se prepara una
# copia por debajo de este tamaño al programar, con la misma resolución.
MAX_SUBIDA = 9_000_000


def _cola():
    return json.loads(COLA.read_text()) if COLA.exists() else []


def _guardar_cola(items):
    COLA.write_text(json.dumps(items, ensure_ascii=False, indent=1))


def _copia_para_subir(video, pid):
    SUBIR.mkdir(parents=True, exist_ok=True)
    destino = SUBIR / f"{pid}.mp4"
    if video.stat().st_size <= MAX_SUBIDA:
        destino.write_bytes(video.read_bytes())
        return destino
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout)
    kbps = int(MAX_SUBIDA * 0.95 * 8 / dur / 1000 - 130)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(video), "-c:v", "libx264",
                    "-preset", "slow", "-b:v", f"{kbps}k", "-maxrate", f"{kbps * 3 // 2}k",
                    "-bufsize", f"{kbps * 2}k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart", str(destino)], check=True)
    return destino


def programar(archivo, titulo, descripcion, cuando, plataforma="youtube"):
    """Deja un clip en la cola de publicación. `cuando`: «2026-10-09T09:00», hora de Madrid."""
    video = _permitida(archivo)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", cuando or ""):
        raise ValueError("fecha no válida: «2026-10-09T09:00»")
    if datetime.strptime(cuando, "%Y-%m-%dT%H:%M") <= datetime.now():
        raise ValueError("esa hora ya ha pasado")
    titulo = (titulo or "").strip()
    if not 0 < len(titulo) <= 100:
        raise ValueError("el título tiene que tener entre 1 y 100 caracteres")
    pid = uuid.uuid4().hex[:8]
    subir = _copia_para_subir(video, pid)
    item = {"id": pid, "plataforma": plataforma, "archivo": str(video), "subir": str(subir),
            "titulo": titulo, "descripcion": (descripcion or "").strip()[:4900],
            "cuando": cuando, "zona": "Europe/Madrid", "estado": "pendiente",
            "creado": time.time(), "url": None, "nota": None}
    items = _cola()
    items.append(item)
    _guardar_cola(items)
    return item


def cola():
    return {"cola": sorted(_cola(), key=lambda x: x["cuando"])}


def actualizar_cola(id, estado, url=None, nota=None):
    """Para el publicador: marca un elemento como programado, publicado o fallido."""
    if estado not in ("pendiente", "programado", "publicado", "fallido", "cancelado"):
        raise ValueError("estado no válido")
    items = _cola()
    for x in items:
        if x["id"] == id:
            x["estado"], x["actualizado"] = estado, time.time()
            if url:
                x["url"] = url
            if nota:
                x["nota"] = str(nota)[:300]
            _guardar_cola(items)
            return x
    raise ValueError("no está en la cola")


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
    "analizar": (analizar, "Baja un vídeo y lo transcribe entero, en segundo plano. Devuelve el id del "
                 "análisis; con él se piden la transcripción y los clips elegidos.",
                 _obj({"url": {"type": "string"}, "vocabulario": {"type": "string"},
                       "sesion_chrome": {"type": "boolean"}}, ["url"]), False),
    "transcripcion": (transcripcion, "La transcripción de un análisis terminado, en bloques de 30 s.",
                      _obj({"analisis": {"type": "string"}, "bloque": {"type": "integer"}},
                           ["analisis"]), True),
    "clipear": (clipear, "Corta clips. Con url, el clipper elige solo. Con analisis + tramos, corta "
                "los momentos elegidos («356-386,19:30-20:02») y guarda sus propuestas de título.",
                _obj({"url": {"type": "string"}, "analisis": {"type": "string"},
                      "tramos": {"type": "string"},
                      "propuestas": {"type": "array", "items": {"type": "object"}},
                      "cuantos": {"type": "integer", "minimum": 1, "maximum": 10},
                      "duracion": {"type": "number"},
                      "fondo": {"type": "string", "description": "ruta a un vídeo de fondo"},
                      "vocabulario": {"type": "string"}, "corregir": {"type": "string"},
                      "sesion_chrome": {"type": "boolean"}}), False),
    "trabajos": (trabajos, "Análisis y trabajos de clips, del más reciente al más antiguo, con estado, "
                 "registro y clips.", _obj({"limite": {"type": "integer"}}), True),
    "miniatura": (miniatura, "Un fotograma JPEG en base64 de un clip.",
                  _obj({"ruta": {"type": "string"}, "segundo": {"type": "number"},
                        "ancho": {"type": "integer"}}, ["ruta"]), True),
    "abrir": (abrir, "Abre un clip en el reproductor del Mac, o su carpeta en el Finder.",
              _obj({"ruta": {"type": "string"}, "carpeta": {"type": "boolean"}}, ["ruta"]), False),
    "programar": (programar, "Deja un clip en la cola de publicación con su título, descripción y "
                  "hora (hora de Madrid, «2026-10-09T09:00»).",
                  _obj({"archivo": {"type": "string"}, "titulo": {"type": "string"},
                        "descripcion": {"type": "string"}, "cuando": {"type": "string"},
                        "plataforma": {"type": "string"}},
                       ["archivo", "titulo", "cuando"]), False),
    "cola": (cola, "La cola de publicación, por fecha.", _obj({}), True),
    "actualizar_cola": (actualizar_cola, "Marca un elemento de la cola: programado, publicado, "
                        "fallido o cancelado.",
                        _obj({"id": {"type": "string"}, "estado": {"type": "string"},
                              "url": {"type": "string"}, "nota": {"type": "string"}},
                             ["id", "estado"]), False),
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

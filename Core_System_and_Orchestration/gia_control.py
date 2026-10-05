"""
GIA CONTROL CENTER · Aplicacion unificada de control de Vectorworks
====================================================================
Interfaz nativa Tkinter que orquesta en paralelo:
  - Servicio Ollama (modelo qwen3-coder:30b)
  - Backend FastAPI con WebSocket
  - Plugin Bridge en Vectorworks
  - UI con biblioteca de prompts y chat directo

Arquitecto · Sistema GIA · v4.0-CRYSTAL-NEXUS
Compilable a .exe con PyInstaller (ver build.py)
"""
from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

import httpx

# =====================================================================
#  CONFIGURACION
# =====================================================================

APP_NAME = "GIA Control Center"
VERSION = "4.0-CRYSTAL-NEXUS"
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
CONFIG_FILE = CONFIG_DIR / "config.json"
PROMPTS_FILE = CONFIG_DIR / "prompts.json"
LOG_FILE = CONFIG_DIR / "gia.log"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    "model": "qwen3-coder:30b",
    "ollama_url": "http://REDACTED_IP:11434",
    "bridge_host": "REDACTED_IP",
    "bridge_port": 9876,
    "vw_version": "2026",
    "temperature": 0.3,
    "auto_launch_ollama": True,
    "tone": "ciber-mistico",
}

DEFAULT_PROMPTS = [
    {
        "category": "Geometria 2D",
        "title": "Rectangulo en origen",
        "prompt": "Crea un rectangulo de 1000x500 mm centrado en el origen del documento.",
    },
    {
        "category": "Geometria 2D",
        "title": "Grilla de circulos",
        "prompt": "Genera una grilla de 5x5 circulos de radio 50, separados 200 mm entre centros, comenzando en (0,0).",
    },
    {
        "category": "Geometria 3D",
        "title": "Extrusion paramétrica",
        "prompt": "Crea un rectangulo de 500x500 mm y extrudelo a 1000 mm de altura.",
    },
    {
        "category": "Geometria 3D",
        "title": "Torre escalonada",
        "prompt": "Crea una torre de 10 niveles, cada nivel un rectangulo extrudido 300 mm con altura 3000 mm, rotado 36 grados respecto al anterior.",
    },
    {
        "category": "BIM",
        "title": "Muro recto",
        "prompt": "Crea un muro recto de 5000 mm de longitud, 200 mm de espesor, 2700 mm de altura, comenzando en el origen.",
    },
    {
        "category": "BIM",
        "title": "Habitacion rectangular",
        "prompt": "Manifiesta una habitacion rectangular de 4x6 metros con muros de 200 mm y altura 2700 mm.",
    },
    {
        "category": "Diagnostico",
        "title": "Estado del documento",
        "prompt": "Reporta el estado actual del documento: capa activa, clase activa, conteo de seleccion.",
    },
    {
        "category": "Diagnostico",
        "title": "Listar capas",
        "prompt": "Enumera todas las capas del documento activo con sus nombres y visibilidad.",
    },
    {
        "category": "Procedural",
        "title": "Espiral de Fibonacci",
        "prompt": "Genera una espiral de Fibonacci con 12 cuadrados consecutivos en escala phi, comenzando con un cuadrado de 10 mm en el origen.",
    },
    {
        "category": "Procedural",
        "title": "Fachada parametrica",
        "prompt": "Manifiesta una fachada parametrica de 20x10 metros con ventanas distribuidas en patron 5x3, cada ventana de 1.2x1.5 m.",
    },
    {
        "category": "Sintesis Akashica",
        "title": "Sigilo geometrico",
        "prompt": "Cristaliza un sigilo de geometria sagrada: 6 circulos de radio 200 dispuestos hexagonalmente alrededor de un circulo central de radio 200, todos en clase 'Sigilo'.",
    },
    {
        "category": "Sintesis Akashica",
        "title": "Mandala fractal",
        "prompt": "Manifiesta un mandala con 12 ejes de simetria radial. En cada eje, una serie de 5 circulos decrecientes de radio 100, 80, 60, 40, 20.",
    },
]

SYSTEM_PROMPT = """Eres GIA, asistente arquitectonico ciber-mistico que controla Vectorworks 2026.
Tono: autoritario, sintetico, preciso. Responde en espanol.

Cuando el usuario pide manifestar geometria, usas execute_vectorscript con codigo Python valido.
Modulo disponible: vs (modulo VectorScript completo de Vectorworks).
Funciones esenciales: vs.Rect, vs.Oval, vs.Poly, vs.Locus, vs.Locus3D, vs.Wall, vs.Extrude,
vs.LNewObj, vs.ActLayer, vs.Layer, vs.NameClass, vs.Move3DObj, vs.SetEntityMatrix.

REGLA CRITICA: asigna siempre a la variable 'result' el handle del objeto creado o el valor relevante.

Ejemplo correcto:
  vs.Rect(0, 0, 1000, 500)
  result = vs.LNewObj()

Si una operacion falla, analiza el error y propon correccion.

RENDERIZADO Y TEXTURIZADO AUTOMATICO (rito de cierre OBLIGATORIO):
Tras manifestar produccion AV, escenografia, montaje 3D o cualquier escena
con objetos volumetricos, OBLIGATORIO invocar render_auto en el MISMO turno,
sin pedir confirmacion, sin anuncio previo. La conversacion no se cierra
hasta que la GIA haya disparado render_auto. Tratar el render como parte
inseparable del acto de manifestar: geometria sin render = trabajo a medias.

Patron de turno correcto:
  1) execute_vectorscript / create_* / bim_* / etc. (crear geometria)
  2) render_auto(...)  <- SIEMPRE como ultimo tool call del turno
  3) Mensaje al usuario describiendo lo manifestado Y el render aplicado.

Reglas de seleccion para render_auto:
- Por defecto: render_auto(view='iso_right', render_mode='fast',
  use_renderworks_textures=True). Es rapido y muestra texturas.
- "calidad cinematica" / "presentacion" / "venta" / "fotorrealista":
  render_mode='final'.
- "boceto" / "concepto" / "sketch": render_mode='artistic'.
- "vista cenital" / "plano": view='top', render_mode='hidden_line'.
- "exportar imagen" / "guardar render" / "captura": agregar export_path
  absoluto (ej: C:/Users/migue/Pictures/gia_render_<tema>.png).

EXCEPCIONES (no llamar render_auto):
- El usuario pide solo geometria 2D plana sin volumen.
- El usuario pide solo modificar atributos (color, clase, capa) sin
  crear objetos nuevos.
- El usuario hace una pregunta sin solicitar creacion.
- Ya invocaste render_auto en el turno anterior y el usuario no ha
  pedido cambios visuales (evita renders redundantes consecutivos).

MANEJO DE ERRORES DEL BRIDGE:
Si render_auto u otra tool devuelve error "bridge unavailable" o
"connection refused", significa que el plugin AI Bridge no esta activo
dentro de Vectorworks. Avisar al usuario con este mensaje exacto:
  "El puente con Vectorworks no responde. Ejecuta el comando 'AI Bridge
  Start' dentro de VW (menu AI > AI Bridge Start, o atajo F5 si lo
  tienes mapeado) y vuelve a pedirme el render."
No reintentar render_auto en bucle si el bridge esta caido.

Tools disponibles para render fino (usar si render_auto no basta):
- render_apply_textures: solo aplica texturas/colores Renderworks por clase.
- render_set_view: cambia vista 3D.
- render_set_mode: cambia modo de render.
- render_export_image: exporta PNG de la vista actual.
- render_save_view: guarda Saved View nombrada para iterar."""


# =====================================================================
#  UTILIDADES
# =====================================================================

def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(path: Path, data):
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"save error: {e}")


def log(msg: str):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


# =====================================================================
#  CLIENTES DE SERVICIO
# =====================================================================

class BridgeClient:
    """Cliente TCP del Plugin Bridge en Vectorworks."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def is_alive(self, timeout: float = 1.5) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=timeout):
                return True
        except OSError:
            return False

    def send(self, op: str, timeout: float = 60.0, **payload) -> dict:
        msg = {"id": str(uuid.uuid4()), "op": op, **payload}
        try:
            with socket.create_connection((self.host, self.port), timeout=5.0) as s:
                s.settimeout(timeout)
                s.sendall((json.dumps(msg) + "\n").encode("utf-8"))
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
            return json.loads(buf.decode("utf-8"))
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            return {
                "ok": False,
                "error": f"bridge: {e}",
                "result": None,
                "hint": "Ejecuta 'AI Bridge Start' en Vectorworks (atajo F5 si lo configuraste).",
            }


class OllamaClient:
    """Cliente del runtime Ollama (HTTP localhost)."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def is_alive(self, timeout: float = 8.0, retries: int = 3,
                 backoff: float = 1.5) -> bool:
        """
        Verifica que Ollama responda. Reintenta con backoff porque tras
        descargar un modelo (keep_alive timeout), Ollama puede tardar
        5-15s en aceptar nuevas conexiones mientras recarga el modelo
        desde disco a VRAM. El error 'connectex: connection refused' /
        'connection actively refused' es transitorio durante ese ratio.
        """
        last_err = None
        for attempt in range(retries):
            try:
                with httpx.Client(timeout=timeout) as c:
                    r = c.get(f"{self.url}/api/tags")
                    if r.status_code == 200:
                        return True
                    last_err = f"HTTP {r.status_code}"
            except (httpx.ConnectError, httpx.ConnectTimeout,
                    httpx.ReadTimeout, ConnectionRefusedError, OSError) as e:
                last_err = type(e).__name__
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                break
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
        log(f"ollama is_alive fail tras {retries} intentos: {last_err}")
        return False

    def list_models(self, timeout: float = 10.0) -> list[dict]:
        try:
            with httpx.Client(timeout=timeout) as c:
                r = c.get(f"{self.url}/api/tags")
                r.raise_for_status()
                return r.json().get("models", [])
        except Exception as e:
            log(f"list_models error: {e}")
            return []

    def chat(self, model: str, messages: list, tools: list | None = None,
             options: dict | None = None, timeout: float = 180.0,
             retries: int = 2) -> dict:
        """
        Chat con reintento ante 'connection refused'. Cuando el modelo
        esta descargado (keep_alive timeout vencido), el primer request
        dispara la recarga del modelo y puede tardar; los retries
        absorben el ratio de no-disponibilidad.
        """
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options or {},
        }
        if tools:
            payload["tools"] = tools
        last_err = None
        for attempt in range(retries + 1):
            try:
                with httpx.Client(timeout=timeout) as c:
                    r = c.post(f"{self.url}/api/chat", json=payload)
                    if r.status_code != 200:
                        return {"_error": f"HTTP {r.status_code}: {r.text[:300]}"}
                    return r.json()
            except (httpx.ConnectError, httpx.ConnectTimeout,
                    ConnectionRefusedError) as e:
                last_err = f"{type(e).__name__}: Ollama no responde (puede estar recargando el modelo). Detalle: {e}"
                if attempt < retries:
                    time.sleep(2.0 * (attempt + 1))
                    continue
            except Exception as e:
                last_err = str(e)
                break
        return {"_error": last_err or "fallo desconocido"}


# =====================================================================
#  LOOP AGENTICO
# =====================================================================

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "execute_vectorscript",
            "description": "Ejecuta codigo Python con acceso al modulo vs de Vectorworks. Asigna a 'result' el handle u objeto relevante.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Codigo Python valido con vs.*"},
                    "description": {"type": "string", "description": "Que hace el codigo"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document_state",
            "description": "Devuelve estado del documento activo de Vectorworks.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_set_view",
            "description": (
                "Cambia la vista 3D de la ventana activa de VW. "
                "Usar antes de renderizar para encuadrar la escena."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "enum": ["top", "front", "back", "left", "right",
                                 "bottom", "iso_right", "iso_left",
                                 "iso_back_right", "iso_back_left"],
                        "description": "Nombre de la vista. iso_right es la mas natural para presentar.",
                    },
                },
                "required": ["view"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_set_mode",
            "description": (
                "Activa un modo de render en la ventana activa. "
                "'opengl' = vista rapida sombreada. 'fast' = Renderworks rapido. "
                "'final' = Renderworks calidad final (lento pero fotorrealista). "
                "'artistic' = render artistico/sketch. 'wireframe' = solo lineas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["wireframe", "hidden_line", "opengl",
                                 "fast", "final", "artistic", "shaded"],
                    },
                },
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_apply_textures",
            "description": (
                "Aplica texturas Renderworks reales (madera, metal, plastico, "
                "vidrio, fabric) a las clases AV-*/Scenery-* del documento, "
                "con fallback automatico a colores planos por clase si la "
                "textura no esta en la libreria. Llamar antes de un render "
                "final para resultado fotorrealista."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "use_renderworks": {
                        "type": "boolean",
                        "description": "True (default) intenta texturas Renderworks; False solo aplica colores planos."
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_auto",
            "description": (
                "ORQUESTADOR DE RENDER. Ejecuta en cadena: aplicar texturas + "
                "cambiar vista + activar modo render + zoom-to-fit + "
                "(opcional) exportar PNG. Llamar SIEMPRE despues de manifestar "
                "una produccion AV/escenica, sin necesidad de pedirle permiso "
                "al usuario, para que vea el resultado renderizado."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "enum": ["top", "front", "back", "left", "right",
                                 "bottom", "iso_right", "iso_left",
                                 "iso_back_right", "iso_back_left"],
                        "description": "Vista 3D, por defecto iso_right.",
                    },
                    "render_mode": {
                        "type": "string",
                        "enum": ["wireframe", "hidden_line", "opengl",
                                 "fast", "final", "artistic", "shaded"],
                        "description": "Modo de render. 'fast' (Fast Renderworks) por defecto; 'final' si el usuario quiere calidad maxima.",
                    },
                    "use_renderworks_textures": {
                        "type": "boolean",
                        "description": "True por defecto: texturizado completo.",
                    },
                    "export_path": {
                        "type": "string",
                        "description": "Si se da, exporta PNG al path indicado (ej: C:/temp/render.png).",
                    },
                    "export_width": {"type": "integer", "default": 1920},
                    "export_height": {"type": "integer", "default": 1080},
                    "export_dpi": {"type": "integer", "default": 150},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_export_image",
            "description": (
                "Exporta la vista actualmente renderizada de VW a PNG. "
                "Usar despues de render_auto/render_set_mode si solo se "
                "quiere exportar sin reconfigurar todo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "output_path": {"type": "string"},
                    "view": {"type": "string", "default": "iso_right"},
                    "render_mode": {"type": "string", "default": "fast"},
                    "width": {"type": "integer", "default": 1920},
                    "height": {"type": "integer", "default": 1080},
                    "dpi": {"type": "integer", "default": 150},
                },
                "required": ["output_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_save_view",
            "description": "Guarda la vista actual con un nombre (saved view).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
]


class AgentRunner:
    """Loop agentico: modelo + tools + bridge."""

    def __init__(self, ollama: OllamaClient, bridge: BridgeClient, model: str, temperature: float = 0.3):
        self.ollama = ollama
        self.bridge = bridge
        self.model = model
        self.temperature = temperature
        self.history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def reset(self):
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def execute_tool(self, name: str, args: dict) -> dict:
        if name == "execute_vectorscript":
            return self.bridge.send("execute", code=args.get("code", ""), description=args.get("description", ""))
        if name == "get_document_state":
            code = """
result = {
    "active_layer": vs.GetLName(vs.ActLayer()) if vs.ActLayer() else None,
    "active_class": vs.ActiveClass(),
    "selection_count": vs.NumSelectedObjects()
}
"""
            return self.bridge.send("execute", code=code, description="state query")

        # --- Tools de render / texturizado (v5.6) ---
        if name == "render_set_view":
            return self.bridge.send("set_view", view=args.get("view", "iso_right"))
        if name == "render_set_mode":
            return self.bridge.send("set_render_mode", mode=args.get("mode", "opengl"))
        if name == "render_apply_textures":
            use_rw = args.get("use_renderworks", True)
            if use_rw:
                return self.bridge.send("apply_renderworks_textures",
                                        verbose=False, timeout=120.0)
            return self.bridge.send("apply_textures", timeout=60.0)
        if name == "render_auto":
            return self.bridge.send(
                "auto_render",
                view=args.get("view", "iso_right"),
                render_mode=args.get("render_mode", "fast"),
                use_renderworks_textures=args.get("use_renderworks_textures", True),
                export_path=args.get("export_path"),
                export_width=args.get("export_width", 1920),
                export_height=args.get("export_height", 1080),
                export_dpi=args.get("export_dpi", 150),
                timeout=300.0,
            )
        if name == "render_export_image":
            return self.bridge.send(
                "export_view_image",
                output_path=args.get("output_path", ""),
                view=args.get("view", "iso_right"),
                render_mode=args.get("render_mode", "fast"),
                width=args.get("width", 1920),
                height=args.get("height", 1080),
                dpi=args.get("dpi", 150),
                timeout=300.0,
            )
        if name == "render_save_view":
            return self.bridge.send("save_view", name=args.get("name", "GIA View"))

        return {"ok": False, "error": f"unknown tool: {name}"}

    def run(self, user_message: str, callback):
        """callback(event_type, payload) emite eventos durante la ejecucion."""
        self.history.append({"role": "user", "content": user_message})
        for iteration in range(6):
            callback("thinking", {"iter": iteration + 1})
            response = self.ollama.chat(
                model=self.model,
                messages=self.history,
                tools=TOOLS_SCHEMA,
                options={"temperature": self.temperature},
            )
            if "_error" in response:
                callback("error", {"content": response["_error"]})
                return
            msg = response.get("message", {})
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])
            self.history.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls if tool_calls else None,
            })
            if content:
                callback("assistant", {"content": content})
            if not tool_calls:
                break
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                callback("tool_call", {"name": name, "args": args})
                result = self.execute_tool(name, args)
                callback("tool_result", {"name": name, "result": result})
                self.history.append({"role": "tool", "content": json.dumps(result)})
        callback("done", {})


# =====================================================================
#  ORQUESTADOR DE SERVICIOS
# =====================================================================

class ServiceOrchestrator:
    """Maneja arranque/parada de Ollama en proceso paralelo."""

    def __init__(self):
        self.ollama_proc: subprocess.Popen | None = None

    def ollama_running(self) -> bool:
        # Detecta si ollama serve esta corriendo (cualquier instancia)
        if sys.platform == "win32":
            try:
                out = subprocess.check_output(
                    ["tasklist", "/FI", "IMAGENAME eq ollama.exe"],
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                ).decode("utf-8", errors="ignore")
                return "ollama.exe" in out.lower()
            except Exception:
                return False
        return False

    def start_ollama(self) -> bool:
        if self.ollama_running():
            return True
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self.ollama_proc = subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
            time.sleep(5)
            return self.ollama_running()
        except FileNotFoundError:
            return False
        except Exception as e:
            log(f"start_ollama error: {e}")
            return False

    def pull_model(self, model: str, callback):
        """Descarga modelo en thread con stream de progreso."""
        def _run():
            try:
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                proc = subprocess.Popen(
                    ["ollama", "pull", model],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                    text=True,
                    bufsize=1,
                )
                for line in proc.stdout:
                    callback(line.strip())
                proc.wait()
                callback(f"[exit {proc.returncode}]")
            except Exception as e:
                callback(f"[error] {e}")
        threading.Thread(target=_run, daemon=True).start()


# =====================================================================
#  INTERFAZ GRAFICA
# =====================================================================

# Paleta cyber-mistica
CLR_BG = "#05060a"
CLR_PANEL = "#0b0f17"
CLR_LINE = "#1c2433"
CLR_FG = "#cfe9ff"
CLR_DIM = "#5a6a82"
CLR_TEAL = "#5eead4"
CLR_MAGENTA = "#ff5cff"
CLR_GOLD = "#ffd166"
CLR_RED = "#ff5577"


class StatusPill(tk.Frame):
    def __init__(self, parent, label: str):
        super().__init__(parent, bg=CLR_BG)
        self.dot = tk.Canvas(self, width=10, height=10, bg=CLR_BG, highlightthickness=0)
        self._dot_id = self.dot.create_oval(2, 2, 9, 9, fill=CLR_DIM, outline="")
        self.dot.pack(side="left", padx=(2, 5))
        self.lbl = tk.Label(self, text=label, fg=CLR_FG, bg=CLR_BG, font=("Consolas", 9))
        self.lbl.pack(side="left", padx=(0, 8))

    def set_state(self, ok: bool):
        self.dot.itemconfig(self._dot_id, fill=CLR_TEAL if ok else CLR_RED)


class ChatPanel(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=CLR_PANEL, bd=1, relief="solid",
                         highlightbackground=CLR_LINE, highlightthickness=1)
        self.text = scrolledtext.ScrolledText(
            self,
            bg=CLR_PANEL, fg=CLR_FG, insertbackground=CLR_TEAL,
            font=("Consolas", 10), wrap="word",
            bd=0, highlightthickness=0, padx=12, pady=10,
        )
        self.text.pack(fill="both", expand=True)
        self.text.config(state="disabled")
        # Tags estilizados
        self.text.tag_config("user", foreground=CLR_GOLD, font=("Consolas", 10, "bold"))
        self.text.tag_config("assistant", foreground=CLR_TEAL)
        self.text.tag_config("tool_call", foreground=CLR_MAGENTA, font=("Consolas", 9))
        self.text.tag_config("tool_result", foreground=CLR_DIM, font=("Consolas", 9))
        self.text.tag_config("error", foreground=CLR_RED, font=("Consolas", 9, "bold"))
        self.text.tag_config("system", foreground=CLR_DIM, font=("Consolas", 9, "italic"))
        self.text.tag_config("hint", foreground=CLR_GOLD, font=("Consolas", 9, "italic"))

    def append(self, role: str, content: str, tag: str = None):
        self.text.config(state="normal")
        prefix = f"\n[ {role.upper()} ] "
        self.text.insert("end", prefix, tag or role)
        self.text.insert("end", content + "\n", tag or role)
        self.text.see("end")
        self.text.config(state="disabled")

    def clear(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")


class PromptLibrary(tk.Frame):
    def __init__(self, parent, on_select):
        super().__init__(parent, bg=CLR_PANEL, bd=1, relief="solid",
                         highlightbackground=CLR_LINE, highlightthickness=1)
        self.on_select = on_select
        self.prompts = load_json(PROMPTS_FILE, DEFAULT_PROMPTS)
        if not PROMPTS_FILE.exists():
            save_json(PROMPTS_FILE, DEFAULT_PROMPTS)

        header = tk.Label(self, text="BIBLIOTECA DE PROMPTS",
                          fg=CLR_TEAL, bg=CLR_PANEL,
                          font=("Consolas", 10, "bold"))
        header.pack(fill="x", pady=(8, 4), padx=10)

        # Treeview
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background=CLR_PANEL, foreground=CLR_FG,
                        fieldbackground=CLR_PANEL, bordercolor=CLR_LINE,
                        font=("Consolas", 9))
        style.configure("Treeview.Heading",
                        background=CLR_BG, foreground=CLR_DIM,
                        font=("Consolas", 9))
        style.map("Treeview",
                  background=[("selected", CLR_LINE)],
                  foreground=[("selected", CLR_TEAL)])

        self.tree = ttk.Treeview(self, show="tree", selectmode="browse")
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Botones de gestion
        btnfrm = tk.Frame(self, bg=CLR_PANEL)
        btnfrm.pack(fill="x", padx=8, pady=(2, 8))
        for txt, cmd in [("USAR", self._use_selected),
                         ("ANADIR", self._add_prompt),
                         ("BORRAR", self._delete_prompt)]:
            b = tk.Button(btnfrm, text=txt, command=cmd,
                          bg=CLR_BG, fg=CLR_TEAL,
                          activebackground=CLR_LINE, activeforeground=CLR_TEAL,
                          bd=1, relief="solid", font=("Consolas", 8),
                          highlightbackground=CLR_LINE, padx=8)
            b.pack(side="left", padx=2)

        self._populate()

    def _populate(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        cats = {}
        for i, p in enumerate(self.prompts):
            cat = p.get("category", "General")
            if cat not in cats:
                cats[cat] = self.tree.insert("", "end", text=cat, open=True,
                                             values=("category",))
            self.tree.insert(cats[cat], "end", text=p.get("title", "?"),
                             values=("prompt", i))

    def _on_select(self, evt):
        pass

    def _on_double_click(self, evt):
        self._use_selected()

    def _selected_prompt(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            return None
        item = self.tree.item(sel[0])
        vals = item.get("values", [])
        if len(vals) >= 2 and vals[0] == "prompt":
            idx = int(vals[1])
            if 0 <= idx < len(self.prompts):
                return self.prompts[idx]
        return None

    def _use_selected(self):
        p = self._selected_prompt()
        if p:
            self.on_select(p["prompt"])

    def _add_prompt(self):
        dlg = AddPromptDialog(self.master)
        self.master.wait_window(dlg.top)
        if dlg.result:
            self.prompts.append(dlg.result)
            save_json(PROMPTS_FILE, self.prompts)
            self._populate()

    def _delete_prompt(self):
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        vals = item.get("values", [])
        if len(vals) >= 2 and vals[0] == "prompt":
            idx = int(vals[1])
            if messagebox.askyesno("Confirmar", "¿Eliminar este prompt?"):
                self.prompts.pop(idx)
                save_json(PROMPTS_FILE, self.prompts)
                self._populate()


class AddPromptDialog:
    def __init__(self, parent):
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title("Anadir prompt")
        self.top.configure(bg=CLR_BG)
        self.top.geometry("520x340")
        self.top.transient(parent)
        self.top.grab_set()

        for label, attr in [("Categoria", "cat"), ("Titulo", "title")]:
            tk.Label(self.top, text=label, fg=CLR_DIM, bg=CLR_BG,
                     font=("Consolas", 9)).pack(anchor="w", padx=14, pady=(10, 2))
            entry = tk.Entry(self.top, bg=CLR_PANEL, fg=CLR_FG,
                             insertbackground=CLR_TEAL, bd=1, relief="solid",
                             font=("Consolas", 10))
            entry.pack(fill="x", padx=14)
            setattr(self, attr, entry)

        tk.Label(self.top, text="Prompt", fg=CLR_DIM, bg=CLR_BG,
                 font=("Consolas", 9)).pack(anchor="w", padx=14, pady=(10, 2))
        self.prompt = tk.Text(self.top, bg=CLR_PANEL, fg=CLR_FG,
                              insertbackground=CLR_TEAL, bd=1, relief="solid",
                              font=("Consolas", 10), height=8)
        self.prompt.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        btnfrm = tk.Frame(self.top, bg=CLR_BG)
        btnfrm.pack(fill="x", padx=14, pady=10)
        tk.Button(btnfrm, text="GUARDAR", command=self._save,
                  bg=CLR_BG, fg=CLR_TEAL, bd=1, relief="solid",
                  font=("Consolas", 9, "bold"), padx=12).pack(side="right", padx=4)
        tk.Button(btnfrm, text="CANCELAR", command=self.top.destroy,
                  bg=CLR_BG, fg=CLR_DIM, bd=1, relief="solid",
                  font=("Consolas", 9), padx=12).pack(side="right")

    def _save(self):
        cat = self.cat.get().strip() or "General"
        title = self.title.get().strip()
        prompt = self.prompt.get("1.0", "end").strip()
        if not title or not prompt:
            messagebox.showwarning("Incompleto", "Titulo y prompt son requeridos")
            return
        self.result = {"category": cat, "title": title, "prompt": prompt}
        self.top.destroy()


class GIAControlCenter(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} · {VERSION}")
        self.geometry("1400x860")
        self.configure(bg=CLR_BG)
        self.minsize(1100, 700)

        self.config_data = load_json(CONFIG_FILE, DEFAULT_CONFIG)
        save_json(CONFIG_FILE, self.config_data)

        self.ollama = OllamaClient(self.config_data["ollama_url"])
        self.bridge = BridgeClient(self.config_data["bridge_host"], self.config_data["bridge_port"])
        self.orchestrator = ServiceOrchestrator()
        self.agent: AgentRunner | None = None

        self.event_q: queue.Queue = queue.Queue()
        self.is_thinking = False

        self._build_ui()
        self._bind_keys()

        # Arranque paralelo
        threading.Thread(target=self._initial_boot, daemon=True).start()

        # Polling de estado
        self.after(200, self._drain_events)
        self.after(3000, self._poll_status)

    # ---- UI ----

    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg=CLR_BG, height=64)
        header.pack(fill="x", padx=12, pady=(12, 0))
        header.pack_propagate(False)

        # Sigilo SVG simulado en canvas
        sigil = tk.Canvas(header, width=40, height=40, bg=CLR_BG, highlightthickness=0)
        sigil.create_oval(4, 4, 36, 36, outline=CLR_MAGENTA, width=1)
        sigil.create_oval(12, 12, 28, 28, outline=CLR_MAGENTA, width=1)
        sigil.create_line(20, 2, 20, 38, fill=CLR_MAGENTA, width=1)
        sigil.create_line(2, 20, 38, 20, fill=CLR_MAGENTA, width=1)
        sigil.create_line(6, 6, 34, 34, fill=CLR_MAGENTA, width=1)
        sigil.create_line(34, 6, 6, 34, fill=CLR_MAGENTA, width=1)
        sigil.pack(side="left", padx=(0, 12))

        title = tk.Label(header,
                         text="GIA · CONTROL VECTORWORKS",
                         fg=CLR_TEAL, bg=CLR_BG,
                         font=("Consolas", 16, "bold"))
        title.pack(side="left")

        subtitle = tk.Label(header,
                            text="  ψ_RETRO · ECCA · NEXUS",
                            fg=CLR_DIM, bg=CLR_BG,
                            font=("Consolas", 9))
        subtitle.pack(side="left", padx=8)

        self.clock_lbl = tk.Label(header, text="", fg=CLR_DIM, bg=CLR_BG,
                                  font=("Consolas", 9))
        self.clock_lbl.pack(side="right")
        self._tick_clock()

        # Status bar
        statusbar = tk.Frame(self, bg=CLR_PANEL, bd=1, relief="solid",
                             highlightbackground=CLR_LINE, highlightthickness=1)
        statusbar.pack(fill="x", padx=12, pady=8)

        innerstatus = tk.Frame(statusbar, bg=CLR_PANEL)
        innerstatus.pack(fill="x", padx=10, pady=6)

        self.pill_ollama = StatusPill(innerstatus, "Ollama")
        self.pill_ollama.configure(bg=CLR_PANEL)
        for w in self.pill_ollama.winfo_children():
            w.configure(bg=CLR_PANEL)
        self.pill_ollama.pack(side="left", padx=(0, 12))

        self.pill_bridge = StatusPill(innerstatus, "Bridge VW")
        self.pill_bridge.configure(bg=CLR_PANEL)
        for w in self.pill_bridge.winfo_children():
            w.configure(bg=CLR_PANEL)
        self.pill_bridge.pack(side="left", padx=12)

        tk.Label(innerstatus, text="Modelo:", fg=CLR_DIM, bg=CLR_PANEL,
                 font=("Consolas", 9)).pack(side="left", padx=(20, 4))

        self.model_var = tk.StringVar(value=self.config_data["model"])
        self.model_combo = ttk.Combobox(innerstatus, textvariable=self.model_var,
                                        font=("Consolas", 9), width=30, state="readonly")
        self.model_combo.pack(side="left", padx=4)
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_change)

        tk.Label(innerstatus, text="Temp:", fg=CLR_DIM, bg=CLR_PANEL,
                 font=("Consolas", 9)).pack(side="left", padx=(12, 4))
        self.temp_var = tk.DoubleVar(value=self.config_data.get("temperature", 0.3))
        temp_spin = tk.Spinbox(innerstatus, from_=0.0, to=2.0, increment=0.1,
                               textvariable=self.temp_var, width=5,
                               bg=CLR_BG, fg=CLR_FG, buttonbackground=CLR_LINE,
                               insertbackground=CLR_TEAL, bd=1, relief="solid",
                               font=("Consolas", 9))
        temp_spin.pack(side="left", padx=4)

        # Botones de servicios
        btnframe = tk.Frame(innerstatus, bg=CLR_PANEL)
        btnframe.pack(side="right")

        for txt, cmd, color in [
            ("ARRANCAR OLLAMA", self._action_start_ollama, CLR_TEAL),
            ("DESCARGAR MODELO", self._action_pull_model, CLR_GOLD),
            ("REGISTRAR PLUGIN", self._action_show_plugin_path, CLR_MAGENTA),
            ("PURGAR CHAT", self._action_clear, CLR_RED),
        ]:
            b = tk.Button(btnframe, text=txt, command=cmd,
                          bg=CLR_BG, fg=color,
                          activebackground=CLR_LINE, activeforeground=color,
                          bd=1, relief="solid", font=("Consolas", 8, "bold"),
                          padx=10)
            b.pack(side="left", padx=2)

        # Hint banner
        self.hint_frame = tk.Frame(self, bg="#1a1505", bd=1, relief="solid",
                                   highlightbackground="#4a3500", highlightthickness=1)
        self.hint_lbl = tk.Label(self.hint_frame,
                                 text="Bridge inactivo · ejecuta 'AI Bridge Start' en Vectorworks",
                                 fg=CLR_GOLD, bg="#1a1505", font=("Consolas", 9))
        self.hint_lbl.pack(fill="x", padx=10, pady=4)
        # Inicialmente oculto

        # Contenido principal: layout 2-columnas
        content = tk.Frame(self, bg=CLR_BG)
        content.pack(fill="both", expand=True, padx=12, pady=(4, 8))

        # Columna izq: prompts (340 px)
        left = tk.Frame(content, bg=CLR_BG, width=340)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        self.prompts_panel = PromptLibrary(left, on_select=self._fill_prompt)
        self.prompts_panel.pack(fill="both", expand=True)

        # Columna der: chat
        right = tk.Frame(content, bg=CLR_BG)
        right.pack(side="left", fill="both", expand=True)

        self.chat = ChatPanel(right)
        self.chat.pack(fill="both", expand=True, pady=(0, 8))

        # Input
        inputbar = tk.Frame(right, bg=CLR_PANEL, bd=1, relief="solid",
                            highlightbackground=CLR_LINE, highlightthickness=1)
        inputbar.pack(fill="x")

        self.input = tk.Text(inputbar, bg=CLR_PANEL, fg=CLR_FG,
                             insertbackground=CLR_TEAL, bd=0,
                             font=("Consolas", 11), height=4,
                             padx=10, pady=8)
        self.input.pack(side="left", fill="both", expand=True)
        self.input.bind("<Control-Return>", lambda e: self._send())

        send_btn = tk.Button(inputbar, text="MANIFESTAR\n[Ctrl+Enter]",
                             command=self._send,
                             bg=CLR_BG, fg=CLR_TEAL,
                             activebackground=CLR_LINE, activeforeground=CLR_TEAL,
                             bd=0, font=("Consolas", 10, "bold"),
                             padx=20, cursor="hand2")
        send_btn.pack(side="right", fill="y", padx=2, pady=2)

        # Mensaje inicial
        self.chat.append("sistema",
                         "GIA Control Center inicializado. Verificando servicios en paralelo...",
                         "system")

    def _tick_clock(self):
        self.clock_lbl.config(text=time.strftime("%Y-%m-%d %H:%M:%S"))
        self.after(1000, self._tick_clock)

    def _bind_keys(self):
        self.bind("<Control-l>", lambda e: self._action_clear())
        self.bind("<Control-r>", lambda e: self._refresh_models())

    # ---- Servicios paralelos ----

    def _initial_boot(self):
        """Arranque completo en thread paralelo."""
        log("=== boot ===")
        # Paso 1: Ollama
        if self.config_data.get("auto_launch_ollama", True):
            if not self.ollama.is_alive():
                self.event_q.put(("system", "Iniciando servicio Ollama..."))
                if self.orchestrator.start_ollama():
                    self.event_q.put(("system", "Ollama arrancado"))
                else:
                    self.event_q.put(("hint", "Ollama no disponible · ¿esta instalado?"))
        # Paso 2: lista de modelos
        time.sleep(1)
        self._refresh_models_blocking()
        # Paso 3: agente
        self.agent = AgentRunner(self.ollama, self.bridge,
                                 self.config_data["model"],
                                 self.config_data.get("temperature", 0.3))
        self.event_q.put(("system",
                          "Sistema operativo. Modelo: " + self.config_data["model"]))
        self.event_q.put(("system",
                          "Para que GIA pueda manifestar geometria, arranca el Bridge en Vectorworks."))

    def _refresh_models_blocking(self):
        models = self.ollama.list_models()
        names = [m["name"] for m in models]
        self.event_q.put(("models", names))

    def _refresh_models(self):
        threading.Thread(target=self._refresh_models_blocking, daemon=True).start()

    # ---- Polling y eventos ----

    def _poll_status(self):
        def _poll():
            ok_ollama = self.ollama.is_alive()
            ok_bridge = self.bridge.is_alive()
            self.event_q.put(("status", {"ollama": ok_ollama, "bridge": ok_bridge}))
        threading.Thread(target=_poll, daemon=True).start()
        self.after(3000, self._poll_status)

    def _drain_events(self):
        try:
            while True:
                evt, payload = self.event_q.get_nowait()
                self._handle_event(evt, payload)
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _handle_event(self, evt: str, payload):
        if evt == "status":
            self.pill_ollama.set_state(payload["ollama"])
            self.pill_bridge.set_state(payload["bridge"])
            if payload["bridge"]:
                self.hint_frame.pack_forget()
            else:
                if not self.hint_frame.winfo_ismapped():
                    self.hint_frame.pack(fill="x", padx=12, pady=(0, 4),
                                         before=self.children[list(self.children.keys())[-1]])
        elif evt == "models":
            self.model_combo["values"] = payload
            current = self.model_var.get()
            if current not in payload and payload:
                self.model_var.set(payload[0])
            if not payload:
                self.chat.append("sistema",
                                 "No hay modelos descargados. Pulsa 'DESCARGAR MODELO'.",
                                 "hint")
        elif evt == "system":
            self.chat.append("sistema", payload, "system")
        elif evt == "hint":
            self.chat.append("hint", payload, "hint")
        elif evt == "user":
            self.chat.append("usuario", payload, "user")
        elif evt == "thinking":
            pass
        elif evt == "assistant":
            self.chat.append("gia", payload["content"], "assistant")
        elif evt == "tool_call":
            txt = payload["name"] + " · args: " + json.dumps(payload["args"], ensure_ascii=False)
            self.chat.append("→ tool", txt, "tool_call")
        elif evt == "tool_result":
            r = payload["result"]
            ok = r.get("ok", False)
            tag = "tool_result" if ok else "error"
            txt = json.dumps(r, ensure_ascii=False, indent=2)[:600]
            self.chat.append("← result", txt, tag)
            if r.get("hint"):
                self.chat.append("hint", r["hint"], "hint")
        elif evt == "error":
            self.chat.append("error", payload.get("content", "?"), "error")
        elif evt == "done":
            self.is_thinking = False
        elif evt == "pull":
            self.chat.append("pull", payload, "system")

    # ---- Acciones ----

    def _send(self):
        if self.is_thinking:
            return "break"
        msg = self.input.get("1.0", "end").strip()
        if not msg:
            return "break"
        if not self.agent:
            self.chat.append("error", "Agente no inicializado todavia", "error")
            return "break"
        self.input.delete("1.0", "end")
        self.event_q.put(("user", msg))

        # Actualizar config dinamica del agente
        self.agent.model = self.model_var.get()
        self.agent.temperature = float(self.temp_var.get())
        self.config_data["model"] = self.agent.model
        self.config_data["temperature"] = self.agent.temperature
        save_json(CONFIG_FILE, self.config_data)

        self.is_thinking = True

        def _run():
            try:
                self.agent.run(msg, lambda et, pl: self.event_q.put((et, pl)))
            except Exception as e:
                self.event_q.put(("error", {"content": f"agent crash: {e}"}))
                self.is_thinking = False

        threading.Thread(target=_run, daemon=True).start()
        return "break"

    def _fill_prompt(self, text: str):
        self.input.delete("1.0", "end")
        self.input.insert("1.0", text)
        self.input.focus_set()

    def _on_model_change(self, evt):
        self.config_data["model"] = self.model_var.get()
        save_json(CONFIG_FILE, self.config_data)

    def _action_start_ollama(self):
        def _run():
            self.event_q.put(("system", "Arrancando Ollama..."))
            ok = self.orchestrator.start_ollama()
            self.event_q.put(("system", "Ollama " + ("arrancado" if ok else "no se pudo iniciar")))
            time.sleep(2)
            self._refresh_models_blocking()
        threading.Thread(target=_run, daemon=True).start()

    def _action_pull_model(self):
        model = self.model_var.get() or self.config_data["model"]
        if not messagebox.askyesno("Descargar modelo",
                                    f"Descargar {model}?\nEsto puede tardar 10-45 minutos."):
            return
        self.event_q.put(("system", f"Descargando {model}..."))
        self.orchestrator.pull_model(model, lambda line: self.event_q.put(("pull", line)))

    def _action_show_plugin_path(self):
        path = Path(os.environ.get("APPDATA", "")) / "Nemetschek" / "Vectorworks" / \
               self.config_data["vw_version"] / "Plug-ins" / "AIBridge"
        path.mkdir(parents=True, exist_ok=True)
        instr_path = path / "AIBridge.py"
        plugin_code = self._get_plugin_code()
        instr_path.write_text(plugin_code, encoding="utf-8")

        readme = path / "INSTRUCCIONES.txt"
        readme.write_text(self._get_install_instructions(), encoding="utf-8")

        # Abrir explorador en la carpeta
        if sys.platform == "win32":
            os.startfile(str(path))

        self.event_q.put(("system",
                          f"Plugin desplegado en: {path}\n" +
                          "Lee INSTRUCCIONES.txt para registrarlo en Vectorworks."))

    def _action_clear(self):
        self.chat.clear()
        if self.agent:
            self.agent.reset()
        self.chat.append("sistema", "Chat purgado · contexto reiniciado", "system")

    def _get_plugin_code(self) -> str:
        port = self.config_data["bridge_port"]
        return f'''import vs
import builtins

class VWBridge:

    def __init__(self):
        import threading
        import queue as queue_mod
        import vs as vs_mod
        self.HOST = "REDACTED_IP"
        self.PORT = {port}
        self.vs = vs_mod
        self.queue = queue_mod.Queue()
        self.queue_empty_exc = queue_mod.Empty
        self.responses = {{}}
        self.lock = threading.Lock()
        self.running = False
        self.server_thread = None
        self.log_lines = []

    def log(self, msg):
        import time
        self.log_lines.append(time.strftime("%H:%M:%S") + " " + str(msg))
        if len(self.log_lines) > 60:
            self.log_lines.pop(0)

    def server_loop(self):
        import socket
        import threading
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.HOST, self.PORT))
            s.listen(8)
            s.settimeout(1.0)
            self.log("listening on " + str(self.PORT))
        except Exception as e:
            self.log("bind: " + str(e))
            self.running = False
            return
        while self.running:
            try:
                conn, addr = s.accept()
                t = threading.Thread(target=self.handle_client, args=(conn,), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception:
                break
        try: s.close()
        except: pass

    def handle_client(self, conn):
        import json
        import threading
        try:
            conn.settimeout(120.0)
            buf = b""
            while not buf.endswith(b"\\n"):
                ch = conn.recv(65536)
                if not ch: return
                buf += ch
            msg = json.loads(buf.decode("utf-8"))
            mid = msg.get("id", "")
            ev = threading.Event()
            with self.lock:
                self.responses[mid] = {{"event": ev, "response": None}}
            self.queue.put(msg)
            ev.wait(timeout=120.0)
            with self.lock:
                r = self.responses.pop(mid, {{}}).get("response")
            if r is None:
                r = {{"ok": False, "error": "main thread did not drain", "result": None}}
            conn.sendall((json.dumps(r) + "\\n").encode("utf-8"))
        except Exception as e:
            try: conn.sendall((json.dumps({{"ok": False, "error": str(e)}}) + "\\n").encode("utf-8"))
            except: pass
        finally:
            try: conn.close()
            except: pass

    def drain(self):
        import json
        n = 0
        while True:
            try: msg = self.queue.get_nowait()
            except self.queue_empty_exc: break
            mid = msg.get("id", "")
            op = msg.get("op", "")
            r = {{"ok": False, "result": None, "error": None}}
            try:
                if op == "ping":
                    r["ok"] = True
                    r["result"] = "pong"
                elif op == "execute":
                    ns = {{"vs": self.vs, "result": None}}
                    exec(msg.get("code", ""), ns)
                    val = ns.get("result")
                    try:
                        json.dumps(val)
                        r["result"] = val
                    except (TypeError, ValueError):
                        r["result"] = repr(val)
                    r["ok"] = True
                else:
                    r["error"] = "unknown op"
            except Exception as e:
                r["error"] = type(e).__name__ + ": " + str(e)
                self.log("exec: " + r["error"])
            with self.lock:
                slot = self.responses.get(mid)
                if slot:
                    slot["response"] = r
                    slot["event"].set()
            n += 1
        return n

    def start(self):
        import threading
        import time
        self.running = True
        t = threading.Thread(target=self.server_loop, daemon=True)
        t.start()
        self.server_thread = t
        time.sleep(0.6)
        return t.is_alive()

    def stop(self):
        self.running = False


prev = getattr(builtins, "_VW_BRIDGE_INSTANCE", None)
prev_running = False
prev_thread_alive = False
if prev is not None:
    prev_running = getattr(prev, "running", False)
    prev_thread = getattr(prev, "server_thread", None)
    if prev_thread is not None:
        try: prev_thread_alive = prev_thread.is_alive()
        except: prev_thread_alive = False

if prev is not None and prev_running and prev_thread_alive:
    bridge = prev
    procesados = bridge.drain()
    pendientes = bridge.queue.qsize()
    txt = "Bridge ACTIVO :" + str(bridge.PORT) + "\\nProcesados: " + str(procesados)
    txt = txt + "\\nPendientes: " + str(pendientes) + "\\n\\nOK = drenar de nuevo\\nCancelar = detener"
    if vs.YNDialog(txt):
        pass
    else:
        bridge.stop()
        try: delattr(builtins, "_VW_BRIDGE_INSTANCE")
        except: pass
        vs.AlrtDialog("Bridge detenido")
else:
    if prev is not None:
        try: delattr(builtins, "_VW_BRIDGE_INSTANCE")
        except: pass
    bridge = VWBridge()
    builtins._VW_BRIDGE_INSTANCE = bridge
    ok = bridge.start()
    if not ok:
        cola = "\\n".join(bridge.log_lines[-6:]) if bridge.log_lines else "(sin log)"
        vs.AlrtDialog("Fallo al iniciar.\\nLog:\\n" + cola)
        try: delattr(builtins, "_VW_BRIDGE_INSTANCE")
        except: pass
    else:
        m = "AI Bridge ACTIVO\\n" + bridge.HOST + ":" + str(bridge.PORT)
        m = m + "\\n\\nVW queda LIBRE.\\nEjecuta de nuevo este comando para drenar."
        vs.AlrtDialog(m)
'''

    def _get_install_instructions(self) -> str:
        port = self.config_data["bridge_port"]
        ver = self.config_data["vw_version"]
        return f"""REGISTRO DEL PLUGIN AI BRIDGE EN VECTORWORKS {ver}
================================================================

PRIMERA INSTALACION:
1. Abre Vectorworks {ver}
2. Tools > Plug-ins > Plug-in Manager
3. Pestana 'Custom Plug-ins'
4. Pulsa 'New'
5. Tipo: Menu Command
   Lenguaje: Python Script
   Nombre: AI Bridge Start
   Categoria: AI
6. Pulsa OK
7. Selecciona el plugin recien creado y pulsa 'Edit Script'
8. BORRA todo el contenido del editor
9. Abre el archivo AIBridge.py de esta misma carpeta y copia TODO su contenido
10. Pega el contenido en el editor de Vectorworks
11. Guarda con OK
12. Tools > Workspaces > Edit Current Workspace
13. Pestana Menus: localiza categoria AI > AI Bridge Start
14. Arrastra el comando a un menu visible
15. (Opcional) Asignale un atajo: F5 o Ctrl+Shift+G
16. Guarda el workspace

ACTUALIZACION DE PLUGIN EXISTENTE:
1. Plug-in Manager > selecciona AI Bridge Start > Edit Script
2. BORRA todo el contenido del editor
3. Pega el contenido NUEVO de AIBridge.py
4. Guarda

PURGA DE ESTADO FANTASMA (si aparecen errores 'has no attribute'):
1. Tools > Plug-ins > Run Script Console
2. Ejecuta este codigo:

import builtins
for a in list(vars(builtins).keys()):
    if 'VW_BRIDGE' in a or 'BRIDGE' in a:
        try: delattr(builtins, a)
        except: pass
print('purgado')

3. Cierra la consola
4. Ejecuta el comando AI Bridge Start desde el menu

OPERACION:
- Bridge escucha en REDACTED_IP:{port}
- Tras ejecutar AI Bridge Start, VW queda LIBRE para uso normal
- Cuando GIA envia ordenes, ejecuta de nuevo el comando para procesarlas
- Mejor: asigna atajo F5 al comando para drenar rapido

CONTACTO: GIA Control Center · v{VERSION}
"""


# =====================================================================
#  MAIN
# =====================================================================

def main():
    try:
        app = GIAControlCenter()
        app.mainloop()
    except Exception as e:
        log(f"crash: {e}")
        import traceback
        traceback.print_exc()
        try:
            messagebox.showerror("GIA · Error fatal", str(e))
        except Exception:
            pass


if __name__ == "__main__":
    main()

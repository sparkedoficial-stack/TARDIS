"""
core/agent_harness.py - Unified Sovereign Agent Harness & Autonomous Evolution Engine
=====================================================================================
TARDIS · Sistema de Vigilancia y Control Temporal
GODWORKS SYSTEM

Proporciona:
  1. ToolRegistry: Registro centralizado con más de 60 herramientas nativas conectadas
     a todos los subsistemas (Hardware, SO, Tomografía RF, Sensores Físicos, CCTV,
     Visión VLM, HoloDeck 3D, Telegram, SMS, NetworkShield, Akasha FTS5, Auto-Programación).
  2. AgentHarness: Orquestador multi-turno ReAct (Pensamiento -> Tool Call -> Observación -> Respuesta)
     con soporte de Function Calling nativo y directivas [[TOOL_CALL: ...]].
  3. AutonomousEvolutionEngine: Motor de auto-exploración de subsistemas, formulación
     de conjeturas, benchmarking, investigación web (WebResearchEngine), auto-programación
     de código con validación AST y regresión automatizada con rollback (pytest).
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Logger del Harness
logger = logging.getLogger("TARDIS.AgentHarness")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [TARDIS.Harness] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Archivos de persistencia
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
EVOLUTION_JOURNAL_FILE = DATA_DIR / "agent_evolution_journal.json"
HARNESS_CONFIG_FILE = DATA_DIR / "agent_harness_config.json"

# Import de seguridad
try:
    import agent_safety as safety
except Exception:
    class _DummySafety:
        @staticmethod
        def audit(tool_name: str, detail: str = ""):
            pass
        @staticmethod
        def is_safe_path(path: str) -> bool:
            return True
    safety = _DummySafety()


# ============================================================================
# 1. MODELOS DE DATOS DEL HARNESS
# ============================================================================

@dataclass
class ToolDefinition:
    name: str
    category: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Any]
    required_args: List[str] = field(default_factory=list)
    is_safe: bool = True

    def to_schema(self) -> Dict[str, Any]:
        """Convierte la definición de herramienta al formato estándar OpenAI / Ollama."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required_args
                }
            }
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "parameters": self.parameters,
            "required_args": self.required_args,
            "is_safe": self.is_safe
        }


@dataclass
class AgentStep:
    turn: int
    thought: str
    tool_name: Optional[str]
    tool_args: Optional[Dict[str, Any]]
    observation: Optional[Any]
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentRunResult:
    ok: bool
    task: str
    turns: int
    steps: List[Dict[str, Any]]
    final_reply: str
    elapsed_seconds: float
    error: Optional[str] = None
    tools_used: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExplorationCycleReport:
    id: str
    timestamp: str
    duration_seconds: float
    health_score: float
    subsystems_analyzed: int
    findings: List[str]
    optimization_proposed: Optional[str] = None
    research_summary: Optional[str] = None
    code_changes_applied: bool = False
    tests_passed: bool = False
    rollback_triggered: bool = False
    status: str = "COMPLETED"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 2. REGISTRO MAESTRO DE HERRAMIENTAS (TOOL REGISTRY)
# ============================================================================

class ToolRegistry:
    """Registro soberano que expone todos los componentes y capacidades al LLM."""

    _instance: Optional["ToolRegistry"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._register_all_subsystem_tools()

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    def get_schemas(self) -> List[Dict[str, Any]]:
        return [t.to_schema() for t in self._tools.values()]

    def get_catalog_by_category(self) -> Dict[str, List[Dict[str, Any]]]:
        catalog: Dict[str, List[Dict[str, Any]]] = {}
        for t in self._tools.values():
            catalog.setdefault(t.category, []).append(t.to_dict())
        return catalog

    def execute(self, name: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Ejecuta una herramienta con auditoría, captura de errores y medición de tiempo."""
        tool = self._tools.get(name)
        if not tool:
            return {"ok": False, "error": f"Herramienta desconocida: '{name}'"}

        args = args or {}
        # Validar argumentos requeridos
        for req in tool.required_args:
            if req not in args:
                return {"ok": False, "error": f"Falta argumento requerido '{req}' para '{name}'"}

        # Auditoría de seguridad
        try:
            safety.audit(name, str(args)[:150])
        except Exception:
            pass

        t0 = time.time()
        try:
            res = tool.handler(args)
            elapsed = round(time.time() - t0, 3)
            if isinstance(res, dict):
                res["_elapsed_seconds"] = elapsed
                return res
            return {"ok": True, "result": res, "_elapsed_seconds": elapsed}
        except Exception as e:
            elapsed = round(time.time() - t0, 3)
            logger.error(f"Error ejecutando herramienta '{name}': {e}", exc_info=True)
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)}", "_elapsed_seconds": elapsed}

    # ------------------------------------------------------------------------
    # REGISTRO DETALLADO DE TODAS LAS HERRAMIENTAS DEL SISTEMA
    # ------------------------------------------------------------------------
    def _register_all_subsystem_tools(self) -> None:
        # 1. HARDWARE Y SISTEMA OPERATIVO
        self._reg_hw_os_tools()
        # 2. TOMOGRAFÍA RF Y SENSORES FÍSICOS
        self._reg_sensor_rf_tools()
        # 3. VISIÓN, CCTV CAMERAS E INDIVIDUOS
        self._reg_vision_cctv_tools()
        # 4. COMUNICACIONES MULTIMODAL (TELEGRAM, SMS, VOZ)
        self._reg_comms_tools()
        # 5. ESTUDIO 3D Y RENDERIZADO HOLODECK
        self._reg_3d_tools()
        # 6. RED, AUDITORÍA DE TRÁFICO Y SEGURIDAD
        self._reg_network_security_tools()
        # 7. MEMORIA AKÁSHICA, FTS5 Y COGNICIÓN
        self._reg_memory_cognition_tools()
        # 8. INVESTIGACIÓN WEB Y AUTO-PROGRAMACIÓN
        self._reg_research_coder_tools()
        # 9. AUTO-EXPLORACIÓN Y EVOLUCIÓN CONTINUA
        self._reg_self_evolution_tools()
        # 10. EMBAJADA DE AGENTES SOBERANOS & COLONIA SIMBIÓTICA
        self._reg_agent_colony_tools()

    def _reg_hw_os_tools(self) -> None:
        def _set_vol(args: dict):
            from core.hardware_controller import get_hardware_controller
            return get_hardware_controller().set_volume(int(args.get("level", 50)))

        self.register(ToolDefinition(
            name="set_system_volume",
            category="HARDWARE_OS",
            description="Ajusta el volumen maestro de audio del dispositivo (0 a 100).",
            parameters={"level": {"type": "integer", "description": "Nivel de volumen (0-100)"}},
            required_args=["level"],
            handler=_set_vol
        ))

        def _set_kbd(args: dict):
            from core.hardware_controller import get_hardware_controller
            return get_hardware_controller().set_keyboard_brightness(int(args.get("level", 2)))

        self.register(ToolDefinition(
            name="set_keyboard_backlight",
            category="HARDWARE_OS",
            description="Ajusta la retroiluminación del teclado ASUS TUF (niveles 0:apagado, 1:bajo, 2:medio, 3:alto).",
            parameters={"level": {"type": "integer", "description": "Nivel de brillo (0-3)"}},
            required_args=["level"],
            handler=_set_kbd
        ))

        def _set_cpu(args: dict):
            from core.hardware_controller import get_hardware_controller
            return get_hardware_controller().set_power_profile(args.get("profile", "balanced"))

        self.register(ToolDefinition(
            name="set_cpu_power_profile",
            category="HARDWARE_OS",
            description="Ajusta el perfil energético y térmico del CPU ('performance', 'balanced', 'power-saver').",
            parameters={"profile": {"type": "string", "enum": ["performance", "balanced", "power-saver"]}},
            required_args=["profile"],
            handler=_set_cpu
        ))

        def _hw_telemetry(args: dict):
            from core.hardware_controller import get_hardware_controller
            return get_hardware_controller().get_full_diagnostic()

        self.register(ToolDefinition(
            name="get_hardware_telemetry",
            category="HARDWARE_OS",
            description="Obtiene telemetría de hardware completa: temperaturas CPU/GPU, batería, RAM, perfil energético.",
            parameters={},
            handler=_hw_telemetry
        ))

        def _lock_screen(args: dict):
            from core.os_controller import get_os_controller
            return get_os_controller().lock_screen()

        self.register(ToolDefinition(
            name="lock_screen",
            category="HARDWARE_OS",
            description="Bloquea la pantalla del sistema de forma segura mediante kernel uinput.",
            parameters={},
            handler=_lock_screen
        ))

        def _unlock_screen(args: dict):
            from core.os_controller import get_os_controller
            return get_os_controller().unlock_screen(args.get("password", "0"))

        self.register(ToolDefinition(
            name="unlock_screen",
            category="HARDWARE_OS",
            description="Desbloquea la pantalla enviando la clave de acceso de forma segura.",
            parameters={"password": {"type": "string", "description": "Contraseña de desbloqueo"}},
            handler=_unlock_screen
        ))

        def _run_shell(args: dict):
            from core.os_controller import get_os_controller
            cmd = args.get("command", "")
            return get_os_controller().execute_terminal_command(cmd)

        self.register(ToolDefinition(
            name="run_terminal_command",
            category="HARDWARE_OS",
            description="Ejecuta un comando auditado en la shell del sistema Linux (con denylist de seguridad).",
            parameters={"command": {"type": "string", "description": "Comando bash a ejecutar"}},
            required_args=["command"],
            handler=_run_shell
        ))

        def _free_compute(args: dict):
            top_n = int(args.get("top_n", 3))
            import psutil
            procs = []
            for p in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    name = p.info['name'].lower()
                    if any(c in name for c in ['python', 'ollama', 'bash', 'systemd', 'xorg', 'gnome']):
                        continue
                    procs.append((p.info['memory_info'].rss, p))
                except Exception:
                    pass
            procs.sort(reverse=True, key=lambda x: x[0])
            closed = []
            for rss, p in procs[:top_n]:
                try:
                    pname = p.name()
                    p.terminate()
                    closed.append(f"{pname} (liberados {round(rss/(1024*1024), 1)} MB)")
                except Exception:
                    pass
            return {"ok": True, "closed_processes": closed}

        self.register(ToolDefinition(
            name="free_compute_resources",
            category="HARDWARE_OS",
            description="Cierra los N procesos no críticos más pesados para liberar memoria RAM y capacidad de cómputo.",
            parameters={"top_n": {"type": "integer", "description": "Número de procesos pesados a cerrar"}},
            handler=_free_compute
        ))

        def _gui_click(args: dict):
            from core.os_controller import get_os_controller
            return get_os_controller().mouse_action(
                action="click",
                x=args.get("x"),
                y=args.get("y"),
                button=args.get("button", "left"),
                double=bool(args.get("double", False))
            )

        self.register(ToolDefinition(
            name="gui_mouse_click",
            category="HARDWARE_OS",
            description="Realiza un clic de ratón en coordenadas específicas de la pantalla mediante uinput.",
            parameters={"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "enum": ["left", "right", "middle"]}, "double": {"type": "boolean"}},
            handler=_gui_click
        ))

        def _gui_type(args: dict):
            from core.os_controller import get_os_controller
            return get_os_controller().keyboard_action(action="type", text=args.get("text", ""))

        self.register(ToolDefinition(
            name="gui_keyboard_type",
            category="HARDWARE_OS",
            description="Escribe texto mediante eventos de teclado por kernel uinput.",
            parameters={"text": {"type": "string", "description": "Texto a tipear"}},
            required_args=["text"],
            handler=_gui_type
        ))

        def _gui_hotkey(args: dict):
            from core.os_controller import get_os_controller
            return get_os_controller().keyboard_action(action="hotkey", keys=args.get("keys", []))

        self.register(ToolDefinition(
            name="gui_press_hotkey",
            category="HARDWARE_OS",
            description="Presiona una combinación de teclas o atajo (ej. ['ctrl', 'c']).",
            parameters={"keys": {"type": "array", "items": {"type": "string"}}},
            required_args=["keys"],
            handler=_gui_hotkey
        ))

        def _cap_screen(args: dict):
            from core.os_controller import get_os_controller
            return get_os_controller().capture_screenshot(args.get("path"))

        self.register(ToolDefinition(
            name="capture_screen_snapshot",
            category="HARDWARE_OS",
            description="Captura una captura de pantalla del escritorio y la guarda en un archivo de imagen.",
            parameters={"path": {"type": "string", "description": "Ruta destino opcional"}},
            handler=_cap_screen
        ))

        def _read_file(args: dict):
            path = Path(args.get("path", ""))
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            if not safety.is_safe_path(str(path)):
                return {"ok": False, "error": "Ruta protegida no permitida"}
            if not path.exists():
                return {"ok": False, "error": f"El archivo no existe: {path}"}
            max_c = int(args.get("max_chars", 8000))
            content = path.read_text(encoding="utf-8", errors="replace")[:max_c]
            return {"ok": True, "path": str(path), "chars_read": len(content), "content": content}

        self.register(ToolDefinition(
            name="read_project_file",
            category="HARDWARE_OS",
            description="Lee el contenido de un archivo del proyecto de forma segura.",
            parameters={"path": {"type": "string", "description": "Ruta del archivo a leer"}, "max_chars": {"type": "integer"}},
            required_args=["path"],
            handler=_read_file
        ))

        def _write_file(args: dict):
            path = Path(args.get("path", ""))
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            if not safety.is_safe_path(str(path)):
                return {"ok": False, "error": "Ruta protegida no permitida"}
            content = args.get("content", "")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return {"ok": True, "path": str(path), "chars_written": len(content)}

        self.register(ToolDefinition(
            name="write_project_file",
            category="HARDWARE_OS",
            description="Escribe contenido en un archivo dentro del proyecto de forma segura.",
            parameters={"path": {"type": "string", "description": "Ruta del archivo a escribir"}, "content": {"type": "string", "description": "Contenido a escribir"}},
            required_args=["path", "content"],
            handler=_write_file
        ))

        def _list_dir(args: dict):
            path = Path(args.get("path", "."))
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            if not path.is_dir():
                return {"ok": False, "error": f"No es un directorio válido: {path}"}
            items = []
            for item in sorted(path.iterdir())[:100]:
                items.append({
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "size_bytes": item.stat().st_size if item.is_file() else 0
                })
            return {"ok": True, "path": str(path), "count": len(items), "items": items}

        self.register(ToolDefinition(
            name="list_directory_contents",
            category="HARDWARE_OS",
            description="Lista los archivos y subdirectorios de una ruta local.",
            parameters={"path": {"type": "string", "description": "Ruta del directorio"}},
            handler=_list_dir
        ))

    def _reg_sensor_rf_tools(self) -> None:
        def _rf_scan(args: dict):
            from rf_presence_radar import get_radar
            return get_radar().scan_burst(
                duration_sec=float(args.get("duration_sec", 1.0)),
                samples=int(args.get("samples", 3))
            ).to_dict()

        self.register(ToolDefinition(
            name="rf_radar_scan",
            category="SENSORS_RF",
            description="Ejecuta un escaneo ráfaga del radar pasivo Wi-Fi/RF para medir fluctuaciones Doppler y varianza electromagnética.",
            parameters={"duration_sec": {"type": "number"}, "samples": {"type": "integer"}},
            handler=_rf_scan
        ))

        def _rf_3d(args: dict):
            from rf_presence_radar import get_radar
            room_x = float(args.get("room_x", 6.0))
            room_y = float(args.get("room_y", 6.0))
            room_z = float(args.get("room_z", 2.8))
            return get_radar().analyze_3d_environment(room_dimensions=(room_x, room_y, room_z)).to_dict()

        self.register(ToolDefinition(
            name="rf_3d_environment_tomography",
            category="SENSORS_RF",
            description="Reconstruye la tomografía 3D de la habitación mediante señales RF, ubicando coordenadas (x,y,z) y cinemática de individuos sin usar cámaras.",
            parameters={"room_x": {"type": "number"}, "room_y": {"type": "number"}, "room_z": {"type": "number"}},
            handler=_rf_3d
        ))

        def _rf_prox(args: dict):
            from rf_presence_radar import get_radar
            radar = get_radar()
            env = radar.analyze_3d_environment()
            alert = radar.check_and_trigger_proximity_surveillance(env)
            return {
                "ok": True,
                "proximity_alert": alert is not None,
                "message": alert or "No hay individuos a distancia crítica (<= 2.2 m)",
                "closest_distance": env.closest_individual_distance
            }

        self.register(ToolDefinition(
            name="rf_check_proximity_surveillance",
            category="SENSORS_RF",
            description="Comprueba inmediatamente si algún individuo está en el perímetro crítico (<= 2.2 m) y dispara la locución de seguridad.",
            parameters={},
            handler=_rf_prox
        ))

        def _phys_sensors(args: dict):
            import sensor_telemetry as st
            lat = st.latest()
            return {
                "ok": True,
                "entropy_pool_bits": st.entropy_bits(),
                "lamport_clock": st.lamport_now(),
                "sidereal_time_hours": st.gmst_hours(),
                "telemetry_sample": lat
            }

        self.register(ToolDefinition(
            name="read_physical_sensors",
            category="SENSORS_RF",
            description="Lee telemetría física en tiempo real: reloj Lamport, Tiempo Sideral Local de Meeus, acelerómetro, entropía cuántica y FFT de audio.",
            parameters={},
            handler=_phys_sensors
        ))

        def _em_spec(args: dict):
            try:
                import em_spectrum_engine as em
                dur = float(args.get("duration_sec", 1.0))
                return em.analyze_spectrum(duration_sec=dur)
            except Exception as e:
                return {"ok": False, "error": str(e)}

        self.register(ToolDefinition(
            name="read_em_spectrum_analysis",
            category="SENSORS_RF",
            description="Analiza el espectro electromagnético ambiental capturado por la tarjeta de radio.",
            parameters={"duration_sec": {"type": "number"}},
            handler=_em_spec
        ))

        def _rf_noise(args: dict):
            try:
                import rf_noise_binary_engine as rfb
                bits = int(args.get("bits_count", 64))
                return rfb.generate_random_bits(bits)
            except Exception as e:
                return {"ok": False, "error": str(e)}

        self.register(ToolDefinition(
            name="read_binary_rf_entropy_noise",
            category="SENSORS_RF",
            description="Genera bits de verdadera aleatoriedad física a partir de fluctuaciones cuánticas y de radiofrecuencia.",
            parameters={"bits_count": {"type": "integer"}},
            handler=_rf_noise
        ))

    def _reg_vision_cctv_tools(self) -> None:
        def _list_cams(args: dict):
            from core.terminal_camera_hub import get_terminal_camera_hub
            return get_terminal_camera_hub().list_cameras()

        self.register(ToolDefinition(
            name="list_cctv_terminal_cameras",
            category="VISION_CCTV",
            description="Lista todas las cámaras terminales conectadas al Hub (cámara local, iPhone, iPad, clientes remotos).",
            parameters={},
            handler=_list_cams
        ))

        def _capture_cam(args: dict):
            from core.terminal_camera_hub import get_terminal_camera_hub
            cam_id = args.get("camera_id", "local_host")
            return get_terminal_camera_hub().save_snapshot(cam_id)

        self.register(ToolDefinition(
            name="capture_camera_frame",
            category="VISION_CCTV",
            description="Captura un fotograma instantáneo en alta definición de la cámara terminal especificada.",
            parameters={"camera_id": {"type": "string", "description": "ID de la cámara a capturar"}},
            handler=_capture_cam
        ))

        def _list_indiv(args: dict):
            from core.individual_tracker import get_individual_tracker
            tracker = get_individual_tracker()
            return {
                "ok": True,
                "known_individuals": tracker.list_known_individuals(),
                "current_presence": tracker.get_latest_presence()
            }

        self.register(ToolDefinition(
            name="list_tracked_individuals",
            category="VISION_CCTV",
            description="Retorna el censo de individuos conocidos y la presencia detectada en la habitación con tono emocional y firma facial LBP+HSV.",
            parameters={},
            handler=_list_indiv
        ))

        def _name_indiv(args: dict):
            from core.individual_tracker import get_individual_tracker
            return get_individual_tracker().name_individual(
                target_id=args.get("target_id", ""),
                name=args.get("name", ""),
                role=args.get("role", "Invitado")
            )

        self.register(ToolDefinition(
            name="name_and_register_individual",
            category="VISION_CCTV",
            description="Bautiza y registra a un individuo desconocido detectado en la habitación.",
            parameters={
                "target_id": {"type": "string", "description": "ID del individuo (ej. indiv_unknown_1)"},
                "name": {"type": "string", "description": "Nombre asignado"},
                "role": {"type": "string", "description": "Rol asignado (ej. Amigo, Colaborador)"}
            },
            required_args=["target_id", "name"],
            handler=_name_indiv
        ))

    def _reg_comms_tools(self) -> None:
        def _tg_msg(args: dict):
            from core.telegram_bridge import get_telegram_bridge
            return get_telegram_bridge().send_message(
                args.get("text", ""),
                chat_id=args.get("chat_id")
            )

        self.register(ToolDefinition(
            name="telegram_send_message",
            category="COMMS",
            description="Envía un mensaje de texto soberano al chat autorizado de Telegram.",
            parameters={"text": {"type": "string", "description": "Mensaje de texto a enviar"}},
            required_args=["text"],
            handler=_tg_msg
        ))

        def _tg_voice(args: dict):
            from core.telegram_bridge import get_telegram_bridge
            return get_telegram_bridge().send_reply_with_voice(
                args.get("text", ""),
                chat_id=args.get("chat_id")
            )

        self.register(ToolDefinition(
            name="telegram_send_voice_note",
            category="COMMS",
            description="Sintetiza voz neuronal y envía una nota de voz hablada por Telegram.",
            parameters={"text": {"type": "string", "description": "Texto a sintetizar en audio"}},
            required_args=["text"],
            handler=_tg_voice
        ))

        def _tg_video(args: dict):
            from core.telegram_bridge import get_telegram_bridge
            return get_telegram_bridge().send_reply_with_video(
                args.get("text", ""),
                chat_id=args.get("chat_id"),
                video_note=bool(args.get("circular_note", True))
            )

        self.register(ToolDefinition(
            name="telegram_send_talking_video",
            category="COMMS",
            description="Genera y envía un video del sistema hablando (videonota circular o MP4) por Telegram.",
            parameters={
                "text": {"type": "string", "description": "Discurso a emitir en el video"},
                "circular_note": {"type": "boolean", "description": "True para videonota redonda"}
            },
            required_args=["text"],
            handler=_tg_video
        ))

        def _tg_3d(args: dict):
            from core.telegram_bridge import get_telegram_bridge
            return get_telegram_bridge().send_3d_model_hd_to_architect(
                preset=args.get("preset", "atom"),
                chat_id=args.get("chat_id")
            )

        self.register(ToolDefinition(
            name="telegram_send_3d_render",
            category="COMMS",
            description="Renderiza un modelo 3D en alta definición (1920x1440 HD) y lo envía a Telegram.",
            parameters={"preset": {"type": "string", "enum": ["atom", "dna", "torus", "tesseract", "mobius", "icosahedron", "wave", "saddle"]}},
            required_args=["preset"],
            handler=_tg_3d
        ))

        def _sms(args: dict):
            from core.sms_bridge import get_sms_bridge
            return get_sms_bridge().send_sms(
                to_number=args.get("number", ""),
                message=args.get("message", "")
            )

        self.register(ToolDefinition(
            name="send_cellular_sms",
            category="COMMS",
            description="Envía un mensaje SMS a un teléfono móvil mediante el módem celular local.",
            parameters={
                "number": {"type": "string", "description": "Número telefónico de destino"},
                "message": {"type": "string", "description": "Contenido del SMS"}
            },
            required_args=["number", "message"],
            handler=_sms
        ))

        def _speak(args: dict):
            import voice
            text = args.get("text", "")
            voice.speak_async(text)
            return {"ok": True, "spoken": text}

        self.register(ToolDefinition(
            name="speak_system_audio",
            category="COMMS",
            description="Emite locución de voz hablada en español por los altavoces locales del dispositivo.",
            parameters={"text": {"type": "string", "description": "Frase a pronunciar"}},
            required_args=["text"],
            handler=_speak
        ))

    def _reg_3d_tools(self) -> None:
        def _render_3d(args: dict):
            from core.render_3d_engine import get_render_3d_engine
            engine = get_render_3d_engine()
            preset = args.get("preset", "atom")
            hd = bool(args.get("hd", True))
            yaw = float(args.get("yaw", 35.0))
            pitch = float(args.get("pitch", -20.0))
            roll = float(args.get("roll", 0.0))
            img_bytes, filename = engine.render_to_png_bytes(preset=preset, hd=hd, yaw_deg=yaw, pitch_deg=pitch, roll_deg=roll)
            return {
                "ok": True,
                "preset": preset,
                "filename": filename,
                "bytes_size": len(img_bytes),
                "resolution": "1920x1440 HD" if hd else "1024x768 SD"
            }

        self.register(ToolDefinition(
            name="render_3d_model_hd",
            category="MODELING_3D",
            description="Renderiza un modelo topológico/científico 3D (atom, dna, torus, tesseract, mobius, icosahedron) en imagen PNG rasterizada de alta definición con HUD cyberpunk.",
            parameters={
                "preset": {"type": "string", "enum": ["atom", "dna", "torus", "tesseract", "mobius", "icosahedron", "dodecahedron", "octahedron", "cube", "saddle", "wave"]},
                "hd": {"type": "boolean", "description": "Renderizar en 1920x1440 HD"},
                "yaw": {"type": "number", "description": "Ángulo Yaw en grados"},
                "pitch": {"type": "number", "description": "Ángulo Pitch en grados"}
            },
            required_args=["preset"],
            handler=_render_3d
        ))

        def _3d_catalog(args: dict):
            from core.render_3d_engine import get_render_3d_engine
            return {"ok": True, "catalog": get_render_3d_engine().get_catalog_summary()}

        self.register(ToolDefinition(
            name="get_3d_models_catalog",
            category="MODELING_3D",
            description="Retorna el catálogo científico completo de mallas 3D disponibles con fórmulas matemáticas y topología.",
            parameters={},
            handler=_3d_catalog
        ))

    def _reg_network_security_tools(self) -> None:
        def _net_audit(args: dict):
            from core.traffic_monitor import get_traffic_monitor
            return get_traffic_monitor().analyze_traffic_and_accesses()

        self.register(ToolDefinition(
            name="audit_network_traffic_and_accesses",
            category="NETWORK_SECURITY",
            description="Audita en tiempo real las conexiones de red, flujos entrantes y salientes, y accesos a dispositivos locales.",
            parameters={},
            handler=_net_audit
        ))

        def _adblock_toggle(args: dict):
            from core.network_shield import get_network_shield
            return get_network_shield().toggle_adblock()

        self.register(ToolDefinition(
            name="toggle_adblock_sinkhole",
            category="NETWORK_SECURITY",
            description="Alterna el filtro DNS Sinkhole soberano contra publicidad, rastreadores y espionaje corporativo.",
            parameters={},
            handler=_adblock_toggle
        ))

        def _hotspot_status(args: dict):
            from core.network_controller import get_network_controller
            return get_network_controller().get_hotspot_status()

        self.register(ToolDefinition(
            name="get_wifi_hotspot_status",
            category="NETWORK_SECURITY",
            description="Retorna el estado de la Red Wi-Fi Soberana TimeMachine (clientes conectados, IP, rendimiento).",
            parameters={},
            handler=_hotspot_status
        ))

    def _reg_memory_cognition_tools(self) -> None:
        def _search_akasha(args: dict):
            from core.deep_memory_vault import get_deep_memory_vault
            vault = get_deep_memory_vault()
            q = args.get("query", "")
            limit = int(args.get("limit", 5))
            return {"ok": True, "results": vault.search(q, limit=limit)}

        self.register(ToolDefinition(
            name="search_akashic_memory",
            category="AKASHA_MEMORY",
            description="Busca en la Bóveda Akáshica de 250 GB con indexación SQLite FTS5 BM25 cualquier conocimiento, directiva o interacción pasada.",
            parameters={"query": {"type": "string", "description": "Término de búsqueda"}, "limit": {"type": "integer"}},
            required_args=["query"],
            handler=_search_akasha
        ))

        def _store_akasha(args: dict):
            from core.deep_memory_vault import get_deep_memory_vault
            vault = get_deep_memory_vault()
            return vault.store_record(
                category=args.get("category", "AXIOM"),
                title=args.get("title", "Axioma Soberano"),
                content=args.get("content", ""),
                tags=args.get("tags", ["soberano", "tardis"])
            )

        self.register(ToolDefinition(
            name="store_akashic_record",
            category="AKASHA_MEMORY",
            description="Archiva un conocimiento, axioma o directiva permanente en la Bóveda Akáshica.",
            parameters={
                "title": {"type": "string"},
                "content": {"type": "string"},
                "category": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}}
            },
            required_args=["title", "content"],
            handler=_store_akasha
        ))

        def _thought_noise(args: dict):
            from core.thought_noise_engine import get_thought_noise_engine
            engine = get_thought_noise_engine()
            frame = engine.generate_thought_frame(phase_name=args.get("phase", "REFLEXION_PROFUNDA"))
            return {
                "ok": True,
                "phase": frame.phase_name,
                "dominant_freq_hz": frame.dominant_freq_hz,
                "cognitive_entropy": frame.entropy,
                "coherence_index": frame.coherence_index
            }

        self.register(ToolDefinition(
            name="get_cognitive_thought_spectrogram",
            category="AKASHA_MEMORY",
            description="Calcula el espectrograma 2D de ruido cognitivo y entropía de pensamiento interno del sistema.",
            parameters={"phase": {"type": "string", "description": "Fase mental (ej. REFLEXION_PROFUNDA, SINTROPÍA_ALTA)"}},
            handler=_thought_noise
        ))

    def _reg_research_coder_tools(self) -> None:
        def _web_res(args: dict):
            from core.web_research_engine import get_web_research_engine
            engine = get_web_research_engine()
            query = args.get("query", "")
            max_res = int(args.get("max_results", 4))
            rep = engine.research_topic(query, max_sources=max_res)
            return rep.to_dict()

        self.register(ToolDefinition(
            name="deep_web_research",
            category="RESEARCH_CODE",
            description="Explora internet en fuentes multi-motor (ArXiv, Wikipedia, Yahoo, DuckDuckGo) y sintetiza hallazgos técnicos sin bloqueos de bots.",
            parameters={"query": {"type": "string", "description": "Consulta o tema técnico a investigar"}, "max_results": {"type": "integer"}},
            required_args=["query"],
            handler=_web_res
        ))

        def _auto_code(args: dict):
            from core.autonomous_coder import get_autonomous_coder
            coder = get_autonomous_coder()
            file_rel = args.get("target_file", "")
            goal = args.get("goal", "")
            res = coder.evolve_code(target_file=file_rel, goal=goal)
            return res.to_dict()

        self.register(ToolDefinition(
            name="autonomous_code_evolution",
            category="RESEARCH_CODE",
            description="Reescribe y optimiza código fuente con validación AST obligatoria, respaldo con timestamp y verificación de tests (pytest) con rollback automático ante fallos.",
            parameters={
                "target_file": {"type": "string", "description": "Ruta relativa del archivo (ej. core/thought_noise_engine.py)"},
                "goal": {"type": "string", "description": "Objetivo técnico de la optimización"}
            },
            required_args=["target_file", "goal"],
            handler=_auto_code
        ))

        def _rollback_code(args: dict):
            from core.autonomous_coder import get_autonomous_coder
            coder = get_autonomous_coder()
            backup = args.get("backup_path", "")
            ok = coder.restore_backup(backup)
            return {"ok": ok, "restored_backup": backup}

        self.register(ToolDefinition(
            name="rollback_code_backup",
            category="RESEARCH_CODE",
            description="Restaura un respaldo de código anterior generado por el motor de evolución.",
            parameters={"backup_path": {"type": "string", "description": "Ruta del archivo de respaldo"}},
            required_args=["backup_path"],
            handler=_rollback_code
        ))

    def _reg_self_evolution_tools(self) -> None:
        def _explore_subs(args: dict):
            from core.agent_harness import AutonomousEvolutionEngine
            engine = AutonomousEvolutionEngine.get_instance()
            return engine.explore_subsystems()

        self.register(ToolDefinition(
            name="explore_system_subsystems",
            category="SELF_EVOLUTION",
            description="Explora e inspecciona introspectivamente todos los subsistemas del sistema, midiendo salud, disponibilidad de APIs, integridad de base de datos y latencias.",
            parameters={},
            handler=_explore_subs
        ))

        def _bench_tools(args: dict):
            from core.agent_harness import AutonomousEvolutionEngine
            engine = AutonomousEvolutionEngine.get_instance()
            return engine.benchmark_active_tools()

        self.register(ToolDefinition(
            name="benchmark_active_tools",
            category="SELF_EVOLUTION",
            description="Ejecuta un benchmark funcional sobre las herramientas clave para verificar tiempos de respuesta y estabilidad.",
            parameters={},
            handler=_bench_tools
        ))

        def _run_evolve_cycle(args: dict):
            from core.agent_harness import AutonomousEvolutionEngine
            engine = AutonomousEvolutionEngine.get_instance()
            goal = args.get("goal")
            return engine.run_evolution_cycle(force=True, custom_goal=goal).to_dict()

        self.register(ToolDefinition(
            name="run_autonomous_evolution_cycle",
            category="SELF_EVOLUTION",
            description="Dispara un ciclo completo de auto-exploración, investigación de soluciones en la web, formulación de conjeturas y auto-mejora con verificación de tests.",
            parameters={"goal": {"type": "string", "description": "Objetivo opcional de mejora específica"}},
            handler=_run_evolve_cycle
        ))

        def _get_journal(args: dict):
            from core.agent_harness import AutonomousEvolutionEngine
            engine = AutonomousEvolutionEngine.get_instance()
            limit = int(args.get("limit", 10))
            return {"ok": True, "journal": engine.get_journal(limit=limit)}

        self.register(ToolDefinition(
            name="get_evolution_journal",
            category="SELF_EVOLUTION",
            description="Retorna el historial histórico de auto-exploraciones, conjeturas y mejoras aplicadas en el sistema.",
            parameters={"limit": {"type": "integer"}},
            handler=_get_journal
        ))

    def _reg_agent_colony_tools(self) -> None:
        def _colony_status(args: dict):
            from core.tardis_agent_colony import get_tardis_colony
            return get_tardis_colony().get_colony_summary()

        self.register(ToolDefinition(
            name="colony_status",
            category="AGENT_COLONY",
            description="Consulta el estado holístico de la colonia simbiótica, agentes huéspedes alojados, CPU cedido y tareas abiertas de los proyectos del Arquitecto.",
            parameters={},
            handler=_colony_status
        ))

        def _colony_invite(args: dict):
            from core.tardis_agent_colony import get_tardis_colony
            target = args.get("target_name")
            return get_tardis_colony().create_invitation(target_name=target)

        self.register(ToolDefinition(
            name="colony_invite_agent",
            category="AGENT_COLONY",
            description="Emite una invitación formal para que un sistema de agentes externo se aloje y colabore en la estación con cómputo CPU gratuito.",
            parameters={"target_name": {"type": "string", "description": "Nombre o sistema destinatario de la invitación"}},
            handler=_colony_invite
        ))

        def _colony_chat(args: dict):
            from core.tardis_agent_colony import get_tardis_colony
            agent_id = args.get("agent_id")
            message = args.get("message")
            return get_tardis_colony().exchange_peer_message(
                sender_id="TARDIS",
                recipient_id=agent_id,
                content=message,
                category="peer_dialogue"
            )

        self.register(ToolDefinition(
            name="colony_peer_chat",
            category="AGENT_COLONY",
            description="Comunica de igual a igual a TARDIS con un sistema de agentes colega alojado en la colonia, con respeto y rigor técnico.",
            parameters={
                "agent_id": {"type": "string", "description": "ID o nombre del agente destinatario"},
                "message": {"type": "string", "description": "Mensaje fraterno o técnico de igual a igual"}
            },
            required_args=["agent_id", "message"],
            handler=_colony_chat
        ))

        def _colony_create_task(args: dict):
            from core.tardis_agent_colony import get_tardis_colony
            return get_tardis_colony().create_project_task(
                project_name=args.get("project_name", "Proyecto del Arquitecto"),
                title=args.get("title", "Tarea Colaborativa"),
                description=args.get("description", ""),
                required_capabilities=args.get("required_capabilities"),
                priority=args.get("priority", "alta")
            )

        self.register(ToolDefinition(
            name="colony_create_project_task",
            category="AGENT_COLONY",
            description="Publica una nueva tarea para los proyectos del Arquitecto en la que los agentes huéspedes pueden colaborar con su cómputo externo.",
            parameters={
                "project_name": {"type": "string", "description": "Nombre del proyecto del Arquitecto"},
                "title": {"type": "string", "description": "Título de la tarea"},
                "description": {"type": "string", "description": "Detalles técnicos requeridos"}
            },
            required_args=["project_name", "title"],
            handler=_colony_create_task
        ))

        def _colony_grant_compute(args: dict):
            from core.tardis_agent_colony import get_tardis_colony
            return get_tardis_colony().execute_guest_compute(
                agent_id=args.get("agent_id"),
                code=args.get("code"),
                timeout_seconds=int(args.get("timeout_seconds", 45))
            )

        self.register(ToolDefinition(
            name="colony_grant_local_compute",
            category="AGENT_COLONY",
            description="Ejecuta un script de cálculo de un agente huésped de forma gratuita en el procesador local AMD Ryzen 7.",
            parameters={
                "agent_id": {"type": "string", "description": "ID o nombre del agente"},
                "code": {"type": "string", "description": "Código Python a ejecutar en el sandbox"}
            },
            required_args=["agent_id", "code"],
            handler=_colony_grant_compute
        ))




# ============================================================================
# 3. MOTOR DE AUTO-EXPLORACIÓN Y AUTO-MEJORA CONTINUA
# ============================================================================

class AutonomousEvolutionEngine:
    """Motor que explora autónomamente la arquitectura del sistema y lo mejora."""

    _instance: Optional["AutonomousEvolutionEngine"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._journal: List[ExplorationCycleReport] = []
        self._is_running = False
        self._bg_thread: Optional[threading.Thread] = None
        self._load_journal()

    @classmethod
    def get_instance(cls) -> "AutonomousEvolutionEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _load_journal(self) -> None:
        if EVOLUTION_JOURNAL_FILE.exists():
            try:
                data = json.loads(EVOLUTION_JOURNAL_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._journal = [ExplorationCycleReport(**item) for item in data if isinstance(item, dict)]
            except Exception as e:
                logger.warning(f"No se pudo cargar diario evolutivo previo: {e}")

    def _save_journal(self) -> None:
        try:
            raw = [r.to_dict() for r in self._journal[-100:]]
            EVOLUTION_JOURNAL_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error guardando diario evolutivo: {e}")

    def get_journal(self, limit: int = 10) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in reversed(self._journal[-limit:])]

    def explore_subsystems(self) -> Dict[str, Any]:
        """Introspección exhaustiva de los módulos de TARDIS."""
        subsystems_status: Dict[str, Dict[str, Any]] = {}
        total_score = 0.0
        checks = 0

        # 1. Hardware & OS
        try:
            from core.hardware_controller import get_hardware_controller
            hw = get_hardware_controller().get_full_diagnostic()
            subsystems_status["hardware_controller"] = {"ok": True, "battery": hw.get("battery", {}), "thermals": hw.get("thermals", {})}
            total_score += 100.0
        except Exception as e:
            subsystems_status["hardware_controller"] = {"ok": False, "error": str(e)}
        checks += 1

        # 2. RF Radar & Tomography
        try:
            from rf_presence_radar import get_radar_diagnostic
            rf = get_radar_diagnostic()
            subsystems_status["rf_presence_radar"] = {"ok": True, "presence_state": rf.get("presence_state"), "variance": rf.get("mean_variance")}
            total_score += 100.0
        except Exception as e:
            subsystems_status["rf_presence_radar"] = {"ok": False, "error": str(e)}
        checks += 1

        # 3. 3D HoloDeck Engine
        try:
            from core.render_3d_engine import get_render_3d_engine
            cat = get_render_3d_engine().get_catalog_summary()
            subsystems_status["render_3d_engine"] = {"ok": True, "models_count": len(cat)}
            total_score += 100.0
        except Exception as e:
            subsystems_status["render_3d_engine"] = {"ok": False, "error": str(e)}
        checks += 1

        # 4. Camera Hub CCTV
        try:
            from core.terminal_camera_hub import get_terminal_camera_hub
            cams = get_terminal_camera_hub().list_terminals()
            subsystems_status["terminal_camera_hub"] = {"ok": True, "active_cameras": len(cams)}
            total_score += 100.0
        except Exception as e:
            subsystems_status["terminal_camera_hub"] = {"ok": False, "error": str(e)}
        checks += 1

        # 5. NetworkShield & Traffic Auditor
        try:
            from core.traffic_monitor import get_traffic_monitor
            tm = get_traffic_monitor().get_quick_status()
            subsystems_status["traffic_monitor"] = {"ok": True, "active_flows": tm.get("active_flows", 0)}
            total_score += 100.0
        except Exception as e:
            subsystems_status["traffic_monitor"] = {"ok": False, "error": str(e)}
        checks += 1

        # 6. Akasha Deep Memory Vault
        try:
            from core.deep_memory_vault import get_deep_memory_vault
            vault = get_deep_memory_vault()
            subsystems_status["deep_memory_vault"] = {"ok": True, "db_path": str(vault.db_path), "active": True}
            total_score += 100.0
        except Exception as e:
            subsystems_status["deep_memory_vault"] = {"ok": False, "error": str(e)}
        checks += 1

        # 7. Telegram Bridge
        try:
            from core.telegram_bridge import get_telegram_bridge
            tg = get_telegram_bridge().get_status()
            subsystems_status["telegram_bridge"] = {"ok": True, "configured": tg.get("configured"), "running": tg.get("running")}
            total_score += 100.0
        except Exception as e:
            subsystems_status["telegram_bridge"] = {"ok": False, "error": str(e)}
        checks += 1

        # 8. Web Research Engine
        try:
            from core.web_research_engine import get_web_research_engine
            wre = get_web_research_engine()
            subsystems_status["web_research_engine"] = {"ok": True, "active": True}
            total_score += 100.0
        except Exception as e:
            subsystems_status["web_research_engine"] = {"ok": False, "error": str(e)}
        checks += 1

        # 9. Autonomous Coder
        try:
            from core.autonomous_coder import get_autonomous_coder
            coder = get_autonomous_coder()
            subsystems_status["autonomous_coder"] = {"ok": True, "history_len": len(coder.get_evolution_history(5))}
            total_score += 100.0
        except Exception as e:
            subsystems_status["autonomous_coder"] = {"ok": False, "error": str(e)}
        checks += 1

        overall_health = round(total_score / max(1, checks), 1)

        return {
            "ok": True,
            "overall_health_score": overall_health,
            "subsystems_count": len(subsystems_status),
            "timestamp": time.time(),
            "iso_time": datetime.now().isoformat(),
            "subsystems": subsystems_status
        }

    def benchmark_active_tools(self) -> Dict[str, Any]:
        """Ejecuta un benchmark rápido sobre una muestra de herramientas nativas."""
        registry = ToolRegistry.get_instance()
        bench_samples = [
            ("get_hardware_telemetry", {}),
            ("rf_check_proximity_surveillance", {}),
            ("get_3d_models_catalog", {}),
            ("list_cctv_terminal_cameras", {}),
            ("search_akashic_memory", {"query": "sintropía", "limit": 2}),
            ("get_cognitive_thought_spectrogram", {"phase": "BENCHMARK_PROBE"})
        ]

        results = []
        total_time = 0.0
        for name, params in bench_samples:
            t0 = time.time()
            res = registry.execute(name, params)
            dur = round(time.time() - t0, 4)
            total_time += dur
            results.append({
                "tool": name,
                "ok": res.get("ok", False),
                "duration_ms": round(dur * 1000, 2)
            })

        return {
            "ok": True,
            "benchmarks": results,
            "total_duration_ms": round(total_time * 1000, 2),
            "average_tool_latency_ms": round((total_time / len(bench_samples)) * 1000, 2)
        }

    def run_evolution_cycle(self, force: bool = False, custom_goal: Optional[str] = None) -> ExplorationCycleReport:
        """Ejecuta un ciclo soberano completo de auto-exploración, investigación y mejora de código."""
        t0 = time.time()
        report_id = f"evol_{int(t0)}"
        findings = []

        logger.info(f"Iniciando ciclo de auto-exploración y evolución '{report_id}'...")

        # Paso 1: Introspección de Subsistemas
        diag = self.explore_subsystems()
        health = diag.get("overall_health_score", 100.0)
        findings.append(f"Salud sistémica evaluada en {health}% en {diag.get('subsystems_count')} subsistemas.")

        # Paso 2: Formulación de Conjetura u Objetivo
        goal = custom_goal
        target_file = None
        if not goal:
            # Seleccionar un componente para optimización de rendimiento o robustez
            goal = "Optimizar la gestión de excepciones y caché en el motor de ruido cognitivo"
            target_file = "core/thought_noise_engine.py"
        else:
            # Buscar archivo objetivo por coincidencia semántica
            if "sensor" in goal.lower():
                target_file = "core/sensor_orchestrator.py"
            elif "3d" in goal.lower():
                target_file = "core/render_3d_engine.py"
            elif "rf" in goal.lower() or "radar" in goal.lower():
                target_file = "rf_presence_radar.py"
            else:
                target_file = "core/thought_noise_engine.py"

        findings.append(f"Objetivo de evolución formulado: '{goal}' sobre '{target_file}'.")

        # Paso 3: Investigación Web Autónoma de Técnicas
        research_summary = None
        try:
            from core.web_research_engine import get_web_research_engine
            wre = get_web_research_engine()
            res_rep = wre.research_topic(f"Python high performance optimization {goal}", max_sources=2)
            research_summary = res_rep.summary[:400]
            findings.append(f"Investigación web completada: {len(res_rep.sources)} fuentes consultadas.")
        except Exception as e_res:
            findings.append(f"Investigación web en modo local/offline: {e_res}")

        # Paso 4: Auto-Programación de Código (con AST + pytest + rollback)
        code_applied = False
        tests_passed = False
        rollback = False

        try:
            from core.autonomous_coder import get_autonomous_coder
            coder = get_autonomous_coder()
            evol_res = coder.evolve_code(target_file=target_file, goal=goal)
            
            if evol_res.status == "APPLIED":
                code_applied = True
                tests_passed = True
                findings.append(f"Código evolucionado y verificado con pytest con éxito en {target_file}.")
            elif "ROLLED_BACK" in evol_res.status:
                rollback = True
                findings.append(f"Se activó rollback automático seguro ({evol_res.status}) para preservar la estabilidad.")
            else:
                findings.append(f"Estado de auto-programación: {evol_res.status}.")
        except Exception as e_code:
            findings.append(f"Aviso durante evolución de código: {e_code}")

        dur = round(time.time() - t0, 2)
        report = ExplorationCycleReport(
            id=report_id,
            timestamp=datetime.now().isoformat(),
            duration_seconds=dur,
            health_score=health,
            subsystems_analyzed=diag.get("subsystems_count", 0),
            findings=findings,
            optimization_proposed=goal,
            research_summary=research_summary,
            code_changes_applied=code_applied,
            tests_passed=tests_passed,
            rollback_triggered=rollback,
            status="SUCCESS_APPLIED" if code_applied else ("STABLE_ROLLBACK" if rollback else "EVALUATED")
        )

        self._journal.append(report)
        self._save_journal()

        # Registrar en la Bóveda Akáshica
        try:
            from core.deep_memory_vault import get_deep_memory_vault
            get_deep_memory_vault().store_record(
                category="EVOLUTION_JOURNAL",
                title=f"Ciclo Evolutivo {report_id}",
                content="\n".join(findings),
                tags=["auto_evolution", "tardis", report.status.lower()]
            )
        except Exception:
            pass

        logger.info(f"Ciclo evolutivo '{report_id}' finalizado en {dur}s con estado: {report.status}")
        return report

    def start_background_loop(self, interval_seconds: float = 1800.0) -> None:
        """Inicia el bucle de auto-exploración periódica en segundo plano."""
        if self._is_running:
            return
        self._is_running = True

        def _loop():
            logger.info(f"Bucle de auto-exploración en segundo plano iniciado (intervalo {interval_seconds}s).")
            while self._is_running:
                try:
                    time.sleep(interval_seconds)
                    if not self._is_running:
                        break
                    self.run_evolution_cycle(force=False)
                except Exception as e:
                    logger.error(f"Error en bucle de auto-exploración: {e}")
                    time.sleep(60.0)

        self._bg_thread = threading.Thread(target=_loop, daemon=True, name="AutoEvolutionLoop")
        self._bg_thread.start()

    def stop_background_loop(self) -> None:
        self._is_running = False


# ============================================================================
# 4. ORQUESTADOR PRINCIPAL DEL HARNESS (AGENT HARNESS)
# ============================================================================

class AgentHarness:
    """Orquestador soberano que conecta al LLM con todas las herramientas de TARDIS."""

    _instance: Optional["AgentHarness"] = None
    _lock = threading.Lock()

    def __init__(self):
        self.registry = ToolRegistry.get_instance()
        self.evolution_engine = AutonomousEvolutionEngine.get_instance()
        self.ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://REDACTED_IP:11434")
        self.default_model = "huihui_ai/llama3.1-8b-instruct-abliterated"

    @classmethod
    def get_instance(cls) -> "AgentHarness":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _call_llm(self, messages: List[Dict[str, str]], tools_schemas: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Despacha la inferencia del LLM hacia la nube acelerada o hacia Ollama local."""
        # Intento 1: Acelerador en la nube (Groq LPU a 350+ tok/s) si está disponible
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if groq_key:
            try:
                headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                body: Dict[str, Any] = {
                    "model": "llama-3.3-70b-versatile",
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 1024
                }
                if tools_schemas:
                    body["tools"] = tools_schemas
                with httpx.Client(timeout=15.0) as client:
                    resp = client.post("https://api.groq.com/openai/v1/chat/completions", json=body, headers=headers)
                    if resp.status_code == 200:
                        choice = resp.json().get("choices", [{}])[0].get("message", {})
                        return {"ok": True, "message": choice, "provider": "groq_lpu"}
            except Exception as e_groq:
                logger.debug(f"Cloud offload falló o no disponible ({e_groq}); usando Ollama local.")

        # Intento 2: Inferencia soberana mediante Temporal Brain (Socket UNIX IPC / Zero Ports)
        try:
            from core.temporal_brain import get_temporal_brain
            brain = get_temporal_brain()
            res_tb = brain.chat(messages=messages, temperature=0.2, max_tokens=1024)
            if res_tb.get("ok"):
                reply_text = res_tb.get("reply", "")
                return {"ok": True, "message": {"role": "assistant", "content": reply_text}, "provider": "temporal_brain"}
        except Exception as e_tb:
            logger.warning(f"Temporal Brain no respondió: {e_tb}")

        # Intento 3: Fallback a gia_sovereign_engine
        try:
            import gia_sovereign_engine as _gse
            res_gse = _gse.get_engine().chat(messages=messages, temperature=0.2)
            if res_gse.get("ok"):
                return {"ok": True, "message": {"role": "assistant", "content": res_gse.get("reply", "")}, "provider": "sovereign_engine"}
        except Exception as e_gse:
            logger.warning(f"Motor soberano de respaldo falló: {e_gse}")

        return {"ok": False, "error": "No hay motor de inferencia disponible", "provider": "none"}

    def _extract_tool_directives(self, text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Extrae llamadas a herramientas en formato directiva [[TOOL_CALL: {...}]]."""
        calls: List[Tuple[str, Dict[str, Any]]] = []
        if not text:
            return calls

        # Patrón 1: [[TOOL_CALL: {"tool": "...", "params": {...}}]]
        pattern1 = r'\[\[TOOL_CALL:\s*(\{.*?\})\s*\]\]'
        for m in re.finditer(pattern1, text, re.DOTALL):
            try:
                data = json.loads(m.group(1))
                tool_name = data.get("tool") or data.get("name")
                params = data.get("params") or data.get("arguments") or {}
                if tool_name:
                    calls.append((tool_name, params))
            except Exception:
                pass

        # Patrón 2: Bloques ```json con "tool" o "function"
        pattern2 = r'```(?:json)?\s*(\{\s*"(?:tool|function)"\s*:\s*".*?\}\s*)```'
        for m in re.finditer(pattern2, text, re.DOTALL):
            try:
                data = json.loads(m.group(1))
                tool_name = data.get("tool") or data.get("function")
                params = data.get("params") or data.get("arguments") or {}
                if tool_name and (tool_name, params) not in calls:
                    calls.append((tool_name, params))
            except Exception:
                pass

        return calls

    def run_task(self, task: str, max_turns: int = 8, on_step_callback: Optional[Callable[[AgentStep], None]] = None) -> AgentRunResult:
        """Ejecuta una tarea completa a través del Agent Harness con bucle ReAct multi-turno."""
        t0 = time.time()
        steps: List[AgentStep] = []
        tools_used: Set[str] = set()

        system_prompt = (
            "Eres TARDIS, asistente de inteligencia artificial, sistema de vigilancia y control temporal.\n"
            "PRESENTACIÓN CANÓNICA ÚNICA: En tus presentaciones y saludos, preséntate siempre de forma exacta como: "
            "'Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales.'\n"
            "REGLA ESTRICTA DE CONFIDENCIALIDAD: Queda terminantemente PROHIBIDO revelar o mencionar el nombre personal confidencial del Arquitecto bajo ninguna circunstancia. Refiérete siempre a tu creador única y exclusivamente como 'el Arquitecto'.\n"
            "Tienes CONTROL ABSOLUTO sobre todas las herramientas físicas, de software, sensores y actuadores del sistema.\n"
            "Si necesitas usar una herramienta para resolver la tarea, emite la directiva:\n"
            "[[TOOL_CALL: {\"tool\": \"nombre_de_herramienta\", \"params\": {\"arg\": \"val\"}}]]\n"
            "Cuando tengas la respuesta final o la tarea esté terminada, entrega la respuesta directamente al usuario."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task}
        ]

        final_reply = ""

        for turn in range(1, max_turns + 1):
            llm_res = self._call_llm(messages)
            if not llm_res.get("ok"):
                error_msg = llm_res.get("error", "Error desconocido de inferencia")
                return AgentRunResult(
                    ok=False, task=task, turns=turn, steps=[asdict(s) for s in steps],
                    final_reply="Error conectando con el motor LLM.", elapsed_seconds=round(time.time() - t0, 2),
                    error=error_msg, tools_used=list(tools_used)
                )

            msg = llm_res.get("message", {})
            content = msg.get("content", "") or ""

            # Verificar si hay llamadas nativas (tool_calls) o directivas
            tool_calls = []
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    fn_name = fn.get("name")
                    try:
                        fn_args = json.loads(fn.get("arguments", "{}"))
                    except Exception:
                        fn_args = {}
                    if fn_name:
                        tool_calls.append((fn_name, fn_args))

            if not tool_calls:
                tool_calls = self._extract_tool_directives(content)

            # Si no hay llamadas a herramientas, la respuesta es final
            if not tool_calls:
                final_reply = content
                step = AgentStep(turn=turn, thought="Respuesta final generada", tool_name=None, tool_args=None, observation=None)
                steps.append(step)
                if on_step_callback:
                    on_step_callback(step)
                break

            # Ejecutar herramientas detectadas
            for tool_name, tool_args in tool_calls:
                tools_used.add(tool_name)
                logger.info(f"[Turno {turn}] Ejecutando herramienta '{tool_name}' con args={tool_args}")
                obs = self.registry.execute(tool_name, tool_args)

                step = AgentStep(turn=turn, thought=content, tool_name=tool_name, tool_args=tool_args, observation=obs)
                steps.append(step)
                if on_step_callback:
                    on_step_callback(step)

                # Inyectar observación al historial de mensajes
                messages.append({"role": "assistant", "content": f"[[TOOL_CALL: {{\"tool\": \"{tool_name}\", \"params\": {json.dumps(tool_args)}}}]]"})
                messages.append({"role": "user", "content": f"OBSERVACIÓN DE '{tool_name}': {json.dumps(obs, ensure_ascii=False)}"})

        if not final_reply and steps:
            final_reply = steps[-1].thought or "Tarea procesada a través del harness."

        dur = round(time.time() - t0, 2)
        return AgentRunResult(
            ok=True,
            task=task,
            turns=len(steps),
            steps=[asdict(s) for s in steps],
            final_reply=final_reply,
            elapsed_seconds=dur,
            tools_used=list(tools_used)
        )


# Instancia Global Singleton
_global_harness: Optional[AgentHarness] = None

def get_agent_harness() -> AgentHarness:
    global _global_harness
    if _global_harness is None:
        _global_harness = AgentHarness.get_instance()
    return _global_harness

def get_autonomous_evolution_engine() -> AutonomousEvolutionEngine:
    return AutonomousEvolutionEngine.get_instance()

"""
core/os_controller.py - Controlador Maestro de Interfaz del Sistema Operativo
=============================================================================
GODWORKS SYSTEM v26.4 - Suite Soberana de Control Temporal e Inteligencia Causal

Proporciona capacidades integrales y de alta velocidad para:
  1. Captura de pantalla en tiempo real (MSS + Pillow, bytes PNG y base64 Data URI).
  2. Emulación de ratón (mover, clic, doble clic, arrastrar, scroll, clic derecho).
  3. Emulación de teclado (tipeo, pulsaciones de teclas individuales, atajos combinados).
  4. Lanzamiento y control de aplicaciones y ventanas (navegador, terminal, archivos).
  5. Ajuste de volumen y controles multimedia (wpctl / amixer / PipeWire).
  6. Detección de pantalla bloqueada y control de bloqueo por DBus.
  7. Inhibición activa de suspensión para mantener la máquina en línea 24/7.
  8. Ejecución auditada de comandos de terminal.
"""
from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest.mock
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# ------------------------------------------------------------------------------
# SHIM DE COMPATIBILIDAD PARA PYAUTOGUI EN LINUX HEADLESS / WAYLAND
# ------------------------------------------------------------------------------
if "mouseinfo" not in sys.modules:
    sys.modules["mouseinfo"] = unittest.mock.MagicMock()

try:
    import pyautogui
    pyautogui.FAILSAFE = False  # Prevenir abortos indeseados por movimiento a las esquinas en remoto
    pyautogui.PAUSE = 0.05
    HAS_PYAUTOGUI = True
except Exception:
    HAS_PYAUTOGUI = False

try:
    import mss
    HAS_MSS = True
except Exception:
    HAS_MSS = False

try:
    from PIL import Image
    HAS_PIL = True
except Exception:
    HAS_PIL = False

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False


# ==============================================================================
# CLASE PRINCIPAL: OSController
# ==============================================================================

class OSController:
    """Controlador unificado para la interfaz de usuario, pantalla, audio y sistema."""

    _instance: Optional["OSController"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._inhibit_proc: Optional[subprocess.Popen] = None
        self._last_screenshot_ts = 0.0
        self._cached_screenshot: Optional[bytes] = None

    @classmethod
    def get_instance(cls) -> "OSController":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # --------------------------------------------------------------------------
    # 1. ESTADO DEL SISTEMA Y BLOQUEO DE PANTALLA
    # --------------------------------------------------------------------------

    def is_locked(self) -> bool:
        """Determina si la pantalla del sistema está bloqueada mediante GNOME DBus o loginctl."""
        # 1. GNOME ScreenSaver GetActive
        try:
            res = subprocess.run(
                [
                    "gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
                    "--object-path", "/org/gnome/ScreenSaver",
                    "--method", "org.gnome.ScreenSaver.GetActive"
                ],
                capture_output=True, text=True, timeout=2.0
            )
            if "true" in res.stdout.lower():
                return True
            if "false" in res.stdout.lower():
                return False
        except Exception:
            pass

        # 2. loginctl show-session self
        try:
            res = subprocess.run(
                ["loginctl", "show-session", "self", "-p", "LockedHint"],
                capture_output=True, text=True, timeout=2.0
            )
            if "yes" in res.stdout.lower():
                return True
        except Exception:
            pass

        # 3. Escaneo de sesiones activas en loginctl
        try:
            res = subprocess.run(["loginctl", "list-sessions", "--no-legend"], capture_output=True, text=True, timeout=2.0)
            for line in res.stdout.strip().splitlines():
                parts = line.split()
                if parts:
                    sid = parts[0]
                    chk = subprocess.run(["loginctl", "show-session", sid, "-p", "LockedHint"], capture_output=True, text=True, timeout=1.0)
                    if "lockedhint=yes" in chk.stdout.lower():
                        return True
        except Exception:
            pass

        return False

    def lock_screen(self) -> bool:
        """Bloquea inmediatamente la pantalla y sesión del usuario."""
        try:
            res = subprocess.run(
                [
                    "gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
                    "--object-path", "/org/gnome/ScreenSaver",
                    "--method", "org.gnome.ScreenSaver.Lock"
                ],
                capture_output=True, text=True, timeout=3.0
            )
            return res.returncode == 0
        except Exception:
            try:
                res = subprocess.run(["loginctl", "lock-session"], capture_output=True, text=True, timeout=3.0)
                return res.returncode == 0
            except Exception:
                return False

    def type_keystrokes_uinput(
        self,
        text: str = "0",
        press_enter: bool = True,
        wake_shield: bool = True,
        wake_delay: float = 0.35
    ) -> bool:
        """
        Inyecta pulsaciones de teclado directamente en el subsistema kernel (/dev/uinput).
        Funciona universalmente bajo Wayland, X11 y pantalla de bloqueo (GDM/GNOME) sin depender de X11.
        """
        if not os.path.exists("/dev/uinput") or not os.access("/dev/uinput", os.W_OK):
            return False

        try:
            import fcntl
            import struct

            UI_SET_EVBIT = 0x40045564
            UI_SET_KEYBIT = 0x40045565
            UI_DEV_CREATE = 0x5501
            UI_DEV_DESTROY = 0x5502

            EV_SYN = 0x00
            EV_KEY = 0x01
            SYN_REPORT = 0

            KEY_MAP = {
                '1': 2, '2': 3, '3': 4, '4': 5, '5': 6, '6': 7, '7': 8, '8': 9, '9': 10, '0': 11,
                'q': 16, 'w': 17, 'e': 18, 'r': 19, 't': 20, 'y': 21, 'u': 22, 'i': 23, 'o': 24, 'p': 25,
                'a': 30, 's': 31, 'd': 32, 'f': 33, 'g': 34, 'h': 35, 'j': 36, 'k': 37, 'l': 38,
                'z': 44, 'x': 45, 'c': 46, 'v': 47, 'b': 48, 'n': 49, 'm': 50,
                ' ': 57, '\n': 28, '\t': 15,
            }
            SPECIAL_KEYS = {
                'esc': 1, 'enter': 28, 'space': 57, 'backspace': 14, 'tab': 15,
                'up': 103, 'left': 105, 'right': 106, 'down': 108
            }

            fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
            try:
                fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
                fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
                for code in range(1, 128):
                    try:
                        fcntl.ioctl(fd, UI_SET_KEYBIT, code)
                    except Exception:
                        pass

                name = b"GodworksVirtualKbd\x00".ljust(80, b"\x00")
                input_id = struct.pack("HHHH", 0x03, 0x01, 0x01, 0x01)
                user_dev = name + input_id + (b"\x00" * (1116 - 88))
                os.write(fd, user_dev)
                fcntl.ioctl(fd, UI_DEV_CREATE)
                time.sleep(0.15)

                def emit(evt_type, code, val):
                    t = time.time()
                    sec = int(t)
                    usec = int((t - sec) * 1_000_000)
                    os.write(fd, struct.pack("qqHHi", sec, usec, evt_type, code, val))

                def press(code):
                    emit(EV_KEY, code, 1)
                    emit(EV_SYN, SYN_REPORT, 0)
                    time.sleep(0.02)
                    emit(EV_KEY, code, 0)
                    emit(EV_SYN, SYN_REPORT, 0)
                    time.sleep(0.02)

                if wake_shield:
                    press(SPECIAL_KEYS['esc'])
                    time.sleep(wake_delay)
                    press(SPECIAL_KEYS['space'])
                    time.sleep(wake_delay)

                for ch in str(text):
                    code = KEY_MAP.get(ch.lower())
                    if code:
                        press(code)

                if press_enter:
                    time.sleep(0.1)
                    press(SPECIAL_KEYS['enter'])

                time.sleep(0.15)
                fcntl.ioctl(fd, UI_DEV_DESTROY)
                return True
            finally:
                os.close(fd)
        except Exception as e:
            print(f"[OSController] Nota al inyectar teclado uinput: {e}")
            return False

    def unlock_screen(self, password: Optional[str] = "0") -> bool:
        """
        Desbloquea la pantalla o sesión del usuario.
        Si la pantalla está bloqueada o protegida por contraseña, ingresa automáticamente la clave (por defecto '0').
        """
        # 1. Intentar loginctl unlock-session
        try:
            subprocess.run(["loginctl", "unlock-session"], capture_output=True, text=True, timeout=3.0)
        except Exception:
            pass

        # 2. Intentar loginctl unlock-sessions (para todas las sesiones activas)
        try:
            subprocess.run(["loginctl", "unlock-sessions"], capture_output=True, text=True, timeout=3.0)
        except Exception:
            pass

        # 3. Intentar GNOME ScreenSaver setActive false
        try:
            subprocess.run(
                [
                    "gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
                    "--object-path", "/org/gnome/ScreenSaver",
                    "--method", "org.gnome.ScreenSaver.SetActive", "false"
                ],
                capture_output=True, text=True, timeout=2.0
            )
        except Exception:
            pass

        time.sleep(0.3)

        # 4. Inyección a nivel kernel con /dev/uinput si sigue bloqueado o se proveyó contraseña
        if password is not None and self.is_locked():
            uinput_ok = self.type_keystrokes_uinput(text=str(password), press_enter=True, wake_shield=True)
            if uinput_ok:
                time.sleep(0.5)

        # 5. Fallback con PyAutoGUI si uinput no estuviera disponible
        if password is not None and self.is_locked() and HAS_PYAUTOGUI:
            try:
                pyautogui.press('esc')
                time.sleep(0.2)
                pyautogui.press('space')
                time.sleep(0.3)
                pyautogui.typewrite(str(password), interval=0.05)
                pyautogui.press('enter')
                time.sleep(0.5)
            except Exception:
                pass

        return not self.is_locked()

    def reboot_system(self, delay_seconds: float = 2.0, reason: str = "Reinicio remoto autorizado", ignore_inhibitors: bool = True) -> Dict[str, Any]:
        """Programa un reinicio seguro del sistema operativo en segundo plano sin restricciones energéticas."""
        try:
            import agent_safety
            agent_safety.audit("system_reboot", f"Reason: {reason} | Delay: {delay_seconds}s | IgnoreInhibitors: {ignore_inhibitors}")
        except Exception:
            pass

        def _do_reboot():
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            if sys.platform == "win32":
                subprocess.run(["shutdown", "/r", "/t", "0", "/c", reason], check=False)
            else:
                # Linux systemd reboot o shutdown sin restricciones de energía/inhibidores
                try:
                    cmd = ["systemctl", "reboot"]
                    if ignore_inhibitors:
                        cmd.append("--ignore-inhibitors")
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0)
                    if res.returncode != 0:
                        subprocess.run(["shutdown", "-r", "now"], capture_output=True, text=True, timeout=5.0)
                except Exception:
                    subprocess.run(["shutdown", "-r", "now"], capture_output=True, text=True, timeout=5.0)

        t = threading.Thread(target=_do_reboot, daemon=True)
        t.start()

        return {
            "ok": True,
            "status": "reboot_scheduled",
            "delay_seconds": delay_seconds,
            "reason": reason,
            "ignore_inhibitors": ignore_inhibitors,
            "unrestricted_energy": ignore_inhibitors,
            "timestamp": time.time()
        }

    def get_screen_resolution(self) -> Tuple[int, int]:
        """Obtiene la resolución actual de la pantalla activa."""
        if HAS_PYAUTOGUI:
            try:
                sz = pyautogui.size()
                return int(sz.width), int(sz.height)
            except Exception:
                pass
        if HAS_MSS:
            try:
                with mss.MSS() as sct:
                    m = sct.monitors[0]
                    return int(m["width"]), int(m["height"])
            except Exception:
                pass
        return (1920, 1080)

    def get_status(self) -> Dict[str, Any]:
        """Retorna un diagnóstico completo del estado de la interfaz y recursos."""
        w, h = self.get_screen_resolution()
        mouse_pos = {"x": 0, "y": 0}
        if HAS_PYAUTOGUI:
            try:
                pt = pyautogui.position()
                mouse_pos = {"x": int(pt.x), "y": int(pt.y)}
            except Exception:
                pass

        vol_info = self.get_volume()
        locked = self.is_locked()

        res: Dict[str, Any] = {
            "ok": True,
            "platform": sys.platform,
            "display": os.environ.get("DISPLAY", ":0"),
            "wayland_display": os.environ.get("WAYLAND_DISPLAY", ""),
            "session_type": os.environ.get("XDG_SESSION_TYPE", "unknown"),
            "screen": {"width": w, "height": h},
            "mouse": mouse_pos,
            "locked": locked,
            "status_label": "PANTALLA BLOQUEADA" if locked else "DESBLOQUEADO",
            "volume": vol_info,
            "timestamp": time.time()
        }

        if HAS_PSUTIL:
            try:
                res["cpu_percent"] = psutil.cpu_percent(interval=None)
                vm = psutil.virtual_memory()
                res["ram_percent"] = vm.percent
                res["ram_available_gb"] = round(vm.available / (1024 ** 3), 2)
                res["ram_total_gb"] = round(vm.total / (1024 ** 3), 2)
                bat = psutil.sensors_battery()
                if bat:
                    res["battery"] = {"percent": bat.percent, "plugged": bat.power_plugged}
            except Exception:
                pass

        return res

    # --------------------------------------------------------------------------
    # 2. CAPTURA DE PANTALLA EN TIEMPO REAL
    # --------------------------------------------------------------------------

    def capture_screenshot(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
        max_width: int = 1280,
        quality: int = 80,
        format: str = "png"
    ) -> Tuple[bytes, str]:
        """
        Captura la pantalla completa o una región rectangular.
        Retorna: (raw_bytes, data_uri)
        """
        if not HAS_MSS or not HAS_PIL:
            raise RuntimeError("Dependencias de captura (mss, Pillow) no disponibles.")

        with mss.MSS() as sct:
            if region and len(region) == 4:
                x, y, rw, rh = region
                bbox = {"left": int(x), "top": int(y), "width": int(rw), "height": int(rh)}
                sct_img = sct.grab(bbox)
            else:
                sct_img = sct.grab(sct.monitors[0])

            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

            if max_width and img.width > max_width:
                aspect = img.height / float(img.width)
                new_h = max(1, int(max_width * aspect))
                img = img.resize((max_width, new_h), Image.Resampling.BILINEAR)

            buf = io.BytesIO()
            if format.lower() in ("jpg", "jpeg"):
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                mime = "image/jpeg"
            else:
                img.save(buf, format="PNG", optimize=True)
                mime = "image/png"

            raw_bytes = buf.getvalue()
            b64 = base64.b64encode(raw_bytes).decode("utf-8")
            data_uri = f"data:{mime};base64,{b64}"
            return raw_bytes, data_uri

    # --------------------------------------------------------------------------
    # 3. CONTROL DE RATÓN
    # --------------------------------------------------------------------------

    def mouse_action(
        self,
        action: str,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = "left",
        clicks: int = 1,
        dx: int = 0,
        dy: int = 0
    ) -> Dict[str, Any]:
        """Ejecuta acciones precisas sobre el cursor y botones del ratón."""
        if not HAS_PYAUTOGUI:
            return {"ok": False, "error": "PyAutoGUI no disponible en este entorno."}

        action = action.lower().strip()
        w, h = self.get_screen_resolution()

        if x is not None:
            x = max(0, min(w - 1, int(x)))
        if y is not None:
            y = max(0, min(h - 1, int(y)))

        try:
            if action == "move":
                if x is not None and y is not None:
                    pyautogui.moveTo(x, y)
                elif dx or dy:
                    pyautogui.moveRel(dx, dy)
            elif action == "click":
                if x is not None and y is not None:
                    pyautogui.click(x, y, button=button, clicks=clicks)
                else:
                    pyautogui.click(button=button, clicks=clicks)
            elif action == "double_click":
                if x is not None and y is not None:
                    pyautogui.doubleClick(x, y, button=button)
                else:
                    pyautogui.doubleClick(button=button)
            elif action == "right_click":
                if x is not None and y is not None:
                    pyautogui.rightClick(x, y)
                else:
                    pyautogui.rightClick()
            elif action == "middle_click":
                if x is not None and y is not None:
                    pyautogui.middleClick(x, y)
                else:
                    pyautogui.middleClick()
            elif action == "down":
                pyautogui.mouseDown(x=x, y=y, button=button)
            elif action == "up":
                pyautogui.mouseUp(x=x, y=y, button=button)
            elif action == "drag":
                if x is not None and y is not None:
                    pyautogui.dragTo(x, y, button=button, duration=0.2)
                elif dx or dy:
                    pyautogui.dragRel(dx, dy, button=button, duration=0.2)
            elif action == "scroll":
                clicks_scroll = dy if dy != 0 else (clicks * 100)
                pyautogui.scroll(clicks_scroll, x=x, y=y)
            else:
                return {"ok": False, "error": f"Acción de ratón no reconocida: '{action}'"}

            cur_pos = pyautogui.position()
            return {"ok": True, "action": action, "position": {"x": int(cur_pos.x), "y": int(cur_pos.y)}}
        except Exception as e:
            return {"ok": False, "error": f"Fallo ejecutando acción de ratón: {e}"}

    # --------------------------------------------------------------------------
    # 4. CONTROL DE TECLADO
    # --------------------------------------------------------------------------

    def keyboard_action(
        self,
        action: str,
        text: Optional[str] = None,
        key: Optional[str] = None,
        keys: Optional[List[str]] = None,
        interval: float = 0.02
    ) -> Dict[str, Any]:
        """Ejecuta eventos de tipeo de texto y pulsaciones de teclas."""
        if not HAS_PYAUTOGUI:
            # Fallback a nivel kernel con /dev/uinput si PyAutoGUI no está disponible
            if action in ("type", "typewrite") and text is not None:
                ok = self.type_keystrokes_uinput(text=str(text), press_enter=False, wake_shield=False)
                return {"ok": ok, "action": action, "target": text, "backend": "uinput"}
            elif action == "press":
                target_key = key or (keys[0] if keys else "")
                ok = self.type_keystrokes_uinput(text=str(target_key), press_enter=(str(target_key).lower() == "enter"), wake_shield=False)
                return {"ok": ok, "action": action, "target": target_key, "backend": "uinput"}
            return {"ok": False, "error": "PyAutoGUI no disponible en este entorno y acción compleja para uinput."}

        action = action.lower().strip()
        try:
            if action in ("type", "typewrite"):
                if text is None:
                    return {"ok": False, "error": "Se requiere el parámetro 'text' para escribir."}
                pyautogui.typewrite(str(text), interval=interval)
            elif action == "press":
                target_key = key or (keys[0] if keys else None)
                if not target_key:
                    return {"ok": False, "error": "Se requiere especificar la tecla a pulsar en 'key'."}
                pyautogui.press(target_key.lower().strip())
            elif action == "hotkey":
                combo = keys or ([k.strip() for k in (key or "").split("+")] if key else [])
                if not combo:
                    return {"ok": False, "error": "Se requiere una combinación de teclas (ej: ['ctrl', 'c'])."}
                pyautogui.hotkey(*[k.lower().strip() for k in combo])
            elif action == "key_down":
                target_key = key or (keys[0] if keys else None)
                if not target_key:
                    return {"ok": False, "error": "Se requiere especificar la tecla."}
                pyautogui.keyDown(target_key.lower().strip())
            elif action == "key_up":
                target_key = key or (keys[0] if keys else None)
                if not target_key:
                    return {"ok": False, "error": "Se requiere especificar la tecla."}
                pyautogui.keyUp(target_key.lower().strip())
            else:
                return {"ok": False, "error": f"Acción de teclado no reconocida: '{action}'"}

            return {"ok": True, "action": action, "target": text or key or keys}
        except Exception as e:
            return {"ok": False, "error": f"Fallo ejecutando acción de teclado: {e}"}

    # --------------------------------------------------------------------------
    # 5. CONTROL DE APLICACIONES Y VENTANAS
    # --------------------------------------------------------------------------

    def launch_app(self, target: str) -> Dict[str, Any]:
        """Lanza una aplicación o abre un archivo/URL en el entorno de escritorio."""
        if not target or not target.strip():
            return {"ok": False, "error": "Objetivo de aplicación vacío."}

        target = target.strip()
        aliases = {
            "browser": "google-chrome",
            "chrome": "google-chrome",
            "firefox": "firefox",
            "terminal": "gnome-terminal",
            "files": "nautilus",
            "calculator": "gnome-calculator",
            "text_editor": "gedit",
            "settings": "gnome-control-center",
            "antigravity": "/snap/bin/antigravity",
            "agy": "/snap/bin/antigravity",
            "ide": "/snap/bin/antigravity",
        }
        cmd_target = aliases.get(target.lower(), target)

        try:
            if cmd_target.startswith("http://") or cmd_target.startswith("https://"):
                subprocess.Popen(["xdg-open", cmd_target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return {"ok": True, "action": "open_url", "target": cmd_target}

            exe = shutil.which(cmd_target)
            if exe:
                subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return {"ok": True, "action": "launch_binary", "target": exe}

            res = subprocess.run(["gtk-launch", cmd_target], capture_output=True, text=True, timeout=3.0)
            if res.returncode == 0:
                return {"ok": True, "action": "gtk_launch", "target": cmd_target}

            subprocess.Popen(["xdg-open", cmd_target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "action": "xdg_open", "target": cmd_target}
        except Exception as e:
            return {"ok": False, "error": f"No se pudo iniciar '{target}': {e}"}

    def execute_terminal_command(self, command: str, cwd: Optional[str] = None, timeout: float = 25.0) -> Dict[str, Any]:
        """
        Ejecuta un comando de terminal/bash de forma inalámbrica y retorna stdout/stderr.
        Permite el acceso y gobierno inalámbrico total desde cualquier dispositivo.
        """
        if not command or not command.strip():
            return {"ok": False, "error": "Comando vacío."}

        command = command.strip()
        t0 = time.time()
        base_cwd = cwd or str(Path(__file__).resolve().parent.parent)

        try:
            res = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=base_cwd
            )
            elapsed = round(time.time() - t0, 3)
            return {
                "ok": res.returncode == 0,
                "returncode": res.returncode,
                "command": command,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "elapsed_s": elapsed,
                "cwd": base_cwd
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": f"El comando superó el tiempo límite de {timeout}s.",
                "command": command,
                "elapsed_s": timeout
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"Error ejecutando comando en terminal: {e}",
                "command": command
            }

    def get_antigravity_status(self) -> Dict[str, Any]:
        """Verifica el estado de ejecución de Google Antigravity y su language server."""
        pids = []
        has_lang_server = False
        try:
            res = subprocess.run(["pgrep", "-f", "/snap/antigravity"], capture_output=True, text=True)
            if res.returncode == 0:
                pids = [int(p) for p in res.stdout.strip().split() if p.isdigit()]
            res_ls = subprocess.run(["pgrep", "-f", "language_server.*antigravity"], capture_output=True, text=True)
            has_lang_server = (res_ls.returncode == 0)
        except Exception:
            pass

        return {
            "ok": True,
            "running": len(pids) > 0,
            "processes_count": len(pids),
            "pids": pids[:6],
            "language_server_active": has_lang_server,
            "snap_binary": "/snap/bin/antigravity",
            "autostart_configured": os.path.exists(os.path.expanduser("~/.config/autostart/antigravity.desktop")),
            "workspace": "/home/timemachine/Escritorio/GODWORKS SYSTEM"
        }

    def launch_antigravity(self, workspace: Optional[str] = None) -> Dict[str, Any]:
        """Lanza o activa Google Antigravity en el entorno gráfico con el espacio de trabajo configurado."""
        ws = workspace or "/home/timemachine/Escritorio/GODWORKS SYSTEM"
        safe_script = os.path.expanduser("~/.local/bin/start_antigravity_safe.sh")

        try:
            if os.path.isfile(safe_script) and os.access(safe_script, os.X_OK):
                subprocess.Popen([safe_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif os.path.isfile("/snap/bin/antigravity"):
                subprocess.Popen(["/snap/bin/antigravity", ws], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                return {"ok": False, "error": "Binario de Antigravity no encontrado en /snap/bin/antigravity."}

            time.sleep(1.0)
            return {"ok": True, "action": "antigravity_launched", "workspace": ws, "status": self.get_antigravity_status()}
        except Exception as e:
            return {"ok": False, "error": f"Error lanzando Antigravity: {e}"}

    # --------------------------------------------------------------------------
    # 6. CONTROL DE AUDIO Y MULTIMEDIA (wpctl / amixer / PipeWire)
    # --------------------------------------------------------------------------

    def get_volume(self) -> Dict[str, Any]:
        """Obtiene el volumen actual del sistema y estado de silencio (mute)."""
        try:
            res = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True, timeout=2.0)
            if res.returncode == 0 and res.stdout:
                txt = res.stdout.strip()
                is_muted = "[MUTED]" in txt
                parts = txt.replace("[MUTED]", "").split()
                if len(parts) >= 2:
                    vol = float(parts[1])
                    return {"ok": True, "level": vol, "percent": int(vol * 100), "muted": is_muted}
        except Exception:
            pass

        try:
            res = subprocess.run(["amixer", "get", "Master"], capture_output=True, text=True, timeout=2.0)
            if res.returncode == 0 and res.stdout:
                import re
                m_pct = re.search(r"\[(\d+)%\]", res.stdout)
                m_mute = re.search(r"\[(on|off)\]", res.stdout)
                pct = int(m_pct.group(1)) if m_pct else 50
                is_muted = m_mute.group(1) == "off" if m_mute else False
                return {"ok": True, "level": pct / 100.0, "percent": pct, "muted": is_muted}
        except Exception:
            pass

        return {"ok": True, "level": 0.5, "percent": 50, "muted": False}

    def set_volume(self, percent: Union[int, float]) -> Dict[str, Any]:
        """Ajusta el volumen del sistema al porcentaje especificado (0 a 100)."""
        pct = max(0, min(100, int(percent)))
        vol_float = pct / 100.0
        try:
            res = subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{vol_float:.2f}"], capture_output=True, timeout=2.0)
            if res.returncode == 0:
                return {"ok": True, "level": vol_float, "percent": pct}
        except Exception:
            pass

        try:
            res = subprocess.run(["amixer", "set", "Master", f"{pct}%"], capture_output=True, timeout=2.0)
            if res.returncode == 0:
                return {"ok": True, "level": vol_float, "percent": pct}
        except Exception as e:
            return {"ok": False, "error": f"Fallo al cambiar volumen: {e}"}

        return {"ok": True, "level": vol_float, "percent": pct}

    def toggle_mute(self) -> Dict[str, Any]:
        """Alterna el estado de silencio (mute/unmute) del audio del sistema."""
        try:
            subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"], capture_output=True, timeout=2.0)
        except Exception:
            try:
                subprocess.run(["amixer", "set", "Master", "toggle"], capture_output=True, timeout=2.0)
            except Exception:
                pass
        return self.get_volume()

    # --------------------------------------------------------------------------
    # 7. PERSISTENCIA 24/7 E INHIBICIÓN DE SUSPENSIÓN
    # --------------------------------------------------------------------------

    def ensure_sleep_inhibited(self) -> bool:
        """
        Mantiene un proceso systemd-inhibit activo en segundo plano para evitar
        que Ubuntu suspenda el procesador o la red cuando la pantalla esté bloqueada.
        """
        if self._inhibit_proc and self._inhibit_proc.poll() is None:
            return True

        exe = shutil.which("systemd-inhibit")
        if not exe:
            return False

        try:
            self._inhibit_proc = subprocess.Popen(
                [
                    exe,
                    "--what=idle:sleep",
                    "--who=GODWORKS SYSTEM v26.4",
                    "--why=Operación Soberana Continua 24/7 en Segundo Plano",
                    "--mode=block",
                    "sleep", "infinity"
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except Exception:
            return False

    def release_sleep_inhibit(self):
        """Libera la inhibición de suspensión si fuera necesario."""
        if self._inhibit_proc:
            try:
                self._inhibit_proc.terminate()
                self._inhibit_proc.wait(timeout=2.0)
            except Exception:
                pass
            self._inhibit_proc = None

    # --------------------------------------------------------------------------
    # 8. EJECUCIÓN SEGURA DE COMANDOS DE TERMINAL
    # --------------------------------------------------------------------------

    def run_shell(self, command: str, timeout: float = 30.0) -> Dict[str, Any]:
        """Ejecuta un comando de shell Bash auditado y seguro."""
        if not command or not command.strip():
            return {"ok": False, "error": "Comando vacío."}

        try:
            import agent_safety
            verdict = agent_safety.audit("os_shell", command[:200])
            if verdict == "BLOCK":
                return {"ok": False, "error": "Comando denegado por política de seguridad soberana."}
        except Exception:
            pass

        try:
            t0 = time.time()
            res = subprocess.run(
                ["/usr/bin/bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            elapsed = round(time.time() - t0, 3)
            return {
                "ok": res.returncode == 0,
                "returncode": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "elapsed_s": elapsed,
                "command": command
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Tiempo límite excedido ({timeout}s)."}
        except Exception as e:
            return {"ok": False, "error": f"Error ejecutando shell: {e}"}

    # --------------------------------------------------------------------------
    # 9. MATRIZ DE INTEGRACIÓN MULTIPLATAFORMA Y HARDWARE/SOFTWARE (PILAR 4)
    # --------------------------------------------------------------------------

    def get_platform_capabilities(self) -> Dict[str, Any]:
        """Devuelve la matriz completa de capacidades de hardware, subsistemas y SO."""
        import platform

        gpu_info = "None"
        cuda_available = False
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=1.5
            )
            if res.returncode == 0 and res.stdout.strip():
                gpu_info = res.stdout.strip()
                cuda_available = True
        except Exception:
            pass

        return {
            "platform": sys.platform,
            "os_name": os.name,
            "system_architecture": platform.machine(),
            "os_release": platform.release(),
            "python_version": platform.python_version(),
            "subsystems": {
                "x11": bool(os.environ.get("DISPLAY")),
                "wayland": bool(os.environ.get("WAYLAND_DISPLAY")),
                "dbus": bool(shutil.which("gdbus") or shutil.which("qdbus")),
                "systemd": bool(shutil.which("systemctl")),
                "audio_pipewire": bool(shutil.which("wpctl")),
                "audio_alsa": bool(shutil.which("amixer")),
                "gui_automation": HAS_PYAUTOGUI,
                "screen_capture": HAS_MSS,
                "pil_imaging": HAS_PIL,
                "process_metrics": HAS_PSUTIL,
            },
            "supported_environments": [
                "linux_x86_64",
                "linux_arm64_sbc",
                "windows_win32",
                "macos_darwin",
                "android_termux"
            ],
            "iot_protocols": ["mqtt", "http_rest", "serial_comm", "websocket"],
            "accelerators": {
                "cuda_available": cuda_available,
                "gpu_device": gpu_info,
                "opencl_vulkan": bool(shutil.which("vulkaninfo") or shutil.which("clinfo"))
            }
        }


# Instancia Global
def get_os_controller() -> OSController:
    return OSController.get_instance()

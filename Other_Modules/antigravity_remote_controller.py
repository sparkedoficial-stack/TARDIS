"""
core/antigravity_remote_controller.py
======================================
Control Remoto Soberano y Acoplamiento Bidireccional con Antigravity GUI
GODWORKS SYSTEM v26.4 · TARDIS

Permite al sistema (local daemon, TARDIS, FTL, CLI y Web Cockpit):
1. Detectar el estado activo de la aplicación gráfica Antigravity (GUI).
2. Sincronizar de forma atómica e inmediata la base de datos de resúmenes
   (conversation_summaries.db), almacenamiento de layout (app_storage.json),
   y archivos de conversación entre el entorno CLI y la aplicación GUI.
3. Abrir, cambiar o enfocar de forma remota cualquier sesión de conversación
   (por defecto: 2425f3ac-4fb8-427e-9232-388ebcc90c19) directamente en la GUI
   usando Chrome DevTools Protocol (CDP) sobre el puerto activo expuesto.
4. Interactuar e inyectar prompts o directivas remotamente en el editor de la GUI.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# Rutas estándar de Antigravity
CURRENT_CONVERSATION_ID = "2425f3ac-4fb8-427e-9232-388ebcc90c19"
DEFAULT_WORKSPACE = "/home/timemachine"
ALT_WORKSPACE = "/home/timemachine/Escritorio/GODWORKS SYSTEM"

HOME = Path(os.path.expanduser("~"))
DEVTOOLS_PORT_FILE = HOME / ".config" / "Antigravity" / "DevToolsActivePort"
APP_STORAGE_FILE = HOME / ".config" / "Antigravity" / "app_storage.json"

CLI_DIR = HOME / ".gemini" / "antigravity-cli"
GUI_DIR = HOME / ".gemini" / "antigravity"

CLI_SUMMARIES_DB = CLI_DIR / "conversation_summaries.db"
GUI_SUMMARIES_DB = GUI_DIR / "conversation_summaries.db"

SNAP_BINARY = "/snap/bin/antigravity"
SAFE_LAUNCHER = HOME / ".local" / "bin" / "start_antigravity_safe.sh"


class AntigravityRemoteController:
    """Controlador y puente remoto de la aplicación Antigravity GUI."""

    def __init__(self, target_conversation_id: str = CURRENT_CONVERSATION_ID):
        self.target_conversation_id = target_conversation_id

    def get_devtools_info(self) -> Optional[Dict[str, Any]]:
        """Lee el puerto activo y la ruta expuesta por Electron en DevToolsActivePort."""
        if not DEVTOOLS_PORT_FILE.is_file():
            return None
        try:
            lines = DEVTOOLS_PORT_FILE.read_text(encoding="utf-8").strip().splitlines()
            if not lines:
                return None
            port = int(lines[0].strip())
            browser_path = lines[1].strip() if len(lines) > 1 else ""
            return {"port": port, "browser_path": browser_path}
        except Exception:
            return None

    def get_cdp_targets(self, port: int, timeout: float = 3.0) -> List[Dict[str, Any]]:
        """Consulta los targets CDP activos en http://REDACTED_IP:<port>/json."""
        try:
            url = f"http://REDACTED_IP:{port}/json"
            req = urllib.request.Request(url, headers={"User-Agent": "TARDIS-Controller"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []

    def get_gui_status(self) -> Dict[str, Any]:
        """Diagnóstico completo del estado del proceso, ventana gráfica y sesión."""
        # 1. Procesos en ejecución
        pids = []
        try:
            res = subprocess.run(["pgrep", "-f", "/snap/antigravity"], capture_output=True, text=True)
            if res.returncode == 0:
                pids = [int(p) for p in res.stdout.strip().split() if p.isdigit()]
        except Exception:
            pass

        running = len(pids) > 0
        dt_info = self.get_devtools_info()
        cdp_available = False
        main_page = None
        active_url = ""
        page_title = ""

        if dt_info and running:
            port = dt_info["port"]
            targets = self.get_cdp_targets(port)
            if targets:
                cdp_available = True
                # Buscar la página principal (la que apunta a https://REDACTED_IP:<ls_port>/)
                for t in targets:
                    t_url = t.get("url", "")
                    if t.get("type") == "page" and not t_url.startswith("data:"):
                        main_page = t
                        active_url = t_url
                        page_title = t.get("title", "")
                        break

        # Comprobar si la conversación objetivo está abierta actualmente en la GUI
        in_target_convo = False
        if active_url:
            in_target_convo = (self.target_conversation_id in active_url)

        return {
            "ok": True,
            "running": running,
            "processes_count": len(pids),
            "pids": pids[:6],
            "devtools_port": dt_info["port"] if dt_info else None,
            "cdp_available": cdp_available,
            "active_url": active_url,
            "window_title": page_title,
            "target_conversation_id": self.target_conversation_id,
            "target_conversation_open": in_target_convo,
            "summaries_in_gui_db": self._check_conversation_in_gui_db(),
            "snap_binary": "/snap/bin/antigravity",
            "autostart_configured": os.path.exists(os.path.expanduser("~/.config/autostart/antigravity.desktop")),
            "timestamp": time.time(),
            "iso": datetime.datetime.now().isoformat()
        }

    def _check_conversation_in_gui_db(self) -> bool:
        """Verifica si la conversación está indexada en conversation_summaries.db de la GUI."""
        if not GUI_SUMMARIES_DB.is_file():
            return False
        try:
            import sqlite3
            conn = sqlite3.connect(str(GUI_SUMMARIES_DB))
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM conversation_summaries WHERE conversation_id = ?", (self.target_conversation_id,))
            return cur.fetchone() is not None
        except Exception:
            return False

    def sync_session(self, conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Sincroniza atómicamente la sesión activa hacia la aplicación Antigravity:
        1. Copia y actualiza el registro en conversation_summaries.db con timestamp actual.
        2. Asegura symlinks en ~/.gemini/antigravity/conversations y ~/.gemini/antigravity/brain.
        3. Configura el layout multi-panel en app_storage.json.
        """
        cid = conversation_id or self.target_conversation_id
        results = {"conversation_id": cid, "db_synced": False, "symlinks_ok": False, "storage_synced": False}

        # 1. Asegurar symlinks
        cli_conv = CLI_DIR / "conversations" / f"{cid}.db"
        gui_conv_dir = GUI_DIR / "conversations"
        gui_conv_dir.mkdir(parents=True, exist_ok=True)
        gui_conv_link = gui_conv_dir / f"{cid}.db"

        if cli_conv.is_file() and not gui_conv_link.exists():
            try:
                gui_conv_link.symlink_to(cli_conv)
            except Exception:
                pass

        cli_brain = CLI_DIR / "brain" / cid
        gui_brain_dir = GUI_DIR / "brain"
        gui_brain_dir.mkdir(parents=True, exist_ok=True)
        gui_brain_link = gui_brain_dir / cid

        if cli_brain.is_dir() and not gui_brain_link.exists():
            try:
                gui_brain_link.symlink_to(cli_brain)
            except Exception:
                pass

        results["symlinks_ok"] = gui_conv_link.exists() and gui_brain_link.exists()

        # 2. Sincronizar registro de SQLite en conversation_summaries.db
        if CLI_SUMMARIES_DB.is_file() and GUI_SUMMARIES_DB.is_file():
            try:
                import sqlite3
                c_cli = sqlite3.connect(str(CLI_SUMMARIES_DB))
                cur_cli = c_cli.cursor()
                row = cur_cli.execute("SELECT * FROM conversation_summaries WHERE conversation_id = ?", (cid,)).fetchone()
                cols = [c[1] for c in cur_cli.execute("PRAGMA table_info(conversation_summaries)").fetchall()]

                if row:
                    data = dict(zip(cols, row))
                    data["app_data_dir"] = "antigravity"
                    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f+00:00")
                    data["last_modified_time"] = now_iso

                    c_gui = sqlite3.connect(str(GUI_SUMMARIES_DB))
                    cur_gui = c_gui.cursor()
                    placeholders = ", ".join(["?"] * len(cols))
                    update_clause = ", ".join([f"{col} = excluded.{col}" for col in cols if col != "conversation_id"])
                    sql = f"INSERT INTO conversation_summaries ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT(conversation_id) DO UPDATE SET {update_clause}"
                    cur_gui.execute(sql, [data[c] for c in cols])
                    c_gui.commit()
                    c_gui.close()
                    results["db_synced"] = True
                c_cli.close()
            except Exception as e:
                results["db_error"] = str(e)

        # 3. Sincronizar app_storage.json
        if APP_STORAGE_FILE.is_file():
            try:
                storage_data = json.loads(APP_STORAGE_FILE.read_text(encoding="utf-8", errors="ignore"))
                layout_key = f"antigravity-multi-conversation-layout-v3-{cid}"
                storage_data[layout_key] = json.dumps({
                    "rootNode": {"type": "pane", "id": "pane-1", "cascadeId": cid},
                    "focusedPaneId": "pane-1"
                })
                storage_data["new-convo-last-selected-project"] = "default-cli-project"

                if "aux-pane-session" in storage_data:
                    try:
                        aux = json.loads(storage_data["aux-pane-session"])
                        aux.setdefault("conversationPanes", {})[cid] = {
                            "tabs": [],
                            "activeTabId": "",
                            "sidebarOpenStates": {"overview": True},
                            "isPaneOpen": True
                        }
                        storage_data["aux-pane-session"] = json.dumps(aux)
                    except Exception:
                        pass

                if "aux-pane-v2-session" in storage_data:
                    try:
                        aux2 = json.loads(storage_data["aux-pane-v2-session"])
                        aux2.setdefault("conversationPanes", {})[cid] = {
                            "tabs": [],
                            "activeTabId": "newTab__empty"
                        }
                        storage_data["aux-pane-v2-session"] = json.dumps(aux2)
                    except Exception:
                        pass

                APP_STORAGE_FILE.write_text(json.dumps(storage_data, indent=2), encoding="utf-8")
                results["storage_synced"] = True
            except Exception as e:
                results["storage_error"] = str(e)

        results["ok"] = results["db_synced"] or results["storage_synced"]
        return results

    async def _async_cdp_navigate_and_focus(self, port: int, cid: str) -> Dict[str, Any]:
        """Comando CDP asíncrono para navegar al enlace de la conversación y enfocar la ventana."""
        import websockets

        targets = self.get_cdp_targets(port)
        main_page = None
        for t in targets:
            if t.get("type") == "page" and not t.get("url", "").startswith("data:"):
                main_page = t
                break

        if not main_page:
            return {"ok": False, "error": "No se encontró el target de la página principal en Antigravity."}

        ws_url = main_page["webSocketDebuggerUrl"]
        target_path = f"/c/{cid}?section=default-cli-project"

        async with websockets.connect(ws_url) as ws:
            # 1. Intentar hacer click en el enlace dentro del DOM de React si existe
            click_js = f"""
            (() => {{
                // Buscar enlace directo por data-cascade-id
                const container = document.querySelector('[data-cascade-id="{cid}"]');
                if (container) {{
                    const a = container.querySelector('a');
                    if (a) {{
                        a.click();
                        return {{action: "clicked_link", href: a.href}};
                    }}
                    container.click();
                    return {{action: "clicked_container"}};
                }}
                
                // Fallback: búsqueda por enlace parcial de href
                const a = document.querySelector('a[href*="{cid}"]');
                if (a) {{
                    a.click();
                    return {{action: "clicked_href", href: a.href}};
                }}

                // Fallback directo: navegar history
                window.location.href = "{target_path}";
                return {{action: "navigated_location", href: window.location.href}};
            }})()
            """
            msg_click = {
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": click_js, "returnByValue": True}
            }
            await ws.send(json.dumps(msg_click))
            res_click = json.loads(await ws.recv())

            # 2. Llevar la ventana al frente (Window focus)
            msg_front = {
                "id": 2,
                "method": "Page.bringToFront"
            }
            await ws.send(json.dumps(msg_front))
            res_front = json.loads(await ws.recv())

            return {
                "ok": True,
                "action": "cdp_switch_and_focus",
                "click_result": res_click.get("result", {}).get("result", {}).get("value"),
                "bring_to_front": res_front.get("result", {}),
                "conversation_id": cid
            }

    @staticmethod
    def _run_coro_sync(coro, timeout: float = 12.0) -> Any:
        """Ejecuta una corrutina asíncrona de manera segura desde cualquier hilo o bucle de eventos."""
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=timeout)

    def open_conversation_in_gui(self, conversation_id: Optional[str] = None, workspace: Optional[str] = None) -> Dict[str, Any]:
        """
        Punto de entrada universal para control remoto:
        - Si Antigravity está en ejecución: cambia la conversación inmediatamente vía CDP y enfoca la ventana.
        - Si Antigravity está cerrado: sincroniza estado y lanza la aplicación abriendo directo en la conversación.
        """
        cid = conversation_id or self.target_conversation_id
        ws_path = workspace or DEFAULT_WORKSPACE

        # 1. Asegurar sincronización previa
        sync_res = self.sync_session(cid)

        # 2. Verificar si ya está en ejecución
        gui_stat = self.get_gui_status()

        if gui_stat["running"] and gui_stat["cdp_available"]:
            port = gui_stat["devtools_port"]
            try:
                res = self._run_coro_sync(self._async_cdp_navigate_and_focus(port, cid))
                res["sync"] = sync_res
                return res
            except Exception as e:
                pass

        # 3. Si no está en ejecución (o no responde CDP), lanzar Antigravity
        env = os.environ.copy()
        env["DISPLAY"] = env.get("DISPLAY", ":0")
        env["WAYLAND_DISPLAY"] = env.get("WAYLAND_DISPLAY", "wayland-0")
        env["XDG_RUNTIME_DIR"] = env.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        env["XDG_SESSION_TYPE"] = env.get("XDG_SESSION_TYPE", "wayland")

        try:
            if SAFE_LAUNCHER.is_file() and os.access(SAFE_LAUNCHER, os.X_OK):
                subprocess.Popen([str(SAFE_LAUNCHER), ws_path, cid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif os.path.isfile(SNAP_BINARY):
                subprocess.Popen([SNAP_BINARY, ws_path], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                return {"ok": False, "error": f"Binario no encontrado en {SNAP_BINARY}."}
        except Exception as e:
            return {"ok": False, "error": f"Error al lanzar Antigravity: {e}"}

        # 4. Esperar arranque breve y conectar CDP para conmutar y enfocar
        for _ in range(12):
            time.sleep(0.8)
            stat = self.get_gui_status()
            if stat["running"] and stat["cdp_available"]:
                try:
                    res = self._run_coro_sync(self._async_cdp_navigate_and_focus(stat["devtools_port"], cid))
                    res["launched_new"] = True
                    return res
                except Exception:
                    pass

        return {
            "ok": True,
            "action": "antigravity_launched",
            "workspace": ws_path,
            "conversation_id": cid,
            "sync": sync_res
        }

    async def _async_cdp_inject_prompt(self, port: int, prompt: str) -> Dict[str, Any]:
        """Inyecta texto en el editor contenteditable de Antigravity vía CDP."""
        import websockets

        targets = self.get_cdp_targets(port)
        main_page = None
        for t in targets:
            if t.get("type") == "page" and not t.get("url", "").startswith("data:"):
                main_page = t
                break

        if not main_page:
            return {"ok": False, "error": "Target de Antigravity no encontrado."}

        ws_url = main_page["webSocketDebuggerUrl"]
        clean_prompt = json.dumps(prompt)

        async with websockets.connect(ws_url) as ws:
            js = f"""
            (() => {{
                const ce = document.querySelector('[contenteditable="true"]');
                if (!ce) return {{found: false}};
                ce.focus();
                // Simular inserción de texto
                document.execCommand('insertText', false, {clean_prompt});
                return {{found: true, length: ce.innerText.length}};
            }})()
            """
            msg = {
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": js, "returnByValue": True}
            }
            await ws.send(json.dumps(msg))
            res = json.loads(await ws.recv())

            # Focus
            await ws.send(json.dumps({"id": 2, "method": "Page.bringToFront"}))
            await ws.recv()

            return {
                "ok": True,
                "result": res.get("result", {}).get("result", {}).get("value")
            }

    def inject_prompt_in_gui(self, prompt: str) -> Dict[str, Any]:
        """Inyecta un prompt de texto en la barra de chat de la GUI de Antigravity."""
        gui_stat = self.get_gui_status()
        if not gui_stat["running"] or not gui_stat["cdp_available"]:
            return {"ok": False, "error": "Antigravity GUI no está en ejecución con CDP activo."}

        port = gui_stat["devtools_port"]
        try:
            return self._run_coro_sync(self._async_cdp_inject_prompt(port, prompt))
        except Exception as e:
            return {"ok": False, "error": str(e)}


_GLOBAL_CONTROLLER: Optional[AntigravityRemoteController] = None


def get_remote_controller() -> AntigravityRemoteController:
    """Singleton del controlador remoto de Antigravity."""
    global _GLOBAL_CONTROLLER
    if _GLOBAL_CONTROLLER is None:
        _GLOBAL_CONTROLLER = AntigravityRemoteController()
    return _GLOBAL_CONTROLLER


if __name__ == "__main__":
    ctrl = get_remote_controller()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        print(json.dumps(ctrl.get_gui_status(), indent=2))
    elif cmd == "sync":
        cid = sys.argv[2] if len(sys.argv) > 2 else CURRENT_CONVERSATION_ID
        print(json.dumps(ctrl.sync_session(cid), indent=2))
    elif cmd == "open":
        cid = sys.argv[2] if len(sys.argv) > 2 else CURRENT_CONVERSATION_ID
        print(json.dumps(ctrl.open_conversation_in_gui(cid), indent=2))
    elif cmd == "prompt":
        if len(sys.argv) < 3:
            print("Uso: python -m core.antigravity_remote_controller prompt <texto>")
            sys.exit(1)
        text = " ".join(sys.argv[2:])
        print(json.dumps(ctrl.inject_prompt_in_gui(text), indent=2))
    else:
        print("Comandos disponibles: status | sync [cid] | open [cid] | prompt <texto>")

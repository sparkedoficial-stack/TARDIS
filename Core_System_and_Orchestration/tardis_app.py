#!/usr/bin/env python3
"""
tardis_app.py - Aplicación Unificada de Escritorio para TARDIS v26.4
=============================================================================
Interfaz soberana de escritorio 100% autónoma en Linux (WebKitGTK / GTK3).
Unifica el servidor maestro, centinela de auto-reparación, chat soberano,
herramientas de subsistemas, telemetría y HUD 3D en una sola aplicación nativa.
=============================================================================
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Configurar librerías gráficas
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, Gdk, WebKit2, GLib, GdkPixbuf

PORT = 8757
AUTH_TOKEN = os.environ.get("GIA_AUTH_TOKEN", "DiosDelTiempo01")
APP_URL = f"http://REDACTED_IP:{PORT}?key={AUTH_TOKEN}"
ICON_PATH = PROJECT_DIR / "tardis-icon.png"


def is_backend_online(timeout: float = 1.0) -> bool:
    """Comprueba si el servidor maestro TARDIS responde en el puerto local."""
    try:
        req = urllib.request.Request(f"http://REDACTED_IP:{PORT}/api/health", headers={"User-Agent": "TardisApp/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_backend_running():
    """Garantiza que el servidor maestro esté corriendo antes de cargar la interfaz."""
    if is_backend_online(0.8):
        print("⚡ [Tardis App] Backend maestro TARDIS detectado en línea.")
        return None

    print("🚀 [Tardis App] Backend maestro no detectado. Iniciando servicio TARDIS en segundo plano...")
    
    # Intentar primero mediante systemd user service si está configurado
    try:
        res = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "tardis.service"], capture_output=True)
        if res.returncode != 0:
            subprocess.run(["systemctl", "--user", "start", "tardis.service"], capture_output=True)
            for _ in range(10):
                if is_backend_online(0.5):
                    print("⚡ [Tardis App] Servicio tardis.service iniciado exitosamente.")
                    return None
                time.sleep(0.5)
    except Exception:
        pass

    # Fallback: levantar proceso local directamente
    venv_python = PROJECT_DIR / ".venv-linux" / "bin" / "python3"
    py_bin = str(venv_python) if venv_python.exists() else sys.executable
    cmd = [
        py_bin,
        str(PROJECT_DIR / "omni_temporal_control.py"),
        "--port", str(PORT),
        "--bridge",
        "--no-window"
    ]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["GIA_AUTH_TOKEN"] = AUTH_TOKEN
    proc = subprocess.Popen(cmd, cwd=str(PROJECT_DIR), env=env)
    
    # Esperar hasta que esté listo (máximo 15s)
    start_t = time.time()
    while time.time() - start_t < 15.0:
        if is_backend_online(0.5):
            print("✅ [Tardis App] Servidor TARDIS inicializado con éxito.")
            return proc
        time.sleep(0.4)
        
    print("⚠️ [Tardis App] Advertencia: El servidor maestro tardó en responder. Continuando carga...")
    return proc


class TardisAppWindow(Gtk.Window):
    """Ventana unificada de escritorio para Tardis."""

    def __init__(self, target_url: str = APP_URL):
        super().__init__(title="Tardis")
        self.set_wmclass("tardis", "Tardis")
        self.set_default_size(1400, 880)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Aplicar estilo oscuro cibernético de fondo
        css = b"""
        window, .background {
            background-color: #05080c;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Cargar Icono Oficial
        if ICON_PATH.exists():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(ICON_PATH))
                self.set_icon(pixbuf)
            except Exception as e:
                print(f"[Tardis App] No se pudo cargar el icono: {e}")

        # Configuración de WebKit2 nativo con aceleración de hardware
        settings = WebKit2.Settings()
        settings.set_enable_javascript(True)
        settings.set_enable_webgl(True)
        settings.set_enable_media_stream(True)
        settings.set_enable_mediasource(True)
        settings.set_enable_smooth_scrolling(True)
        settings.set_enable_developer_extras(True)
        
        # Habilitar aceleración por hardware
        if hasattr(WebKit2, "HardwareAccelerationPolicy"):
            settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)

        user_content_mgr = WebKit2.UserContentManager()
        self.webview = WebKit2.WebView.new_with_user_content_manager(user_content_mgr)
        self.webview.set_settings(settings)
        self.webview.set_background_color(Gdk.RGBA(0.02, 0.03, 0.05, 1.0))

        # Manejo automático de permisos (micrófono / multimedia local)
        self.webview.connect("permission-request", self._on_permission_request)

        # Título dinámico
        self.webview.connect("notify::title", self._on_title_changed)

        # Contenedor con barra de desplazamiento
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.webview)
        self.add(scrolled)

        # Atajos de teclado
        self.connect("key-press-event", self._on_key_press)
        self.connect("destroy", Gtk.main_quit)

        self.is_fullscreen = False
        self.target_url = target_url

        print(f"🌌 [Tardis App] Cargando interfaz unificada en: {self.target_url}")
        self.webview.load_uri(self.target_url)

    def _on_permission_request(self, webview, request):
        """Autorizar acceso a micrófono y audio local sin cuadros de diálogo intrusivos."""
        if isinstance(request, WebKit2.UserMediaPermissionRequest):
            request.allow()
            return True
        return False

    def _on_title_changed(self, webview, param):
        title = webview.get_title()
        if title:
            self.set_title(f"Tardis · {title}" if not title.startswith("Tardis") else title)

    def _on_key_press(self, widget, event):
        # F11: Alternar Pantalla Completa
        if event.keyval == Gdk.KEY_F11:
            if self.is_fullscreen:
                self.unfullscreen()
                self.is_fullscreen = False
            else:
                self.fullscreen()
                self.is_fullscreen = True
            return True

        # Ctrl+R o F5: Recargar
        if (event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval in (Gdk.KEY_r, Gdk.KEY_R)) or event.keyval == Gdk.KEY_F5:
            self.webview.reload()
            return True

        # Ctrl+Q: Salir
        if event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval in (Gdk.KEY_q, Gdk.KEY_Q):
            self.close()
            return True

        # F12: Abrir Inspector
        if event.keyval == Gdk.KEY_F12:
            inspector = self.webview.get_inspector()
            inspector.show()
            return True

        return False


def main():
    # 1. Asegurar backend
    backend_proc = ensure_backend_running()

    # 2. Iniciar ventana de interfaz unificada
    target_url = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("http") else APP_URL
    win = TardisAppWindow(target_url=target_url)
    win.show_all()

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        Gtk.main()
    finally:
        if backend_proc and backend_proc.poll() is None:
            # Si el backend fue levantado por la ventana y no por un demonio, terminarlo limpio
            pass


if __name__ == "__main__":
    main()

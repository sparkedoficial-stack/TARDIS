#!/usr/bin/env python3
"""
tardis_desktop_companion.py - Asistente Flotante Soberano sobre el Sistema Operativo
====================================================================================
GODWORKS SYSTEM v26.4 · TARDIS Desktop Companion Overlay

Crea un widget nativo translúcido, sin bordes y siempre visible sobre TODO el
sistema operativo Linux (GTK3 + WebKit2 · Always-on-Top).
Permite arrastrar el personaje triangular a cualquier lugar del escritorio,
platicar por voz con el modelo local y pedirle que explique la pantalla.
====================================================================================
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, Gdk, WebKit2, GLib, GdkPixbuf

PORT = 8757
AUTH_TOKEN = os.environ.get("GIA_AUTH_TOKEN", "DiosDelTiempo01")
OVERLAY_URL = f"http://REDACTED_IP:{PORT}/companion?key={AUTH_TOKEN}"
FALLBACK_FILE = PROJECT_DIR / "companion_overlay.html"
ICON_PATH = PROJECT_DIR / "tardis-icon.png"


class TardisDesktopCompanion(Gtk.Window):
    """Ventana nativa flotante Always-on-Top translúcida sobre el SO."""

    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("TARDIS · Asistente Flotante")
        self.set_wmclass("tardis_companion", "TardisCompanion")
        
        # 1. Propiedades de widget flotante sobre el Sistema Operativo
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.stick()  # Visible en todos los escritorios virtuales

        # 2. Transparencia total RGBA
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        # 3. Dimensiones y posicionamiento en el escritorio
        self.set_default_size(360, 520)
        disp = Gdk.Display.get_default()
        if disp:
            monitor = disp.get_primary_monitor() or disp.get_monitor(0)
            if monitor:
                geo = monitor.get_geometry()
                target_x = max(20, geo.width - 380)
                target_y = max(20, geo.height - 560)
                self.move(target_x, target_y)

        # 4. Icono oficial
        if ICON_PATH.exists():
            try:
                self.set_icon_from_file(str(ICON_PATH))
            except Exception:
                pass

        # 5. Configurar WebKit2
        settings = WebKit2.Settings()
        settings.set_enable_javascript(True)
        settings.set_enable_webgl(True)
        settings.set_enable_media_stream(True)
        settings.set_enable_mediasource(True)
        settings.set_enable_smooth_scrolling(True)
        if hasattr(WebKit2, "HardwareAccelerationPolicy"):
            settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)

        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("windowDrag")
        ucm.register_script_message_handler("openMainApp")
        ucm.register_script_message_handler("closeCompanion")
        ucm.connect("script-message-received::windowDrag", self._on_window_drag)
        ucm.connect("script-message-received::openMainApp", self._on_open_main_app)
        ucm.connect("script-message-received::closeCompanion", lambda *_: self.hide())

        self.webview = WebKit2.WebView.new_with_user_content_manager(ucm)
        self.webview.set_settings(settings)
        
        # Fondo transparente en WebKit
        color = Gdk.RGBA()
        color.parse("rgba(0,0,0,0)")
        self.webview.set_background_color(color)

        self.add(self.webview)
        self.connect("destroy", Gtk.main_quit)

        # 6. Cargar interfaz del asistente
        self._load_companion_ui()

    def _load_companion_ui(self):
        import urllib.request
        backend_online = False
        try:
            with urllib.request.urlopen(f"http://REDACTED_IP:{PORT}/api/health", timeout=0.8) as resp:
                backend_online = (resp.status == 200)
        except Exception:
            backend_online = False

        if backend_online:
            print(f"🌌 [Tardis Companion] Conectando con servidor local: {OVERLAY_URL}")
            self.webview.load_uri(OVERLAY_URL)
        else:
            local_uri = FALLBACK_FILE.as_uri()
            print(f"🌌 [Tardis Companion] Cargando archivo local offline: {local_uri}")
            self.webview.load_uri(local_uri)

    def _on_window_drag(self, ucm, result):
        """Mueve la ventana nativa suavemente a través del escritorio."""
        try:
            val = result.get_js_value()
            dx = 0
            dy = 0
            if val and val.is_object():
                if val.has_property("dx"):
                    dx = int(val.get_property("dx").to_double())
                if val.has_property("dy"):
                    dy = int(val.get_property("dy").to_double())

            cur_x, cur_y = self.get_position()
            self.move(cur_x + dx, cur_y + dy)
        except Exception as e:
            # Fallback usando begin_move_drag si está disponible
            try:
                seat = Gdk.Display.get_default().get_default_seat()
                dev = seat.get_pointer()
                _, rx, ry = dev.get_position()
                self.begin_move_drag(1, rx, ry, Gtk.get_current_event_time())
            except Exception:
                pass

    def _on_open_main_app(self, *args):
        """Lanza o trae al frente la interfaz principal de TARDIS."""
        launcher_sh = PROJECT_DIR / "launch_tardis.sh"
        if launcher_sh.exists():
            subprocess.Popen([str(launcher_sh)], cwd=str(PROJECT_DIR))


def main():
    print("=" * 70)
    print("   TARDIS · ASISTENTE SOBERANO FLOTANTE SOBRE EL SISTEMA OPERATIVO   ")
    print("=" * 70)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = TardisDesktopCompanion()
    app.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()

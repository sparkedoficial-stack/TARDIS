#!/usr/bin/env python3
"""
tardis_safety_app.py - Aplicación de Escritorio Nativa para Rieles de Seguridad KAIJU
=====================================================================================
Wrapper GTK3 + WebKit2 para la consola local de control de rieles de seguridad
del motor TARDIS-NEURAL-SPACE-KAIJU (Directiva Omega, Constante Aegis, Denylist y Parámetros).
"""

import os
import signal
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ICON_PATH = BASE_DIR / "tardis-master-hub-icon.png"
if not ICON_PATH.exists():
    ICON_PATH = BASE_DIR / "tardis-icon.png"
DEFAULT_URL = "http://REDACTED_IP:8757/safety"


def launch_native_gtk(url: str):
    """Lanza la consola en una ventana nativa GTK3 con WebKit2."""
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import Gtk, Gdk, GdkPixbuf, WebKit2, GLib

    class SafetyRailsWindow(Gtk.Window):
        def __init__(self, target_url: str):
            super().__init__(title="TARDIS · Rieles de Seguridad KAIJU")
            self.set_default_size(1320, 880)
            self.set_position(Gtk.WindowPosition.CENTER)

            # Icono de la ventana
            if ICON_PATH.exists():
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(ICON_PATH), 128, 128, True)
                    self.set_icon(pixbuf)
                except Exception as e:
                    print(f"[Icon Error]: {e}", file=sys.stderr)

            # Configuración de WebKit2
            self.webview = WebKit2.WebView()
            settings = self.webview.get_settings()
            settings.set_enable_webgl(True)
            settings.set_enable_developer_extras(True)
            settings.set_enable_media_stream(True)
            settings.set_enable_smooth_scrolling(True)
            settings.set_javascript_can_access_clipboard(True)
            settings.set_enable_webaudio(True)
            settings.set_enable_accelerated_2d_canvas(True)

            context = WebKit2.WebContext.get_default()
            context.set_cache_model(WebKit2.CacheModel.DOCUMENT_BROWSER)

            dark_color = Gdk.RGBA()
            dark_color.parse("#030712")
            self.webview.set_background_color(dark_color)

            self.scrolled = Gtk.ScrolledWindow()
            self.scrolled.add(self.webview)
            self.add(self.scrolled)

            self.connect("key-press-event", self._on_key_press)
            self.connect("destroy", Gtk.main_quit)

            print(f"[TARDIS Safety Rails] Navegando a {target_url}...")
            self.webview.load_uri(target_url)

        def _on_key_press(self, widget, event):
            # F11: Alternar Pantalla Completa
            if event.keyval == Gdk.KEY_F11:
                if self.get_window().get_state() & Gdk.WindowState.FULLSCREEN:
                    self.unfullscreen()
                else:
                    self.fullscreen()
                return True
            # F5 o Ctrl+R: Recargar
            if event.keyval == Gdk.KEY_F5 or (event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_r):
                self.webview.reload()
                return True
            # Ctrl+Q: Cerrar
            if event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_q:
                self.close()
                return True
            return False

    GLib.set_prgname("tardis-safety-rails")
    GLib.set_application_name("TARDIS Safety Rails")

    win = SafetyRailsWindow(url)
    win.show_all()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    Gtk.main()


def launch_browser_fallback(url: str):
    """Fallback si GTK3/WebKit2 no se encuentra disponible."""
    import subprocess
    import shutil

    for chrome_bin in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser"]:
        found = shutil.which(chrome_bin) or (Path.home() / ".local/bin" / chrome_bin if (Path.home() / ".local/bin" / chrome_bin).exists() else None)
        if found:
            print(f"[Fallback] Iniciando mediante {found} en modo app...")
            subprocess.Popen([str(found), f"--app={url}", "--new-window"])
            return

    print("[Fallback] Abriendo navegador predeterminado del sistema...")
    import webbrowser
    webbrowser.open(url)


def main():
    target_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    try:
        launch_native_gtk(target_url)
    except Exception as e:
        print(f"[Native Launch Notice]: {e}. Activando modo aplicación web...", file=sys.stderr)
        launch_browser_fallback(target_url)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
TARDIS MASTER HUB - Aplicación de Escritorio Nativa
==================================================
Wrapper GTK3 + WebKit2 para la Cabina de Mando Soberana de GODWORKS SYSTEM / TARDIS.
Empaqueta todos los subsistemas (Chat, Clientes, Bóveda, Radar RF, HoloDeck 3D, Red/Hardware y Telemetría)
en una sola ventana nativa soberana.
"""

import sys
import os
import signal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ICON_PATH = BASE_DIR / "tardis-master-hub-icon.png"
DEFAULT_URL = "http://REDACTED_IP:8757/hub"


def launch_native_gtk(url: str):
    """Lanza la aplicación en una ventana nativa GTK3 con WebKit2."""
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import Gtk, Gdk, GdkPixbuf, WebKit2, GLib

    class MasterCockpitWindow(Gtk.Window):
        def __init__(self, target_url: str):
            super().__init__(title="TARDIS · Cabina de Mando Soberana")
            self.set_default_size(1440, 920)
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

            # Contexto y caché
            context = WebKit2.WebContext.get_default()
            context.set_cache_model(WebKit2.CacheModel.DOCUMENT_BROWSER)

            # Color de fondo oscuro acorde al tema TARDIS
            dark_color = Gdk.RGBA()
            dark_color.parse("#030712")
            self.webview.set_background_color(dark_color)

            # Contenedor con Scroll
            self.scrolled = Gtk.ScrolledWindow()
            self.scrolled.add(self.webview)
            self.add(self.scrolled)

            # Atajos de teclado
            self.connect("key-press-event", self._on_key_press)
            self.connect("destroy", Gtk.main_quit)

            # Carga de la URL
            print(f"[TARDIS Hub] Navegando a {target_url}...")
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

    # Configurar título del proceso
    GLib.set_prgname("tardis-master-hub")
    GLib.set_application_name("TARDIS Master Hub")

    win = MasterCockpitWindow(url)
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

    # Si no hay Chromium/Chrome, usar xdg-open / firefox
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

#!/usr/bin/env python3
"""
native_gui/gia_standalone_shell.py - Ventana Nativa Standalone para GODWORKS SYSTEM
===================================================================================
Abre la interfaz completa de GODWORKS SYSTEM (incluyendo Canvas 3D de Three.js y HUD visual)
en una ventana de escritorio 100% nativa utilizando WebKitGTK, sin abrir Chrome, Firefox
ni ningún navegador web del sistema.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2, GLib, GdkPixbuf


class GiaStandaloneWindow(Gtk.Window):
    def __init__(self, target_url: str = "http://REDACTED_IP:8757?key=DiosDelTiempo01"):
        super().__init__(title="GODWORKS · GIA NODO SOBERANO (VENTANA NATIVA)")
        self.set_default_size(1366, 860)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Icono de la ventana
        icon_path = PROJECT_DIR / "godworks-icon.png"
        if icon_path.exists():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(icon_path))
                self.set_icon(pixbuf)
            except Exception:
                pass

        # Configuración de WebKit2 nativo
        settings = WebKit2.Settings()
        settings.set_enable_javascript(True)
        settings.set_enable_webgl(True)
        settings.set_enable_media_stream(True)
        settings.set_enable_smooth_scrolling(True)
        settings.set_enable_developer_extras(True)

        user_content_mgr = WebKit2.UserContentManager()
        self.webview = WebKit2.WebView.new_with_user_content_manager(user_content_mgr)
        self.webview.set_settings(settings)

        # Contenedor con barra de desplazamiento
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.webview)
        self.add(scrolled)

        self.connect("destroy", Gtk.main_quit)

        # Cargar URL local
        print(f"[GIA Native Shell] Cargando interfaz nativa en: {target_url}")
        self.webview.load_uri(target_url)


def main():
    target_url = sys.argv[1] if len(sys.argv) > 1 else "http://REDACTED_IP:8757?key=DiosDelTiempo01"
    win = GiaStandaloneWindow(target_url=target_url)
    win.show_all()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    Gtk.main()


if __name__ == "__main__":
    main()

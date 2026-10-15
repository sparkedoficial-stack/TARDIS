"""
Aplicación Principal AirPlay Monitor (Adw.Application / Adw.ApplicationWindow)
"""
from __future__ import annotations

import os
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, Gio

from ..backend.config import ConfigManager
from ..backend.service import AirPlayServiceManager
from ..backend.log_monitor import AirPlayLogMonitor
from ..backend.usb_manager import AppleUsbManager

from .dashboard_page import DashboardPage
from .connections_page import ConnectionsPage
from .apple_devices_page import AppleDevicesPage
from .logs_page import LogsPage
from .settings_page import SettingsPage

APP_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = APP_DIR / "assets"
CSS_FILE = Path(__file__).resolve().parent / "style.css"


class AirPlayMonitorWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="AirPlay Monitor")
        self.set_default_size(960, 680)
        self.set_size_request(600, 500)

        # Iniciar módulos del backend
        self.config_manager = ConfigManager()
        self.service_manager = AirPlayServiceManager()
        self.log_monitor = AirPlayLogMonitor()
        self.usb_manager = AppleUsbManager()

        # Iniciar captura de logs en segundo plano
        self.log_monitor.start()

        # Configurar icono de ventana
        self._setup_icon()

        # Estructura de UI
        self._build_ui()

    def _setup_icon(self):
        icon_path = ASSETS_DIR / "icon_512.png"
        if icon_path.exists():
            self.set_icon_name("airplay-monitor")

    def _build_ui(self):
        # Toast Overlay para notificaciones flotantes
        self.toast_overlay = Adw.ToastOverlay()
        
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # -------------------------------------------------------------
        # HeaderBar con ViewSwitcher
        # -------------------------------------------------------------
        header = Adw.HeaderBar()
        header.set_centering_policy(Adw.CenteringPolicy.STRICT)

        # Botón de información en el lado izquierdo
        btn_about = Gtk.Button()
        btn_about.set_icon_name("help-about-symbolic")
        btn_about.set_tooltip_text("Acerca de AirPlay Monitor")
        btn_about.connect("clicked", self._on_about_clicked)
        header.pack_start(btn_about)

        # ViewStack para las 5 secciones
        self.stack = Adw.ViewStack()
        self.stack.set_vexpand(True)

        # ViewSwitcher en el centro del HeaderBar
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        # Botón Pantalla Completa en el lado derecho
        btn_fs = Gtk.Button()
        btn_fs.set_icon_name("view-fullscreen-symbolic")
        btn_fs.set_tooltip_text("Pantalla Completa")
        btn_fs.connect("clicked", self._toggle_fullscreen)
        header.pack_end(btn_fs)

        main_box.append(header)

        # -------------------------------------------------------------
        # Páginas en el ViewStack
        # -------------------------------------------------------------
        # 1. Panel Principal (Dashboard)
        self.page_dash = DashboardPage(
            service=self.service_manager,
            log_monitor=self.log_monitor,
            config=self.config_manager,
            show_toast_cb=self.show_toast
        )
        self.stack.add_titled_with_icon(
            self.page_dash,
            "dashboard",
            "Panel Principal",
            "video-display-symbolic"
        )

        # 2. Dispositivos en Red (mDNS)
        self.page_net = ConnectionsPage(show_toast_cb=self.show_toast)
        self.stack.add_titled_with_icon(
            self.page_net,
            "network",
            "Red & Dispositivos",
            "network-wireless-symbolic"
        )

        # 3. Dispositivos USB
        self.page_usb = AppleDevicesPage(
            usb_manager=self.usb_manager,
            show_toast_cb=self.show_toast
        )
        self.stack.add_titled_with_icon(
            self.page_usb,
            "usb",
            "Dispositivos USB",
            "phone-symbolic"
        )

        # 4. Registro en Vivo (Logs)
        self.page_logs = LogsPage(
            log_monitor=self.log_monitor,
            show_toast_cb=self.show_toast
        )
        self.stack.add_titled_with_icon(
            self.page_logs,
            "logs",
            "Registro en Vivo",
            "utilities-terminal-symbolic"
        )

        # 5. Ajustes y Configuración
        self.page_settings = SettingsPage(
            config=self.config_manager,
            service=self.service_manager,
            show_toast_cb=self.show_toast
        )
        self.stack.add_titled_with_icon(
            self.page_settings,
            "settings",
            "Configuración",
            "emblem-system-symbolic"
        )

        main_box.append(self.stack)

        self.toast_overlay.set_child(main_box)
        self.set_content(self.toast_overlay)

    def show_toast(self, message: str):
        toast = Adw.Toast.new(message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def _toggle_fullscreen(self, btn):
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()

    def _on_about_clicked(self, btn):
        about = Adw.AboutDialog()
        about.set_application_name("AirPlay Monitor Soberano")
        about.set_application_icon("airplay-monitor")
        about.set_version("1.0.0")
        about.set_developer_name("GODWORKS SYSTEM & TimeMachine")
        about.set_comments(
            "Sistema interactivo para la monitorización, telemetría y control "
            "del servidor de duplicación de pantalla AirPlay (iOS/macOS) en Linux."
        )
        about.set_website("https://github.com/FDH2/UxPlay")
        about.present(self)


class AirPlayMonitorApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="org.timemachine.AirPlayMonitor",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._load_css()

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = AirPlayMonitorWindow(self)
        win.present()

    def _load_css(self):
        if CSS_FILE.exists():
            provider = Gtk.CssProvider()
            provider.load_from_path(str(CSS_FILE))
            display = Gdk.Display.get_default()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )


def main():
    app = AirPlayMonitorApp()
    return app.run(None)

"""
Página de Dispositivos y Servicios en Red (mDNS Discovery)
Explora en vivo todos los dispositivos Apple y receptores/transmisores AirPlay.
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from ..backend.mdns_scanner import AppleNetworkScanner


class ConnectionsPage(Gtk.ScrolledWindow):
    def __init__(self, show_toast_cb=None):
        super().__init__()
        self.show_toast_cb = show_toast_cb
        self.set_vexpand(True)
        self.set_hexpand(True)

        self._build_ui()
        self.refresh_devices()

    def _build_ui(self):
        clamp = Adw.Clamp(maximum_size=900, tightening_threshold=650)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.box.set_margin_top(24)
        self.box.set_margin_bottom(24)
        self.box.set_margin_start(20)
        self.box.set_margin_end(20)

        # Barra superior con título y botón de escaneo
        header_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_hexpand(True)
        lbl_title = Gtk.Label(label="Explorador de Dispositivos Apple en Red", xalign=0)
        lbl_title.add_css_class("title-2")
        title_box.append(lbl_title)

        lbl_sub = Gtk.Label(label="Detecta en tiempo real servicios AirPlay, AirTunes y Apple CompanionLink", xalign=0)
        lbl_sub.add_css_class("dim-label")
        title_box.append(lbl_sub)
        header_bar.append(title_box)

        self.spinner = Gtk.Spinner()
        header_bar.append(self.spinner)

        self.btn_scan = Gtk.Button(label="Escanear Red")
        self.btn_scan.set_icon_name("system-search-symbolic")
        self.btn_scan.connect("clicked", lambda _: self.refresh_devices())
        header_bar.append(self.btn_scan)

        self.box.append(header_bar)

        # Grupo de Dispositivos Detectados
        self.devices_group = Adw.PreferencesGroup()
        self.devices_group.set_title("Dispositivos y Receptores Detectados")
        self.devices_group.set_description("Dispositivos activos anunciados mediante mDNS / DNS-SD:")
        self.box.append(self.devices_group)

        # Estado Vacío inicial
        self.empty_page = Adw.StatusPage()
        self.empty_page.set_icon_name("network-wireless-symbolic")
        self.empty_page.set_title("Buscando dispositivos...")
        self.empty_page.set_description("Haz clic en 'Escanear Red' para descubrir equipos Apple o receptores AirPlay en la subred.")
        self.box.append(self.empty_page)

        clamp.set_child(self.box)
        self.set_child(clamp)

    def refresh_devices(self):
        self.btn_scan.set_sensitive(False)
        self.spinner.start()

        def on_results(devices: list[dict]):
            GLib.idle_add(self._display_devices, devices)

        AppleNetworkScanner.scan_async(on_results)

    def _display_devices(self, devices: list[dict]):
        self.spinner.stop()
        self.btn_scan.set_sensitive(True)

        # Limpiar grupo anterior
        # Creamos un nuevo Adw.PreferencesGroup para reconstruir
        self.box.remove(self.devices_group)
        self.devices_group = Adw.PreferencesGroup()
        self.devices_group.set_title(f"Dispositivos y Receptores Detectados ({len(devices)})")
        self.devices_group.set_description("Dispositivos activos anunciados mediante mDNS / DNS-SD:")

        if not devices:
            self.empty_page.set_visible(True)
            self.empty_page.set_title("No se encontraron dispositivos externos")
            self.empty_page.set_description("Verifica que tus dispositivos Apple estén conectados a la misma red Wi-Fi o Hotspot.")
            self.box.append(self.devices_group)
            return

        self.empty_page.set_visible(False)

        for dev in devices:
            row = Adw.ActionRow()
            row.set_title(f"{dev['name']}")
            
            sub = f"IP: {dev['ip']}:{dev['port']}  ·  Servicio: {dev['service_type']}  ·  Modelo: {dev['model']}"
            row.set_subtitle(sub)

            # Icono según tipo
            icon_name = "network-wireless-symbolic"
            if "Audio" in dev["service_type"]:
                icon_name = "audio-volume-high-symbolic"
            elif "Companion" in dev["service_type"]:
                icon_name = "phone-symbolic"
            elif "Video" in dev["service_type"]:
                icon_name = "video-display-symbolic"

            prefix_icon = Gtk.Image.new_from_icon_name(icon_name)
            prefix_icon.set_pixel_size(24)
            row.add_prefix(prefix_icon)

            # Badges al final
            badges_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            badges_box.set_valign(Gtk.Align.CENTER)

            if dev["is_local_host"]:
                local_badge = Gtk.Label(label="Este Equipo")
                local_badge.add_css_class("status-badge-streaming")
                badges_box.append(local_badge)

            proto_badge = Gtk.Label(label=dev["protocol"])
            proto_badge.add_css_class("ip-chip")
            badges_box.append(proto_badge)

            if dev["lockdown_port"] == "ABIERTO":
                lock_badge = Gtk.Label(label="Lockdown: Abierto")
                lock_badge.add_css_class("status-badge-active")
                badges_box.append(lock_badge)

            row.add_suffix(badges_box)
            self.devices_group.add(row)

        self.box.append(self.devices_group)

        if self.show_toast_cb:
            self.show_toast_cb(f"Escaneo de red completado: {len(devices)} servicio(s) detectado(s).")

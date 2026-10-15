"""
Página de Dispositivos Apple Físicos (USB / Cable)
Integración nativa con usbmuxd, idevicepair, ideviceinfo e ifuse para almacenamiento.
"""
from __future__ import annotations

import threading
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from ..backend.usb_manager import AppleUsbManager


class AppleDevicesPage(Gtk.ScrolledWindow):
    def __init__(self, usb_manager: AppleUsbManager, show_toast_cb=None):
        super().__init__()
        self.usb = usb_manager
        self.show_toast_cb = show_toast_cb
        self.set_vexpand(True)
        self.set_hexpand(True)

        self._build_ui()
        self.refresh_usb()

    def _build_ui(self):
        clamp = Adw.Clamp(maximum_size=900, tightening_threshold=650)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.box.set_margin_top(24)
        self.box.set_margin_bottom(24)
        self.box.set_margin_start(20)
        self.box.set_margin_end(20)

        # Barra Superior
        header_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_hexpand(True)
        
        lbl_title = Gtk.Label(label="Control de Dispositivos iOS por Cable USB", xalign=0)
        lbl_title.add_css_class("title-2")
        title_box.append(lbl_title)

        lbl_sub = Gtk.Label(label="Protocolos usbmuxd, lockdown pairing y montaje de almacenamiento nativo", xalign=0)
        lbl_sub.add_css_class("dim-label")
        title_box.append(lbl_sub)
        header_bar.append(title_box)

        btn_refresh = Gtk.Button(label="Refrescar USB")
        btn_refresh.set_icon_name("view-refresh-symbolic")
        btn_refresh.connect("clicked", lambda _: self.refresh_usb())
        header_bar.append(btn_refresh)

        self.box.append(header_bar)

        # Tarjeta de Estado de Dispositivo USB
        self.device_group = Adw.PreferencesGroup()
        self.device_group.set_title("Dispositivo Físico Conectado")
        self.device_group.set_description("Información extraída del chip de seguridad de iOS:")
        self.box.append(self.device_group)

        # Fila de Nombre / Modelo
        self.row_device = Adw.ActionRow(title="Nombre del Dispositivo", subtitle="Buscando...")
        self.icon_device = Gtk.Image.new_from_icon_name("phone-symbolic")
        self.icon_device.set_pixel_size(24)
        self.row_device.add_prefix(self.icon_device)
        self.device_group.add(self.row_device)

        # Fila de Versión de iOS & Serie
        self.row_system = Adw.ActionRow(title="Sistema Operativo y Modelo", subtitle="-")
        self.row_system.add_prefix(Gtk.Image.new_from_icon_name("system-software-update-symbolic"))
        self.device_group.add(self.row_system)

        # Fila de Batería
        self.row_battery = Adw.ActionRow(title="Nivel de Batería", subtitle="Desconocido")
        self.icon_battery = Gtk.Image.new_from_icon_name("battery-symbolic")
        self.row_battery.add_prefix(self.icon_battery)
        self.device_group.add(self.row_battery)

        # Fila de Emparejamiento
        self.row_pair = Adw.ActionRow(title="Estado de Confianza (Lockdown)", subtitle="Sin verificar")
        self.row_pair.add_prefix(Gtk.Image.new_from_icon_name("channel-secure-symbolic"))
        
        self.btn_pair = Gtk.Button(label="Emparejar")
        self.btn_pair.set_valign(Gtk.Align.CENTER)
        self.btn_pair.connect("clicked", self._on_pair_clicked)
        self.row_pair.add_suffix(self.btn_pair)
        self.device_group.add(self.row_pair)

        # Grupo de Almacenamiento iOS
        storage_group = Adw.PreferencesGroup()
        storage_group.set_title("Explorador de Archivos iOS (ifuse)")
        storage_group.set_description("Accede a Fotos, Videos y Documentos de tu dispositivo como una unidad local:")

        self.row_storage = Adw.ActionRow(
            title="Punto de Montaje: ~/Dispositivos/Apple_iOS",
            subtitle="Estado: Desmontado"
        )
        self.row_storage.add_prefix(Gtk.Image.new_from_icon_name("drive-removable-media-symbolic"))

        storage_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        storage_btns.set_valign(Gtk.Align.CENTER)

        self.btn_mount = Gtk.Button(label="Montar y Abrir")
        self.btn_mount.add_css_class("suggested-action")
        self.btn_mount.connect("clicked", self._on_mount_clicked)
        storage_btns.append(self.btn_mount)

        self.btn_unmount = Gtk.Button(label="Desmontar")
        self.btn_unmount.connect("clicked", self._on_unmount_clicked)
        storage_btns.append(self.btn_unmount)

        self.row_storage.add_suffix(storage_btns)
        storage_group.add(self.row_storage)
        self.box.append(storage_group)

        # Tarjeta Informativa
        info_group = Adw.PreferencesGroup(title="Instrucciones para Conexión por Cable")
        tip_row = Adw.ActionRow(
            title="Conexión Directa USB",
            subtitle="1. Conecta el cable USB al equipo.\n2. Desbloquea la pantalla de tu iPhone/iPad.\n3. Si aparece '¿Confiar en este ordenador?', pulsa Confiar e introduce tu código PIN."
        )
        tip_row.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
        info_group.add(tip_row)
        self.box.append(info_group)

        clamp.set_child(self.box)
        self.set_child(clamp)

    def refresh_usb(self):
        def worker():
            usb_devs = self.usb.query_usb_devices()
            info = self.usb.get_device_info()
            mounted = self.usb.is_mounted()
            paired_udids = self.usb.get_paired_udids()
            GLib.idle_add(self._update_display, usb_devs, info, mounted, paired_udids)

        threading.Thread(target=worker, daemon=True).start()

    def _update_display(self, usb_devs: list[dict], info: dict, mounted: bool, paired_udids: list[str]):
        if usb_devs or info.get("connected"):
            name = info.get("name") or "Dispositivo iOS Detectado"
            model = info.get("model") or "Apple Device"
            ios = info.get("ios_version") or "iOS"
            serial = info.get("serial") or "-"
            udid = info.get("udid") or "-"

            self.row_device.set_title(name)
            self.row_device.set_subtitle(f"Modelo: {model}  ·  UDID: {udid[:12]}...")

            self.row_system.set_title(f"Sistema: {ios}")
            self.row_system.set_subtitle(f"Número de Serie: {serial}")

            bat = info.get("battery_percent")
            charging = info.get("battery_charging")
            if bat is not None:
                chg_str = " (Cargando ⚡)" if charging else ""
                self.row_battery.set_subtitle(f"{bat}%{chg_str}")
            else:
                self.row_battery.set_subtitle("Información de batería protegida o no disponible")

            is_paired = udid in paired_udids or len(paired_udids) > 0
            if is_paired:
                self.row_pair.set_subtitle("Dispositivo Emparejado y de Confianza ✅")
                self.btn_pair.set_label("Re-verificar")
            else:
                self.row_pair.set_subtitle("Pendiente de Emparejar / Autorizar ⚠️")
                self.btn_pair.set_label("Emparejar Ahora")
        else:
            self.row_device.set_title("No hay dispositivo Apple conectado por USB")
            self.row_device.set_subtitle("Conecta tu iPhone o iPad mediante cable Lightning o USB-C")
            self.row_system.set_title("Sistema Operativo")
            self.row_system.set_subtitle("Esperando conexión...")
            self.row_battery.set_subtitle("Desconectado")
            self.row_pair.set_subtitle("Sin conexión física activa")

        # Actualizar montaje
        if mounted:
            self.row_storage.set_subtitle("Estado: Montado en ~/Dispositivos/Apple_iOS (Activo)")
            self.btn_mount.set_sensitive(False)
            self.btn_unmount.set_sensitive(True)
        else:
            self.row_storage.set_subtitle("Estado: Desmontado")
            self.btn_mount.set_sensitive(True)
            self.btn_unmount.set_sensitive(False)

    def _on_pair_clicked(self, btn):
        btn.set_sensitive(False)
        def worker():
            ok, msg = self.usb.pair_device()
            def finish():
                if self.show_toast_cb:
                    self.show_toast_cb(msg)
                btn.set_sensitive(True)
                self.refresh_usb()
            GLib.idle_add(finish)
        threading.Thread(target=worker, daemon=True).start()

    def _on_mount_clicked(self, btn):
        btn.set_sensitive(False)
        def worker():
            ok, msg = self.usb.mount_storage()
            def finish():
                if self.show_toast_cb:
                    self.show_toast_cb(msg)
                btn.set_sensitive(True)
                self.refresh_usb()
            GLib.idle_add(finish)
        threading.Thread(target=worker, daemon=True).start()

    def _on_unmount_clicked(self, btn):
        btn.set_sensitive(False)
        def worker():
            ok, msg = self.usb.unmount_storage()
            def finish():
                if self.show_toast_cb:
                    self.show_toast_cb(msg)
                btn.set_sensitive(True)
                self.refresh_usb()
            GLib.idle_add(finish)
        threading.Thread(target=worker, daemon=True).start()

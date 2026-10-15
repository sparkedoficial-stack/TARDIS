"""
Página Principal del Panel de Control (Dashboard)
Muestra el estado en vivo del servidor AirPlay, cliente conectado y controles inmediatos.
"""
from __future__ import annotations

import subprocess
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from ..backend.service import AirPlayServiceManager
from ..backend.log_monitor import AirPlayLogMonitor
from ..backend.config import ConfigManager


class DashboardPage(Gtk.ScrolledWindow):
    def __init__(
        self,
        service: AirPlayServiceManager,
        log_monitor: AirPlayLogMonitor,
        config: ConfigManager,
        show_toast_cb=None
    ):
        super().__init__()
        self.service = service
        self.log_monitor = log_monitor
        self.config = config
        self.show_toast_cb = show_toast_cb
        self._updating_switch = False

        self.set_vexpand(True)
        self.set_hexpand(True)

        self._build_ui()
        self.update_status()

        # Registrar callback de eventos de conexión en tiempo real
        self.log_monitor.add_connection_callback(self._on_connection_event)

        # Sondeo suave de estado cada 3 segundos
        GLib.timeout_add_seconds(3, self._poll_status)

    def _build_ui(self):
        clamp = Adw.Clamp(maximum_size=900, tightening_threshold=650)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # -------------------------------------------------------------
        # 1. TARJETA HERO: ESTADO DEL SERVIDOR AIRPLAY
        # -------------------------------------------------------------
        hero_frame = Gtk.Frame()
        hero_frame.add_css_class("hero-card")
        hero_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)

        # Fila Superior: Icono, Nombre del Servidor y Switch ON/OFF
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        
        icon = Gtk.Image.new_from_icon_name("video-display-symbolic")
        icon.set_pixel_size(44)
        top_row.append(icon)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_hexpand(True)
        
        self.lbl_server_name = Gtk.Label(label="TimeMachine-AirPlay", xalign=0)
        self.lbl_server_name.add_css_class("title-1")
        title_box.append(self.lbl_server_name)

        self.lbl_server_sub = Gtk.Label(label="Receptor Soberano AirPlay 2 / RAOP", xalign=0)
        self.lbl_server_sub.add_css_class("dim-label")
        title_box.append(self.lbl_server_sub)
        top_row.append(title_box)

        # Badge de Estado (Activo / Inactivo)
        self.lbl_status_badge = Gtk.Label(label="Activo")
        self.lbl_status_badge.add_css_class("status-badge-active")
        top_row.append(self.lbl_status_badge)

        # Badge de FPS Dinámico
        self.lbl_fps_badge = Gtk.Label(label="⚡ 144 FPS Dinámico")
        self.lbl_fps_badge.add_css_class("status-badge-streaming")
        top_row.append(self.lbl_fps_badge)

        # Badge de Pantalla Completa
        self.lbl_fs_badge = Gtk.Label(label="📺 Pantalla Completa")
        self.lbl_fs_badge.add_css_class("status-badge-purple")
        top_row.append(self.lbl_fs_badge)

        # Switch Principal ON/OFF
        self.switch_power = Gtk.Switch()
        self.switch_power.set_valign(Gtk.Align.CENTER)
        self.switch_power.connect("notify::active", self._on_switch_toggled)
        top_row.append(self.switch_power)

        hero_box.append(top_row)

        # Separador fino
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        hero_box.append(sep)

        # Información de Red y Telemetría
        meta_grid = Gtk.Grid()
        meta_grid.set_column_spacing(24)
        meta_grid.set_row_spacing(10)

        # Columna 1: IPs de Red
        lbl_ip_title = Gtk.Label(label="Direcciones de Red mDNS:", xalign=0)
        lbl_ip_title.add_css_class("dim-label")
        meta_grid.attach(lbl_ip_title, 0, 0, 1, 1)

        self.ips_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        meta_grid.attach(self.ips_container, 0, 1, 1, 1)

        # Columna 2: Telemetría de recursos
        lbl_res_title = Gtk.Label(label="Recursos en Ejecución:", xalign=0)
        lbl_res_title.add_css_class("dim-label")
        meta_grid.attach(lbl_res_title, 1, 0, 1, 1)

        self.lbl_telemetry = Gtk.Label(label="PID: - | RAM: - | CPU: -", xalign=0)
        meta_grid.attach(self.lbl_telemetry, 1, 1, 1, 1)

        hero_box.append(meta_grid)

        # Botones de Acciones Inmediatas
        btn_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_bar.set_margin_top(6)

        self.btn_fs_toggle = Gtk.Button(label="Alternar Pantalla Completa")
        self.btn_fs_toggle.set_icon_name("view-fullscreen-symbolic")
        self.btn_fs_toggle.connect("clicked", self._on_toggle_fs_clicked)
        btn_bar.append(self.btn_fs_toggle)

        btn_restart = Gtk.Button(label="Reiniciar Receptor")
        btn_restart.set_icon_name("view-refresh-symbolic")
        btn_restart.connect("clicked", self._on_restart_clicked)
        btn_bar.append(btn_restart)

        btn_avahi = Gtk.Button(label="Verificar mDNS")
        btn_avahi.set_icon_name("network-wireless-symbolic")
        btn_avahi.connect("clicked", self._on_check_mdns_clicked)
        btn_bar.append(btn_avahi)

        hero_box.append(btn_bar)
        hero_frame.set_child(hero_box)
        box.append(hero_frame)

        # -------------------------------------------------------------
        # 2. TARJETA DE CLIENTE CONECTADO EN DIRECTO
        # -------------------------------------------------------------
        self.client_frame = Gtk.Frame()
        self.client_frame.add_css_class("device-card-idle")
        
        self.client_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        
        self.client_icon = Gtk.Image.new_from_icon_name("tablet-symbolic")
        self.client_icon.set_pixel_size(48)
        self.client_box.append(self.client_icon)

        client_text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        client_text_box.set_hexpand(True)

        self.lbl_client_title = Gtk.Label(label="Esperando conexión AirPlay...", xalign=0)
        self.lbl_client_title.add_css_class("title-3")
        client_text_box.append(self.lbl_client_title)

        self.lbl_client_details = Gtk.Label(
            label="Inicia 'Duplicar pantalla' en tu iPhone, iPad o Mac para comenzar.",
            xalign=0
        )
        self.lbl_client_details.add_css_class("dim-label")
        client_text_box.append(self.lbl_client_details)

        self.client_box.append(client_text_box)

        self.lbl_client_badge = Gtk.Label(label="En espera")
        self.lbl_client_badge.add_css_class("status-badge-inactive")
        self.lbl_client_badge.set_valign(Gtk.Align.CENTER)
        self.client_box.append(self.lbl_client_badge)

        self.client_frame.set_child(self.client_box)
        box.append(self.client_frame)

        # -------------------------------------------------------------
        # 3. GUÍA RÁPIDA DE CONEXIÓN Y MODOS DE USO
        # -------------------------------------------------------------
        guide_group = Adw.PreferencesGroup(
            title="¿Cómo duplicar pantalla o transmitir video desde tu iPhone o iPad?",
            description="Aprovecha la pantalla completa, rotación dinámica y el modo monitor receptor:"
        )

        row1 = Adw.ActionRow(
            title="1. Conexión a la Misma Red",
            subtitle="Asegúrate de que tu iPhone/iPad esté en la misma red Wi-Fi o Hotspot que TimeMachine."
        )
        row1.add_prefix(self._create_step_badge("1"))
        guide_group.add(row1)

        row2 = Adw.ActionRow(
            title="2. Duplicar Pantalla (Mirroring) con Adaptación Dinámica",
            subtitle="Abre el Centro de Control de iOS > 'Duplicar pantalla' > selecciona 'TimeMachine-AirPlay'. Al girar el dispositivo entre vertical y horizontal, la imagen se adapta automáticamente."
        )
        row2.add_prefix(self._create_step_badge("2"))
        guide_group.add(row2)

        row3 = Adw.ActionRow(
            title="3. Modo Monitor Receptor de Video Directo (AirPlay Cast / HLS 4K HDR)",
            subtitle="En YouTube, Safari o Fotos, pulsa el icono AirPlay dentro del reproductor. El video se reproducirá directamente a pantalla completa en calidad nativa hasta 4K HDR decodificado por GPU NVIDIA NVDEC."
        )
        row3.add_prefix(self._create_step_badge("3"))
        guide_group.add(row3)

        row4 = Adw.ActionRow(
            title="4. Controles y Atajos de Pantalla Completa",
            subtitle="Usa el botón 'Alternar Pantalla Completa' de este panel, o presiona F11 / Alt+Enter sobre la ventana para alternar entre pantalla completa y ventana."
        )
        row4.add_prefix(Gtk.Image.new_from_icon_name("view-fullscreen-symbolic"))
        guide_group.add(row4)

        box.append(guide_group)

        clamp.set_child(box)
        self.set_child(clamp)

    def _create_step_badge(self, number: str) -> Gtk.Widget:
        lbl = Gtk.Label(label=number)
        lbl.add_css_class("guide-step-number")
        return lbl

    def _poll_status(self) -> bool:
        self.update_status()
        return True

    def update_status(self):
        """Actualiza la telemetría del servidor y los clientes."""
        details = self.service.get_status_details()
        is_active = details.get("active", False)

        # Actualizar nombre del servidor
        cfg_name = self.config.config.get("server_name", "TimeMachine-AirPlay")
        self.lbl_server_name.set_label(cfg_name)

        # Actualizar Switch
        self._updating_switch = True
        self.switch_power.set_active(is_active)
        self._updating_switch = False

        # Actualizar Badge de Estado
        if is_active:
            self.lbl_status_badge.set_label("Activo (En línea)")
            self.lbl_status_badge.remove_css_class("status-badge-inactive")
            self.lbl_status_badge.add_css_class("status-badge-active")
        else:
            self.lbl_status_badge.set_label("Detenido")
            self.lbl_status_badge.remove_css_class("status-badge-active")
            self.lbl_status_badge.add_css_class("status-badge-inactive")

        # Actualizar Badge y Botón de Pantalla Completa
        is_fs = self.config.config.get("fullscreen", True)
        if is_fs:
            self.lbl_fs_badge.set_label("📺 Pantalla Completa")
            self.btn_fs_toggle.set_label("Modo Ventana")
            self.btn_fs_toggle.set_icon_name("view-restore-symbolic")
        else:
            self.lbl_fs_badge.set_label("🪟 Modo Ventana")
            self.btn_fs_toggle.set_label("Pantalla Completa")
            self.btn_fs_toggle.set_icon_name("view-fullscreen-symbolic")

        # Actualizar IPs
        while child := self.ips_container.get_first_child():
            self.ips_container.remove(child)

        ips = details.get("network_ips", [])
        if ips:
            for item in ips:
                chip = Gtk.Label(label=f"{item['type']}: {item['ip']}:36443")
                chip.add_css_class("ip-chip")
                self.ips_container.append(chip)
        else:
            none_lbl = Gtk.Label(label="Sin interfaz de red detectada", xalign=0)
            self.ips_container.append(none_lbl)

        # Telemetría de recursos
        pid = details.get("pid", "-")
        mem = details.get("memory", "0 MB")
        cpu = details.get("cpu", "0s")
        self.lbl_telemetry.set_label(f"PID: {pid}  |  RAM: {mem}  |  CPU: {cpu}")

        # Cliente activo
        active_client = self.log_monitor.get_active_client()
        self._render_active_client(active_client)

    def _render_active_client(self, client: dict | None):
        if client:
            self.client_frame.remove_css_class("device-card-idle")
            self.client_frame.add_css_class("device-card-connected")

            self.client_icon.set_from_icon_name("video-display-symbolic")
            self.lbl_client_title.set_label(f"📲 {client.get('name', 'Dispositivo Apple')}")
            
            model = client.get("model", "Apple")
            mode = client.get("mode", "Mirroring Activo")
            ip = client.get("ip", "")
            time_str = client.get("connected_at", "")
            
            source_res = client.get("source_res")
            orientation = client.get("orientation")
            live_fps = client.get("live_fps") or "Hasta 144 FPS Dinámico (ProMotion)"
            res_str = f"  ·  Output Crudo: {source_res}" if source_res else ""
            orient_str = f"  ·  {orientation}" if orientation else ""

            sub_text = f"Modelo: {model}  ·  Modo: {mode}{res_str}{orient_str}\nFrecuencia: {live_fps}  ·  IP: {ip}  ·  Hora: {time_str}"
            self.lbl_client_details.set_label(sub_text)

            is_hls = "🎬" in mode or "HLS" in mode
            if is_hls:
                self.lbl_client_badge.set_label("🎬 Video Directo (HLS)")
                self.lbl_client_badge.remove_css_class("status-badge-inactive")
                self.lbl_client_badge.remove_css_class("status-badge-streaming")
                self.lbl_client_badge.add_css_class("status-badge-purple")
            else:
                self.lbl_client_badge.set_label("Transmisión Activa")
                self.lbl_client_badge.remove_css_class("status-badge-inactive")
                self.lbl_client_badge.remove_css_class("status-badge-purple")
                self.lbl_client_badge.add_css_class("status-badge-streaming")
        else:
            self.client_frame.remove_css_class("device-card-connected")
            self.client_frame.add_css_class("device-card-idle")

            self.client_icon.set_from_icon_name("tablet-symbolic")
            self.lbl_client_title.set_label("Esperando conexión AirPlay...")
            self.lbl_client_details.set_label("Inicia 'Duplicar pantalla' en tu iPhone, iPad o Mac para comenzar.")

            self.lbl_client_badge.set_label("En espera")
            self.lbl_client_badge.remove_css_class("status-badge-streaming")
            self.lbl_client_badge.add_css_class("status-badge-inactive")

    def _on_connection_event(self, client: dict | None):
        GLib.idle_add(self._render_active_client, client)

    def _on_switch_toggled(self, switch, gparam):
        if self._updating_switch:
            return
        active = switch.get_active()
        if active:
            ok, msg = self.service.start()
        else:
            ok, msg = self.service.stop()

        if self.show_toast_cb:
            self.show_toast_cb(msg)
        self.update_status()

    def _on_restart_clicked(self, btn):
        btn.set_sensitive(False)
        ok, msg = self.service.restart()
        if self.show_toast_cb:
            self.show_toast_cb(msg)
        self.update_status()
        btn.set_sensitive(True)

    def _on_check_mdns_clicked(self, btn):
        res = subprocess.run(["avahi-browse", "-r", "-t", "-p", "_airplay._tcp"], capture_output=True, text=True)
        if "TimeMachine" in res.stdout:
            msg = "✅ Servicio AirPlay anunciado correctamente en la red mDNS."
        else:
            msg = "⚠️ Anuncio mDNS no detectado. Reiniciando avahi-daemon..."
            subprocess.run(["systemctl", "restart", "avahi-daemon"], capture_output=True)
        if self.show_toast_cb:
            self.show_toast_cb(msg)

    def _on_toggle_fs_clicked(self, btn):
        btn.set_sensitive(False)
        curr_fs = self.config.config.get("fullscreen", True)
        new_fs = not curr_fs
        self.config.save({"fullscreen": new_fs})

        if self.service.is_active():
            ok, _ = self.service.restart()
            msg = "📺 Modo Pantalla Completa activado por defecto." if new_fs else "🪟 Modo Ventana activado."
        else:
            msg = "📺 Modo Pantalla Completa activado para la próxima sesión." if new_fs else "🪟 Modo Ventana activado."

        if self.show_toast_cb:
            self.show_toast_cb(msg)
        self.update_status()
        btn.set_sensitive(True)

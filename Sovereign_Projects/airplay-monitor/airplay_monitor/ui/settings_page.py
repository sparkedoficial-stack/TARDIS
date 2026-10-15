"""
Página de Ajustes y Configuración del Servidor AirPlay
Edita opciones de red, decodificación por hardware (NVIDIA NVDEC), calidad cruda y latencia.
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from ..backend.config import ConfigManager
from ..backend.service import AirPlayServiceManager


class SettingsPage(Adw.PreferencesPage):
    def __init__(self, config: ConfigManager, service: AirPlayServiceManager, show_toast_cb=None):
        super().__init__()
        self.config = config
        self.service = service
        self.show_toast_cb = show_toast_cb

        self._build_ui()
        self._load_values()

    def _build_ui(self):
        # -------------------------------------------------------------
        # 1. CALIDAD DE IMAGEN Y RESOLUCIÓN CRUDA
        # -------------------------------------------------------------
        perf_group = Adw.PreferencesGroup()
        perf_group.set_title("Calidad de Imagen y Rendimiento")
        perf_group.set_description("Configuración por defecto para obtener el output crudo nativo del dispositivo:")

        # Resolución y Tasa de Refresco
        self.res_options = [
            ("2560x1440@144", "2K QHD @ 144 FPS Dinámico (Nativo Monitor 144Hz - Recomendado)"),
            ("3840x2160@144", "4K UHD @ 144 FPS Dinámico (Máxima Fidelidad Retina)"),
            ("1920x1080@144", "1080p Full HD @ 144 FPS Dinámico"),
            ("2560x1440@60", "2K QHD @ 60 FPS"),
            ("1920x1080@60", "1080p Full HD @ 60 FPS"),
            ("default", "Automática del Dispositivo"),
        ]
        res_model = Gtk.StringList.new([opt[1] for opt in self.res_options])
        self.row_res = Adw.ComboRow(title="Resolución y Frecuencia Solicitada", model=res_model)
        perf_group.add(self.row_res)

        # FPS Dinámico
        self.row_dynamic_fps = Adw.SwitchRow(
            title="Tasa de Cuadros Dinámica hasta 144 FPS",
            subtitle="Permite streaming adaptativo hasta 144 FPS (ProMotion / Variable Refresh)"
        )
        perf_group.add(self.row_dynamic_fps)

        # Códec H.265 / HEVC y 4K HDR
        self.row_h265 = Adw.SwitchRow(
            title="Soporte Códec H.265 / HEVC y 4K HDR",
            subtitle="Habilita recepción de flujos 4K UHD y HDR (High Dynamic Range 10-bit) vía aceleración por GPU NVDEC"
        )
        perf_group.add(self.row_h265)

        # Rango sRGB Completo
        self.row_srgb = Adw.SwitchRow(
            title="Rango Dinámico Completo sRGB [0-255]",
            subtitle="Mantiene negros puros y blancos sin compresión a niveles de video [16-235]"
        )
        perf_group.add(self.row_srgb)

        self.add(perf_group)

        # -------------------------------------------------------------
        # 2. ULTRA-BAJA LATENCIA Y MOTOR DE RENDERIZADO
        # -------------------------------------------------------------
        latency_group = Adw.PreferencesGroup()
        latency_group.set_title("Optimización de Ultra-Baja Latencia")
        latency_group.set_description("Elimina retardos de búfer y activa aceleración por GPU:")

        # Modo Ultra-Baja Latencia (vsync no)
        self.row_low_latency = Adw.SwitchRow(
            title="Modo Tiempo Real (Ultra-Baja Latencia)",
            subtitle="Desactiva el búfer de retardo por timestamp (vsync no) para respuesta inmediata"
        )
        latency_group.add(self.row_low_latency)

        # Decodificador por Hardware (NVIDIA RTX 3050 NVDEC)
        self.dec_options = [
            ("nvh264dec", "NVIDIA NVDEC Hardware (GeForce RTX 3050 - Recomendado)"),
            ("decodebin", "GStreamer Automático (decodebin)"),
            ("vaapih264dec", "VA-API Hardware (vaapih264dec)"),
            ("avdec_h264", "Software CPU (avdec_h264)"),
        ]
        dec_model = Gtk.StringList.new([opt[1] for opt in self.dec_options])
        self.row_decoder = Adw.ComboRow(title="Decodificador de Video", model=dec_model)
        latency_group.add(self.row_decoder)

        # Sink de Video
        self.sink_options = [
            ("waylandsink", "Wayland Nativo (waylandsink - Renderizado Directo a GPU)"),
            ("autovideosink", "Automático (autovideosink)"),
            ("gtksink", "GTK Sink (gtksink)"),
            ("ximagesink", "X11 Image Sink (ximagesink)"),
            ("vaapisink", "VAAPI Video Sink (vaapisink)"),
        ]
        sink_model = Gtk.StringList.new([opt[1] for opt in self.sink_options])
        self.row_sink = Adw.ComboRow(title="Motor de Salida (Video Sink)", model=sink_model)
        latency_group.add(self.row_sink)

        # Latencia reportada a iOS
        self.row_audio_latency = Adw.SpinRow.new_with_range(0.01, 0.50, 0.01)
        self.row_audio_latency.set_title("Latencia de Búfer Cliente iOS (segundos)")
        self.row_audio_latency.set_subtitle("Valores bajos (0.02 - 0.05s) obligan a iOS a enviar paquetes sin esperar búfer")
        latency_group.add(self.row_audio_latency)

        self.add(latency_group)

        # -------------------------------------------------------------
        # 3. PANTALLA COMPLETA, ORIENTACIÓN Y MODO MONITOR HLS
        # -------------------------------------------------------------
        display_group = Adw.PreferencesGroup()
        display_group.set_title("Pantalla Completa y Modo Receptor de Video")
        display_group.set_description("Comportamiento visual inmersivo como pantalla y monitor receptor:")

        # Pantalla Completa
        self.row_fullscreen = Adw.SwitchRow(
            title="Modo Pantalla Completa por Defecto (Fullscreen)",
            subtitle="Ocupa todo el monitor automáticamente al iniciar la transmisión"
        )
        display_group.add(self.row_fullscreen)

        # Rotación Dinámica
        self.row_auto_orientation = Adw.SwitchRow(
            title="Adaptación Dinámica Horizontal / Vertical",
            subtitle="Ajusta dinámicamente entre formato vertical (retrato) y panorámico (16:9) al girar el dispositivo"
        )
        display_group.add(self.row_auto_orientation)

        # Modo Monitor Receptor de Video Directo (HLS)
        self.row_hls = Adw.SwitchRow(
            title="Modo Monitor Receptor de Video Directo (AirPlay HLS / Cast)",
            subtitle="Permite enviar videos a pantalla completa desde YouTube, Safari o Fotos en calidad nativa (hasta 4K HDR) como un Smart TV"
        )
        display_group.add(self.row_hls)

        # Versión de Motor HLS
        self.hls_options = [
            ("3", "GStreamer Playbin 3 (Pipeline Moderno - Recomendado)"),
            ("2", "GStreamer Playbin 2 (Compatibilidad Clásica)"),
        ]
        hls_model = Gtk.StringList.new([opt[1] for opt in self.hls_options])
        self.row_hls_ver = Adw.ComboRow(title="Motor de Reproducción HLS", model=hls_model)
        display_group.add(self.row_hls_ver)

        self.add(display_group)

        # -------------------------------------------------------------
        # 3. IDENTIDAD Y SISTEMA
        # -------------------------------------------------------------
        sys_group = Adw.PreferencesGroup()
        sys_group.set_title("Identidad y Arranque")

        self.row_name = Adw.EntryRow(title="Nombre del Servidor AirPlay")
        sys_group.add(self.row_name)

        self.row_pin = Adw.EntryRow(title="Código PIN Opcional (4 dígitos)")
        self.row_pin.set_show_apply_button(False)
        sys_group.add(self.row_pin)

        self.row_autostart = Adw.SwitchRow(
            title="Iniciar con el Sistema",
            subtitle="Ejecuta el receptor AirPlay en segundo plano al encender el equipo"
        )
        sys_group.add(self.row_autostart)

        self.add(sys_group)

        # -------------------------------------------------------------
        # 4. BOTÓN GUARDAR Y APLICAR
        # -------------------------------------------------------------
        action_group = Adw.PreferencesGroup()
        btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        btn_box.set_margin_top(12)
        btn_box.set_margin_bottom(24)

        self.btn_save = Gtk.Button(label="Guardar y Aplicar Ajustes de Máximo Rendimiento")
        self.btn_save.add_css_class("suggested-action")
        self.btn_save.add_css_class("pill")
        self.btn_save.set_size_request(320, 48)
        self.btn_save.set_halign(Gtk.Align.CENTER)
        self.btn_save.connect("clicked", self._on_save_clicked)
        btn_box.append(self.btn_save)

        action_group.add(btn_box)
        self.add(action_group)

    def _load_values(self):
        cfg = self.config.config

        # Nombre y PIN
        self.row_name.set_text(cfg.get("server_name", "TimeMachine-AirPlay"))
        self.row_pin.set_text(cfg.get("pin_code", ""))

        # Resolución
        current_res = cfg.get("resolution", "3840x2160@60")
        for i, (k, _) in enumerate(self.res_options):
            if k == current_res:
                self.row_res.set_selected(i)
                break

        # Video Decoder
        current_dec = cfg.get("video_decoder", "nvh264dec")
        for i, (k, _) in enumerate(self.dec_options):
            if k == current_dec:
                self.row_decoder.set_selected(i)
                break

        # Video Sink
        current_sink = cfg.get("video_sink", "waylandsink")
        for i, (k, _) in enumerate(self.sink_options):
            if k == current_sink:
                self.row_sink.set_selected(i)
                break

        # Switches
        self.row_dynamic_fps.set_active(cfg.get("dynamic_fps", True))
        self.row_h265.set_active(cfg.get("h265", True))
        self.row_srgb.set_active(cfg.get("srgb", True))
        self.row_low_latency.set_active(cfg.get("low_latency", True))
        self.row_fullscreen.set_active(cfg.get("fullscreen", True))
        self.row_auto_orientation.set_active(cfg.get("auto_orientation", True))
        self.row_hls.set_active(cfg.get("hls", True))

        current_hls_v = str(cfg.get("hls_version", "3"))
        for i, (k, _) in enumerate(self.hls_options):
            if k == current_hls_v:
                self.row_hls_ver.set_selected(i)
                break

        # Audio latency spin
        self.row_audio_latency.set_value(cfg.get("audio_latency", 0.05))

        # Autostart
        self.row_autostart.set_active(self.service.is_autostart_enabled())

    def _on_save_clicked(self, btn):
        btn.set_sensitive(False)

        server_name = self.row_name.get_text().strip() or "TimeMachine-AirPlay"
        pin_code = self.row_pin.get_text().strip()

        res_idx = self.row_res.get_selected()
        resolution = self.res_options[res_idx][0]

        dec_idx = self.row_decoder.get_selected()
        video_decoder = self.dec_options[dec_idx][0]

        sink_idx = self.row_sink.get_selected()
        video_sink = self.sink_options[sink_idx][0]

        dynamic_fps = self.row_dynamic_fps.get_active()
        h265 = self.row_h265.get_active()
        srgb = self.row_srgb.get_active()
        low_latency = self.row_low_latency.get_active()
        audio_latency = round(self.row_audio_latency.get_value(), 2)
        fullscreen = self.row_fullscreen.get_active()
        auto_orientation = self.row_auto_orientation.get_active()
        hls = self.row_hls.get_active()
        hls_idx = self.row_hls_ver.get_selected()
        hls_version = self.hls_options[hls_idx][0]
        autostart = self.row_autostart.get_active()

        fps_val = "144" if dynamic_fps else "60"

        new_cfg = {
            "server_name": server_name,
            "video_decoder": video_decoder,
            "video_sink": video_sink,
            "resolution": resolution,
            "fps": fps_val,
            "dynamic_fps": dynamic_fps,
            "fps_data": True,
            "h265": h265,
            "srgb": srgb,
            "low_latency": low_latency,
            "audio_latency": audio_latency,
            "fullscreen": fullscreen,
            "auto_orientation": auto_orientation,
            "hls": hls,
            "hls_version": hls_version,
            "pin_code": pin_code,
            "autostart": autostart
        }
        self.config.save(new_cfg)

        self.service.set_autostart(autostart)

        if self.service.is_active():
            self.service.restart()
            msg = "⚡ Configuración de pantalla completa, HLS y ultra-rendimiento aplicada con éxito."
        else:
            msg = "✅ Ajustes guardados correctamente."

        if self.show_toast_cb:
            self.show_toast_cb(msg)

        btn.set_sensitive(True)

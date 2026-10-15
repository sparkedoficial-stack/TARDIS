"""
Página de Registro y Telemetría en Tiempo Real (Live Logs)
Muestra la salida continua de UxPlay y eventos del protocolo AirPlay.
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gdk

from ..backend.log_monitor import AirPlayLogMonitor


class LogsPage(Gtk.Box):
    def __init__(self, log_monitor: AirPlayLogMonitor, show_toast_cb=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.log_monitor = log_monitor
        self.show_toast_cb = show_toast_cb
        self.auto_scroll = True
        self.filter_text = ""

        self.set_margin_top(16)
        self.set_margin_bottom(16)
        self.set_margin_start(16)
        self.set_margin_end(16)

        self._build_ui()
        self._load_existing_logs()

        # Conectar callback en vivo
        self.log_monitor.add_log_callback(self._on_new_log)

    def _build_ui(self):
        # Barra de herramientas superior
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        # Campo de búsqueda / filtro
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Filtrar registros (ej: iPad, connect, error)...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_filter_changed)
        toolbar.append(self.search_entry)

        # Toggle de Auto-Scroll
        self.btn_autoscroll = Gtk.ToggleButton(label="Auto-Scroll")
        self.btn_autoscroll.set_active(True)
        self.btn_autoscroll.set_icon_name("go-bottom-symbolic")
        self.btn_autoscroll.connect("toggled", self._on_autoscroll_toggled)
        toolbar.append(self.btn_autoscroll)

        # Botón Copiar
        btn_copy = Gtk.Button(label="Copiar")
        btn_copy.set_icon_name("edit-copy-symbolic")
        btn_copy.connect("clicked", self._on_copy_clicked)
        toolbar.append(btn_copy)

        # Botón Limpiar
        btn_clear = Gtk.Button(label="Limpiar")
        btn_clear.set_icon_name("edit-clear-symbolic")
        btn_clear.connect("clicked", self._on_clear_clicked)
        toolbar.append(btn_clear)

        self.append(toolbar)

        # Vista de Texto Monospace
        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_vexpand(True)
        self.scrolled.set_hexpand(True)

        self.text_view = Gtk.TextView()
        self.text_view.set_editable(False)
        self.text_view.set_cursor_visible(False)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.add_css_class("log-view")

        self.buffer = self.text_view.get_buffer()

        # Configurar tags de color
        self.tag_ts = self.buffer.create_tag("timestamp", foreground="#38BDF8")
        self.tag_info = self.buffer.create_tag("info", foreground="#E2E8F0")
        self.tag_success = self.buffer.create_tag("success", foreground="#4ADE80", weight=700)
        self.tag_warning = self.buffer.create_tag("warning", foreground="#FACC15", weight=700)
        self.tag_error = self.buffer.create_tag("error", foreground="#F87171", weight=700)

        self.scrolled.set_child(self.text_view)
        self.append(self.scrolled)

        # Barra de estado inferior
        self.lbl_stats = Gtk.Label(label="Registros: 0 líneas", xalign=0)
        self.lbl_stats.add_css_class("dim-label")
        self.append(self.lbl_stats)

    def _load_existing_logs(self):
        logs = self.log_monitor.get_logs()
        for entry in logs:
            self._append_entry(entry)
        self._update_stats()

    def _on_new_log(self, entry: dict):
        GLib.idle_add(self._handle_new_log_safe, entry)

    def _handle_new_log_safe(self, entry: dict):
        if self.filter_text and self.filter_text not in entry["raw"].lower():
            return
        self._append_entry(entry)
        self._update_stats()
        if self.auto_scroll:
            self._scroll_to_bottom()

    def _append_entry(self, entry: dict):
        end_iter = self.buffer.get_end_iter()
        ts_text = f"[{entry['timestamp']}] "
        self.buffer.insert_with_tags(end_iter, ts_text, self.tag_ts)

        level = entry.get("level", "info")
        tag_map = {
            "info": self.tag_info,
            "success": self.tag_success,
            "warning": self.tag_warning,
            "error": self.tag_error,
        }
        tag = tag_map.get(level, self.tag_info)

        end_iter = self.buffer.get_end_iter()
        msg_text = f"{entry['raw']}\n"
        self.buffer.insert_with_tags(end_iter, msg_text, tag)

    def _scroll_to_bottom(self):
        adj = self.scrolled.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())

    def _update_stats(self):
        lines = self.buffer.get_line_count()
        self.lbl_stats.set_label(f"Registros en memoria: {lines} líneas | Estado: Transmisión continua")

    def _on_filter_changed(self, entry):
        self.filter_text = entry.get_text().strip().lower()
        self.buffer.set_text("")
        all_logs = self.log_monitor.get_logs()
        for log in all_logs:
            if not self.filter_text or self.filter_text in log["raw"].lower():
                self._append_entry(log)
        self._update_stats()

    def _on_autoscroll_toggled(self, btn):
        self.auto_scroll = btn.get_active()

    def _on_copy_clicked(self, btn):
        start = self.buffer.get_start_iter()
        end = self.buffer.get_end_iter()
        text = self.buffer.get_text(start, end, False)
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)
        if self.show_toast_cb:
            self.show_toast_cb("Registros copiados al portapapeles.")

    def _on_clear_clicked(self, btn):
        self.buffer.set_text("")
        self._update_stats()
        if self.show_toast_cb:
            self.show_toast_cb("Consola de registros limpiada.")

#!/usr/bin/env python3
"""
native_gui/app.py - Interfaz Nativa de Escritorio para GODWORKS SYSTEM v26.4
=============================================================================
Aplicación 100% nativa en Linux con GTK4 y Libadwaita.
Opera directamente sin hacer uso de ningún navegador web.

Módulos integrados:
  1. Chat Soberano & Inferencia (Hermes 3 / Ollama, RAG offline, cancelación, voz)
  2. Metapensamiento & Espectro Cognitivo (Espectro Cairo animado, thought stream)
  3. Control Físico & Hardware (Bloqueo uinput, volumen PipeWire, captura de pantalla)
  4. Seguridad & Auditoría de Red (Escáner Wi-Fi, monitor de tráfico, hotspot)
  5. Bóveda de Chats Offline (Búsqueda SQLite FTS5 BM25, exportación)
  6. Telemetría & Tareas (CPU, RAM, systemd, kill process)
  7. Terminal Soberana (Comandos slash y shell interactivo)
"""

from __future__ import annotations

import datetime
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Asegurar que el directorio raíz del proyecto esté en sys.path
PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, Gio, Pango

# Importación de subsistemas y controladores soberanos
from core.os_controller import get_os_controller
from core.hardware_controller import get_hardware_controller
from core.network_controller import get_network_controller
from core.traffic_monitor import get_traffic_monitor
from core.offline_chat_vault import get_offline_chat_vault
from core.thought_noise_engine import get_thought_noise_engine
from core.background_thought_engine import get_background_thought_engine
from engine.sovereign_client import get_sovereign_client
from omni_temporal_control import process_hardware_chat_intent, CFG


class NativeGiaWindow(Adw.ApplicationWindow):
    """Ventana maestra nativa de GODWORKS SYSTEM."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_title("TARDIS · NEXO CRONO-NÁUTICO SOBERANO v26.4")
        self.set_default_size(1280, 850)

        # Cargar estilos cibernéticos personalizados
        self._load_css()

        # Controladores de estado
        self.os_ctrl = get_os_controller()
        self.hw_ctrl = get_hardware_controller()
        self.net_ctrl = get_network_controller()
        self.traffic_mon = get_traffic_monitor()
        self.vault = get_offline_chat_vault()
        self.thought_engine = get_thought_noise_engine()
        self.bg_thought = get_background_thought_engine()
        self.sovereign_client = get_sovereign_client()

        self.current_cancel_event = threading.Event()
        self.is_generating = False

        # Construir estructura principal
        self._build_ui()

    def _load_css(self):
        css_file = Path(__file__).parent / "cyber_theme.css"
        if css_file.exists():
            provider = Gtk.CssProvider()
            provider.load_from_path(str(css_file))
            display = Gdk.Display.get_default()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )

    def _build_ui(self):
        # Contenedor raíz vertical
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_content(main_box)

        # 1. Barra de Título / Encabezado
        header = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(
            title="TARDIS · NODO SOBERANO",
            subtitle="SISTEMA TARDIS v26.4 · MODO NATIVO DESKTOP"
        )
        header.set_title_widget(title_widget)

        # Badges en HeaderBar
        self.badge_status = Gtk.Label(label="⚡ SOBERANO LOCAL")
        self.badge_status.add_css_class("badge-active")
        header.pack_end(self.badge_status)

        btn_desktop_vault = Gtk.Button(label="💾 Bóveda Offline")
        btn_desktop_vault.set_tooltip_text("Abre el archivo HTML autónomo del escritorio")
        btn_desktop_vault.connect("clicked", lambda b: self._open_desktop_vault())
        header.pack_end(btn_desktop_vault)

        main_box.append(header)

        # 2. Contenedor de Navegación (Sidebar + Stack)
        split_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        split_box.set_vexpand(True)
        split_box.set_hexpand(True)
        main_box.append(split_box)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(200)
        self.stack.set_vexpand(True)
        self.stack.set_hexpand(True)

        # Barra lateral nativa
        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self.stack)
        sidebar.add_css_class("sidebar-view")
        sidebar.set_size_request(240, -1)
        split_box.append(sidebar)
        split_box.append(self.stack)

        # 3. Construcción de Vistas
        self._build_chat_view()
        self._build_cognitive_view()
        self._build_hardware_view()
        self._build_security_view()
        self._build_vault_view()
        self._build_telemetry_view()
        self._build_terminal_view()

    # =========================================================================
    # 1. PESTAÑA: CHAT SOBERANO & INFERENCIA
    # =========================================================================
    def _build_chat_view(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(16)
        box.set_margin_end(16)

        # Barra superior de configuración de inferencia
        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top_bar.add_css_class("gia-card")

        lbl_model = Gtk.Label(label="Modelo:")
        lbl_model.add_css_class("chat-meta")
        top_bar.append(lbl_model)

        self.model_combo = Gtk.DropDown.new_from_strings([
            "dolphin3:latest", "hermes3:8b", "llama3.2:3b", "llama3:latest", "mistral:latest"
        ])
        top_bar.append(self.model_combo)

        lbl_temp = Gtk.Label(label="Temp:")
        lbl_temp.add_css_class("chat-meta")
        top_bar.append(lbl_temp)

        self.scale_temp = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05)
        self.scale_temp.set_value(0.3)
        self.scale_temp.set_size_request(120, -1)
        top_bar.append(self.scale_temp)

        self.chk_voice = Gtk.CheckButton(label="Sintetizar Voz (TTS)")
        top_bar.append(self.chk_voice)

        self.lbl_rag_status = Gtk.Label(label="💾 RAG Offline: Activo")
        self.lbl_rag_status.add_css_class("badge-active")
        self.lbl_rag_status.set_hexpand(True)
        self.lbl_rag_status.set_halign(Gtk.Align.END)
        top_bar.append(self.lbl_rag_status)

        box.append(top_bar)

        # Transcripción de mensajes (ScrolledWindow)
        self.chat_scroll = Gtk.ScrolledWindow()
        self.chat_scroll.set_vexpand(True)
        self.chat_scroll.set_hexpand(True)
        self.chat_scroll.add_css_class("gia-card")

        self.chat_flow = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.chat_flow.set_margin_top(12)
        self.chat_flow.set_margin_bottom(12)
        self.chat_flow.set_margin_start(12)
        self.chat_flow.set_margin_end(12)
        self.chat_scroll.set_child(self.chat_flow)
        box.append(self.chat_scroll)

        # Mensaje de bienvenida inicial
        self._append_chat_bubble(
            "system",
            "🚀 **TARDIS Sistema Nativo Iniciado** · Conexión directa a Ollama y memoria SQLite FTS5 activa.\n"
            "Escribe cualquier instrucción o comando soberano (`/status`, `/lock`, `/vol`, `/ayuda`, etc.)."
        )

        # Barra inferior de entrada
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        input_box.set_margin_top(4)

        self.chat_input = Gtk.Entry()
        self.chat_input.set_placeholder_text("Escribe una instrucción, consulta o comando soberano...")
        self.chat_input.set_hexpand(True)
        self.chat_input.connect("activate", lambda e: self._send_chat_message())
        input_box.append(self.chat_input)

        self.btn_send = Gtk.Button(label="ENVIAR")
        self.btn_send.add_css_class("btn-primary")
        self.btn_send.connect("clicked", lambda b: self._send_chat_message())
        input_box.append(self.btn_send)

        self.btn_cancel = Gtk.Button(label="CANCELAR")
        self.btn_cancel.add_css_class("btn-danger")
        self.btn_cancel.set_sensitive(False)
        self.btn_cancel.connect("clicked", lambda b: self._cancel_chat_inference())
        input_box.append(self.btn_cancel)

        box.append(input_box)
        self.stack.add_titled(box, "chat", "💬 Chat Soberano")

    def _append_chat_bubble(self, role: str, text: str, model_info: str = ""):
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        if role == "user":
            bubble.add_css_class("chat-bubble-user")
            header_text = f"👤 Usuario · {datetime.datetime.now().strftime('%H:%M:%S')}"
        elif role == "assistant":
            bubble.add_css_class("chat-bubble-assistant")
            header_text = f"🤖 {model_info or 'Dolphin 3.0'} · {datetime.datetime.now().strftime('%H:%M:%S')}"
        else:
            bubble.add_css_class("chat-bubble-system")
            header_text = "⚙️ Sistema Soberano"

        lbl_hdr = Gtk.Label(label=header_text)
        lbl_hdr.set_halign(Gtk.Align.START)
        lbl_hdr.add_css_class("chat-meta")
        bubble.append(lbl_hdr)

        lbl_body = Gtk.Label()
        lbl_body.set_wrap(True)
        lbl_body.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lbl_body.set_selectable(True)
        lbl_body.set_halign(Gtk.Align.START)

        # Formatear markdown básico en Pango markup seguro
        clean_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        formatted = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", clean_text)
        formatted = re.sub(r"__(.*?)__", r"<i>\1</i>", formatted)
        formatted = re.sub(r"`(.*?)`", r"<tt>\1</tt>", formatted)
        try:
            lbl_body.set_markup(formatted)
        except Exception:
            lbl_body.set_text(text)

        bubble.append(lbl_body)
        self.chat_flow.append(bubble)

        # Scroll automático al final
        GLib.idle_add(self._scroll_chat_to_bottom)
        return lbl_body

    def _scroll_chat_to_bottom(self):
        adj = self.chat_scroll.get_vadjustment()
        if adj:
            adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def _send_chat_message(self):
        text = self.chat_input.get_text().strip()
        if not text or self.is_generating:
            return

        self.chat_input.set_text("")
        self._append_chat_bubble("user", text)

        # Verificar si es comando de hardware / slash directo
        hw_res = process_hardware_chat_intent(text)
        if hw_res and hw_res.get("direct_return"):
            feedback = hw_res.get("system_feedback", "Comando ejecutado.")
            self._append_chat_bubble("system", feedback)
            self.vault.record_turn(
                user_message=text,
                assistant_reply=feedback,
                model="hardware_controller",
                hardware_action=hw_res.get("action")
            )
            return

        # Preparar inferencia en hilo secundario
        self.is_generating = True
        self.btn_send.set_sensitive(False)
        self.btn_cancel.set_sensitive(True)
        self.current_cancel_event.clear()

        model_name = self.model_combo.get_selected_item().get_string()
        temp_val = float(self.scale_temp.get_value())
        use_voice = self.chk_voice.get_active()

        # Inyectar memoria histórica offline (RAG)
        rag_ctx = self.vault.get_context_for_prompt(text, k_relevant=3, n_recent=2)

        thread = threading.Thread(
            target=self._run_inference_worker,
            args=(text, model_name, temp_val, rag_ctx, use_voice),
            daemon=True
        )
        thread.start()

    def _run_inference_worker(self, prompt: str, model: str, temp: float, rag_ctx: str, use_voice: bool):
        sys_prompt = (
            "Eres GIA (General Intelligence Autonomous), la entidad soberana de inferencia y control "
            "de hardware de GODWORKS SYSTEM v26.4. Responde con concisión técnica, calidez y precisión impecable.\n\n"
        )
        if rag_ctx:
            sys_prompt += rag_ctx + "\n\n"

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt}
        ]

        # Crear burbuja del asistente vacía para streaming
        lbl_target = [None]
        def create_target():
            lbl_target[0] = self._append_chat_bubble("assistant", "...", model_info=model)
            return False
        GLib.idle_add(create_target)

        while lbl_target[0] is None:
            time.sleep(0.02)

        accumulated = []
        try:
            for chunk in self.sovereign_client.chat_stream(
                messages=messages,
                model=model,
                temperature=temp,
                cancel_event=self.current_cancel_event
            ):
                if self.current_cancel_event.is_set():
                    break
                accumulated.append(chunk)
                current_text = "".join(accumulated)
                
                # Actualizar etiqueta en UI
                def update_label(txt=current_text):
                    clean = txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    try:
                        lbl_target[0].set_markup(clean)
                    except Exception:
                        lbl_target[0].set_text(txt)
                    self._scroll_chat_to_bottom()
                    return False
                GLib.idle_add(update_label)

        except Exception as e:
            accumulated.append(f"\n[Error de inferencia: {e}]")
            GLib.idle_add(lambda: lbl_target[0].set_text("".join(accumulated)))

        final_reply = "".join(accumulated).strip() or "(Respuesta vacía o cancelada)"

        # Registrar en la bóveda de chats offline permanentemente
        self.vault.record_turn(
            user_message=prompt,
            assistant_reply=final_reply,
            model=model,
            provider="GIA Nativo Desktop",
            direction="present"
        )

        # Síntesis de voz opcional
        if use_voice and final_reply and not self.current_cancel_event.is_set():
            clean_speech = final_reply.replace("*", "").replace("#", "").strip()[:400]
            self.os_ctrl.speak(clean_speech)

        # Restaurar estado de controles
        def finish():
            self.is_generating = False
            self.btn_send.set_sensitive(True)
            self.btn_cancel.set_sensitive(False)
            return False
        GLib.idle_add(finish)

    def _cancel_chat_inference(self):
        if self.is_generating:
            self.current_cancel_event.set()
            self._append_chat_bubble("system", "⛔ Inferencia cancelada por el usuario.")
            self.is_generating = False
            self.btn_send.set_sensitive(True)
            self.btn_cancel.set_sensitive(False)

    # =========================================================================
    # 2. PESTAÑA: METAPENSAMIENTO & ESPECTRO COGNITIVO
    # =========================================================================
    def _build_cognitive_view(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)

        # Tarjeta del espectro gráfico
        card_spectrum = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card_spectrum.add_css_class("gia-card")

        lbl_spec_title = Gtk.Label(label="⚡ ESPECTRO DE RUIDO Y FRECUENCIA COGNITIVA (TIEMPO REAL)")
        lbl_spec_title.add_css_class("gia-card-header")
        lbl_spec_title.set_halign(Gtk.Align.START)
        card_spectrum.append(lbl_spec_title)

        # Área de dibujo Cairo nativa
        self.spectrum_area = Gtk.DrawingArea()
        self.spectrum_area.set_size_request(-1, 180)
        self.spectrum_area.set_draw_func(self._draw_spectrum)
        card_spectrum.append(self.spectrum_area)

        # Controles y estimulación
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_margin_top(8)

        btn_stimulate = Gtk.Button(label="🧠 Estimular Metapensamiento")
        btn_stimulate.add_css_class("btn-primary")
        btn_stimulate.connect("clicked", lambda b: self._stimulate_metathought())
        btn_box.append(btn_stimulate)

        self.lbl_psi = Gtk.Label(label="Coherencia Ψ: 0.892 | Entropía: Mínima")
        self.lbl_psi.add_css_class("badge-active")
        btn_box.append(self.lbl_psi)

        card_spectrum.append(btn_box)
        box.append(card_spectrum)

        # Flujo de preguntas en segundo plano
        card_questions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card_questions.add_css_class("gia-card")
        card_questions.set_vexpand(True)

        lbl_q_title = Gtk.Label(label="🌊 FLUJO DE PREGUNTAS & SÍNTESIS COGNITIVA EN SEGUNDO PLANO")
        lbl_q_title.add_css_class("gia-card-header")
        lbl_q_title.set_halign(Gtk.Align.START)
        card_questions.append(lbl_q_title)

        self.thought_scrolled = Gtk.ScrolledWindow()
        self.thought_scrolled.set_vexpand(True)

        self.thought_list = Gtk.ListBox()
        self.thought_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.thought_scrolled.set_child(self.thought_list)
        card_questions.append(self.thought_scrolled)

        box.append(card_questions)
        self.stack.add_titled(box, "cognitive", "🧠 Metapensamiento")

        # Animación continua del espectro (30 FPS)
        self.spectrum_phase = 0.0
        GLib.timeout_add(50, self._tick_spectrum)
        GLib.timeout_add(4000, self._refresh_thoughts)

    def _tick_spectrum(self):
        self.spectrum_phase += 0.12
        self.spectrum_area.queue_draw()
        return True

    def _draw_spectrum(self, area, cr, width, height):
        # Fondo oscuro del espectrograma
        cr.set_source_rgb(0.02, 0.04, 0.07)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Cuadrícula
        cr.set_source_rgba(0.12, 0.16, 0.24, 0.4)
        cr.set_line_width(1.0)
        for x in range(0, int(width), 40):
            cr.move_to(x, 0)
            cr.line_to(x, height)
        for y in range(0, int(height), 30):
            cr.move_to(0, y)
            cr.line_to(width, y)
        cr.stroke()

        # Onda Sintrópica Principal (Cian / Esmeralda)
        cr.set_source_rgba(0.0, 1.0, 0.66, 0.85)
        cr.set_line_width(2.5)
        mid_y = height / 2.0
        cr.move_to(0, mid_y)
        for x in range(0, int(width), 4):
            val = (
                math.sin((x * 0.03) + self.spectrum_phase) * 35.0 +
                math.sin((x * 0.07) - self.spectrum_phase * 1.5) * 15.0 +
                math.cos((x * 0.015) + self.spectrum_phase * 0.5) * 20.0
            )
            cr.line_to(x, mid_y + val)
        cr.stroke()

        # Onda Armónica Secundaria (Magenta / Neón)
        cr.set_source_rgba(1.0, 0.0, 0.35, 0.5)
        cr.set_line_width(1.5)
        cr.move_to(0, mid_y)
        for x in range(0, int(width), 6):
            val = math.sin((x * 0.04) - self.spectrum_phase * 0.8) * 25.0
            cr.line_to(x, mid_y + val)
        cr.stroke()

    def _stimulate_metathought(self):
        def worker():
            try:
                self.thought_engine.stimulate()
                self._refresh_thoughts()
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_thoughts(self):
        try:
            questions = self.bg_thought.get_recent_questions(limit=8)
            def update():
                # Limpiar lista previa
                while True:
                    row = self.thought_list.get_row_at_index(0)
                    if row is None:
                        break
                    self.thought_list.remove(row)

                if not questions:
                    row = Gtk.ListBoxRow()
                    lbl = Gtk.Label(label="* Sin metapensamientos activos en cola. Pulsa 'Estimular'. *")
                    lbl.add_css_class("chat-meta")
                    row.set_child(lbl)
                    self.thought_list.append(row)
                else:
                    for q in questions:
                        row = Gtk.ListBoxRow()
                        rbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                        rbox.set_margin_top(6)
                        rbox.set_margin_bottom(6)
                        rbox.set_margin_start(8)
                        rbox.set_margin_end(8)

                        badge = Gtk.Label(label="🧠 PREGUNTA")
                        badge.add_css_class("badge-active")
                        rbox.append(badge)

                        lbl_text = Gtk.Label(label=q.get("question", ""))
                        lbl_text.set_wrap(True)
                        lbl_text.set_halign(Gtk.Align.START)
                        rbox.append(lbl_text)

                        row.set_child(rbox)
                        self.thought_list.append(row)
                return False
            GLib.idle_add(update)
        except Exception:
            pass
        return True

    # =========================================================================
    # 3. PESTAÑA: CONTROL FÍSICO & HARDWARE
    # =========================================================================
    def _build_hardware_view(self):
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        scrolled.set_child(box)

        # 1. Pantalla & Bloqueo
        card_disp = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card_disp.add_css_class("gia-card")
        lbl_d = Gtk.Label(label="🖥️ PANTALLA & CONTROL DE ACCESO INMEDIATO")
        lbl_d.add_css_class("gia-card-header")
        lbl_d.set_halign(Gtk.Align.START)
        card_disp.append(lbl_d)

        btn_box_disp = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_lock = Gtk.Button(label="🔒 Bloquear Pantalla (Uinput)")
        btn_lock.add_css_class("btn-warning")
        btn_lock.connect("clicked", lambda b: self._execute_hw_action("lock_screen"))
        btn_box_disp.append(btn_lock)

        btn_unlock = Gtk.Button(label="🔓 Desbloquear Pantalla")
        btn_unlock.add_css_class("btn-primary")
        btn_unlock.connect("clicked", lambda b: self._execute_hw_action("unlock_screen"))
        btn_box_disp.append(btn_unlock)

        card_disp.append(btn_box_disp)
        box.append(card_disp)

        # 2. Audio & Multimedia PipeWire
        card_audio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card_audio.add_css_class("gia-card")
        lbl_a = Gtk.Label(label="🔊 MULTIMEDIA & AUDIO (PIPEWIRE / ALSA)")
        lbl_a.add_css_class("gia-card-header")
        lbl_a.set_halign(Gtk.Align.START)
        card_audio.append(lbl_a)

        audio_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        lbl_vol = Gtk.Label(label="Volumen:")
        audio_row.append(lbl_vol)

        self.scale_volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale_volume.set_value(75)
        self.scale_volume.set_hexpand(True)
        self.scale_volume.connect("value-changed", self._on_volume_changed)
        audio_row.append(self.scale_volume)

        btn_mute = Gtk.Button(label="🔇 Alternar Silencio")
        btn_mute.connect("clicked", lambda b: self._execute_hw_action("toggle_mute"))
        audio_row.append(btn_mute)

        card_audio.append(audio_row)
        box.append(card_audio)

        # 3. Teclado & Retroiluminación
        card_kbd = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card_kbd.add_css_class("gia-card")
        lbl_k = Gtk.Label(label="⌨️ RETROILUMINACIÓN DE TECLADO")
        lbl_k.add_css_class("gia-card-header")
        lbl_k.set_halign(Gtk.Align.START)
        card_kbd.append(lbl_k)

        kbd_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for level in [0, 1, 2, 3]:
            btn_lvl = Gtk.Button(label=f"Nivel {level}")
            btn_lvl.connect("clicked", lambda b, lvl=level: self._set_keyboard_level(lvl))
            kbd_row.append(btn_lvl)
        card_kbd.append(kbd_row)
        box.append(card_kbd)

        # 4. Visor de Capturas & Visión
        card_vision = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card_vision.add_css_class("gia-card")
        lbl_v = Gtk.Label(label="📷 VISIÓN EN VIVO & CAPTURA DE PANTALLA")
        lbl_v.add_css_class("gia-card-header")
        lbl_v.set_halign(Gtk.Align.START)
        card_vision.append(lbl_v)

        vis_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_shot = Gtk.Button(label="📸 Capturar Pantalla")
        btn_shot.add_css_class("btn-primary")
        btn_shot.connect("clicked", lambda b: self._take_screenshot())
        vis_btn_box.append(btn_shot)

        self.lbl_shot_status = Gtk.Label(label="Sin capturas recientes")
        self.lbl_shot_status.add_css_class("chat-meta")
        vis_btn_box.append(self.lbl_shot_status)
        card_vision.append(vis_btn_box)

        # Previsualizador nativo de imagen
        self.pic_preview = Gtk.Picture()
        self.pic_preview.set_size_request(-1, 220)
        self.pic_preview.set_can_shrink(True)
        card_vision.append(self.pic_preview)

        box.append(card_vision)

        # 5. Energía & Sistema
        card_power = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card_power.add_css_class("gia-card")
        lbl_p = Gtk.Label(label="⚡ GESTIÓN DE ENERGÍA Y REINICIO")
        lbl_p.add_css_class("gia-card-header")
        lbl_p.set_halign(Gtk.Align.START)
        card_power.append(lbl_p)

        pwr_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_reboot = Gtk.Button(label="🔄 Reiniciar Sistema")
        btn_reboot.add_css_class("btn-danger")
        btn_reboot.connect("clicked", lambda b: self._execute_hw_action("reboot"))
        pwr_btn_box.append(btn_reboot)

        btn_poweroff = Gtk.Button(label="🛑 Apagar Sistema")
        btn_poweroff.add_css_class("btn-danger")
        btn_poweroff.connect("clicked", lambda b: self._execute_hw_action("poweroff"))
        pwr_btn_box.append(btn_poweroff)

        card_power.append(pwr_btn_box)
        box.append(card_power)

        self.stack.add_titled(scrolled, "hardware", "🎛️ Hardware & Sensores")

    def _execute_hw_action(self, action: str):
        def worker():
            if action == "lock_screen":
                self.os_ctrl.lock_screen()
            elif action == "unlock_screen":
                self.os_ctrl.unlock_screen()
            elif action == "toggle_mute":
                self.os_ctrl.toggle_mute()
            elif action == "reboot":
                self.os_ctrl.reboot()
            elif action == "poweroff":
                self.os_ctrl.poweroff()
        threading.Thread(target=worker, daemon=True).start()

    def _on_volume_changed(self, scale):
        vol = int(scale.get_value())
        def worker():
            self.os_ctrl.set_volume(vol)
        threading.Thread(target=worker, daemon=True).start()

    def _set_keyboard_level(self, level: int):
        def worker():
            self.os_ctrl.set_keyboard_backlight(level)
        threading.Thread(target=worker, daemon=True).start()

    def _take_screenshot(self):
        self.lbl_shot_status.set_text("Capturando pantalla...")
        def worker():
            shot_file = PROJECT_DIR / "data" / "screenshot_reciente.png"
            shot_file.parent.mkdir(parents=True, exist_ok=True)
            res = self.os_ctrl.take_screenshot(str(shot_file))
            if shot_file.exists():
                gfile = Gio.File.new_for_path(str(shot_file))
                GLib.idle_add(lambda: self.pic_preview.set_file(gfile))
                GLib.idle_add(lambda: self.lbl_shot_status.set_text(f"Captura guardada: {shot_file.name}"))
            else:
                GLib.idle_add(lambda: self.lbl_shot_status.set_text(f"Fallo en captura: {res.get('error', 'Desconocido')}"))
        threading.Thread(target=worker, daemon=True).start()

    # =========================================================================
    # 4. PESTAÑA: SEGURIDAD & AUDITORÍA DE RED
    # =========================================================================
    def _build_security_view(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)

        # Controles y Resumen
        top_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top_card.add_css_class("gia-card")

        btn_scan = Gtk.Button(label="🔍 Escanear Red Wi-Fi")
        btn_scan.add_css_class("btn-primary")
        btn_scan.connect("clicked", lambda b: self._scan_wifi_network())
        top_card.append(btn_scan)

        self.lbl_net_stats = Gtk.Label(label="Clientes: Calculando... | Rogue Devices: 0")
        self.lbl_net_stats.add_css_class("badge-active")
        top_card.append(self.lbl_net_stats)

        btn_hotspot = Gtk.Button(label="📡 Hotspot TimeMachine")
        btn_hotspot.connect("clicked", lambda b: self._toggle_hotspot())
        top_card.append(btn_hotspot)

        box.append(top_card)

        # Tabla de Dispositivos Conectados
        card_table = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card_table.add_css_class("gia-card")
        card_table.set_vexpand(True)

        lbl_t = Gtk.Label(label="🛡️ DISPOSITIVOS CONECTADOS & ANÁLISIS DE TRÁFICO")
        lbl_t.add_css_class("gia-card-header")
        lbl_t.set_halign(Gtk.Align.START)
        card_table.append(lbl_t)

        scrolled_table = Gtk.ScrolledWindow()
        scrolled_table.set_vexpand(True)

        self.net_list = Gtk.ListBox()
        self.net_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scrolled_table.set_child(self.net_list)
        card_table.append(scrolled_table)

        box.append(card_table)
        self.stack.add_titled(box, "security", "🛡️ Seguridad & Red")

        # Escaneo inicial automático
        GLib.timeout_add(1000, self._scan_wifi_network)

    def _scan_wifi_network(self):
        def worker():
            try:
                clients = self.net_ctrl.get_connected_clients()
                def update():
                    while True:
                        row = self.net_list.get_row_at_index(0)
                        if row is None:
                            break
                        self.net_list.remove(row)

                    count = len(clients)
                    self.lbl_net_stats.set_text(f"Dispositivos Conectados: {count} | Escaneo Activo")

                    if not clients:
                        row = Gtk.ListBoxRow()
                        lbl = Gtk.Label(label="* No se detectaron dispositivos o escaneo en progreso *")
                        lbl.add_css_class("chat-meta")
                        row.set_child(lbl)
                        self.net_list.append(row)
                    else:
                        for c in clients:
                            row = Gtk.ListBoxRow()
                            rbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
                            rbox.set_margin_top(8)
                            rbox.set_margin_bottom(8)
                            rbox.set_margin_start(10)
                            rbox.set_margin_end(10)

                            lbl_ip = Gtk.Label(label=f"IP: {c.get('ip', 'N/A')}")
                            lbl_ip.add_css_class("badge-active")
                            rbox.append(lbl_ip)

                            lbl_mac = Gtk.Label(label=f"MAC: {c.get('mac', 'N/A')}")
                            lbl_mac.add_css_class("chat-meta")
                            rbox.append(lbl_mac)

                            lbl_host = Gtk.Label(label=f"Host: {c.get('hostname', 'Desconocido')}")
                            lbl_host.set_hexpand(True)
                            lbl_host.set_halign(Gtk.Align.START)
                            rbox.append(lbl_host)

                            row.set_child(rbox)
                            self.net_list.append(row)
                    return False
                GLib.idle_add(update)
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()
        return False

    def _toggle_hotspot(self):
        def worker():
            try:
                self.net_ctrl.start_hotspot()
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    # =========================================================================
    # 5. PESTAÑA: BÓVEDA DE CHATS OFFLINE
    # =========================================================================
    def _build_vault_view(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)

        # Barra de búsqueda FTS5 y herramientas de exportación
        search_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        search_card.add_css_class("gia-card")

        self.vault_search = Gtk.SearchEntry()
        self.vault_search.set_placeholder_text("Buscar en toda la memoria offline (FTS5 BM25)...")
        self.vault_search.set_hexpand(True)
        self.vault_search.connect("search-changed", self._on_vault_search_changed)
        search_card.append(self.vault_search)

        btn_export_md = Gtk.Button(label="📄 Exportar Markdown")
        btn_export_md.connect("clicked", lambda b: self._export_vault_markdown())
        search_card.append(btn_export_md)

        btn_export_json = Gtk.Button(label="💾 Exportar JSON")
        btn_export_json.connect("clicked", lambda b: self._export_vault_json())
        search_card.append(btn_export_json)

        box.append(search_card)

        # Lista de turnos recuperados
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.add_css_class("gia-card")

        self.vault_list = Gtk.ListBox()
        self.vault_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        scrolled.set_child(self.vault_list)
        box.append(scrolled)

        self.stack.add_titled(box, "vault", "💾 Bóveda Offline")
        self._load_vault_turns()

    def _load_vault_turns(self, query: str = ""):
        def worker():
            if query:
                turns = self.vault.search(query, limit=50)
            else:
                turns = self.vault.get_recent(limit=50)

            def update():
                while True:
                    row = self.vault_list.get_row_at_index(0)
                    if row is None:
                        break
                    self.vault_list.remove(row)

                if not turns:
                    row = Gtk.ListBoxRow()
                    lbl = Gtk.Label(label="* No se encontraron turnos en la bóveda *")
                    lbl.add_css_class("chat-meta")
                    row.set_child(lbl)
                    self.vault_list.append(row)
                else:
                    for t in turns:
                        row = Gtk.ListBoxRow()
                        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                        card.set_margin_top(8)
                        card.set_margin_bottom(8)
                        card.set_margin_start(10)
                        card.set_margin_end(10)

                        lbl_h = Gtk.Label(label=f"Turno #{t['id']} · {t['iso']} · Modelo: {t['model']}")
                        lbl_h.add_css_class("chat-meta")
                        lbl_h.set_halign(Gtk.Align.START)
                        card.append(lbl_h)

                        p_txt = t.get("user_message") or t.get("prompt") or ""
                        lbl_u = Gtk.Label(label=f"👤 Usuario: {p_txt[:180]}")
                        lbl_u.set_halign(Gtk.Align.START)
                        lbl_u.set_wrap(True)
                        card.append(lbl_u)

                        r_txt = t.get("assistant_reply") or t.get("reply") or ""
                        lbl_a = Gtk.Label(label=f"🤖 {t.get('model', 'Dolphin 3.0')}: {r_txt[:260]}")
                        lbl_a.set_halign(Gtk.Align.START)
                        lbl_a.set_wrap(True)
                        card.append(lbl_a)

                        row.set_child(card)
                        self.vault_list.append(row)
                return False
            GLib.idle_add(update)
        threading.Thread(target=worker, daemon=True).start()

    def _on_vault_search_changed(self, entry):
        q = entry.get_text().strip()
        self._load_vault_turns(q)

    def _open_desktop_vault(self):
        desk_path = Path("/home/timemachine/Escritorio/HISTORIAL_CHATS_OFFLINE.html")
        if desk_path.exists():
            subprocess.Popen(["xdg-open", str(desk_path)])

    def _export_vault_markdown(self):
        out_path = Path("/home/timemachine/Escritorio") / f"godworks_chats_{int(time.time())}.md"
        turns = self.vault.get_recent(limit=2000)
        md = "# Historial Soberano de Chats - GODWORKS SYSTEM v26.4\n\n"
        for t in turns:
            md += f"### Turno #{t['id']} ({t['iso']}) | Modelo: {t['model']}\n"
            md += f"> **Usuario:**\n{t.get('user_message', '')}\n\n"
            md += f"**{t.get('model', 'Dolphin 3.0')}:**\n{t.get('assistant_reply', '')}\n\n---\n\n"
        out_path.write_text(md, encoding="utf-8")
        self.badge_status.set_text("✓ Markdown Exportado al Escritorio")

    def _export_vault_json(self):
        out_path = Path("/home/timemachine/Escritorio") / f"godworks_chats_backup_{int(time.time())}.json"
        turns = self.vault.get_recent(limit=2000)
        out_path.write_text(json.dumps(turns, ensure_ascii=False, indent=2), encoding="utf-8")
        self.badge_status.set_text("✓ JSON Exportado al Escritorio")

    # =========================================================================
    # 6. PESTAÑA: TELEMETRÍA & TAREAS
    # =========================================================================
    def _build_telemetry_view(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)

        # Barras de carga de hardware
        card_gauges = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card_gauges.add_css_class("gia-card")

        lbl_g = Gtk.Label(label="📊 ESTADO DE RECURSOS DEL SISTEMA")
        lbl_g.add_css_class("gia-card-header")
        lbl_g.set_halign(Gtk.Align.START)
        card_gauges.append(lbl_g)

        # CPU
        self.lbl_cpu = Gtk.Label(label="CPU: 0%")
        self.lbl_cpu.set_halign(Gtk.Align.START)
        card_gauges.append(self.lbl_cpu)
        self.prog_cpu = Gtk.ProgressBar()
        card_gauges.append(self.prog_cpu)

        # RAM
        self.lbl_ram = Gtk.Label(label="RAM: 0%")
        self.lbl_ram.set_halign(Gtk.Align.START)
        card_gauges.append(self.lbl_ram)
        self.prog_ram = Gtk.ProgressBar()
        card_gauges.append(self.prog_ram)

        box.append(card_gauges)

        # Servicio Systemd
        card_srv = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        card_srv.add_css_class("gia-card")

        self.lbl_service = Gtk.Label(label="godworks.service: Activo")
        self.lbl_service.add_css_class("badge-active")
        card_srv.append(self.lbl_service)

        btn_restart_srv = Gtk.Button(label="🔄 Reiniciar godworks.service")
        btn_restart_srv.connect("clicked", lambda b: self._restart_godworks_service())
        card_srv.append(btn_restart_srv)

        box.append(card_srv)
        self.stack.add_titled(box, "telemetry", "📊 Telemetría & Tareas")

        GLib.timeout_add(2000, self._update_telemetry)

    def _update_telemetry(self):
        try:
            import psutil
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            self.lbl_cpu.set_text(f"Carga CPU: {cpu:.1f}%")
            self.prog_cpu.set_fraction(cpu / 100.0)
            self.lbl_ram.set_text(f"Memoria RAM: {ram:.1f}% ({psutil.virtual_memory().used // (1024*1024)} MB)")
            self.prog_ram.set_fraction(ram / 100.0)
        except Exception:
            pass
        return True

    def _restart_godworks_service(self):
        def worker():
            subprocess.run(["systemctl", "--user", "restart", "godworks.service"], check=False)
            GLib.idle_add(lambda: self.lbl_service.set_text("godworks.service: Reiniciado"))
        threading.Thread(target=worker, daemon=True).start()

    # =========================================================================
    # 7. PESTAÑA: TERMINAL SOBERANA
    # =========================================================================
    def _build_terminal_view(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.add_css_class("terminal-box")

        self.term_view = Gtk.TextView()
        self.term_view.set_editable(False)
        self.term_view.set_cursor_visible(False)
        self.term_view.set_monospace(True)
        self.term_buffer = self.term_view.get_buffer()
        self.term_buffer.set_text(
            "===============================================================\n"
            "   GIA TERMINAL SOBERANA · MODO NATIVO DESKTOP v26.4          \n"
            "===============================================================\n"
            "Escribe comandos slash (/status, /lock, /vol, /shot) o bash...\n\n"
        )
        scrolled.set_child(self.term_view)
        box.append(scrolled)

        # Entrada de comando
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.term_entry = Gtk.Entry()
        self.term_entry.set_placeholder_text("Ejemplo: /status o uname -a...")
        self.term_entry.set_hexpand(True)
        self.term_entry.connect("activate", lambda e: self._execute_terminal_command())
        input_box.append(self.term_entry)

        btn_run = Gtk.Button(label="EJECUTAR")
        btn_run.add_css_class("btn-primary")
        btn_run.connect("clicked", lambda b: self._execute_terminal_command())
        input_box.append(btn_run)

        box.append(input_box)
        self.stack.add_titled(box, "terminal", "⚡ Terminal")

    def _execute_terminal_command(self):
        cmd = self.term_entry.get_text().strip()
        if not cmd:
            return
        self.term_entry.set_text("")
        self._append_term_text(f"\n$ {cmd}\n")

        def worker():
            if cmd.startswith("/"):
                res = process_hardware_chat_intent(cmd)
                out = res.get("system_feedback", str(res)) if res else "Comando no reconocido."
            else:
                try:
                    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                    out = p.stdout or p.stderr or "[Comando completado sin salida]"
                except Exception as e:
                    out = f"[Error: {e}]"
            GLib.idle_add(lambda: self._append_term_text(out + "\n"))

        threading.Thread(target=worker, daemon=True).start()

    def _append_term_text(self, text: str):
        end_iter = self.term_buffer.get_end_iter()
        self.term_buffer.insert(end_iter, text)


class NativeGiaApplication(Adw.Application):
    """Aplicación Libadwaita nativa de GODWORKS."""

    def __init__(self):
        super().__init__(
            application_id="org.godworks.gia.native",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = NativeGiaWindow(application=self)
        win.present()


def main():
    app = NativeGiaApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  TARDIS SOBERANO · CALCULADORA NEURONAL POR VOZ
  GODWORKS SYSTEM v26.4 · Núcleo de Inferencia Cuántica y Traducción Fonética
  Autoridad Absoluta: El Arquitecto (₪)
=============================================================================
"""

import os
import sys
import math
import time
import ctypes
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import speech_recognition as sr

# Importar motor matemático y módulo de voz
from tardis_math_engine import parse_spoken_text_to_math, evaluate_expression
from tardis_voice_feedback import speak_async, set_voice_enabled

# Supresión de errores ruidosos de ALSA / JACK en C
def suppress_alsa_errors():
    try:
        ERROR_HANDLER_FUNC = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_int,
                                              ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p)
        def py_error_handler(filename, line, function, err, fmt):
            pass
        c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
        asound = ctypes.cdll.LoadLibrary('libasound.so.2')
        asound.snd_lib_error_set_handler(c_error_handler)
    except Exception:
        pass

suppress_alsa_errors()

# Colores de la interfaz (TARDIS Cyberpunk / Dark Glassmorphism)
COLOR_BG = "#0b0f19"
COLOR_SURFACE = "#111827"
COLOR_CARD = "#1f2937"
COLOR_DISPLAY_BG = "#030712"
COLOR_ACCENT_CYAN = "#00f2fe"
COLOR_ACCENT_BLUE = "#38bdf8"
COLOR_ACCENT_PURPLE = "#818cf8"
COLOR_ACCENT_GREEN = "#10b981"
COLOR_ACCENT_RED = "#ef4444"
COLOR_ACCENT_AMBER = "#f59e0b"
COLOR_TEXT_PRIMARY = "#f9fafb"
COLOR_TEXT_MUTED = "#9ca3af"
COLOR_BTN_NUM = "#1e293b"
COLOR_BTN_OP = "#312e81"
COLOR_BTN_FN = "#1e1e38"
COLOR_BTN_HOVER = "#374151"

class TardisVoiceCalculator(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TARDIS · Calculadora Neuronal por Voz (₪)")
        self.geometry("980x720")
        self.minsize(860, 640)
        self.configure(bg=COLOR_BG)

        # Estado de la calculadora
        self.current_expr = ""
        self.last_result = ""
        self.angle_mode = "DEG"
        self.voice_feedback_on = True
        self.continuous_listening = False
        self.is_listening = False
        self.history = []

        # Reconocedor de voz
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.8

        self._build_ui()
        self._bind_keyboard()
        self._update_display()

        # Saludo TARDIS
        self.after(500, lambda: self._set_voice_status("🟢 Sistema en línea", "Listo para calcular por voz o teclado"))

    def _build_ui(self):
        # Contenedor Principal (2 Columnas: Calculadora y Panel de Historial)
        main_frame = tk.Frame(self, bg=COLOR_BG)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        # Columna Izquierda: Calculadora
        calc_frame = tk.Frame(main_frame, bg=COLOR_SURFACE, highlightbackground="#1e293b", highlightthickness=1)
        calc_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        # Barra Superior de Control / Opciones
        top_bar = tk.Frame(calc_frame, bg=COLOR_SURFACE)
        top_bar.pack(fill=tk.X, padx=16, pady=(12, 6))

        title_lbl = tk.Label(top_bar, text="⚡ TARDIS CALCULATOR", font=("DejaVu Sans", 13, "bold"),
                             fg=COLOR_ACCENT_CYAN, bg=COLOR_SURFACE)
        title_lbl.pack(side=tk.LEFT)

        # Botón DEG/RAD
        self.deg_btn = tk.Button(top_bar, text="DEG", font=("DejaVu Sans", 9, "bold"),
                                 bg=COLOR_CARD, fg=COLOR_ACCENT_BLUE, activebackground="#374151",
                                 relief=tk.FLAT, padx=10, pady=3, command=self._toggle_angle_mode)
        self.deg_btn.pack(side=tk.RIGHT, padx=4)

        # Botón Voz Síntesis (Audio Feedback)
        self.voice_out_btn = tk.Button(top_bar, text="🔊 Audio: ON", font=("DejaVu Sans", 9, "bold"),
                                       bg=COLOR_CARD, fg=COLOR_ACCENT_GREEN, activebackground="#374151",
                                       relief=tk.FLAT, padx=10, pady=3, command=self._toggle_voice_feedback)
        self.voice_out_btn.pack(side=tk.RIGHT, padx=4)

        # Botón Modo Continuo
        self.continuous_btn = tk.Button(top_bar, text="🔄 Continuo: OFF", font=("DejaVu Sans", 9, "bold"),
                                        bg=COLOR_CARD, fg=COLOR_TEXT_MUTED, activebackground="#374151",
                                        relief=tk.FLAT, padx=10, pady=3, command=self._toggle_continuous)
        self.continuous_btn.pack(side=tk.RIGHT, padx=4)

        # Pantalla Digital de la Calculadora (OLED Display)
        display_frame = tk.Frame(calc_frame, bg=COLOR_DISPLAY_BG, highlightbackground="#1e293b",
                                 highlightthickness=2, padx=16, pady=12)
        display_frame.pack(fill=tk.X, padx=16, pady=8)

        # Expresión previa / Subdisplay
        self.sub_display = tk.Label(display_frame, text="", font=("DejaVu Sans Mono", 12),
                                    fg=COLOR_TEXT_MUTED, bg=COLOR_DISPLAY_BG, anchor="e")
        self.sub_display.pack(fill=tk.X)

        # Display Principal (Números Grandes)
        self.main_display = tk.Label(display_frame, text="0", font=("DejaVu Sans Mono", 28, "bold"),
                                     fg=COLOR_TEXT_PRIMARY, bg=COLOR_DISPLAY_BG, anchor="e")
        self.main_display.pack(fill=tk.X, pady=(4, 0))

        # Panel de Estado de Voz y Transcripción
        voice_status_frame = tk.Frame(calc_frame, bg=COLOR_CARD, padx=12, pady=8)
        voice_status_frame.pack(fill=tk.X, padx=16, pady=6)

        self.status_badge = tk.Label(voice_status_frame, text="🟢 EN ESPERA", font=("DejaVu Sans", 9, "bold"),
                                     fg=COLOR_ACCENT_GREEN, bg=COLOR_CARD)
        self.status_badge.pack(side=tk.LEFT)

        self.status_msg = tk.Label(voice_status_frame, text="Pulsa el botón 🎙️ o presiona la Barra Espaciadora para dictar",
                                   font=("DejaVu Sans", 9), fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w")
        self.status_msg.pack(side=tk.LEFT, padx=12, fill=tk.X, expand=True)

        # Botón Gigante de Dictado por Voz
        self.mic_btn = tk.Button(calc_frame, text="🎙️  DICTAR POR VOZ  (Hablar)",
                                 font=("DejaVu Sans", 13, "bold"),
                                 bg="#4338ca", fg="#ffffff", activebackground="#4f46e5",
                                 relief=tk.FLAT, pady=10, cursor="hand2",
                                 command=self.toggle_voice_listening)
        self.mic_btn.pack(fill=tk.X, padx=16, pady=(6, 10))

        # Teclado de Botones
        self._build_keypad(calc_frame)

        # Columna Derecha: Panel de Historial de Operaciones
        history_frame = tk.Frame(main_frame, bg=COLOR_SURFACE, width=280,
                                 highlightbackground="#1e293b", highlightthickness=1)
        history_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))
        history_frame.pack_propagate(False)

        hist_header = tk.Frame(history_frame, bg=COLOR_SURFACE)
        hist_header.pack(fill=tk.X, padx=12, pady=12)

        tk.Label(hist_header, text="📜 Historial TARDIS", font=("DejaVu Sans", 11, "bold"),
                 fg=COLOR_ACCENT_BLUE, bg=COLOR_SURFACE).pack(side=tk.LEFT)

        clear_hist_btn = tk.Button(hist_header, text="🗑️", font=("DejaVu Sans", 10),
                                   bg=COLOR_CARD, fg=COLOR_TEXT_MUTED, relief=tk.FLAT,
                                   padx=6, pady=2, command=self._clear_history)
        clear_hist_btn.pack(side=tk.RIGHT)

        # Lista de Historial con Scrollbar
        list_container = tk.Frame(history_frame, bg=COLOR_SURFACE)
        list_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        scrollbar = tk.Scrollbar(list_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.history_listbox = tk.Listbox(list_container, bg=COLOR_DISPLAY_BG, fg=COLOR_TEXT_PRIMARY,
                                          font=("DejaVu Sans Mono", 10), selectbackground="#312e81",
                                          highlightthickness=0, yscrollcommand=scrollbar.set,
                                          activestyle='none')
        self.history_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.history_listbox.yview)
        self.history_listbox.bind("<Double-Button-1>", self._on_history_select)

        # Ayuda de comandos por voz en pie de historial
        help_frame = tk.Frame(history_frame, bg=COLOR_CARD, padx=8, pady=8)
        help_frame.pack(fill=tk.X, padx=12, pady=(0, 12))
        help_text = (
            "🗣️ Ejemplos por voz:\n"
            "• 'cuánto es 50 por 4'\n"
            "• '120 entre 5'\n"
            "• 'raíz cuadrada de 144'\n"
            "• 'seno de 90 más 5'\n"
            "• '20 por ciento de 500'\n"
            "• 'diez al cuadrado'\n"
            "• 'borrar' o 'limpiar'"
        )
        tk.Label(help_frame, text=help_text, font=("DejaVu Sans", 8),
                 fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, justify=tk.LEFT).pack(anchor="w")

    def _build_keypad(self, parent):
        grid_frame = tk.Frame(parent, bg=COLOR_SURFACE)
        grid_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 14))

        buttons = [
            # Fila 0: Científica
            [("sin", "sin("), ("cos", "cos("), ("tan", "tan("), ("√", "sqrt("), ("x²", "**2"), ("xʸ", "^"), ("π", "pi"), ("e", "e")],
            # Fila 1: Edición y operaciones
            [("C", "C"), ("CE", "CE"), ("⌫", "BACKSPACE"), ("(", "("), (")", ")"), ("%", "%"), ("÷", "/"), ("log", "log(")],
            # Fila 2: Números y Operaciones
            [("7", "7"), ("8", "8"), ("9", "9"), ("×", "*"), ("ln", "ln("), ("abs", "abs(")],
            # Fila 3
            [("4", "4"), ("5", "5"), ("6", "6"), ("-", "-"), ("1/x", "1/("), ("x!", "factorial(")],
            # Fila 4
            [("1", "1"), ("2", "2"), ("3", "3"), ("+", "+"), ("(", "("), (")", ")")],
            # Fila 5
            [("±", "NEG"), ("0", "0"), (".", "."), ("=", "=")]
        ]

        # Configurar filas y columnas adaptativas
        for r in range(6):
            grid_frame.rowconfigure(r, weight=1)
        for c in range(6):
            grid_frame.columnconfigure(c, weight=1)

        # Fila 0 (Científica superior - 6 botones principales)
        row0_btns = [("sin", "sin("), ("cos", "cos("), ("tan", "tan("), ("√", "sqrt("), ("x²", "**2"), ("^", "^")]
        for c, (text, val) in enumerate(row0_btns):
            self._create_btn(grid_frame, text, val, 0, c, COLOR_BTN_FN, COLOR_ACCENT_PURPLE)

        # Fila 1
        row1_btns = [("C", "C"), ("CE", "CE"), ("⌫", "BACKSPACE"), ("(", "("), (")", ")"), ("÷", "/")]
        for c, (text, val) in enumerate(row1_btns):
            bg = COLOR_ACCENT_RED if text in ("C", "CE") else COLOR_BTN_OP
            fg = "#ffffff" if text in ("C", "CE") else COLOR_ACCENT_CYAN
            self._create_btn(grid_frame, text, val, 1, c, bg, fg)

        # Fila 2
        row2_btns = [("7", "7"), ("8", "8"), ("9", "9"), ("×", "*"), ("%", "%"), ("π", "pi")]
        for c, (text, val) in enumerate(row2_btns):
            bg = COLOR_BTN_OP if text in ("×", "%", "π") else COLOR_BTN_NUM
            fg = COLOR_ACCENT_CYAN if text in ("×", "%", "π") else COLOR_TEXT_PRIMARY
            self._create_btn(grid_frame, text, val, 2, c, bg, fg)

        # Fila 3
        row3_btns = [("4", "4"), ("5", "5"), ("6", "6"), ("-", "-"), ("log", "log("), ("e", "e")]
        for c, (text, val) in enumerate(row3_btns):
            bg = COLOR_BTN_OP if text in ("-", "log", "e") else COLOR_BTN_NUM
            fg = COLOR_ACCENT_CYAN if text in ("-", "log", "e") else COLOR_TEXT_PRIMARY
            self._create_btn(grid_frame, text, val, 3, c, bg, fg)

        # Fila 4
        row4_btns = [("1", "1"), ("2", "2"), ("3", "3"), ("+", "+"), ("ln", "ln("), ("|x|", "abs(")]
        for c, (text, val) in enumerate(row4_btns):
            bg = COLOR_BTN_OP if text in ("+", "ln", "|x|") else COLOR_BTN_NUM
            fg = COLOR_ACCENT_CYAN if text in ("+", "ln", "|x|") else COLOR_TEXT_PRIMARY
            self._create_btn(grid_frame, text, val, 4, c, bg, fg)

        # Fila 5
        self._create_btn(grid_frame, "±", "NEG", 5, 0, COLOR_BTN_NUM, COLOR_TEXT_PRIMARY)
        self._create_btn(grid_frame, "0", "0", 5, 1, COLOR_BTN_NUM, COLOR_TEXT_PRIMARY)
        self._create_btn(grid_frame, ".", ".", 5, 2, COLOR_BTN_NUM, COLOR_TEXT_PRIMARY)
        
        # Botón igual extendido sobre 3 columnas
        eq_btn = tk.Button(grid_frame, text="=", font=("DejaVu Sans", 18, "bold"),
                           bg=COLOR_ACCENT_GREEN, fg="#000000", activebackground="#34d399",
                           relief=tk.FLAT, cursor="hand2", command=self.calculate)
        eq_btn.grid(row=5, column=3, columnspan=3, sticky="nsew", padx=3, pady=3)

    def _create_btn(self, parent, text, value, row, col, bg, fg):
        btn = tk.Button(parent, text=text, font=("DejaVu Sans", 12, "bold"),
                        bg=bg, fg=fg, activebackground=COLOR_BTN_HOVER, activeforeground="#ffffff",
                        relief=tk.FLAT, cursor="hand2",
                        command=lambda: self._on_btn_click(value))
        btn.grid(row=row, column=col, sticky="nsew", padx=3, pady=3)
        return btn

    def _bind_keyboard(self):
        self.bind("<Return>", lambda e: self.calculate())
        self.bind("<KP_Enter>", lambda e: self.calculate())
        self.bind("<Escape>", lambda e: self._on_btn_click("C"))
        self.bind("<BackSpace>", lambda e: self._on_btn_click("BACKSPACE"))
        self.bind("<space>", lambda e: self.toggle_voice_listening())
        
        # Mapeo de teclas numéricas y operadores
        for char in "0123456789.+-*/()%^":
            self.bind(char, lambda e, c=char: self._append_char(c))

    def _on_btn_click(self, val):
        if val == "=":
            self.calculate()
        elif val == "C":
            self.current_expr = ""
            self.sub_display.config(text="")
            self._update_display("0")
        elif val == "CE":
            self.current_expr = ""
            self._update_display("0")
        elif val == "BACKSPACE":
            self.current_expr = self.current_expr[:-1]
            self._update_display()
        elif val == "NEG":
            if self.current_expr and self.current_expr.startswith("-"):
                self.current_expr = self.current_expr[1:]
            else:
                self.current_expr = "-" + self.current_expr
            self._update_display()
        else:
            self._append_char(val)

    def _append_char(self, char):
        self.current_expr += str(char)
        self._update_display()

    def _update_display(self, override_text=None):
        text = override_text if override_text is not None else (self.current_expr if self.current_expr else "0")
        self.main_display.config(text=text)

    def calculate(self, source_tag="⌨️ Teclado"):
        expr = self.current_expr.strip()
        if not expr:
            return

        try:
            res, clean_expr = evaluate_expression(expr, angle_mode=self.angle_mode)
            res_str = str(res)
            
            # Formato entero si termina en .0
            if res_str.endswith(".0"):
                res_str = res_str[:-2]

            self.sub_display.config(text=f"{clean_expr} =")
            self.main_display.config(text=res_str)
            self.last_result = res_str
            self.current_expr = res_str

            # Agregar al historial
            hist_item = f"{source_tag} {clean_expr} = {res_str}"
            self.history.append((clean_expr, res_str))
            self.history_listbox.insert(0, hist_item)

            # Respuesta por voz hablada si está activa
            if self.voice_feedback_on:
                spoken_phrase = f"El resultado es {res_str}"
                speak_async(spoken_phrase)

            self._set_voice_status("🟢 Cálculo completado", f"Resultado: {res_str}")
        except Exception as e:
            self.sub_display.config(text=f"Error en: {expr}")
            self.main_display.config(text="Error")
            self._set_voice_status("🔴 Error sintáctico", str(e))
            if self.voice_feedback_on:
                speak_async("Hubo un error en la expresión.")

    # ------------------ SISTEMA DE VOZ ------------------
    def toggle_voice_listening(self):
        if self.is_listening:
            self.is_listening = False
            self.mic_btn.config(text="🎙️  DICTAR POR VOZ  (Hablar)", bg="#4338ca")
            self._set_voice_status("🟢 En espera", "Micrófono detenido.")
        else:
            self.is_listening = True
            self.mic_btn.config(text="🔴  ESCUCHANDO... (Habla ahora)", bg="#dc2626")
            self._set_voice_status("🔴 ESCUCHANDO TU VOZ", "Di tu operación, ej: 'veinticinco por cuatro'")
            threading.Thread(target=self._listen_worker, daemon=True).start()

    def _listen_worker(self):
        try:
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
                
                while self.is_listening:
                    try:
                        self.after(0, lambda: self._set_voice_status("🔴 ESCUCHANDO...", "Escuchando sonido ambiental..."))
                        audio = self.recognizer.listen(source, timeout=6, phrase_time_limit=10)
                    except sr.WaitTimeoutError:
                        if not self.continuous_listening:
                            break
                        continue

                    # Procesar reconocimiento
                    self.after(0, lambda: self._set_voice_status("🟡 PROCESANDO VOZ...", "Analizando fonemas y operadores..."))
                    try:
                        raw_text = self.recognizer.recognize_google(audio, language="es-ES")
                        self.after(0, lambda t=raw_text: self._handle_voice_result(t))
                    except sr.UnknownValueError:
                        self.after(0, lambda: self._set_voice_status("🟡 Sin audio claro", "No pude entender lo dicho. Intenta de nuevo."))
                    except sr.RequestError as e:
                        self.after(0, lambda: self._set_voice_status("🔴 Error de red", f"Fallo en servidor de voz: {e}"))

                    if not self.continuous_listening:
                        break

        except Exception as e:
            self.after(0, lambda err=e: self._set_voice_status("🔴 Error de micrófono", str(err)))
        finally:
            self.is_listening = False
            self.after(0, lambda: self.mic_btn.config(text="🎙️  DICTAR POR VOZ  (Hablar)", bg="#4338ca"))

    def _handle_voice_result(self, raw_text: str):
        self._set_voice_status("🟣 RECONOCIDO", f"Dijiste: '{raw_text}'")
        parsed_expr, action = parse_spoken_text_to_math(raw_text)

        if action == "CLEAR":
            self.current_expr = ""
            self.sub_display.config(text="")
            self._update_display("0")
            if self.voice_feedback_on:
                speak_async("Pantalla borrada")
        elif action == "BACKSPACE":
            self.current_expr = self.current_expr[:-1]
            self._update_display()
        elif action == "REPEAT":
            if self.last_result and self.voice_feedback_on:
                speak_async(f"El resultado anterior fue {self.last_result}")
        elif parsed_expr:
            self.current_expr = parsed_expr
            self._update_display()
            self.calculate(source_tag=f"🎤 Voz ('{raw_text}')")

    def _set_voice_status(self, badge: str, message: str):
        color = COLOR_ACCENT_GREEN
        if "ESCUCHANDO" in badge:
            color = COLOR_ACCENT_RED
        elif "PROCESANDO" in badge:
            color = COLOR_ACCENT_AMBER
        elif "RECONOCIDO" in badge:
            color = COLOR_ACCENT_PURPLE
        elif "Error" in badge:
            color = COLOR_ACCENT_RED

        self.status_badge.config(text=badge, fg=color)
        self.status_msg.config(text=message)

    def _toggle_angle_mode(self):
        self.angle_mode = "RAD" if self.angle_mode == "DEG" else "DEG"
        self.deg_btn.config(text=self.angle_mode)

    def _toggle_voice_feedback(self):
        self.voice_feedback_on = not self.voice_feedback_on
        set_voice_enabled(self.voice_feedback_on)
        state_txt = "ON" if self.voice_feedback_on else "OFF"
        color = COLOR_ACCENT_GREEN if self.voice_feedback_on else COLOR_TEXT_MUTED
        self.voice_out_btn.config(text=f"🔊 Audio: {state_txt}", fg=color)

    def _toggle_continuous(self):
        self.continuous_listening = not self.continuous_listening
        state_txt = "ON" if self.continuous_listening else "OFF"
        color = COLOR_ACCENT_CYAN if self.continuous_listening else COLOR_TEXT_MUTED
        self.continuous_btn.config(text=f"🔄 Continuo: {state_txt}", fg=color)

    def _on_history_select(self, event):
        selection = self.history_listbox.curselection()
        if selection:
            idx = selection[0]
            if idx < len(self.history):
                expr, res = self.history[idx]
                self.current_expr = str(res)
                self._update_display()

    def _clear_history(self):
        self.history.clear()
        self.history_listbox.delete(0, tk.END)

if __name__ == "__main__":
    app = TardisVoiceCalculator()
    app.mainloop()

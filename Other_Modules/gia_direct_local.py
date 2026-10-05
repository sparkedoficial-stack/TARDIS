"""
gia_direct_local.py - Suite y Motor de Ejecución Local Directa sin Servidor Web
==============================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana GIA
Permite interacción ultra-rápida, resiliente y de mínima latencia directamente
con el motor LLM local (Ollama) sin depender de servidores web (HTTP/Flask),
eliminando por completo caídas de conexión, bloqueos de puertos y latencia de red.

Modos de uso:
1. Interfaz Gráfica de Escritorio (GUI Cyber-Dark):
   python gia_direct_local.py

2. Modo Consola Interactivo (CLI):
   python gia_direct_local.py --cli

3. Ejecución directa de una consulta (One-shot):
   python gia_direct_local.py --prompt "Explica la teoría causal"

4. Como módulo importable en Python:
   from gia_direct_local import DirectLocalGIA
   gia = DirectLocalGIA()
   print(gia.chat("Hola GIA"))
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

# Importación de bootstrap para arranque garantizado de dependencias
import gia_bootstrap

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Intentar importar agent_context si existe para enriquecimiento causal
try:
    import agent_context as _ctx
    HAS_CTX = True
except Exception:
    HAS_CTX = False

WORKSPACE_DIR = Path(__file__).resolve().parent
DEFAULT_SYSTEM_PROMPT = (
    "Eres GIA-V26-OMNI-LOCAL, Sistema Autónomo y Soberano de Inteligencia Artificial Causal. "
    "Operas en modo LOCAL DIRECTO con máxima eficiencia de cómputo. "
    "Responde siempre en español con precisión, profundidad y rigor."
)


class DirectLocalGIA:
    """
    Cliente y motor directo local con Ollama. No requiere levantar servidor web.
    Maneja dependencias, streaming, memoria de conversación y optimizaciones de hardware.
    """

    def __init__(
        self,
        endpoint: str = gia_bootstrap.DEFAULT_OLLAMA_ENDPOINT,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.4,
        num_ctx: int = 4096
    ):
        self.endpoint = gia_bootstrap.normalize_endpoint(endpoint)
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.history: List[Dict[str, str]] = []
        self._lock = threading.Lock()

        # Garantizar dependencias en el arranque
        self.status = gia_bootstrap.ensure_all_dependencies(preferred_model=model, verbose=False)
        self.model = self.status.get("active_model", model or "llama3.2:3b")

        # Cargar directivas de contexto permanente si están disponibles
        self._refresh_directives()

    def _refresh_directives(self):
        if HAS_CTX:
            try:
                c = _ctx.get()
                if c.get("enabled") and c.get("directives"):
                    self.system_prompt = f"{DEFAULT_SYSTEM_PROMPT}\n\n[DIRECTRICES MAESTRAS]:\n{c['directives']}"
            except Exception:
                pass

    def get_available_models(self) -> List[str]:
        """Obtiene la lista actualizada de modelos instalados en Ollama."""
        return gia_bootstrap.list_local_models(self.endpoint)

    def set_model(self, model_name: str) -> bool:
        """Cambia el modelo activo."""
        with self._lock:
            self.model = model_name
            return True

    def clear_history(self):
        """Limpia el historial de conversación en memoria."""
        with self._lock:
            self.history.clear()

    def _build_messages(self, prompt: str, include_history: bool = True) -> List[Dict[str, str]]:
        messages = [{"role": "system", "content": self.system_prompt}]
        if include_history:
            # Mantener los últimos 8 turnos para economía de contexto
            messages.extend(self.history[-8:])
        messages.append({"role": "user", "content": prompt})
        return messages

    def chat_stream(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        num_ctx: Optional[int] = None
    ) -> Generator[str, None, str]:
        """
        Generador de streaming directo desde el motor soberano. Emite fragmentos de texto en tiempo real.
        """
        import gia_sovereign_engine as _gse
        eng = _gse.get_engine()

        messages = self._build_messages(prompt, include_history=True)
        # Quitar el rol de sistema de messages para pasarlo explícitamente
        conv = [m for m in messages if m.get("role") != "system"]
        temp = temperature if temperature is not None else self.temperature
        ctx = num_ctx if num_ctx is not None else self.num_ctx

        full_reply = []
        try:
            for piece in eng.chat_stream(
                conv,
                model=self.model,
                system=self.system_prompt,
                temperature=temp,
                num_ctx=ctx
            ):
                full_reply.append(piece)
                yield piece
        except Exception as e:
            err_msg = f"\n[Error en motor local soberano]: {e}"
            yield err_msg
            full_reply.append(err_msg)

        final_text = "".join(full_reply)
        with self._lock:
            self.history.append({"role": "user", "content": prompt})
            self.history.append({"role": "assistant", "content": final_text})

        return final_text

    def chat(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        num_ctx: Optional[int] = None
    ) -> str:
        """
        Consulta síncrona directa. Devuelve la respuesta completa generada por el LLM.
        """
        chunks = list(self.chat_stream(prompt, temperature, num_ctx))
        return "".join(chunks)


# =============================================================================
#  MODO CONSOLA INTERACTIVO (CLI)
# =============================================================================

def run_cli(initial_prompt: Optional[str] = None):
    """Ejecuta el chat interactivo en consola con colores y streaming."""
    os.system("")
    c_gold = "\033[93m"
    c_cyan = "\033[96m"
    c_teal = "\033[92m"
    c_dim = "\033[90m"
    c_err = "\033[91m"
    c_end = "\033[0m"

    print(f"{c_gold}===================================================================={c_end}")
    print(f"{c_gold}   GIA DIRECT LOCAL RUNNER · GODWORKS SYSTEM v26.4{c_end}")
    print(f"{c_gold}   Ruta de Inferencia Local Directa (Sin Servidor Web Activo){c_end}")
    print(f"{c_gold}===================================================================={c_end}")
    print(f"{c_dim}[Iniciando dependencias maestras...]{c_end}")

    gia = DirectLocalGIA()
    print(f"[ESTADO] Modelo Activo: {c_cyan}{gia.model}{c_end} | Endpoint: {gia.endpoint}")
    print(f"{c_dim}Comandos: /salir, /clear, /model <nombre>, /models{c_end}\n")

    if initial_prompt:
        print(f"{c_gold}TÚ:{c_end} {initial_prompt}")
        print(f"{c_cyan}GIA ({gia.model}):{c_end} ", end="", flush=True)
        for chunk in gia.chat_stream(initial_prompt):
            print(chunk, end="", flush=True)
        print("\n")
        return

    while True:
        try:
            user_input = input(f"{c_gold}TÚ > {c_end}").strip()
            if not user_input:
                continue

            if user_input.lower() in ("/salir", "/exit", "/quit", "/bye"):
                print(f"{c_dim}Cerrando sesión local directa.{c_end}")
                break

            if user_input.lower() in ("/clear", "/cls"):
                gia.clear_history()
                print(f"{c_teal}✔ Historial local reiniciado.{c_end}\n")
                continue

            if user_input.lower() in ("/models", "/list"):
                models = gia.get_available_models()
                print(f"{c_teal}Modelos disponibles:{c_end} {', '.join(models)}\n")
                continue

            if user_input.lower().startswith("/model "):
                new_m = user_input[7:].strip()
                if new_m:
                    gia.set_model(new_m)
                    print(f"{c_teal}✔ Modelo cambiado a: {new_m}{c_end}\n")
                continue

            print(f"{c_cyan}GIA ({gia.model}) > {c_end}", end="", flush=True)
            for chunk in gia.chat_stream(user_input):
                print(chunk, end="", flush=True)
            print("\n")

        except (KeyboardInterrupt, EOFError):
            print(f"\n{c_dim}Interrupción detectada. Saliendo.{c_end}")
            break


# =============================================================================
#  INTERFAZ GRÁFICA DE ESCRITORIO (GUI CYBER-DARK NATIVA)
# =============================================================================

def run_gui():
    """Ejecuta la interfaz gráfica de escritorio autónoma de GIA."""
    import tkinter as tk
    from tkinter import ttk, messagebox

    # Asegurar dependencias de inicio
    dep_status = gia_bootstrap.ensure_all_dependencies(verbose=False)

    gia = DirectLocalGIA()

    root = tk.Tk()
    root.title("GIA · Direct Local Sovereign Interface v26.4")
    root.geometry("1060x780")
    root.minsize(800, 600)

    # Paleta de colores Cyber-Dark
    BG_DARK = "#080d1a"
    BG_CARD = "#0f172a"
    BG_INPUT = "#1e293b"
    ACCENT_GOLD = "#f59e0b"
    ACCENT_TEAL = "#06b6d4"
    ACCENT_GREEN = "#10b981"
    TXT_MAIN = "#f8fafc"
    TXT_MUTED = "#94a3b8"

    root.configure(bg=BG_DARK)

    # --- ENCABEZADO SUPERIOR ---
    header_frame = tk.Frame(root, bg=BG_CARD, height=64, padx=16, pady=10)
    header_frame.pack(fill="x", side="top")

    title_box = tk.Frame(header_frame, bg=BG_CARD)
    title_box.pack(side="left")

    lbl_title = tk.Label(
        title_box,
        text="GIA DIRECT LOCAL",
        font=("Segoe UI", 13, "bold"),
        fg=ACCENT_GOLD,
        bg=BG_CARD
    )
    lbl_title.pack(anchor="w")

    status_text = "🟢 OLLAMA ONLINE (DIRECT SOCKET)" if dep_status.get("ollama_alive") else "🟡 INICIANDO OLLAMA..."
    lbl_status = tk.Label(
        title_box,
        text=status_text,
        font=("Segoe UI", 8, "bold"),
        fg=ACCENT_GREEN if dep_status.get("ollama_alive") else ACCENT_GOLD,
        bg=BG_CARD
    )
    lbl_status.pack(anchor="w")

    # Controles en el encabezado (Selector de modelo, sliders, botones)
    controls_box = tk.Frame(header_frame, bg=BG_CARD)
    controls_box.pack(side="right")

    tk.Label(controls_box, text="Modelo:", font=("Segoe UI", 9), fg=TXT_MUTED, bg=BG_CARD).pack(side="left", padx=(0, 6))

    models = gia.get_available_models()
    if not models:
        models = [gia.model]

    model_var = tk.StringVar(value=gia.model)
    model_combo = ttk.Combobox(controls_box, textvariable=model_var, values=models, width=18, state="readonly")
    model_combo.pack(side="left", padx=(0, 14))

    def on_model_change(event=None):
        m = model_var.get()
        gia.set_model(m)
        add_system_message(f"Modelo activo cambiado a: {m}")

    model_combo.bind("<<ComboboxSelected>>", on_model_change)

    btn_clear = tk.Button(
        controls_box,
        text="Limpiar Chat",
        font=("Segoe UI", 9),
        bg="#334155",
        fg=TXT_MAIN,
        activebackground="#475569",
        activeforeground=TXT_MAIN,
        relief="flat",
        padx=10,
        pady=3,
        command=lambda: clear_chat_view()
    )
    btn_clear.pack(side="left", padx=4)

    # --- ÁREA CENTRAL DE CONVERSACIÓN ---
    chat_container = tk.Frame(root, bg=BG_DARK, padx=16, pady=12)
    chat_container.pack(fill="both", expand=True)

    chat_text = tk.Text(
        chat_container,
        bg=BG_CARD,
        fg=TXT_MAIN,
        insertbackground=ACCENT_TEAL,
        font=("Segoe UI", 10),
        wrap="word",
        relief="flat",
        padx=14,
        pady=14,
        selectbackground="#3b82f6",
        selectforeground="#ffffff"
    )
    chat_scroll = tk.Scrollbar(chat_container, command=chat_text.yview, bg=BG_DARK)
    chat_text.configure(yscrollcommand=chat_scroll.set)

    chat_scroll.pack(side="right", fill="y")
    chat_text.pack(side="left", fill="both", expand=True)

    # Configuración de estilos en el texto
    chat_text.tag_config("user_tag", foreground=ACCENT_GOLD, font=("Segoe UI", 10, "bold"))
    chat_text.tag_config("assistant_tag", foreground=ACCENT_TEAL, font=("Segoe UI", 10, "bold"))
    chat_text.tag_config("system_tag", foreground=TXT_MUTED, font=("Segoe UI", 9, "italic"))
    chat_text.tag_config("code_tag", foreground="#38bdf8", font=("Consolas", 10), background="#090d16")
    chat_text.tag_config("body_tag", foreground=TXT_MAIN, font=("Segoe UI", 10))

    # --- PANEL INFERIOR DE ENTRADA ---
    input_frame = tk.Frame(root, bg=BG_CARD, padx=16, pady=12)
    input_frame.pack(fill="x", side="bottom")

    input_text = tk.Text(
        input_frame,
        bg=BG_INPUT,
        fg=TXT_MAIN,
        insertbackground=ACCENT_GOLD,
        font=("Segoe UI", 10),
        height=3,
        relief="flat",
        padx=10,
        pady=8,
        wrap="word"
    )
    input_text.pack(fill="x", side="left", expand=True, padx=(0, 12))
    input_text.focus_set()

    btn_send = tk.Button(
        input_frame,
        text="ENVIAR\n(Enter)",
        font=("Segoe UI", 9, "bold"),
        bg=ACCENT_GOLD,
        fg="#000000",
        activebackground="#fbbf24",
        activeforeground="#000000",
        relief="flat",
        width=10,
        command=lambda: handle_send()
    )
    btn_send.pack(side="right", fill="y")

    # --- FUNCIONES DE INTERFAZ ---

    def add_system_message(msg: str):
        chat_text.config(state="normal")
        chat_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n\n", "system_tag")
        chat_text.config(state="disabled")
        chat_text.see("end")

    def clear_chat_view():
        gia.clear_history()
        chat_text.config(state="normal")
        chat_text.delete("1.0", "end")
        chat_text.config(state="disabled")
        add_system_message("Historial limpiado. Motor local listo.")

    def handle_send(event=None):
        msg = input_text.get("1.0", "end").strip()
        if not msg:
            return "break"

        input_text.delete("1.0", "end")
        btn_send.config(state="disabled", text="GENERANDO...")

        chat_text.config(state="normal")
        chat_text.insert("end", f"👤 TÚ:\n", "user_tag")
        chat_text.insert("end", f"{msg}\n\n", "body_tag")
        chat_text.insert("end", f"⚡ GIA ({gia.model}):\n", "assistant_tag")
        chat_text.config(state="disabled")
        chat_text.see("end")

        def _worker():
            start_t = time.time()
            try:
                for chunk in gia.chat_stream(msg):
                    def _append(ch=chunk):
                        chat_text.config(state="normal")
                        chat_text.insert("end", ch, "body_tag")
                        chat_text.config(state="disabled")
                        chat_text.see("end")
                    root.after(0, _append)

                elapsed = time.time() - start_t
                def _finish():
                    chat_text.config(state="normal")
                    chat_text.insert("end", f"\n\n", "body_tag")
                    chat_text.config(state="disabled")
                    chat_text.see("end")
                    btn_send.config(state="normal", text="ENVIAR\n(Enter)")
                    lbl_status.config(text=f"🟢 OLLAMA ONLINE ({elapsed:.2f}s)", fg=ACCENT_GREEN)
                root.after(0, _finish)

            except Exception as ex:
                def _error(err=str(ex)):
                    chat_text.config(state="normal")
                    chat_text.insert("end", f"\n⚠️ Error: {err}\n\n", "system_tag")
                    chat_text.config(state="disabled")
                    btn_send.config(state="normal", text="ENVIAR\n(Enter)")
                root.after(0, _error)

        threading.Thread(target=_worker, daemon=True).start()
        return "break"

    def handle_return_key(event):
        if not event.state & 0x0001:  # Sin Shift
            return handle_send()
        return None

    input_text.bind("<Return>", handle_return_key)

    # Mensaje inicial de bienvenida
    add_system_message("Ruta Directa Local Soberana activada. Conexión directa a Ollama sin servidor web.")

    root.mainloop()


# =============================================================================
#  PUNTO DE ENTRADA PRINCIPAL
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="GIA Direct Local Sovereign Runner v26.4")
    parser.add_argument("--cli", action="store_true", help="Iniciar en modo consola interactiva")
    parser.add_argument("--prompt", type=str, default=None, help="Ejecutar una consulta directa y salir")
    parser.add_argument("--model", type=str, default=None, help="Especificar modelo LLM local")
    parser.add_argument("--test", type=str, default=None, help="Prueba rápida de inferencia")
    args = parser.parse_args()

    if args.prompt:
        run_cli(initial_prompt=args.prompt)
    elif args.test:
        print(f"[TEST] Ejecutando prueba local directa: '{args.test}'")
        gia = DirectLocalGIA(model=args.model)
        resp = gia.chat(args.test)
        print(f"[TEST] Respuesta recibida ({len(resp)} caracteres):\n{resp}")
    elif args.cli:
        run_cli()
    else:
        # Por defecto abrir la interfaz gráfica
        run_gui()


if __name__ == "__main__":
    main()

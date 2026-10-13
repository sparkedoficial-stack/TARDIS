#!/usr/bin/env python3
"""
TARDIS Sovereign CLI · Consola de Terminal Universal
Permite consultar telemetría, chatear con el núcleo soberano (Dolphin 3.0 / Ollama), reactivar botones
y controlar el sistema operativo directamente desde cualquier shell.
"""

import sys
import os
import json
import argparse
import urllib.request
import urllib.error
import shutil
import subprocess

PORT = 8757
TOKEN = "REDACTED"
API_BASE = f"http://127.0.0.1:{PORT}"

C_RESET = "\033[0m"
C_CYAN = "\033[96m"
C_BLUE = "\033[94m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_GOLD = "\033[38;5;220m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"

def api_request(endpoint: str, method: str = "GET", payload: dict = None, timeout: int = 15):
    url = f"{API_BASE}{endpoint}"
    if "?" in endpoint:
        url += f"&key={TOKEN}"
    else:
        url += f"?key={TOKEN}"

    data = json.dumps(payload).encode("utf-8") if payload else None
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"No se pudo conectar con TARDIS en {API_BASE}: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def print_banner():
    print(f"{C_CYAN}{C_BOLD}")
    print("      ▲")
    print("    ▲ ▲ ▲   T A R D I S   C L I   v 2 6 . 4")
    print("   ▲ ▲ ▲ ▲  Consola Soberana de Sistema")
    print(f"{C_RESET}")

def cmd_status():
    print(f"{C_BOLD}--- TELEMETRÍA Y ESTADO DE TARDIS ---{C_RESET}")
    res = api_request("/api/health")
    if res.get("status") == "ok" or res.get("ok"):
        print(f"  {C_GREEN}● Servidor Central:{C_RESET} ACTIVO ({API_BASE})")
        print(f"  {C_CYAN}  Modelo Activo:{C_RESET}    {res.get('active_model', res.get('model', 'TARDIS-NEURAL-SPACE-KAIJU'))}")
        print(f"  {C_CYAN}  Versión API:{C_RESET}      {res.get('version', '26.4')}")
        print(f"  {C_CYAN}  Nodos Activos:{C_RESET}    {res.get('nodes_online', 1)}")
    else:
        print(f"  {C_RED}○ Servidor Central:{C_RESET} INACTIVO ({res.get('error')})")

    # Ollama check
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as r:
            tags = json.loads(r.read().decode("utf-8"))
            models = [m.get("name") for m in tags.get("models", [])]
            print(f"  {C_GREEN}● Motor Ollama:{C_RESET}    ACTIVO (Modelos: {', '.join(models[:3])})")
    except Exception:
        print(f"  {C_YELLOW}○ Motor Ollama:{C_RESET}    INACTIVO o no accesible en 11434")

    # Companion check
    res_comp = subprocess.run(["pgrep", "-f", "tardis_desktop_companion.py"], stdout=subprocess.PIPE)
    if res_comp.returncode == 0:
        print(f"  {C_GREEN}● Asistente Flotante:{C_RESET} ACTIVO sobre el Escritorio OS")
    else:
        print(f"  {C_DIM}○ Asistente Flotante: Inactivo (ejecuta 'tardis companion'){C_RESET}")

def cmd_chat(message: str):
    active_m = os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU")
    m_label = active_m

    # Ejecutar petición con Barra de Avance Soberana TARDIS
    bar = None
    try:
        from tardis_progress import TemporalProgressBar, time_estimator
        est_sec = time_estimator.estimate(message, complexity=2, mode="gemini", model="tardis-kaiju")
        bar = TemporalProgressBar(
            prompt=message,
            estimated_duration=est_sec,
            engine_label="TARDIS SOBERANO",
            model_name=m_label,
            complexity_label="Inferencia Causal Línea Cero"
        )
        bar.start()
    except Exception:
        print(f"{C_DIM}Consultando a {m_label} en TARDIS...{C_RESET}")

    res = api_request("/api/chat", method="POST", payload={
        "message": message,
        "stream": False,
        "num_predict": 400
    }, timeout=60)

    if bar:
        bar.finish(returncode=0 if "reply" in res else 1)

    if "reply" in res:
        print(f"\n{C_GOLD}{C_BOLD}▲ TARDIS ({m_label}):{C_RESET}\n{res['reply']}\n")
    else:
        print(f"{C_RED}Error:{C_RESET} {res.get('error', 'Sin respuesta')}")

def cmd_reactivate():
    print(f"{C_CYAN}⚡ Reactivando todos los botones y subsistemas de hardware y software...{C_RESET}")
    res = api_request("/api/system/buttons/auto_activate_all", method="POST")
    if res.get("ok"):
        count = res.get("activated_count", 63)
        print(f"{C_GREEN}✓ Éxito: {count} subsistemas y botones activados.{C_RESET}")
    else:
        print(f"{C_YELLOW}Respuesta:{C_RESET} {res}")

def cmd_analyze():
    print(f"{C_CYAN}🧠 Analizando estructura conversacional y causal con TARDIS...{C_RESET}")
    subprocess.run([sys.executable, "/home/timemachine/Escritorio/GODWORKS SYSTEM/tardis_conversation_analyzer.py"])

def cmd_animate():
    print(f"{C_CYAN}🎬 Sintetizando videos animados de todas las fórmulas con TARDIS ChronoVision...{C_RESET}")
    subprocess.run([sys.executable, "/home/timemachine/Escritorio/GODWORKS SYSTEM/tardis_formula_animator.py"])

def cmd_vp(prompt: str, duration: float = 5.0):
    print(f"{C_CYAN}{C_BOLD}🎨 [CHRONOVISION PIXEL ART 1080P60 · COMANDO /vp]{C_RESET}")
    print(f"  • Concepto:       {prompt}")
    print(f"  • Arquitectura:   Procedural Nano Banana Blueprint [Sujeto + Acción + Contexto + Estilo]")
    print(f"  • Resolución:     1080P Full HD (1920x1080) | Tasa: 60 FPS Nativos")
    print(f"  • Duración:       {duration}s | Aceleración: NVIDIA NVENC Hardware\n")
    try:
        from core.tardis_vp_engine import generate_vp_pixelart_video
        res = generate_vp_pixelart_video(prompt, duration_sec=duration)
        print(f"\n{C_GREEN}{C_BOLD}✓ Síntesis Procedural Pixel Art 1080P60 Completada:{C_RESET}")
        print(f"  ● Concepto:       {res.get('concept', prompt)}")
        print(f"  ● Sujeto:         {res.get('subject', 'Entidad procedural central')}")
        print(f"  ● Acción:         {res.get('action', 'Evolución dinámica continua')}")
        print(f"  ● Contexto:       {res.get('context', 'Atmósfera y entorno cinemático')}")
        print(f"  ● Estilo:         {res.get('art_style', 'Pixel Art 1080P60')}")
        if res.get('formula_latex'):
            print(f"  ● Ecuación:       {res['formula_latex']}")
        if res.get('spectral_research'):
            print(f"  ● Rigor Espectral:{res['spectral_research']}")
        print(f"  ● Resolución:     {res['resolution']}")
        print(f"  ● Tasa / Cuadros: {res['framerate']} FPS Nativos ({int(res['framerate'] * res['duration_sec'])} cuadros)")
        print(f"  ● Boceto 1080P:   {res['sketch_image_1080p']}")
        print(f"  ● Video MP4 60p:  {res['video_path']} ({res['file_size_mb']} MB)")
        print(f"  ● Sonificación:   Multiplexada en MP4 con frecuencias cuánticas")
        print(f"  ● Tiempo Total:   {res['elapsed_seconds']}s")
    except Exception as e:
        print(f"{C_RED}❌ Error generando video Pixel Art:{C_RESET} {e}")

def cmd_v(prompt: str, frames: int = 60, fast: bool = True):
    mode_lbl = "Procedural GPU Core (Nano Banana Blueprint · NVENC 60 FPS)" if fast else "Blender 5.0.1 (Cycles / EEVEE Next PBR)"
    print(f"{C_CYAN}{C_BOLD}🌌 [CHRONOVISION 3D HYPER-PHYSICS · COMANDO /v]{C_RESET}")
    print(f"  • Cuestionamiento / Teoría: {prompt}")
    print(f"  • Motor:          {mode_lbl}")
    print(f"  • Cuadros:        {frames} frames @ 60 FPS Nativos\n")
    try:
        from core.tardis_hyper_physics_animator import TardisHyperPhysicsAnimator
        animator = TardisHyperPhysicsAnimator.get_instance()
        q = f"{prompt} --fast" if fast and "--fast" not in prompt and "--procedural" not in prompt else prompt
        mp4_path, gif_path, meta = animator.generate_physics_video(
            query=q,
            frames=frames,
            fps=60,
            ported_fps=60,
            width=1920,
            height=1080,
            hdr=False
        )
        print(f"\n{C_GREEN}{C_BOLD}✓ Síntesis de Física 3D Procedural Completada:{C_RESET}")
        print(f"  ● Título:         {meta['title']}")
        print(f"  ● Dominio:        {meta.get('domain', 'Física Teórica')} · {meta.get('category', 'General')}")
        print(f"  ● Ecuación:       {meta['formula_latex']}")
        print(f"  ● Abstracción:    {meta.get('abstraction_level', 'Simulación Geométrica 3D')}")
        print(f"  ● Topología 3D:   {meta.get('topology_type', 'procedural')}")
        print(f"  ● Motor:          {meta.get('render_engine')}")
        print(f"  ● Resolución:     {meta['resolution']} @ {meta['fps']} FPS Nativos ({meta['frames']} frames)")
        print(f"  ● Video MP4 60p:  {meta['mp4_path']} ({meta['size_mb']} MB)")
        print(f"  ● Preview GIF:    {meta['gif_path']}")
        print(f"  ● Sonificación:   Multiplexada en MP4 con frecuencias cuánticas")
        print(f"  ● Tiempo Total:   {meta['elapsed_seconds']}s")
    except Exception as e:
        print(f"{C_RED}❌ Error generando video de física /v:{C_RESET} {e}")

def cmd_explain_screen():
    print(f"{C_CYAN}📸 Capturando pantalla de escritorio y analizando con IA...{C_RESET}")
    res = api_request("/api/system/companion/explain_os_screen", method="POST", payload={}, timeout=35)
    if "explanation" in res:
        print(f"\n{C_GREEN}{C_BOLD}▲ Análisis de Pantalla OS:{C_RESET}\n{res['explanation']}\n")
    else:
        print(f"{C_RED}Error analizando pantalla:{C_RESET} {res.get('error', 'Sin datos')}")

def interactive_repl():
    print_banner()
    print(f"{C_DIM}Escribe tu consulta para chatear con el núcleo soberano, o comandos especiales:")
    print("  /status      - Ver salud de servidores")
    print("  /reactivate  - Reactivar todos los botones y módulos")
    print("  /analyze     - Analizar estructura causal de la conversación")
    print("  /animate     - Sintetizar videos animados de todas las fórmulas")
    print("  /v <teoría>  - Sintetizar simulación de física 3D procedural @ 60 FPS (Nano Banana)")
    print("  /vp <texto>  - Generar video Pixel Art hiper-realista a 1080P @ 60 FPS (Nano Banana)")
    print("  /screen      - Explicar lo que hay en tu pantalla")
    print("  /companion   - Abrir el asistente flotante en tu escritorio")
    print(f"  /exit        - Salir de la consola{C_RESET}\n")

    while True:
        try:
            line = input(f"{C_CYAN}{C_BOLD}TARDIS > {C_RESET}").strip()
            if not line:
                continue
            if line in ("/exit", "exit", "quit", ":q"):
                print(f"{C_GREEN}Hasta luego.{C_RESET}")
                break
            elif line in ("/status", "status"):
                cmd_status()
            elif line in ("/reactivate", "reactivate"):
                cmd_reactivate()
            elif line in ("/analyze", "analyze"):
                cmd_analyze()
            elif line in ("/animate", "animate"):
                cmd_animate()
            elif line.startswith("/v ") or line.startswith("v "):
                arg_v = line.split(" ", 1)[1].strip()
                cmd_v(arg_v)
            elif line in ("/v", "v"):
                cmd_v("kerr_black_hole")
            elif line.startswith("/vp ") or line.startswith("vp "):
                arg_vp = line.split(" ", 1)[1].strip()
                cmd_vp(arg_vp)
            elif line in ("/vp", "vp"):
                cmd_vp("Agujero Negro de Kerr con Disco de Acrecion")
            elif line in ("/screen", "screen"):
                cmd_explain_screen()
            elif line in ("/companion", "companion"):
                subprocess.Popen(["/home/timemachine/Escritorio/GODWORKS SYSTEM/launch_tardis_companion.sh"])
                print(f"{C_GREEN}✓ Asistente flotante lanzado.{C_RESET}")
            else:
                cmd_chat(line)
        except (KeyboardInterrupt, EOFError):
            print(f"\n{C_GREEN}Sesión finalizada.{C_RESET}")
            break

def cmd_voice(subcmd: str = "status", arg: str = None):
    print(f"{C_BOLD}--- GESTIÓN DE MENSAJES DE VOZ RECURRENTES ---{C_RESET}")
    if subcmd in ("status", "estado"):
        res = api_request("/api/telegram/voice_recurring")
        st_lbl = f"{C_GREEN}ACTIVO 24/7{C_RESET}" if (res.get("running") and res.get("enabled")) else f"{C_YELLOW}PAUSADO{C_RESET}"
        print(f"  ● Estado:       {st_lbl}")
        print(f"  ● Intervalo:    Cada {res.get('interval_minutes')} minutos ({res.get('interval_seconds')}s)")
        print(f"  ● Modo:         {str(res.get('mode', '')).upper()}")
        print(f"  ● Voz:          {res.get('voice_id')}")
        print(f"  ● Próximo Envío: en {res.get('next_dispatch_in_seconds')}s")
        print(f"  ● Despachos:    {res.get('total_dispatches')}")
    elif subcmd in ("on", "start", "activar"):
        mins = float(arg) if arg and arg.replace(".", "", 1).isdigit() else None
        payload = {"action": "start", "enabled": True}
        if mins:
            payload["interval_minutes"] = mins
        res = api_request("/api/telegram/voice_recurring", method="POST", payload=payload)
        print(f"  {C_GREEN}✓ Mensajes de voz recurrentes activados.{C_RESET}")
    elif subcmd in ("off", "stop", "desactivar"):
        res = api_request("/api/telegram/voice_recurring", method="POST", payload={"action": "stop", "enabled": False})
        print(f"  {C_YELLOW}✓ Mensajes de voz recurrentes pausados.{C_RESET}")
    elif subcmd in ("now", "ahora", "send", "despachar"):
        print(f"{C_CYAN}🎙️ Despachando nota de voz al instante...{C_RESET}")
        res = api_request("/api/telegram/voice_recurring", method="POST", payload={"action": "now", "mode": arg})
        if res.get("voice_sent"):
            print(f"  {C_GREEN}✓ Nota de voz enviada con éxito ({res.get('mode')}).{C_RESET}")
        else:
            print(f"  {C_YELLOW}Resultado:{C_RESET} {res}")

def cmd_infinite(task_str: str):
    print(f"{C_CYAN}{C_BOLD}🛸 [TARDIS INFINITE CODE] Fusión Cuádruple de Frontera:{C_RESET}")
    print(f"  • Gemini Flash High (Scout) + Gemini Pro High (Arquitectura) + Claude Sonnet (Síntesis) + Claude Opus (Apex)")
    print(f"  • Acelerador Externo: Chinese Cloud API (300+ tok/s) | Respaldo: Núcleo Soberano Kaiju\n")
    print(f"{C_GOLD}Tarea:{C_RESET} {task_str}")
    res = api_request("/api/tardis/infinite_code/execute", method="POST", payload={"task": task_str, "background": False}, timeout=600)
    if res.get("ok"):
        print(f"\n{C_GREEN}✔ Síntesis completada con éxito en {res.get('elapsed_seconds', 0)}s:{C_RESET}")
        print(res.get("summary", ""))
    else:
        print(f"\n{C_RED}❌ Error en Infinite Code:{C_RESET} {res.get('error')}")

def cmd_phone(subcmd: str, extra_args: list = None):
    extra = extra_args or []
    sub = (subcmd or "status").lower()

    if sub in ("status", "estado", "info"):
        print(f"{C_CYAN}{C_BOLD}📱 [TARDIS POCKET :: TELEMETRÍA Y CONTROL MÓVIL]{C_RESET}")
        res = api_request("/api/pocket/telephony")
        if res.get("ok"):
            conn = res.get("connection", {})
            tel = res.get("telephony", {})
            pkt = res.get("pocket", {})
            bat = pkt.get("battery", {})
            sim_ok = tel.get("sim_present", False)
            sim_str = f"{C_GREEN}PRESENTE{C_RESET}" if sim_ok else f"{C_YELLOW}SIN SIM ({tel.get('sim_state')}){C_RESET}"
            adb_str = f"{C_GREEN}CONECTADO ({conn.get('transport')}){C_RESET}" if conn.get("adb_connected") else f"{C_RED}DESCONECTADO{C_RESET}"
            fwd_str = f"{C_GREEN}8080 OK{C_RESET}" if conn.get("forward_8080") else f"{C_RED}8080 FAIL{C_RESET}"
            rev_str = f"{C_GREEN}8757 OK{C_RESET}" if conn.get("reverse_8757") else f"{C_RED}8757 FAIL{C_RESET}"

            print(f"  ● Dispositivo:    {C_BOLD}{res.get('device')}{C_RESET} ({res.get('serial')})")
            print(f"  ● Enlace ADB:     {adb_str}")
            print(f"  ● Túneles:        {fwd_str} | {rev_str}")
            print(f"  ● Tarjeta SIM:    {sim_str}")
            print(f"  ● Operador:       {tel.get('operator') or 'Sin operador'} (Red: {tel.get('network_type')})")
            print(f"  ● Batería Móvil:  {bat.get('level', '?')}% ({'Cargando ⚡' if bat.get('charging') else 'Batería 🔋'})")
            print(f"  ● Ruta Activa:    {pkt.get('route_mode')} ({pkt.get('client_ip')})")
            print(f"  ● Modo RIL:       {C_GREEN}{tel.get('telephony_subsystem')}{C_RESET}")
        else:
            print(f"  {C_RED}❌ Error consultando estado móvil:{C_RESET} {res.get('error')}")

    elif sub in ("call", "llamar", "marcar"):
        if not extra:
            print(f"{C_YELLOW}Uso:{C_RESET} tardis phone call <número>")
            return
        num = extra[0]
        print(f"{C_CYAN}📞 Marcando a {num} a través de la red celular de TARDIS POCKET...{C_RESET}")
        res = api_request("/api/pocket/call", method="POST", payload={"number": num})
        if res.get("ok"):
            print(f"  {C_GREEN}✓ Llamada iniciada exitosamente hacia {num}.{C_RESET}")
        else:
            print(f"  {C_RED}❌ Error al llamar:{C_RESET} {res.get('result', {}).get('error', res.get('error'))}")

    elif sub in ("hangup", "colgar", "end"):
        print(f"{C_CYAN}📴 Cortando llamada activa...{C_RESET}")
        res = api_request("/api/pocket/hangup", method="POST", payload={})
        if res.get("ok"):
            print(f"  {C_GREEN}✓ Llamada finalizada.{C_RESET}")
        else:
            print(f"  {C_YELLOW}Resultado:{C_RESET} {res}")

    elif sub in ("answer", "contestar"):
        res = api_request("/api/pocket/answer", method="POST", payload={})
        print(f"  {C_GREEN}✓ Llamada contestada.{C_RESET}" if res.get("ok") else f"  {C_RED}❌ Error:{C_RESET} {res}")

    elif sub in ("sms", "texto"):
        if len(extra) < 2:
            print(f"{C_YELLOW}Uso:{C_RESET} tardis phone sms <número> <mensaje>")
            return
        num = extra[0]
        msg = " ".join(extra[1:])
        print(f"{C_CYAN}📱 Enviando SMS a {num} vía tarjeta SIM TARDIS POCKET...{C_RESET}")
        res = api_request("/api/sms/send", method="POST", payload={"to": num, "message": msg, "provider": "tardis_pocket"})
        if res.get("ok") or res.get("success"):
            print(f"  {C_GREEN}✓ SMS enviado satisfactoriamente.{C_RESET}")
        else:
            print(f"  {C_RED}❌ Error al enviar SMS:{C_RESET} {res.get('error')}")

    elif sub in ("data", "datos"):
        mode = extra[0].lower() if extra else "on"
        enable = mode in ("on", "enable", "activar", "1", "true")
        print(f"{C_CYAN}📶 Configurando datos móviles ({'ACTIVAR' if enable else 'DESACTIVAR'})...{C_RESET}")
        res = api_request("/api/pocket/data", method="POST", payload={"enable": enable})
        print(f"  {C_GREEN}✓ Datos móviles actualizados.{C_RESET}" if res.get("ok") else f"  {C_RED}❌ Error:{C_RESET} {res}")

    elif sub in ("tether", "anclaje"):
        mode = extra[0].lower() if extra else "on"
        enable = mode in ("on", "enable", "activar", "1", "true")
        print(f"{C_CYAN}🔄 Configurando USB Tethering ({'ACTIVAR' if enable else 'DESACTIVAR'})...{C_RESET}")
        res = api_request("/api/pocket/tether", method="POST", payload={"enable": enable})
        print(f"  {C_GREEN}✓ Anclaje USB actualizado.{C_RESET}" if res.get("ok") else f"  {C_RED}❌ Error:{C_RESET} {res}")

    elif sub in ("connect", "conectar"):
        print(f"{C_CYAN}🛰️ Comprobando y asegurando túnel con TARDIS POCKET...{C_RESET}")
        res = api_request("/api/pocket/connect", method="POST", payload={})
        print(f"  {C_GREEN}✓ Vínculo asegurado:{C_RESET} {res}")

def cmd_visual(sub: str, extra: list):
    try:
        from core.visual_intelligence_engine import get_visual_intelligence_engine
        vie = get_visual_intelligence_engine()
    except Exception as e:
        print(f"{C_RED}❌ Error importando Inteligencia Visual:{C_RESET} {e}")
        return

    sub = (sub or "status").lower()
    if sub in ("status", "estado"):
        st = vie.get_status()
        print(f"\n{C_CYAN}{C_BOLD}👁️ --- TARDIS :: INTELIGENCIA VISUAL ---{C_RESET}")
        print(f"  {C_GREEN}● Estado:{C_RESET}             {st.get('status').upper()}")
        print(f"  {C_CYAN}  Motor:{C_RESET}              {st.get('engine')}")
        print(f"  {C_CYAN}  Orquestador:{C_RESET}        {st.get('orchestrator')}")
        print(f"  {C_CYAN}  Whisper LPU:{C_RESET}        {st.get('whisper_accel')}")
        print(f"  {C_CYAN}  OCR Pytesseract:{C_RESET}    {'Listo' if st.get('ocr_ready') else 'No disponible'}")
        print(f"  {C_CYAN}  Videos en Bóveda:{C_RESET}   {st.get('stored_videos_count')}")
        print(f"  {C_CYAN}  Imágenes en Bóveda:{C_RESET} {st.get('stored_images_count')}")
        print(f"  {C_CYAN}  Bóveda Videos:{C_RESET}      {st.get('vault_dir')}")

    elif sub in ("list", "videos", "listar"):
        vids = vie.list_stored_videos(limit=15)
        print(f"\n{C_CYAN}{C_BOLD}📂 --- BÓVEDA DE VIDEOS ALMACENADOS ({len(vids)}) ---{C_RESET}")
        for v in vids:
            print(f"  {C_GREEN}🎬 [{v.get('id')}]{C_RESET} {v.get('duration')}s ({v.get('width')}x{v.get('height')})")
            print(f"     {C_DIM}Remitente: {v.get('user_name')} | {v.get('created_at')[:16]}{C_RESET}")
            print(f"     {C_YELLOW}Resumen:{C_RESET} {v.get('summary', '')[:120]}...\n")

    elif sub in ("analyze", "analizar", "ver"):
        if not extra:
            print(f"{C_YELLOW}Uso: tardis visual analyze <ruta_del_video_o_imagen> [caption]{C_RESET}")
            return
        from pathlib import Path
        target = Path(extra[0])
        caption = " ".join(extra[1:]) if len(extra) > 1 else ""
        if not target.exists():
            print(f"{C_RED}❌ Archivo no encontrado: {target}{C_RESET}")
            return
        ext = target.suffix.lower()
        print(f"{C_CYAN}👁️ Procesando percepción visual y cognitiva sobre {target.name}...{C_RESET}")
        if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
            res = vie.process_image(target, source="cli", user_name="CLI User", caption=caption)
        elif ext in (".mp3", ".wav", ".ogg", ".m4a"):
            res = vie.process_sound(target, source="cli", user_name="CLI User", caption=caption)
        else:
            res = vie.process_video(target, source="cli", user_name="CLI User", caption=caption)
        print(f"\n{res.full_report}\n")

def cmd_distribute(task: str):
    print(f"\n{C_CYAN}{C_BOLD}⚡ [TARDIS CLUSTER :: DIVISIÓN Y DISTRIBUCIÓN DE PROCESAMIENTO]{C_RESET}")
    print(f"  {C_GOLD}Tarea:{C_RESET} {task}")
    print(f"  {C_CYAN}Despachando a 20 núcleos de cómputo (16 locales AMD Ryzen 7 + 4 Apple iMac 14,1)...{C_RESET}\n")

    bar = None
    try:
        from tardis_progress import TemporalProgressBar, time_estimator
        est_sec = time_estimator.estimate(task, complexity=3, mode="gemini", model="cluster-20cores")
        bar = TemporalProgressBar(
            prompt=task,
            estimated_duration=est_sec,
            engine_label="TARDIS CLUSTER",
            model_name="Alfa (ASUS TUF) + Beta (iMac 14,1)",
            complexity_label="Cómputo Heterogéneo Distribuido"
        )
        bar.start()
    except Exception:
        pass

    try:
        from core.tardis_distributed_mesh import get_mesh
        res = get_mesh().split_and_distribute_task(task)
        if bar:
            bar.finish(returncode=0 if res.get("ok") else 1)

        if res.get("ok"):
            print(f"\n{C_GREEN}{C_BOLD}✓ Procesamiento distribuido completado en {res.get('elapsed_seconds')}s:{C_RESET}\n")
            print(res.get("unified_reach_response", ""))
        else:
            print(f"{C_RED}❌ Error en procesamiento distribuido:{C_RESET} {res.get('error')}")
    except Exception as e:
        if bar:
            bar.finish(returncode=1)
def cmd_synergy(prompt: str = ""):
    try:
        from core.tardis_hybrid_synergy import get_tardis_hybrid_synergy
        syn = get_tardis_hybrid_synergy()
        if prompt:
            print(f"\n{C_CYAN}{C_BOLD}=== EVALUACIÓN DE SINERGIA HÍBRIDA (TARDIS APEX) ==={C_RESET}")
            res = syn.evaluate_optimal_combination(prompt, target_environment="cli")
            print(f"{C_BOLD}Prompt:{C_RESET} {prompt}")
            print(f"{C_BOLD}Estrategia:{C_RESET} {res['strategy_summary']}")
            print(f"{C_BOLD}Latencia Esperada:{C_RESET} {res['expected_latency']}")
            print(f"{C_BOLD}Puntuación de Sinergia:{C_RESET} {C_GREEN}{res['synergy_score']}%{C_RESET}\n")
            print(f"{C_YELLOW}Modelos Comprometidos:{C_RESET}")
            for m in res['models_engaged']:
                print(f"  • {m['name']} [{m['category']}] ({m['provider']})")
            print(f"\n{C_BLUE}Capas de Ingeniería Comprometidas:{C_RESET}")
            for l in res['engineering_layers_engaged']:
                print(f"  • {l['name']} [{l['paradigm']}]")
        else:
            matrix = syn.get_full_matrix()
            print(f"\n{C_CYAN}{C_BOLD}=== MATRIZ DE SINERGIA HÍBRIDA DE MODELOS E INGENIERÍAS ==={C_RESET}")
            print(f"Versión: {matrix['version']} | Modelos Activos: {matrix['models_count']} | Capas: {matrix['engineering_layers_count']}\n")
            print(f"{C_YELLOW}{C_BOLD}--- MODELOS HÍBRIDOS DISPONIBLES ---{C_RESET}")
            for k, m in matrix['models'].items():
                status_icon = "🟢" if m.get("active") else "⚪"
                print(f"  {status_icon} [{k}] {m['name']} ({m['context_tokens']} tokens) -> {m['latency_tier']}")
            print(f"\n{C_BLUE}{C_BOLD}--- CAPAS DE INGENIERÍA SOBERANAS ---{C_RESET}")
            for k, l in matrix['engineering_layers'].items():
                status_icon = "⚡" if l.get("active") else "⚪"
                print(f"  {status_icon} [{k}] {l['name']}")
                print(f"     └ Paradigma: {l['paradigm']}")
        print()
    except Exception as e:
        print(f"{C_RED}❌ Error al consultar Matriz de Sinergia:{C_RESET} {e}")

def main():
    parser = argparse.ArgumentParser(description="TARDIS Sovereign CLI Interface", add_help=True)
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Muestra el estado del sistema y servicios")
    subparsers.add_parser("reactivate", help="Reactiva los 63 botones y subsistemas")
    subparsers.add_parser("analyze", help="Analiza la estructura conversacional y causal")
    subparsers.add_parser("animate", help="Sintetiza videos animados de todas las fórmulas")
    v_p = subparsers.add_parser("v", help="Sintetiza simulación de física 3D procedural @ 60 FPS Nativos (Nano Banana)")
    v_p.add_argument("prompt", nargs="+", help="Teorema o cuestionamiento físico, químico o social")
    v_p.add_argument("--frames", type=int, default=60, help="Número de cuadros (def: 60 = 1s a 60 FPS)")
    v_p.add_argument("--blender", action="store_true", default=False, help="Usar Blender 5.0.1 PBR en lugar del motor procedural directo GPU")
    vp_p = subparsers.add_parser("vp", help="Sintetiza video Pixel Art hiper-realista a 1080P @ 60 FPS (Nano Banana)")
    vp_p.add_argument("prompt", nargs="+", help="Texto o tema para el video Pixel Art")
    vp_p.add_argument("--duration", type=float, default=5.0, help="Duración en segundos (por defecto 5.0 s)")
    subparsers.add_parser("explain-screen", help="Captura y explica la pantalla del SO")
    subparsers.add_parser("companion", help="Lanza el asistente flotante de escritorio")

    dist_p = subparsers.add_parser("distribute", aliases=["distribuir", "repartir"], help="Divide y distribuye el procesamiento entre Alfa y Mac 14,1")
    dist_p.add_argument("task", nargs="+", help="Tarea a procesar en el clúster heterogéneo")

    vis_p = subparsers.add_parser("visual", aliases=["vision", "inteligencia-visual"], help="Inteligencia Visual (ver, comprender y almacenar videos/imágenes)")
    vis_p.add_argument("subcommand", nargs="?", default="status", choices=["status", "list", "videos", "analyze", "ver"], help="Subcomando de visión")
    vis_p.add_argument("extra_args", nargs="*", default=[], help="Ruta de archivo o argumentos")

    phone_p = subparsers.add_parser("phone", help="Control móvil celular TARDIS POCKET (llamadas, SMS, datos, tethering)")
    phone_p.add_argument("subcommand", nargs="?", default="status", choices=["status", "call", "hangup", "answer", "sms", "data", "tether", "connect"], help="Subcomando de telefonía")
    phone_p.add_argument("extra_args", nargs="*", default=[], help="Argumentos adicionales (número, mensaje, etc.)")

    voice_p = subparsers.add_parser("voice", help="Control de mensajes de voz recurrentes")
    voice_p.add_argument("subcommand", nargs="?", default="status", choices=["status", "on", "off", "now"], help="Subcomando de voz")
    voice_p.add_argument("arg", nargs="?", default=None, help="Parámetro (minutos o modo)")

    chat_p = subparsers.add_parser("chat", help="Preguntar al núcleo soberano")
    chat_p.add_argument("message", nargs="+", help="Mensaje para el modelo")

    infinite_p = subparsers.add_parser("infinite", help="Ejecutar TARDIS Infinite Code (Fusión Cuádruple de Frontera)")
    infinite_p.add_argument("task", nargs="+", help="Meta o tarea de código para síntesis cuádruple")

    subparsers.add_parser("mesh", help="Supervisa el clúster de cómputo distribuido (Local + iMac 14,1)")
    subparsers.add_parser("cluster", help="Supervisa el clúster de cómputo distribuido (Local + iMac 14,1)")
    vsnap_p = subparsers.add_parser("voice-snap", help="Inicia el asistente de voz interactivo activado por chasquido de dedos")
    vsnap_p.add_argument("extra_args", nargs="*", default=[], help="Argumentos para tardis-voice")
    snap_p = subparsers.add_parser("snap", help="Asistente de voz activado por chasquido de dedos")
    snap_p.add_argument("extra_args", nargs="*", default=[], help="Argumentos para tardis-voice")

    syn_p = subparsers.add_parser("synergy", aliases=["sinergia", "hibrido"], help="Matriz de Sinergia Híbrida de Modelos e Ingenierías")
    syn_p.add_argument("prompt", nargs="*", default=[], help="Prompt o tarea para evaluar combinación óptima")

    args, unknown = parser.parse_known_args()

    if not args.command:
        interactive_repl()
    elif args.command in ("synergy", "sinergia", "hibrido"):
        cmd_synergy(" ".join(args.prompt))
    elif args.command in ("voice-snap", "snap", "asistente-voz"):
        subprocess.run(["/home/timemachine/.local/bin/tardis-voice"] + sys.argv[2:])
    elif args.command in ("mesh", "cluster"):
        subprocess.run(["/home/timemachine/.local/bin/tardis-mesh"])
    elif args.command in ("distribute", "distribuir", "repartir"):
        cmd_distribute(" ".join(args.task))
    elif args.command == "infinite":
        cmd_infinite(" ".join(args.task))
    elif args.command == "status":
        cmd_status()
    elif args.command in ("visual", "vision", "inteligencia-visual"):
        cmd_visual(args.subcommand, args.extra_args)
    elif args.command == "reactivate":
        cmd_reactivate()
    elif args.command == "analyze":
        cmd_analyze()
    elif args.command == "animate":
        cmd_animate()
    elif args.command == "v":
        q = " ".join(args.prompt)
        fast_mode = not args.blender
        cmd_v(q, frames=args.frames, fast=fast_mode)
    elif args.command == "vp":
        cmd_vp(" ".join(args.prompt), duration=args.duration)
    elif args.command == "explain-screen":
        cmd_explain_screen()
    elif args.command == "companion":
        subprocess.Popen(["/home/timemachine/Escritorio/GODWORKS SYSTEM/launch_tardis_companion.sh"])
        print(f"{C_GREEN}✓ Asistente flotante lanzado.{C_RESET}")
    elif args.command == "phone":
        cmd_phone(args.subcommand, args.extra_args)
    elif args.command == "voice":
        cmd_voice(args.subcommand, args.arg)
    elif args.command == "chat":
        cmd_chat(" ".join(args.message))
    elif args.command == "infinite":
        cmd_infinite(" ".join(args.task))

if __name__ == "__main__":
    main()

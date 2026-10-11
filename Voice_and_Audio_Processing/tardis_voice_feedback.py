#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TARDIS SOBERANO :: MÓDULO DE SÍNTESIS DE VOZ Y RETROALIMENTACIÓN ACÚSTICA
"""

import os
import sys
import subprocess
import threading
import tempfile
import asyncio

VOICE_ENABLED = True

def _speak_worker(text: str):
    global VOICE_ENABLED
    if not VOICE_ENABLED or not text:
        return

    # Limpiar texto para pronunciación
    speak_text = text.replace('*', ' por ').replace('/', ' dividido entre ')
    speak_text = speak_text.replace('**', ' elevado a ')
    speak_text = speak_text.replace('sqrt', ' raíz cuadrada ')
    
    # 1. Intentar con edge-tts (voz neuronal de alta definición)
    try:
        temp_file = os.path.join(tempfile.gettempdir(), f"tardis_speech_{os.getpid()}.mp3")
        cmd = [
            sys.executable, "-m", "edge_tts",
            "--voice", "es-MX-DaliaNeural",
            "--text", speak_text,
            "--write-media", temp_file
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
        if res.returncode == 0 and os.path.exists(temp_file):
            subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", temp_file],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
            try:
                os.remove(temp_file)
            except:
                pass
            return
    except Exception:
        pass

    # 2. Fallback con spd-say (local inmediato)
    try:
        subprocess.run(["spd-say", "-l", "es", "-t", "female1", speak_text],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
    except Exception:
        pass

def speak_async(text: str):
    """Pronuncia el texto de forma no bloqueante en un hilo independiente."""
    threading.Thread(target=_speak_worker, args=(text,), daemon=True).start()

def set_voice_enabled(enabled: bool):
    global VOICE_ENABLED
    VOICE_ENABLED = enabled

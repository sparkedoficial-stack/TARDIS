#!/usr/bin/env python3
"""
==============================================================================
TARDIS POCKET - SÍNTESIS DE AUDIO DE ARRANQUE (BOOT AUDIO)
==============================================================================
Sintetiza la locución oficial de TARDIS:
"Iniciando sistema de control universal."
con la voz neural oficial (es-MX-DaliaNeural) y la exporta en formato WAV
PCM 44.1kHz estéreo para reproducción durante el gestor de arranque.
==============================================================================
"""

import asyncio
import subprocess
from pathlib import Path
import edge_tts

BASE_DIR = Path(__file__).resolve().parent
MP3_OUTPUT = BASE_DIR / "boot_audio.mp3"
WAV_OUTPUT = BASE_DIR / "boot_audio.wav"

VOICE = "es-MX-DaliaNeural"
TEXT = "Iniciando sistema de control universal."

async def synthesize():
    print(f"Sintetizando locución de arranque con voz {VOICE}...")
    communicate = edge_tts.Communicate(TEXT, VOICE, rate="+0%", pitch="+0Hz")
    await communicate.save(str(MP3_OUTPUT))
    print(f"✓ Audio MP3 generado: {MP3_OUTPUT}")

    # Convertir a WAV PCM 44.1kHz 16-bit estéreo para máxima compatibilidad con el subsistema de audio Android
    print("Convirtiendo a WAV PCM 44.1kHz estéreo con ffmpeg...")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(MP3_OUTPUT),
        "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
        str(WAV_OUTPUT)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    print(f"✓ WAV de arranque listo ({WAV_OUTPUT.stat().st_size} bytes): {WAV_OUTPUT}")

if __name__ == "__main__":
    asyncio.run(synthesize())

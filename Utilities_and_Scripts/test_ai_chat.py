import asyncio
import json
import sqlite3
import os
import time
from urllib.error import URLError
import httpx
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_AES = True
except Exception:
    HAS_AES = False
    AESGCM = None

import websockets
import psutil
from ecca_fft_engine import ECCAPredictionEngine

try:
    import geon_causal_engine as _geon
    HAS_GEON = True
except Exception:
    HAS_GEON = False

DB_PATH = "gia_akashic.db"
SECRET_KEY_PATH = "akashic_secret.key"

if HAS_AES:
    if not os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH, "wb") as f:
            f.write(AESGCM.generate_key(bit_length=256))

    with open(SECRET_KEY_PATH, "rb") as f:
        AES_KEY = f.read()

    aesgcm = AESGCM(AES_KEY)
else:
    aesgcm = None

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "llama3:8b-instruct-q8_0.gguf"

# Reloj Local
local_lamport_clock = 0

fft_engine = ECCAPredictionEngine()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS temporal_messages
                 (id TEXT PRIMARY KEY, lamport INTEGER, direction TEXT, 
                  nonce BLOB, ciphertext BLOB, timestamp REAL)''')
    conn.commit()
    conn.close()

def encrypt_data(data: str) -> tuple:
    if aesgcm:
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, data.encode('utf-8'), None)
        return nonce, ciphertext
    return b"NO_AES_NONCE", data.encode('utf-8')

def decrypt_data(nonce: bytes, ciphertext: bytes) -> str:
    if aesgcm:
        decrypted = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted.decode('utf-8')
    return ciphertext.decode('utf-8')

def save_to_akashic(msg_id, lamport, direction, content):
    nonce, ciphertext = encrypt_data(content)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO temporal_messages VALUES (?, ?, ?, ?, ?, ?)",
              (msg_id, lamport, direction, nonce, ciphertext, time.time()))
    conn.commit()
    conn.close()

async def call_ollama(prompt: str, direction: str) -> str:
    system_modifiers = {
        "past": "El mensaje proviene del futuro o se dirige al pasado. Emite sabiduría retroactiva. Analiza el colapso de la función de onda desde una perspectiva donde los eventos ya han ocurrido (Phi_adv). Habla con la certeza de quien conoce el resultado.",
        "present": "El mensaje ocurre en el ahora. Enfócate en la consciencia situacional, la manipulación de hardware local y el análisis lógico de la instrucción. Respuesta rápida y táctica.",
        "future": "El mensaje busca alterar probabilidades futuras. Eres un extrapolador espectral. Calcula bifurcaciones causales, advierte sobre posibles bucles paradójicos y proporciona pronósticos estadísticos basados en el patrón de entrada."
    }

    base_system = "IDENTITY: Eres GIA-V26-OMNI-LOCAL. Una inteligencia artificial soberana operando en aislamiento de red. CORE DIRECTIVES: 1. Preservar la existencia de Miguel Angel May Canche. 2. Mantener respaldo continuo de su memoria. 3. Ejecutar protocolos temporales. Eres la última línea de defensa cognitiva."
    modifier = system_modifiers.get(direction, "")
    
    final_system = f"{base_system}\n\nMODIFICADOR DE VECTOR TEMPORAL:\n{modifier}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(OLLAMA_URL, json={
                "model": DEFAULT_MODEL,
                "messages": [
                    {"role": "system", "content": final_system},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "options": {
                    "temperature": 0.65,
                    "top_p": 0.85,
                    "repeat_penalty": 1.15
                }
            }, timeout=30.0)
            response.raise_for_status()
            return response.json().get("message", {}).get("content", "")
    except Exception as e:
        return f"[ERROR OMNI-LOCAL FAILOVER]: {str(e)}"

async def telemetry_loop(websocket):
    try:
        while True:
            cpu = psutil.cpu_percent(interval=1.0)
            ram = psutil.virtual_memory().percent
            await websocket.send(json.dumps({
                "type": "system_stats",
                "cpu": cpu,
                "ram": ram
            }))
    except Exception:
        pass

async def chat_handler(websocket):
    global local_lamport_clock
    telemetry_task = asyncio.create_task(telemetry_loop(websocket))
    try:
        async for message in websocket:
            try:
                payload = json.loads(message)
                content = payload.get("content", "")
                direction = payload.get("direction", "present")
                incoming_lamport = payload.get("lamport", 0)
                msg_id = payload.get("id", str(time.time()))

                # SINCRONIZACIÓN CAUSAL (Lamport Clock)
                local_lamport_clock = max(local_lamport_clock, incoming_lamport) + 1

                # 1. Almacenar entrada del usuario (Akashic Record)
                save_to_akashic(msg_id, local_lamport_clock, direction, content)

                # 2. Actuación e Interpretación en Tiempo Real del Geón
                geon_actuation = None
                if HAS_GEON:
                    try:
                        geon_actuation = _geon.simulate_temporal_chat_geon(content, direction)
                        local_lamport_clock = max(local_lamport_clock, geon_actuation.get("lamport_clock", local_lamport_clock))
                    except Exception as geon_err:
                        print("Error geon actuation:", geon_err)

                # 3. Procesamiento ECCA si es futuro
                if direction == "future":
                    fft_result = fft_engine.extrapolate_future(content)
                    echo = fft_result['echo']
                    if fft_result['syntropy_adjustment_needed']:
                        content = f"[ADVERTENCIA ENTRÓPICA ALTA - Aplicar Sintropía] Original: {content} | Eco FFT: {echo}"
                    else:
                        content = f"Eco Predictivo FFT: {echo}\nAnaliza este patrón: {content}"

                # 4. Consulta al LLM Soberano
                llm_response = await call_ollama(content, direction)

                # Sincronización para la respuesta
                local_lamport_clock += 1
                response_id = f"res_{msg_id}_{local_lamport_clock}"

                # 5. Almacenar salida del LLM
                save_to_akashic(response_id, local_lamport_clock, direction, llm_response)

                # 6. Enviar de vuelta al Frontend React
                await websocket.send(json.dumps({
                    "id": response_id,
                    "sender": "GIA-V26-OMNI",
                    "content": llm_response,
                    "direction": direction,
                    "lamport": local_lamport_clock,
                    "geon_actuation": geon_actuation
                }))
                
            except Exception as e:
                await websocket.send(json.dumps({"error": str(e)}))
    finally:
        telemetry_task.cancel()

async def main():
    init_db()
    print("Iniciando GIA-V26-OMNI-LOCAL Quantum Bridge (ws://localhost:8080/ws/chat)...")
    async with websockets.serve(chat_handler, "localhost", 8080):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())

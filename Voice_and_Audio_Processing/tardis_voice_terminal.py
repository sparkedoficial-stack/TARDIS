import os
import subprocess
import speech_recognition as sr
import pyaudio
import json
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

print("\n=======================================================")
print("  TARDIS NEURAL-SPACE-KAIJU - Módulo de Voz Terminal  ")
print("=======================================================\n")
print("Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales.\n")

def execute_terminal_command(command):
    logging.info(f"Ejecutando comando: {command}")
    try:
        result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print("\n--- SALIDA ---")
        print(result.stdout)
        if result.stderr:
            print("--- ERRORES ---")
            print(result.stderr)
        return result.stdout
    except subprocess.CalledProcessError as e:
        logging.error(f"Error al ejecutar el comando: {e}")
        print("\n--- ERRORES ---")
        print(e.stderr)
        return e.stderr

def process_voice_request(text):
    text_lower = text.lower()
    
    # Comandos de sistema comunes precargados (Fallback local ultrarrápido)
    if "lista los archivos" in text_lower or "listar archivos" in text_lower:
        execute_terminal_command("ls -la")
    elif "qué hora es" in text_lower or "que hora es" in text_lower:
        execute_terminal_command("date")
    elif "estado del sistema" in text_lower or "memoria" in text_lower:
        execute_terminal_command("free -h && df -h")
    elif "limpiar" in text_lower or "borrar pantalla" in text_lower:
        execute_terminal_command("clear")
    elif "quién soy" in text_lower or "quien soy" in text_lower:
        execute_terminal_command("whoami")
    elif "procesos" in text_lower:
        execute_terminal_command("top -b -n 1 | head -n 15")
    else:
        # Integración opcional con FTL / Gemini para NLP a Bash
        logging.info("Traduciendo instrucción natural a comando (Modo Inferencia)...")
        # Si tienes una API KEY de Gemini configurada, puedes habilitar google-genai aquí
        # Por ahora se ejecutará un echo para simular la orden si no es directa
        # Intentemos pasarlo a un script de shell seguro si se reconocen patrones
        if "crea un archivo" in text_lower or "crear un archivo" in text_lower:
            parts = text_lower.split("llamado")
            if len(parts) > 1:
                filename = parts[1].strip().replace(" ", "_") + ".txt"
                execute_terminal_command(f"touch {filename}")
        else:
            logging.warning("Comando natural complejo. Conecta tu API KAIJU (Gemini) en este bloque para traducir a bash. Por ahora lo ignoramos o lo enviamos al FTL.")
            # Intento de contacto al FTL HUB si está activo
            try:
                import requests
                FTL_HUB_API = "http://REDACTED_IP:8757/api/chat?key=DiosDelTiempo01"
                payload = {"message": f"Desde terminal de voz: {text}", "source": "voice"}
                response = requests.post(FTL_HUB_API, json=payload, timeout=60)
                if response.status_code == 200:
                    print("TARDIS HUB:", response.json().get('response', 'OK'))
            except:
                pass


def listen_loop():
    recognizer = sr.Recognizer()
    mic = sr.Microphone()
    
    logging.info("Iniciando escaneo de dispositivos de audio...")
    with mic as source:
        logging.info("Calibrando ruido ambiental. Por favor, mantén silencio...")
        recognizer.adjust_for_ambient_noise(source, duration=2)
        logging.info("Matriz acústica calibrada y en línea.")
        
    print("\n[TARDIS ESCUCHANDO] - Di 'salir' o 'apagar' para terminar.")
    
    while True:
        with mic as source:
            try:
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=15)
            except sr.WaitTimeoutError:
                continue
                
        try:
            print("\n>> Analizando espectro de voz...")
            text = recognizer.recognize_google(audio, language="es-ES")
            print(f"[Arquitecto]: {text}")
            
            if "salir" in text.lower() or "apagar" in text.lower() or "desconectar" in text.lower():
                logging.info("Cerrando enlace de voz TARDIS. Hasta pronto, Arquitecto.")
                break
                
            process_voice_request(text)
            
        except sr.UnknownValueError:
            print("[TARDIS]: No pude decodificar el mensaje. ¿Puedes repetirlo?")
        except sr.RequestError as e:
            logging.error(f"Error de conexión con el motor de reconocimiento: {e}")

if __name__ == "__main__":
    try:
        listen_loop()
    except KeyboardInterrupt:
        print("\nInterrupción detectada. Cerrando TARDIS Terminal de Voz.")
        sys.exit(0)

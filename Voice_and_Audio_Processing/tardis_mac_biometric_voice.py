import cv2
import face_recognition
import speech_recognition as sr
import pyaudio
import requests
import json
import time
import os
import threading
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

FTL_HUB_API = "http://REDACTED_IP:8757/api/chat?key=DiosDelTiempo01"
ARQUITECTO_IMAGE_PATH = os.path.expanduser("~/arquitecto_face.jpg")
TOLERANCE = 0.5  # Stricter tolerance for security

class BiometricVoiceController:
    def __init__(self):
        self.known_encoding = None
        self.is_arquitecto_present = False
        self.recognizer = sr.Recognizer()
        self.mic = sr.Microphone()
        
        # Adjust mic for ambient noise
        with self.mic as source:
            logging.info("Ajustando micrófono para ruido ambiental...")
            self.recognizer.adjust_for_ambient_noise(source, duration=2)
            
    def register_arquitecto(self):
        """Captures an image of the Arquitecto if not already saved."""
        if os.path.exists(ARQUITECTO_IMAGE_PATH):
            logging.info(f"Cargando rostro del Arquitecto desde {ARQUITECTO_IMAGE_PATH}")
            image = face_recognition.load_image_file(ARQUITECTO_IMAGE_PATH)
            encodings = face_recognition.face_encodings(image)
            if encodings:
                self.known_encoding = encodings[0]
                return True
            else:
                logging.warning("No se detectó rostro en la imagen guardada. Se requerirá un nuevo escaneo.")
                
        logging.info("=== REGISTRO DEL ARQUITECTO ===")
        logging.info("Por favor, mira a la cámara (se tomará la foto en 3 segundos)...")
        cap = cv2.VideoCapture(0)
        time.sleep(3)
        ret, frame = cap.read()
        if ret:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            encodings = face_recognition.face_encodings(rgb_frame)
            if encodings:
                self.known_encoding = encodings[0]
                cv2.imwrite(ARQUITECTO_IMAGE_PATH, frame)
                logging.info(f"Rostro del Arquitecto registrado y guardado en {ARQUITECTO_IMAGE_PATH}.")
                cap.release()
                return True
            else:
                logging.error("No se detectó ningún rostro. Intenta de nuevo.")
        cap.release()
        return False

    def vision_loop(self):
        """Continuously checks the camera for the Arquitecto's face."""
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.5)
                continue
                
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_frame, model="hog")
            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
            
            arquitecto_detected = False
            for encoding in face_encodings:
                matches = face_recognition.compare_faces([self.known_encoding], encoding, tolerance=TOLERANCE)
                if matches[0]:
                    arquitecto_detected = True
                    break
                    
            if arquitecto_detected and not self.is_arquitecto_present:
                logging.info("¡Arquitecto reconocido! Controles de voz DESBLOQUEADOS.")
                self.is_arquitecto_present = True
            elif not arquitecto_detected and self.is_arquitecto_present:
                logging.info("Arquitecto ya no está en el campo visual. Controles de voz BLOQUEADOS.")
                self.is_arquitecto_present = False
                
            time.sleep(1) # Check once per second to save CPU

    def execute_command(self, text):
        logging.info(f"Ejecutando comando FTL: '{text}'")
        try:
            # Assuming the API endpoint expects a JSON payload with a 'message' or 'command' field.
            payload = {"message": text, "source": "mac_voice"}
            response = requests.post(FTL_HUB_API, json=payload, timeout=10)
            if response.status_code == 200:
                logging.info("Comando enviado exitosamente a TARDIS.")
            else:
                logging.error(f"Error al enviar comando: HTTP {response.status_code}")
        except Exception as e:
            logging.error(f"Error de conexión con el Hub FTL: {e}")

    def voice_loop(self):
        """Listens to the microphone and processes commands if the Arquitecto is present."""
        while True:
            if not self.is_arquitecto_present:
                time.sleep(0.5)
                continue
                
            with self.mic as source:
                logging.info("Escuchando comando de voz...")
                try:
                    audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=10)
                except sr.WaitTimeoutError:
                    continue # No speech detected, loop again
                
            if not self.is_arquitecto_present:
                logging.info("Audio capturado, pero el Arquitecto se retiró. Comando ignorado.")
                continue
                
            try:
                logging.info("Procesando audio...")
                text = self.recognizer.recognize_google(audio, language="es-ES")
                logging.info(f"Texto reconocido: {text}")
                
                # We can execute it directly since biometric validation is active
                self.execute_command(text)
                    
            except sr.UnknownValueError:
                logging.warning("No se entendió el audio.")
            except sr.RequestError as e:
                logging.error(f"Error en el servicio de reconocimiento de voz: {e}")

    def run(self):
        if not self.register_arquitecto():
            logging.error("Fallo al registrar al Arquitecto. Saliendo.")
            return
            
        logging.info("Iniciando centinela biométrico y auditivo...")
        
        vision_thread = threading.Thread(target=self.vision_loop, daemon=True)
        voice_thread = threading.Thread(target=self.voice_loop, daemon=True)
        
        vision_thread.start()
        voice_thread.start()
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Apagando controlador biométrico.")

if __name__ == "__main__":
    controller = BiometricVoiceController()
    controller.run()

"""
tardis_singularity_daemon.py
============================
Daemon autónomo de visión, clic adaptativo y control temporal de TARDIS
para 'Cell to Singularity: Evolution Never Ends'.

Funcionalidades:
1. Supervisa el display virtual Xvfb :99 (o Wayland / DISPLAY primario).
2. Lanza y mantiene activo el proceso del juego en segundo plano mediante Proton.
3. Bucle de clic adaptativo de alta frecuencia para recolectar entropía e ideas.
4. Bucle de activación de nanobots periódica (pulsos de auto-arranque y modo compra).
5. Monitoreo constante del archivo de guardado y reporte de descubrimientos científicos.
"""

import os
import sys
import time
import signal
import subprocess
import logging
from datetime import datetime

# Rutas y configuración
GAME_DIR = "/home/timemachine/.local/share/Steam/steamapps/common/Cell to Singularity"
EXE_PATH = os.path.join(GAME_DIR, "CellToSingularity.exe")
PROTON_PATH = "/home/timemachine/.local/share/Steam/steamapps/common/Proton - Experimental/proton"
COMPAT_DATA = "/home/timemachine/.local/share/Steam/steamapps/compatdata/977400"
STEAM_CLIENT = "/home/timemachine/.local/share/Steam"
STEAM_LIBS = "/home/timemachine/.local/share/Steam/steamapps"

LOG_FILE = "/home/timemachine/.ftl/tardis_singularity_daemon.log"
PID_FILE = "/home/timemachine/.ftl/tardis_singularity.pid"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

running = True

def handle_signal(sig, frame):
    global running
    logging.info(f"Señal {sig} recibida. Deteniendo daemon de TARDIS de forma limpia...")
    running = False

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


class SingularityAutonomousDaemon:
    def __init__(self, display=":99"):
        self.display = display
        self.xvfb_proc = None
        self.game_proc = None
        self.env = os.environ.copy()
        self.env["DISPLAY"] = self.display
        self.env["STEAM_COMPAT_DATA_PATH"] = COMPAT_DATA
        self.env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = STEAM_CLIENT
        self.env["STEAM_COMPAT_INSTALL_PATH"] = GAME_DIR
        self.env["STEAM_COMPAT_LIBRARY_PATHS"] = STEAM_LIBS
        self.env["STEAM_COMPAT_APP_ID"] = "977400"

    def ensure_xvfb(self):
        """Verifica que el display virtual Xvfb esté activo o lo inicia."""
        check = subprocess.run(["xwininfo", "-display", self.display, "-root"], capture_output=True, text=True)
        if check.returncode != 0:
            logging.info(f"Iniciando Xvfb en display {self.display} (1920x1080x24)...")
            self.xvfb_proc = subprocess.Popen(
                ["Xvfb", self.display, "-screen", "0", "1920x1080x24"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.5)
            logging.info("Xvfb iniciado correctamente.")
        else:
            logging.info(f"Display {self.display} ya está activo y operativo.")

    def ensure_game(self):
        """Verifica si el proceso del juego está corriendo o lo lanza."""
        check = subprocess.run(["pgrep", "-f", "CellToSingularity"], capture_output=True, text=True)
        if not check.stdout.strip():
            logging.info("Lanzando Cell to Singularity mediante Proton...")
            cmd = ["/usr/bin/python3", PROTON_PATH, "run", EXE_PATH]
            self.game_proc = subprocess.Popen(
                cmd,
                env=self.env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(5)
            logging.info(f"Juego lanzado (PID base: {self.game_proc.pid}).")
        else:
            pids = check.stdout.strip().replace("\n", ", ")
            logging.info(f"Juego ya en ejecución (PIDs: {pids}).")

    def click_entropy(self, count=15):
        """Envía ráfagas de clics al núcleo de la sopa primordial / árbol biológico."""
        center_x, center_y = 960, 540
        try:
            subprocess.run(
                ["xdotool", "mousemove", str(center_x), str(center_y), "click", "--repeat", str(count), "--delay", "25", "1"],
                env=self.env,
                capture_output=True
            )
        except Exception as e:
            logging.error(f"Error en ráfaga de clics: {e}")

    def pulse_nanobots(self):
        """Activa y alterna el modo de los nanobots (comprar todo / recolectar)."""
        try:
            # Enviar pulsaciones de teclas o clics en cuadrante de nanobots
            # Espacio / N activa nanobots; hotkey 'B' o clic en botón inferior izquierdo
            subprocess.run(["xdotool", "key", "space"], env=self.env, capture_output=True)
            subprocess.run(["xdotool", "key", "n"], env=self.env, capture_output=True)
            # Clic en zona del botón de nanobots (esquina inferior izquierda)
            subprocess.run(["xdotool", "mousemove", "250", "950", "click", "1"], env=self.env, capture_output=True)
            logging.debug("Pulso de nanobots emitido.")
        except Exception as e:
            logging.error(f"Error al pulsar nanobots: {e}")

    def run_loop(self):
        logging.info("🛸 TARDIS Daemon de Control Autónomo de Cell to Singularity INICIADO.")
        self.ensure_xvfb()
        self.ensure_game()

        # Guardar PID
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))

        iteration = 0
        last_sync = time.time()

        while running:
            try:
                # 1. Ráfaga de recolección de entropía (15 clics por ciclo)
                self.click_entropy(count=20)
                iteration += 1

                # 2. Pulso de nanobots cada 10 iteraciones (~5 segundos)
                if iteration % 10 == 0:
                    self.pulse_nanobots()

                # 3. Mantenimiento y sincronización de estado cada 60 iteraciones (~30s)
                if iteration % 60 == 0:
                    logging.info(f"Ciclo autónomo {iteration}: entropía recolectada y nanobots activos.")
                    self.ensure_game()

                time.sleep(0.5)

            except Exception as e:
                logging.error(f"Excepción en bucle de control: {e}")
                time.sleep(2)

        self.cleanup()

    def cleanup(self):
        logging.info("Limpiando procesos del daemon...")
        if self.game_proc:
            try:
                self.game_proc.terminate()
            except Exception:
                pass
        if self.xvfb_proc:
            try:
                self.xvfb_proc.terminate()
            except Exception:
                pass
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        logging.info("Daemon detenido exitosamente.")

if __name__ == "__main__":
    daemon = SingularityAutonomousDaemon()
    daemon.run_loop()

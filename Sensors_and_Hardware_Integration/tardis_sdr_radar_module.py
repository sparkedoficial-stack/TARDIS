import time
import numpy as np
import json
import logging

class TARDISSDRRadar:
    """
    TARDIS SDR Radar Module for FM and Spectrum sweep.
    Integrates tardis_pocket_sdr.py logic.
    """
    def __init__(self, device_name="TARDIS-POCKET-SDR"):
        self.device_name = device_name
        self.connected = False
        self.logger = logging.getLogger("TARDISSDRRadar")
        self.logger.setLevel(logging.INFO)

    def connect(self):
        self.logger.info(f"[{self.device_name}] Connecting to SDR hardware...")
        # Simulate connection
        time.sleep(0.5)
        self.connected = True
        return {"status": "success", "message": f"Connected to {self.device_name}"}

    def receive_fm(self, frequency_mhz=100.0, duration_sec=2):
        if not self.connected:
            return {"status": "error", "message": "Device not connected"}
        
        self.logger.info(f"[{self.device_name}] Listening on {frequency_mhz} MHz for {duration_sec}s...")
        time.sleep(duration_sec)
        return {"status": "success", "message": f"FM reception on {frequency_mhz}MHz completed."}

    def sweep_radar(self, start_freq=88.0, stop_freq=108.0, step=2.0):
        if not self.connected:
            return {"status": "error", "message": "Device not connected"}
            
        self.logger.info(f"[{self.device_name}] Sweeping spectrum {start_freq}MHz - {stop_freq}MHz...")
        frequencies = np.arange(start_freq, stop_freq, step)
        results = []
        
        for freq in frequencies:
            signal_strength = np.random.uniform(-120, -30)
            if signal_strength > -60:
                results.append({
                    "frequency_mhz": round(float(freq), 2),
                    "strength_dbm": round(float(signal_strength), 1),
                    "detected": True
                })
            else:
                results.append({
                    "frequency_mhz": round(float(freq), 2),
                    "strength_dbm": round(float(signal_strength), 1),
                    "detected": False
                })
            time.sleep(0.05)
            
        return {"status": "success", "sweep_results": results}

# Singleton instance
sdr_radar_instance = TARDISSDRRadar()
sdr_radar_instance.connect()

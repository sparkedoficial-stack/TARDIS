#!/usr/bin/env python3
import os
import time
import subprocess
import re
import math
import sys
import datetime

# Constantes para estimación de distancia (Fórmula Log-Normal Shadowing)
# d = 10 ^ ((TxPower - RSSI) / (10 * n))
TX_POWER_WIFI = -45  # Estimación a 1m
N_FACTOR_WIFI = 3.0  # Factor de atenuación ambiental

TX_POWER_BT = -59
N_FACTOR_BT = 2.0

def calculate_distance(rssi, tx_power, n_factor):
    try:
        rssi = float(rssi)
        ratio = (tx_power - rssi) / (10.0 * n_factor)
        distance = math.pow(10, ratio)
        return round(distance, 2)
    except:
        return -1.0

def run_adb_command(cmd):
    try:
        result = subprocess.run(f"adb shell {cmd}", shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout
    except Exception as e:
        print(f"Error ADB: {e}")
        return ""

def scan_wifi():
    devices = []
    # Trigger un escaneo activo
    run_adb_command("cmd wifi start-scan")
    time.sleep(2)
    
    out = run_adb_command("dumpsys wifi")
    
    in_scan_results = False
    for line in out.splitlines():
        if "mScanResults" in line or "Latest scan results" in line or "Scan Results" in line:
            in_scan_results = True
            continue
        if in_scan_results:
            if line.strip() == "" or "mNetworkHistory" in line or "mLastScanResults" in line:
                in_scan_results = False
                continue
            
            mac_match = re.search(r'([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', line)
            rssi_match = re.search(r'-[0-9]{2,3}', line)
            if mac_match and rssi_match:
                mac = mac_match.group(0)
                rssi = int(rssi_match.group(0))
                dist = calculate_distance(rssi, TX_POWER_WIFI, N_FACTOR_WIFI)
                
                ssid = ""
                ssid_match = re.search(r'"([^"]*)"', line)
                if ssid_match:
                    ssid = ssid_match.group(1)
                elif len(line.split()) > 1 and mac not in line.split()[0]:
                    # Posible SSID sin comillas
                    ssid = line.split()[0]
                
                devices.append({
                    "type": "WiFi/SDR",
                    "mac": mac,
                    "name": ssid,
                    "rssi": rssi,
                    "distance": dist
                })
    return devices

def scan_bluetooth():
    devices = []
    out = run_adb_command("dumpsys bluetooth_manager")
    
    for line in out.splitlines():
        mac_match = re.search(r'([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', line)
        if mac_match and ("mAlias" in line or "Name:" in line or "Device:" in line or "BluetoothDevice" in line):
            mac = mac_match.group(0)
            
            rssi = -70
            rssi_match = re.search(r'Rssi:\s*(-[0-9]+)', line, re.IGNORECASE)
            if rssi_match:
                rssi = int(rssi_match.group(1))
            
            dist = calculate_distance(rssi, TX_POWER_BT, N_FACTOR_BT)
            devices.append({
                "type": "Bluetooth",
                "mac": mac,
                "name": line.strip()[:40], # truncar por limpieza
                "rssi": rssi,
                "distance": dist
            })
    return devices

def is_person_device(name, mac):
    name_lower = name.lower()
    keywords = ['iphone', 'ipad', 'galaxy', 'watch', 'apple', 'samsung', 'phone', 'moto', 'pixel', 'redmi', 'xiaomi', 'huawei']
    for kw in keywords:
        if kw in name_lower:
            return True
    
    # Heurística simple: Si tiene un SSID personal típico, o un nombre de dispositivo
    if "iphone de" in name_lower or "samsung" in name_lower:
        return True
    
    return False

def notify_person(device, distance):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"ALERTA RADAR: Persona detectada. Dispositivo: {device.strip()} a {distance} metros."
    print(f"[{timestamp}] {msg}")
    
    # Notificación de escritorio
    os.system(f"notify-send 'TARDIS RADAR' '{msg}' -u critical")
    
    # Síntesis de voz (alerta inmediata)
    # Intentamos spd-say o espeak
    os.system(f"(spd-say -t female1 -r -10 'Alerta. Persona detectada en el radar a {distance} metros' || espeak 'Alerta. Persona detectada en el radar a {distance} metros') &")

def log_summary(devices):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open("/home/timemachine/tardis_radar_log.txt", "w") as f:
            f.write(f"--- REPORTE DE RADAR TARDIS ({timestamp}) ---\n")
            f.write(f"Total de dispositivos únicos detectados: {len(devices)}\n\n")
            for d in devices:
                f.write(f"[{d['type']}] MAC: {d['mac']} | Nombre: {d['name']} | RSSI: {d['rssi']} | Distancia: {d['distance']}m\n")
    except Exception as e:
        print(f"Error escribiendo log: {e}")

def main():
    print("Iniciando Escáner Radar TARDIS (WiFi/BT/SDR)...")
    seen_persons = set()
    last_clear = time.time()
    
    while True:
        try:
            wifi_devs = scan_wifi()
            bt_devs = scan_bluetooth()
            
            all_devs = wifi_devs + bt_devs
            
            unique_devs = {}
            for d in all_devs:
                unique_devs[d["mac"]] = d
                
            dev_list = list(unique_devs.values())
            
            # Ordenar por distancia
            dev_list.sort(key=lambda x: x['distance'])
            
            log_summary(dev_list)
            
            for d in dev_list:
                if d["distance"] > 0 and d["distance"] < 30.0: # Umbral de 30 metros para persona "cercana"
                    if is_person_device(d["name"], d["mac"]):
                        if d["mac"] not in seen_persons:
                            seen_persons.add(d["mac"])
                            notify_person(d["name"] or d["mac"], d["distance"])
            
            # Limpiar caché de personas cada hora para volver a avisar si siguen en el área
            if time.time() - last_clear > 3600:
                seen_persons.clear()
                last_clear = time.time()
                
        except Exception as e:
            print(f"Error en iteración principal del radar: {e}")
            
        time.sleep(15) # Escanear continuamente cada 15 segundos

if __name__ == "__main__":
    main()

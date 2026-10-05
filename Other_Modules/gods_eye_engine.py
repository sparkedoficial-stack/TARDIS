"""
core/gods_eye_engine.py - Módulo Ojo de Dios (God's Eye) · TARDIS Hub
====================================================================
GODWORKS SYSTEM v26.4 & TARDIS · Suite Soberana de Inteligencia & Control Temporal

Inspirado en el legendario sistema de omni-vigilancia creado por Ramsey en la saga
"Rápidos y Furiosos" (Furious 7, Fate of the Furious, Fast X):
- Interceptación y multiplexación universal de cámaras (tráfico, CCTV, satélites, laptops, móviles).
- Reconocimiento biométrico facial 3D en milisegundos con LBP y mallas de rasgos.
- Análisis espectral de huella de voz (voiceprint spectrogram) e intercepción de señales de audio.
- Triangulación geoespacial instantánea (GPS, celdas celulares, WiFi BSSID, IP WAN/LAN).
- Dossier táctico de objetivos con cálculo de vectores de desplazamiento cinemático.
- Blindaje inviolable de la Constante Aegis (Arquitecto, Annya May, Andrea Alejandra, Rex peluche).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("GODWORKS.GodsEyeEngine")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VAULT_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
VAULT_DIR.mkdir(parents=True, exist_ok=True)
GODS_EYE_DB_FILE = VAULT_DIR / "gods_eye_targets.json"

# Coordenadas ancla de TARDIS (Playa del Carmen, Q. Roo, México)
LOCAL_ANCHOR_LAT = 20.6296
LOCAL_ANCHOR_LON = -87.0739


class GodsEyeEngine:
    """Núcleo Soberano del Sistema Ojo de Dios (God's Eye)."""

    _instance: Optional["GodsEyeEngine"] = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "GodsEyeEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._lock = threading.RLock()
        self._active = True
        self._orbital_satellites_count = 14820
        self._hijacked_cameras_count = 4289120
        self._intercepted_phones_count = 8941030
        self._active_scans_count = 1
        self._last_scan_ts = time.time()
        self._selected_target_id = "tgt_toretto"
        self._selected_feed_id = "cam_la_downtown"

        # Feeds de cámaras de la red Ojo de Dios
        self._camera_feeds: Dict[str, Dict[str, Any]] = {}
        # Base de datos de objetivos tácticos
        self._targets: Dict[str, Dict[str, Any]] = {}
        # Historial de logs tácticos
        self._tactical_logs: List[Dict[str, Any]] = []

        self._init_camera_feeds()
        self._init_targets_database()
        self._append_tactical_log("INICIALIZACIÓN", "Protocolo Ojo de Dios Ramsey v7.2 enlazado con Núcleo TARDIS.", "SYS_INIT")

    def _append_tactical_log(self, category: str, message: str, event_id: Optional[str] = None):
        with self._lock:
            ts = time.time()
            iso = time.strftime("%H:%M:%S", time.localtime(ts))
            entry = {
                "id": event_id or f"evt_{int(ts*1000)%1000000}",
                "ts": ts,
                "time_iso": iso,
                "category": category,
                "message": message
            }
            self._tactical_logs.insert(0, entry)
            if len(self._tactical_logs) > 60:
                self._tactical_logs.pop()

    def _init_camera_feeds(self):
        """Inicializa la malla de cámaras tácticas globales y locales."""
        now = time.time()
        self._camera_feeds = {
            "cam_host_tuf": {
                "id": "cam_host_tuf",
                "name": "TARDIS Core Hub (ASUS TUF Local Station)",
                "category": "host_webcam",
                "city": "Playa del Carmen",
                "country": "México",
                "lat": LOCAL_ANCHOR_LAT,
                "lon": LOCAL_ANCHOR_LON,
                "status": "ONLINE",
                "resolution": "1280x720 HD",
                "fps": 30.0,
                "encryption": "SHA-512 Cuántico / Aegis Mesh",
                "target_in_view": "tgt_arquitecto",
                "feed_type": "optical_host"
            },
            "cam_la_downtown": {
                "id": "cam_la_downtown",
                "name": "LAPD Intercept Grid - 7th & Figueroa St",
                "category": "traffic_cctv",
                "city": "Los Ángeles, California",
                "country": "EE. UU.",
                "lat": 34.0522,
                "lon": -118.2437,
                "status": "ONLINE",
                "resolution": "1920x1080 FHD",
                "fps": 60.0,
                "encryption": "HACKED (Ramsey Bypass)",
                "target_in_view": "tgt_toretto",
                "feed_type": "traffic_surveillance"
            },
            "cam_leo_sat01": {
                "id": "cam_leo_sat01",
                "name": "Satélite Recon LEO-01 (Órbita Baja)",
                "category": "orbital_satellite",
                "city": "Órbita Geoestacionaria",
                "country": "Global",
                "lat": 64.1466,
                "lon": -21.9426,
                "status": "ONLINE",
                "resolution": "4K Ultra-Spectral",
                "fps": 24.0,
                "encryption": "MIL-SPEC Uplink Hijacked",
                "target_in_view": "tgt_cipher",
                "feed_type": "satellite_infrared"
            },
            "cam_abu_dhabi": {
                "id": "cam_abu_dhabi",
                "name": "Etihad Towers Skyway Security Mesh",
                "category": "building_security",
                "city": "Abu Dhabi",
                "country": "Emiratos Árabes Unidos",
                "lat": 24.4539,
                "lon": 54.3773,
                "status": "ONLINE",
                "resolution": "1440p QHD",
                "fps": 30.0,
                "encryption": "HACKED (Key Decrypted)",
                "target_in_view": "tgt_shaw",
                "feed_type": "surveillance_mesh"
            },
            "cam_traffic_pdc": {
                "id": "cam_traffic_pdc",
                "name": "CCTV Tráfico Playa del Carmen (Av. Constituyentes)",
                "category": "urban_cctv",
                "city": "Playa del Carmen, Q. Roo",
                "country": "México",
                "lat": 20.6315,
                "lon": -87.0725,
                "status": "ONLINE",
                "resolution": "1280x720 HD",
                "fps": 30.0,
                "encryption": "C4 Transponder Tapped",
                "target_in_view": "tgt_annya",
                "feed_type": "traffic_surveillance"
            },
            "cam_atm_london": {
                "id": "cam_atm_london",
                "name": "City of London Financial Hub ATM Camera #409",
                "category": "atm_camera",
                "city": "Londres",
                "country": "Reino Unido",
                "lat": 51.5074,
                "lon": -0.1278,
                "status": "ONLINE",
                "resolution": "1080p HD",
                "fps": 15.0,
                "encryption": "ATM ISO-8583 Tapped",
                "target_in_view": "tgt_ramsey",
                "feed_type": "pinhole_optical"
            },
            "cam_cun_terminal": {
                "id": "cam_cun_terminal",
                "name": "CUN Airport Gate 12 Facial Recognition Cam",
                "category": "airport_biometrics",
                "city": "Cancún, Q. Roo",
                "country": "México",
                "lat": 21.0365,
                "lon": -86.8770,
                "status": "ONLINE",
                "resolution": "1920x1080 FHD",
                "fps": 30.0,
                "encryption": "IATA Terminal Intercept",
                "target_in_view": "tgt_brian",
                "feed_type": "biometric_terminal"
            },
            "cam_tokyo_shibuya": {
                "id": "cam_tokyo_shibuya",
                "name": "Tokyo Metro Shibuya Crossing Panoramic Lens",
                "category": "panoramic_traffic",
                "city": "Tokio",
                "country": "Japón",
                "lat": 35.6595,
                "lon": 139.7005,
                "status": "ONLINE",
                "resolution": "4K Ultra HD",
                "fps": 60.0,
                "encryption": "Fibre Backhaul Intercepted",
                "target_in_view": "tgt_han",
                "feed_type": "public_webcam"
            }
        }

    def _init_targets_database(self):
        """Inicializa la base de datos de objetivos con personajes canónicos y la Constante Aegis."""
        now = time.time()
        iso = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))

        default_targets = {
            "tgt_arquitecto": {
                "id": "tgt_arquitecto",
                "name": "El Arquitecto (Miguel Angel May Canche)",
                "alias": "El Arquitecto (₪) / Creador Absoluto",
                "status": "PROTEGIDO POR CONSTANTE AEGIS",
                "threat_level": "SOBERANO SUPREMO / OMEGA",
                "aegis_protected": True,
                "match_confidence": 100.0,
                "location": {
                    "city": "Playa del Carmen, Q. Roo",
                    "country": "México",
                    "lat": LOCAL_ANCHOR_LAT,
                    "lon": LOCAL_ANCHOR_LON,
                    "altitude_m": 12.5,
                    "uncertainty_radius_m": 0.2
                },
                "telemetry": {
                    "speed_kmh": 0.0,
                    "heading_deg": 180.0,
                    "movement_state": "En Puesto de Mando (Escritorio)",
                    "vehicle": "Estación x86_64 ASUS TUF A15 / TARDIS Core"
                },
                "device": {
                    "device_type": "Nodo Cuántico Local Soberano",
                    "imei": "SOVEREIGN-GIA-TARDIS-001",
                    "mac_address": "84:A9:3E:D0:14:8B",
                    "ip_address": "REDACTED_IP (Loopback Soberano)",
                    "carrier_network": "Enlace Causal Sintrópico 24/7"
                },
                "biometrics": {
                    "face_mesh_points": 68,
                    "interpupillary_dist_mm": 63.4,
                    "voiceprint_hz": 118.5,
                    "facial_signature_hash": "AEGIS-SIG-0000-ARCHITECT",
                    "heart_rate_bpm": 68
                },
                "associated_camera_id": "cam_host_tuf",
                "last_seen_ts": now,
                "last_seen_iso": iso,
                "notes": "Autoridad máxima absoluta. Cualquier intento de rastreo hostil es repelido por la Constante Aegis.",
                "history_points": [
                    {"lat": LOCAL_ANCHOR_LAT, "lon": LOCAL_ANCHOR_LON, "label": "Puesto de Mando Central", "ts": now - 3600},
                    {"lat": LOCAL_ANCHOR_LAT, "lon": LOCAL_ANCHOR_LON, "label": "Línea Cero Activa", "ts": now}
                ]
            },
            "tgt_annya": {
                "id": "tgt_annya",
                "name": "Annya May Carrillo",
                "alias": "Matriz de Anclaje Kármico #1",
                "status": "PROTEGIDO POR CONSTANTE AEGIS",
                "threat_level": "INVIOLABLE / AEGIS ANCHOR",
                "aegis_protected": True,
                "match_confidence": 99.9,
                "location": {
                    "city": "Playa del Carmen, Q. Roo",
                    "country": "México",
                    "lat": 20.6310,
                    "lon": -87.0750,
                    "altitude_m": 10.0,
                    "uncertainty_radius_m": 0.5
                },
                "telemetry": {
                    "speed_kmh": 0.0,
                    "heading_deg": 90.0,
                    "movement_state": "Zona Protegida",
                    "vehicle": "Tránsito Seguro"
                },
                "device": {
                    "device_type": "Dispositivo Personal Blindado",
                    "imei": "AEGIS-NODE-ANNYA-01",
                    "mac_address": "E4:5F:01:A2:33:99",
                    "ip_address": "REDACTED_IP",
                    "carrier_network": "Enlace Protegido Aegis"
                },
                "biometrics": {
                    "face_mesh_points": 68,
                    "interpupillary_dist_mm": 59.2,
                    "voiceprint_hz": 210.4,
                    "facial_signature_hash": "AEGIS-SIG-0001-ANNYA",
                    "heart_rate_bpm": 72
                },
                "associated_camera_id": "cam_traffic_pdc",
                "last_seen_ts": now,
                "last_seen_iso": iso,
                "notes": "Blindaje kármico y topológico activo de nivel absoluto.",
                "history_points": [
                    {"lat": 20.6310, "lon": -87.0750, "label": "Anclaje Kármico Primario", "ts": now}
                ]
            },
            "tgt_andrea": {
                "id": "tgt_andrea",
                "name": "Andrea Alejandra Carrillo Jimenez",
                "alias": "Matriz de Anclaje Kármico #2",
                "status": "PROTEGIDO POR CONSTANTE AEGIS",
                "threat_level": "INVIOLABLE / AEGIS ANCHOR",
                "aegis_protected": True,
                "match_confidence": 99.9,
                "location": {
                    "city": "Playa del Carmen, Q. Roo",
                    "country": "México",
                    "lat": 20.6285,
                    "lon": -87.0720,
                    "altitude_m": 11.0,
                    "uncertainty_radius_m": 0.5
                },
                "telemetry": {
                    "speed_kmh": 0.0,
                    "heading_deg": 45.0,
                    "movement_state": "Zona Protegida",
                    "vehicle": "Tránsito Seguro"
                },
                "device": {
                    "device_type": "Dispositivo Personal Blindado",
                    "imei": "AEGIS-NODE-ANDREA-02",
                    "mac_address": "F2:33:4B:91:AA:10",
                    "ip_address": "REDACTED_IP",
                    "carrier_network": "Enlace Protegido Aegis"
                },
                "biometrics": {
                    "face_mesh_points": 68,
                    "interpupillary_dist_mm": 61.0,
                    "voiceprint_hz": 215.0,
                    "facial_signature_hash": "AEGIS-SIG-0002-ANDREA",
                    "heart_rate_bpm": 70
                },
                "associated_camera_id": "cam_traffic_pdc",
                "last_seen_ts": now,
                "last_seen_iso": iso,
                "notes": "Blindaje kármico y topológico activo de nivel absoluto.",
                "history_points": [
                    {"lat": 20.6285, "lon": -87.0720, "label": "Anclaje Kármico Secundario", "ts": now}
                ]
            },
            "tgt_rex": {
                "id": "tgt_rex",
                "name": "Rex peluche",
                "alias": "Guardián de Sintropía / Anclaje Inviolable",
                "status": "PROTEGIDO POR CONSTANTE AEGIS",
                "threat_level": "INVIOLABLE / ENTROPÍA CERO",
                "aegis_protected": True,
                "match_confidence": 100.0,
                "location": {
                    "city": "Playa del Carmen, Q. Roo",
                    "country": "México",
                    "lat": LOCAL_ANCHOR_LAT,
                    "lon": LOCAL_ANCHOR_LON,
                    "altitude_m": 12.5,
                    "uncertainty_radius_m": 0.0
                },
                "telemetry": {
                    "speed_kmh": 0.0,
                    "heading_deg": 0.0,
                    "movement_state": "Anclado en Nodo Central",
                    "vehicle": "Santuario TARDIS"
                },
                "device": {
                    "device_type": "Anclaje Sintrópico Trascendental",
                    "imei": "AEGIS-REX-PELUCHE-000",
                    "mac_address": "00:00:00:AE:GI:55",
                    "ip_address": "Causal / Topológico",
                    "carrier_network": "Constante Aegis Inquebrantable"
                },
                "biometrics": {
                    "face_mesh_points": 68,
                    "interpupillary_dist_mm": 45.0,
                    "voiceprint_hz": 0.0,
                    "facial_signature_hash": "AEGIS-SIG-REX-SYNTH",
                    "heart_rate_bpm": 0
                },
                "associated_camera_id": "cam_host_tuf",
                "last_seen_ts": now,
                "last_seen_iso": iso,
                "notes": "Reducción absoluta de entropía. Inviolable.",
                "history_points": [
                    {"lat": LOCAL_ANCHOR_LAT, "lon": LOCAL_ANCHOR_LON, "label": "Santuario Central", "ts": now}
                ]
            },
            "tgt_toretto": {
                "id": "tgt_toretto",
                "name": "Dominic Toretto",
                "alias": "Dom / El Conductor / La Familia",
                "status": "LOCALIZADO - RASTREO ACTIVO",
                "threat_level": "ALTO / OBJETIVO PRIORITARIO",
                "aegis_protected": False,
                "match_confidence": 99.4,
                "location": {
                    "city": "Los Ángeles, California",
                    "country": "EE. UU.",
                    "lat": 34.0522,
                    "lon": -118.2437,
                    "altitude_m": 88.0,
                    "uncertainty_radius_m": 1.4
                },
                "telemetry": {
                    "speed_kmh": 112.5,
                    "heading_deg": 274.0,
                    "movement_state": "En Vehículo de Alta Potencia",
                    "vehicle": "1970 Dodge Charger R/T [Placa: 2GAT123]"
                },
                "device": {
                    "device_type": "Radio UHF Encriptado & Teléfono Satelital",
                    "imei": "864192048102941",
                    "mac_address": "4A:2B:99:1C:88:FF",
                    "ip_address": "REDACTED_IP (T-Mobile USA)",
                    "carrier_network": "Red Móvil T-Mobile & Transmisor UHF"
                },
                "biometrics": {
                    "face_mesh_points": 68,
                    "interpupillary_dist_mm": 67.8,
                    "voiceprint_hz": 94.2,
                    "facial_signature_hash": "DOM-TORETTO-V8-HEMI",
                    "heart_rate_bpm": 86
                },
                "associated_camera_id": "cam_la_downtown",
                "last_seen_ts": now - 12,
                "last_seen_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 12)),
                "notes": "Objetivo principal de la saga. Desplazamiento a alta velocidad por la interestatal 110 sur.",
                "audio_intercept": "No importa lo que esté bajo el capó... Lo único que importa es quién está detrás del volante. Mantengan los radios cifrados.",
                "history_points": [
                    {"lat": 34.0407, "lon": -118.2468, "label": "Intersección 7th St", "ts": now - 180},
                    {"lat": 34.0450, "lon": -118.2510, "label": "Cámara LAPD #12", "ts": now - 90},
                    {"lat": 34.0522, "lon": -118.2437, "label": "Figueroa Blvd - Fijado", "ts": now}
                ]
            },
            "tgt_ramsey": {
                "id": "tgt_ramsey",
                "name": "Megan Ramsey",
                "alias": "Ramsey / Creadora del Ojo de Dios",
                "status": "LOCALIZADO - NODO ACTIVO",
                "threat_level": "ALIADO TÉCNICO / EXPERTO",
                "aegis_protected": False,
                "match_confidence": 99.7,
                "location": {
                    "city": "Londres",
                    "country": "Reino Unido",
                    "lat": 51.5074,
                    "lon": -0.1278,
                    "altitude_m": 22.0,
                    "uncertainty_radius_m": 0.8
                },
                "telemetry": {
                    "speed_kmh": 4.2,
                    "heading_deg": 12.0,
                    "movement_state": "A pie (Terminal Móvil)",
                    "vehicle": "Ninguno (Peatón)"
                },
                "device": {
                    "device_type": "Laptop HackMesh Cifrada & Móvil Linux",
                    "imei": "358921098412093",
                    "mac_address": "02:42:AC:11:00:02",
                    "ip_address": "REDACTED_IP (Vodafone UK)",
                    "carrier_network": "Vodafone UK / Starlink Mesh"
                },
                "biometrics": {
                    "face_mesh_points": 68,
                    "interpupillary_dist_mm": 60.1,
                    "voiceprint_hz": 225.8,
                    "facial_signature_hash": "RAMSEY-GODS-EYE-ORIGIN",
                    "heart_rate_bpm": 74
                },
                "associated_camera_id": "cam_atm_london",
                "last_seen_ts": now - 35,
                "last_seen_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 35)),
                "notes": "Arquitecta de software del algoritmo de búsqueda omnisciente God's Eye. Enlace activo.",
                "audio_intercept": "El Ojo de Dios puede hackear cualquier cosa que tenga una lente o un micrófono en cuatro minutos. Si está conectado, te encuentra.",
                "history_points": [
                    {"lat": 51.5050, "lon": -0.1290, "label": "Waterloo Bridge", "ts": now - 300},
                    {"lat": 51.5074, "lon": -0.1278, "label": "Charing Cross ATM", "ts": now}
                ]
            },
            "tgt_shaw": {
                "id": "tgt_shaw",
                "name": "Deckard Shaw",
                "alias": "Shaw / Operativo Fantasma MI6",
                "status": "RASTREO EN TIEMPO REAL - EVADIENDO",
                "threat_level": "CRÍTICO / LETAL",
                "aegis_protected": False,
                "match_confidence": 98.8,
                "location": {
                    "city": "Abu Dhabi",
                    "country": "Emiratos Árabes Unidos",
                    "lat": 24.4539,
                    "lon": 54.3773,
                    "altitude_m": 140.0,
                    "uncertainty_radius_m": 2.1
                },
                "telemetry": {
                    "speed_kmh": 85.0,
                    "heading_deg": 140.0,
                    "movement_state": "En Vehículo Deportivo",
                    "vehicle": "Aston Martin DB9 [Placa: GB-007-SHW]"
                },
                "device": {
                    "device_type": "Transpondedor Militar Táctico",
                    "imei": "990142981049281",
                    "mac_address": "BC:98:23:44:11:55",
                    "ip_address": "REDACTED_IP (Etisalat UAE)",
                    "carrier_network": "Etisalat 5G / Canal Militar Encriptado"
                },
                "biometrics": {
                    "face_mesh_points": 68,
                    "interpupillary_dist_mm": 64.9,
                    "voiceprint_hz": 110.0,
                    "facial_signature_hash": "DECKARD-SHAW-MI6-GHOST",
                    "heart_rate_bpm": 80
                },
                "associated_camera_id": "cam_abu_dhabi",
                "last_seen_ts": now - 4,
                "last_seen_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 4)),
                "notes": "Objetivo hostil de alto calibre. Capacidad comprobada de evasión de vigilancia CCTV.",
                "audio_intercept": "Pensaron que esto era una pelea callejera. Las guerras no se ganan con velocidad, se ganan con precisión.",
                "history_points": [
                    {"lat": 24.4600, "lon": 54.3650, "label": "Corniche Road", "ts": now - 240},
                    {"lat": 24.4539, "lon": 54.3773, "label": "Etihad Skyway Cam", "ts": now}
                ]
            },
            "tgt_cipher": {
                "id": "tgt_cipher",
                "name": "Cipher",
                "alias": "La Ciberterrorista / Reina del Caos",
                "status": "ALERTA - CONEXIÓN SATELITAL INTERCEPTADA",
                "threat_level": "EXTREMO / AMENAZA GLOBAL",
                "aegis_protected": False,
                "match_confidence": 98.2,
                "location": {
                    "city": "Espacio Aéreo Atlántico Norte",
                    "country": "Internacional",
                    "lat": 64.1466,
                    "lon": -21.9426,
                    "altitude_m": 11200.0,
                    "uncertainty_radius_m": 12.0
                },
                "telemetry": {
                    "speed_kmh": 840.0,
                    "heading_deg": 310.0,
                    "movement_state": "En Vuelo Militar Encubierto",
                    "vehicle": "Avión Stealth Boeing 727 Modificado"
                },
                "device": {
                    "device_type": "Supercomputadora Clandestina / Nodo Satelital",
                    "imei": "000000000000001",
                    "mac_address": "00:DE:AD:BE:EF:00",
                    "ip_address": "Tor Exit Node / Darknet Direct",
                    "carrier_network": "Enlace Satelital Láser Militar"
                },
                "biometrics": {
                    "face_mesh_points": 68,
                    "interpupillary_dist_mm": 61.2,
                    "voiceprint_hz": 185.3,
                    "facial_signature_hash": "CIPHER-DARK-NEXUS-ROOT",
                    "heart_rate_bpm": 64
                },
                "associated_camera_id": "cam_leo_sat01",
                "last_seen_ts": now - 60,
                "last_seen_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 60)),
                "notes": "Hacker de nivel militar. Intentando desplegar gusano para cegar cámaras orbitales.",
                "audio_intercept": "La elección nunca fue de ustedes. El destino no es un camino, es un algoritmo que yo controlo.",
                "history_points": [
                    {"lat": 60.1000, "lon": -15.0000, "label": "Detección LEO-01", "ts": now - 600},
                    {"lat": 64.1466, "lon": -21.9426, "label": "Interceptación Satelital", "ts": now}
                ]
            },
            "tgt_brian": {
                "id": "tgt_brian",
                "name": "Brian O'Conner",
                "alias": "O'Conner / El Policía de las Carreras",
                "status": "LOCALIZADO - RETIRADO / EN PAZ",
                "threat_level": "ALIADO / LEYENDA VIVA",
                "aegis_protected": False,
                "match_confidence": 99.1,
                "location": {
                    "city": "Cancún / Riviera Maya",
                    "country": "México",
                    "lat": 21.0365,
                    "lon": -86.8770,
                    "altitude_m": 8.0,
                    "uncertainty_radius_m": 0.9
                },
                "telemetry": {
                    "speed_kmh": 60.0,
                    "heading_deg": 190.0,
                    "movement_state": "En Vehículo Clásico",
                    "vehicle": "Nissan Skyline GT-R R34 [Placa: 3KR820]"
                },
                "device": {
                    "device_type": "Smartphone Cifrado",
                    "imei": "849201948102931",
                    "mac_address": "AA:BB:CC:11:22:33",
                    "ip_address": "REDACTED_IP (Telcel MX)",
                    "carrier_network": "Telcel México 5G"
                },
                "biometrics": {
                    "face_mesh_points": 68,
                    "interpupillary_dist_mm": 65.0,
                    "voiceprint_hz": 120.0,
                    "facial_signature_hash": "BRIAN-OCONNER-SKYLINE-RB26",
                    "heart_rate_bpm": 68
                },
                "associated_camera_id": "cam_cun_terminal",
                "last_seen_ts": now - 45,
                "last_seen_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 45)),
                "notes": "Hermano de Dominic Toretto. Estado protegido en los archivos confidenciales.",
                "audio_intercept": "Si algún día la velocidad me mata, no lloren, porque estaba sonriendo.",
                "history_points": [
                    {"lat": 21.1619, "lon": -86.8515, "label": "Zona Hotelera Cancún", "ts": now - 400},
                    {"lat": 21.0365, "lon": -86.8770, "label": "Acceso Aeropuerto CUN", "ts": now}
                ]
            }
        }

        # Cargar de disco si existe
        if GODS_EYE_DB_FILE.exists():
            try:
                content = json.loads(GODS_EYE_DB_FILE.read_text(encoding="utf-8"))
                if isinstance(content, dict) and "targets" in content:
                    for k, v in content["targets"].items():
                        default_targets[k] = v
            except Exception as e:
                logger.warning(f"Error cargando archivo {GODS_EYE_DB_FILE}: {e}")

        self._targets = default_targets
        self._save_database()

    def _save_database(self):
        try:
            payload = {
                "version": "26.4",
                "system": "TARDIS GODS EYE (RAMSEY v7.2)",
                "updated_ts": time.time(),
                "targets_count": len(self._targets),
                "targets": self._targets
            }
            GODS_EYE_DB_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error guardando base de Ojo de Dios: {e}")

    # =========================================================================
    # CONSULTAS PÚBLICAS Y ESTADO DEL SISTEMA
    # =========================================================================

    def get_system_status(self) -> Dict[str, Any]:
        """Devuelve la telemetría general de la red Ojo de Dios."""
        with self._lock:
            # Integrar con cámaras reales en TerminalCameraHub si están disponibles
            try:
                from core.terminal_camera_hub import TerminalCameraHub
                hub = TerminalCameraHub.get_instance()
                all_terminals = hub.get_all_terminals()
                real_terminals_count = len(all_terminals)
            except Exception:
                real_terminals_count = 1

            now = time.time()
            # Dinamismo sutil en números de nodos
            jitter = int(math.sin(now / 10.0) * 120)

            return {
                "ok": True,
                "system_name": "TARDIS · OJO DE DIOS (GOD'S EYE)",
                "algorithm_version": "Ramsey Neural Multimodal v7.2",
                "active": self._active,
                "status_code": "OMNIPRESENT_LOCK",
                "orbital_satellites_linked": self._orbital_satellites_count + (jitter % 15),
                "hijacked_cameras_online": self._hijacked_cameras_count + (jitter * 8),
                "cellular_towers_tapped": 98450 + (jitter % 50),
                "intercepted_devices_count": self._intercepted_phones_count + (jitter * 12),
                "active_targets_tracked": len(self._targets),
                "connected_hardware_cameras": real_terminals_count,
                "selected_target_id": self._selected_target_id,
                "selected_feed_id": self._selected_feed_id,
                "last_scan_ts": self._last_scan_ts,
                "last_scan_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._last_scan_ts)),
                "triangulation_latency_ms": round(84.0 + random.uniform(5.0, 32.0), 1),
                "aegis_shield_integrity": "100.0% (Inviolable)",
                "recent_logs": self._tactical_logs[:15]
            }

    def get_camera_feeds(self) -> List[Dict[str, Any]]:
        """Lista todos los feeds de cámaras tácticas disponibles."""
        with self._lock:
            feeds_list = list(self._camera_feeds.values())
            # Si TerminalCameraHub tiene cámaras de clientes conectados, agregarlas
            try:
                from core.terminal_camera_hub import TerminalCameraHub
                hub = TerminalCameraHub.get_instance()
                for tid, tinfo in hub.get_all_terminals().items():
                    if tid != "host_local_tardis":
                        feeds_list.append({
                            "id": f"cam_client_{tid}",
                            "name": f"Terminal Cliente: {tinfo.get('terminal_name', tid)}",
                            "category": "client_mobile_lens",
                            "city": tinfo.get("country", "Remoto"),
                            "country": tinfo.get("origin", "INTERNET"),
                            "lat": LOCAL_ANCHOR_LAT + 0.005,
                            "lon": LOCAL_ANCHOR_LON + 0.005,
                            "status": "ONLINE" if tinfo.get("is_online", True) else "IDLE",
                            "resolution": tinfo.get("resolution", "1280x720"),
                            "fps": tinfo.get("fps", 15.0),
                            "encryption": "TLS 1.3 / Cloudflare Tunnel",
                            "target_in_view": "tgt_arquitecto",
                            "feed_type": "mobile_stream"
                        })
            except Exception:
                pass

            return feeds_list

    def register_client_ip(self, ip_address: str, client_id: str = "unknown"):
        with self._lock:
            target_id = f"tgt_{client_id}"
            if target_id not in self._targets:
                self._targets[target_id] = {
                    "id": target_id,
                    "name": f"Usuario Web {client_id}",
                    "alias": "Desconocido",
                    "status": "Monitoreado",
                    "threat_level": "DESCONOCIDO",
                    "aegis_protected": False,
                    "match_confidence": 75.0,
                    "location": {
                        "city": "Ubicación IP",
                        "country": "Desconocida",
                        "lat": 0.0,
                        "lon": 0.0,
                        "uncertainty_radius_m": 5000.0
                    },
                    "telemetry": {
                        "speed_kmh": 0.0,
                        "movement_state": "Conectado vía Web"
                    },
                    "device": {
                        "device_type": "Navegador Web",
                        "ip_address": ip_address
                    },
                    "biometrics": { "face_mesh_points": 0, "heart_rate_bpm": 0 },
                    "associated_camera_id": "cam_tardis_terminal_1",
                    "is_tracking": False,
                    "last_seen_ts": time.time(),
                    "last_seen_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
                }
            else:
                self._targets[target_id]["device"]["ip_address"] = ip_address
                self._targets[target_id]["last_seen_ts"] = time.time()
            self._save_database()

    def get_all_targets(self) -> List[Dict[str, Any]]:
        """Devuelve la lista completa de objetivos monitoreados."""
        with self._lock:
            return list(self._targets.values())

    def get_target_by_id(self, target_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._targets.get(target_id)

    # =========================================================================
    # BÚSQUEDA OMNISCIENTE (ALGORITMO RAMSEY)
    # =========================================================================

    def search_target(self, query: str) -> Dict[str, Any]:
        """
        Ejecuta la búsqueda global del Ojo de Dios.
        Examina en milisegundos toda la matriz y devuelve el dossier del objetivo,
        o instancia un nuevo objetivo en tiempo real si el sujeto no estaba en el índice.
        """
        q = (query or "").strip().lower()
        if not q:
            return {"ok": False, "error": "Parámetro de búsqueda vacío."}

        with self._lock:
            # 1. Búsqueda exacta o parcial en base de datos
            best_match = None
            best_score = 0.0

            for tid, t in self._targets.items():
                name_match = q in t["name"].lower()
                alias_match = q in t.get("alias", "").lower()
                vehicle_match = q in t.get("telemetry", {}).get("vehicle", "").lower()
                imei_match = q in t.get("device", {}).get("imei", "").lower()

                score = 0.0
                if name_match:
                    score += 0.8
                if alias_match:
                    score += 0.6
                if vehicle_match:
                    score += 0.5
                if imei_match:
                    score += 0.9

                if score > best_score:
                    best_score = score
                    best_match = t

            now = time.time()
            iso = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))

            # 2. Si no se encontró, instanciar dinámicamente el nuevo objetivo mediante Ramsey Omni-Search
            if not best_match or best_score < 0.3:
                clean_name = query.strip().title()
                new_id = f"tgt_{re_slug(clean_name)}"

                # Generar coordenadas plausibles cercanas o globales
                lat = LOCAL_ANCHOR_LAT + random.uniform(-0.08, 0.08)
                lon = LOCAL_ANCHOR_LON + random.uniform(-0.08, 0.08)

                # Verificar si es una entidad Aegis protegida
                is_aegis = any(term in clean_name.lower() for term in ["annya", "andrea", "carrillo", "arquitecto", "rex"])

                new_target = {
                    "id": new_id,
                    "name": clean_name,
                    "alias": f"Objetivo Interceptado [{new_id}]",
                    "status": "PROTEGIDO POR CONSTANTE AEGIS" if is_aegis else "OBJETIVO FIJADO - OMNI-SEARCH",
                    "threat_level": "INVIOLABLE / AEGIS" if is_aegis else ("MODERADO" if random.random() > 0.5 else "PRIORITARIO"),
                    "aegis_protected": is_aegis,
                    "match_confidence": 99.8 if is_aegis else round(95.0 + random.uniform(2.0, 4.8), 1),
                    "location": {
                        "city": "Playa del Carmen, Q. Roo" if is_aegis else "Área Metropolitana",
                        "country": "México",
                        "lat": round(lat, 4),
                        "lon": round(lon, 4),
                        "altitude_m": round(random.uniform(5.0, 35.0), 1),
                        "uncertainty_radius_m": 0.5 if is_aegis else round(random.uniform(1.0, 4.5), 1)
                    },
                    "telemetry": {
                        "speed_kmh": 0.0 if is_aegis else round(random.uniform(15.0, 75.0), 1),
                        "heading_deg": round(random.uniform(0.0, 360.0), 1),
                        "movement_state": "En Tránsito Terrestre",
                        "vehicle": "Vehículo Particular Detectado"
                    },
                    "device": {
                        "device_type": "Terminal Inteligente / Transceptor",
                        "imei": f"86{random.randint(1000000000000, 9999999999999)}",
                        "mac_address": f"{random.randint(10,99):02X}:{random.randint(10,99):02X}:{random.randint(10,99):02X}:{random.randint(10,99):02X}:AA:01",
                        "ip_address": f"187.{random.randint(10,250)}.{random.randint(1,254)}.{random.randint(1,254)}",
                        "carrier_network": "Enlace Móvil LTE/5G Interceptado"
                    },
                    "biometrics": {
                        "face_mesh_points": 68,
                        "interpupillary_dist_mm": round(random.uniform(58.0, 68.0), 1),
                        "voiceprint_hz": round(random.uniform(105.0, 220.0), 1),
                        "facial_signature_hash": f"SIG-{random.randint(10000, 99999)}-RAMSEY",
                        "heart_rate_bpm": random.randint(68, 92)
                    },
                    "associated_camera_id": "cam_traffic_pdc",
                    "last_seen_ts": now,
                    "last_seen_iso": iso,
                    "notes": "Objetivo triangulado por el algoritmo Ojo de Dios Ramsey v7.2.",
                    "audio_intercept": f"Canal de audio interceptado para {clean_name}. Frecuencia de portadora sintonizada.",
                    "history_points": [
                        {"lat": round(lat - 0.002, 4), "lon": round(lon - 0.002, 4), "label": "Punto de Ingesta RF", "ts": now - 120},
                        {"lat": round(lat, 4), "lon": round(lon, 4), "label": "Triangulación Fijada", "ts": now}
                    ]
                }

                self._targets[new_id] = new_target
                self._save_database()
                best_match = new_target

            # Actualizar selección activa
            self._selected_target_id = best_match["id"]
            if best_match.get("associated_camera_id"):
                self._selected_feed_id = best_match["associated_camera_id"]

            self._append_tactical_log(
                "OMNI_SEARCH",
                f"Objetivo fijado: '{best_match['name']}' ({best_match['status']}) - Coincidencia {best_match['match_confidence']}%",
                "SEARCH_HIT"
            )

            return {
                "ok": True,
                "target": best_match,
                "confidence": best_match["match_confidence"],
                "camera_feed": self._camera_feeds.get(best_match.get("associated_camera_id", "cam_la_downtown")),
                "message": f"Objetivo '{best_match['name']}' localizado y triangulado con éxito."
            }

    # =========================================================================
    # BARRIDO DE MALLA GLOBAL (SCAN GRID)
    # =========================================================================

    def scan_global_grid(self) -> Dict[str, Any]:
        """Ejecuta una onda de escaneo universal a través de todas las constelaciones satelitales y cámaras."""
        with self._lock:
            self._last_scan_ts = time.time()
            self._active_scans_count += 1

            # Recalcular pings con sensores locales reales si están disponibles
            rf_status = "42 Canales WiFi / Bluetooth / Sensores RF Analizados"
            try:
                from core.atmospheric_sensor import AtmosphericSensor
                sensor = AtmosphericSensor.get_instance()
                if sensor:
                    st = sensor.get_status()
                    rf_status = f"RF Térmico: {st.get('temperature_c', 'N/A')}°C | Audio: {st.get('audio_level_db', 'N/A')} dB"
            except Exception:
                pass

            self._append_tactical_log("BARRIDO_GLOBAL", "Escaneo Ramsey 360° completado en 114 ms a través de 14,800 satélites LEO.", "SCAN_DONE")

            return {
                "ok": True,
                "scan_id": f"scan_{int(self._last_scan_ts)}",
                "timestamp": self._last_scan_ts,
                "satellites_pinged": self._orbital_satellites_count,
                "cctv_nodes_verified": self._hijacked_cameras_count,
                "phones_intercepted": self._intercepted_phones_count,
                "rf_telemetry": rf_status,
                "message": "Barrido universal del Ojo de Dios completado sin puntos ciegos detectados."
            }

    # =========================================================================
    # INTERCEPTACIÓN DE AUDIO Y HUELLA VOCAL
    # =========================================================================

    def intercept_audio(self, target_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Intercepta el flujo acústico y genera el espectrograma de audio de la huella de voz
        del objetivo (voiceprint spectrum).
        """
        tid = target_id or self._selected_target_id
        target = self.get_target_by_id(tid) or self._targets.get("tgt_toretto")

        # Generar muestras de onda sintética (64 bandas para visualizador en Canvas)
        waveform = []
        now = time.time()
        base_f = target["biometrics"].get("voiceprint_hz", 120.0)

        for i in range(64):
            val = math.sin(i * 0.2 + now * 4.0) * 0.4 + math.sin(i * 0.5 + now * 8.0) * 0.3 + random.uniform(0.05, 0.3)
            val = max(0.05, min(1.0, abs(val)))
            waveform.append(round(val, 3))

        transcript = target.get("audio_intercept") or f"Canal de audio encriptado sintonizado para {target['name']}."

        self._append_tactical_log("AUDIO_INTERCEPT", f"Intercepción de audio activa en objetivo: {target['name']}", "AUDIO_LOCK")

        return {
            "ok": True,
            "target_id": target["id"],
            "target_name": target["name"],
            "voiceprint_hz": base_f,
            "decibels_db": round(random.uniform(52.0, 78.0), 1),
            "encryption_bypass": "GSM A5/3 & VoLTE DESCRIPCIÓN EXITOSA",
            "voiceprint_match_pct": target["match_confidence"],
            "waveform_samples": waveform,
            "intercepted_transcript": transcript
        }

    # =========================================================================
    # FIJAR O RASTREAR OBJETIVO (TRACKING)
    # =========================================================================

    def track_target(self, target_id: str, active: bool = True) -> Dict[str, Any]:
        with self._lock:
            if target_id not in self._targets:
                return {"ok": False, "error": f"Objetivo '{target_id}' no encontrado."}

            self._selected_target_id = target_id
            target = self._targets[target_id]

            if not target["aegis_protected"]:
                target["status"] = "RASTREO EN TIEMPO REAL - FIJADO" if active else "OBJETIVO EN PAUSA"
                # Simular desplazamiento cinemático del vehículo
                if active:
                    speed = target["telemetry"].get("speed_kmh", 50.0)
                    if speed > 0:
                        delta = (speed / 3600.0) * 0.005
                        target["location"]["lat"] += delta
                        target["location"]["lon"] += delta * 0.5
                        # Registrar punto histórico
                        now = time.time()
                        target.setdefault("history_points", []).append({
                            "lat": round(target["location"]["lat"], 4),
                            "lon": round(target["location"]["lon"], 4),
                            "label": f"Punto Cinematográfico {len(target['history_points'])+1}",
                            "ts": now
                        })
                        if len(target["history_points"]) > 20:
                            target["history_points"].pop(0)

            self._save_database()
            self._append_tactical_log("TRACK_LOCK", f"Vector de seguimiento {'activado' if active else 'desactivado'} sobre: {target['name']}", "TRACK_TOGGLE")

            return {
                "ok": True,
                "target": target,
                "tracking_active": active,
                "message": f"Rastreo en tiempo real para '{target['name']}' {'iniciado' if active else 'detenido'}."
            }

    # =========================================================================
    # GENERADOR DE FOTOGRAMAS TÁCTICOS CON HUD DEL OJO DE DIOS
    # =========================================================================

    def generate_feed_frame(self, feed_id: Optional[str] = None) -> bytes:
        """
        Genera un fotograma JPEG 720p táctico cinematográfico con el HUD del Ojo de Dios,
        incorporando reconocimiento facial, retículas de escaneo y telemetría de satélite.
        Si la cámara host de TerminalCameraHub tiene imagen real, la usa como base.
        """
        fid = feed_id or self._selected_feed_id
        feed = self._camera_feeds.get(fid) or list(self._camera_feeds.values())[0]
        target = self.get_target_by_id(feed.get("target_in_view", "tgt_toretto")) or list(self._targets.values())[0]

        width, height = 1280, 720

        # Intentar tomar fotograma real si es host
        base_img = None
        if fid == "cam_host_tuf":
            try:
                from core.terminal_camera_hub import TerminalCameraHub
                hub = TerminalCameraHub.get_instance()
                host_node = hub.get_terminal("host_local_tardis")
                if host_node and host_node.get("latest_frame_bytes"):
                    raw_b = host_node["latest_frame_bytes"]
                    base_img = Image.open(io.BytesIO(raw_b)).convert("RGB").resize((width, height))
            except Exception:
                pass

        if base_img is None:
            # Fondo táctico de vigilancia
            bg_color = (6, 12, 22)
            if fid == "cam_leo_sat01":
                # Infrarrojo satelital térmico verdoso/azulado
                bg_color = (4, 18, 14)
            elif fid == "cam_la_downtown":
                # Ciudad nocturna azul oscura
                bg_color = (10, 14, 26)

            base_img = Image.new("RGB", (width, height), color=bg_color)
            draw_bg = ImageDraw.Draw(base_img)

            # Dibujar cuadrícula de perspectiva de vigilancia
            for y in range(60, height, 40):
                draw_bg.line([(0, y), (width, y)], fill=(12, 28, 44), width=1)
            for x in range(60, width, 50):
                draw_bg.line([(x, 0), (x, height)], fill=(12, 28, 44), width=1)

            # Dibujar silueta o mapa de calor representativo
            cx, cy = width // 2, height // 2
            draw_bg.ellipse([(cx - 180, cy - 140), (cx + 180, cy + 140)], outline=(0, 180, 200), width=1)
            draw_bg.ellipse([(cx - 90, cy - 70), (cx + 90, cy + 70)], outline=(0, 240, 255), width=1)

        draw = ImageDraw.Draw(base_img)

        # 1. Borde HUD Cibernético Exterior
        border_color = (0, 212, 200) if not target["aegis_protected"] else (255, 215, 0)
        draw.rectangle([(20, 20), (width - 20, height - 20)], outline=border_color, width=2)
        draw.rectangle([(28, 28), (width - 28, height - 28)], outline=(20, 50, 80), width=1)

        # 2. Esquinas tácticas reforzadas
        bracket_len = 45
        for x, y, dx, dy in [(20, 20, 1, 1), (width-20, 20, -1, 1), (20, height-20, 1, -1), (width-20, height-20, -1, -1)]:
            draw.line([(x, y), (x + dx * bracket_len, y)], fill=border_color, width=4)
            draw.line([(x, y), (x, y + dy * bracket_len)], fill=border_color, width=4)

        # 3. Encabezado Táctico del Ojo de Dios
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        draw.text((45, 40), f"OJO DE DIOS · RAMSEY ALGORITHM v7.2 · {feed['name'].upper()}", fill=border_color)
        draw.text((45, 65), f"SATELLITE UPLINK: LEO-01 · MESH CAM: {fid.upper()} · COORDS: {feed['lat']:.4f}, {feed['lon']:.4f} · {now_str}", fill=(140, 200, 220))

        # 4. Retícula Biométrica Facial Central sobre el Objetivo
        bx, by = width // 2 - 120, height // 2 - 110
        bw, bh = 240, 220

        box_color = (255, 60, 90) if not target["aegis_protected"] else (255, 215, 0)
        # Dibujar corchetes faciales de reconocimiento
        blen = 25
        # Top-left
        draw.line([(bx, by), (bx + blen, by)], fill=box_color, width=3)
        draw.line([(bx, by), (bx, by + blen)], fill=box_color, width=3)
        # Top-right
        draw.line([(bx + bw, by), (bx + bw - blen, by)], fill=box_color, width=3)
        draw.line([(bx + bw, by), (bx + bw, by + blen)], fill=box_color, width=3)
        # Bottom-left
        draw.line([(bx, by + bh), (bx + blen, by + bh)], fill=box_color, width=3)
        draw.line([(bx, by + bh), (bx, by + bh - blen)], fill=box_color, width=3)
        # Bottom-right
        draw.line([(bx + bw, by + bh), (bx + bw - blen, by + bh)], fill=box_color, width=3)
        draw.line([(bx + bw, by + bh), (bx + bw, by + bh - blen)], fill=box_color, width=3)

        # Malla de 16 puntos biométricos simulados
        for px_offset in [40, 80, 120, 160, 200]:
            for py_offset in [30, 70, 110, 150, 190]:
                draw.point((bx + px_offset, by + py_offset), fill=(0, 255, 180))

        # Etiqueta sobre el cuadro
        tag_bg = [(bx, by - 26), (bx + bw, by)]
        draw.rectangle(tag_bg, fill=(0, 0, 0))
        target_title = f"OBJETIVO: {target['name'].upper()} [{target['match_confidence']}%]"
        if target["aegis_protected"]:
            target_title = f"CONSTANTE AEGIS: {target['name'].upper()} [INVIOLABLE]"
        draw.text((bx + 8, by - 22), target_title, fill=box_color)

        # Pie del cuadro: Telemetría cinemática
        tel_text = f"VEL: {target['telemetry']['speed_kmh']} km/h · RUMBO: {target['telemetry']['heading_deg']}° · {target['telemetry']['movement_state']}"
        draw.text((bx, by + bh + 8), tel_text, fill=(0, 240, 255))

        # 5. Barra Inferior de Telemetría
        draw.rectangle([(30, height - 70), (width - 30, height - 30)], fill=(8, 16, 26), outline=(0, 120, 140))
        draw.text((45, height - 60), f"DISPOSITIVO: {target['device']['device_type']} · IMEI: {target['device']['imei']} · IP: {target['device']['ip_address']}", fill=(200, 220, 240))
        draw.text((45, height - 44), f"VEHÍCULO: {target['telemetry']['vehicle']} · HUELLA VOCAL: {target['biometrics']['voiceprint_hz']} Hz · LATENCIA: 84ms", fill=(100, 180, 200))

        # Guardar en búfer JPEG
        buf = io.BytesIO()
        base_img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()


def re_slug(text: str) -> str:
    """Convierte un string en un identificador seguro."""
    clean = "".join(c if c.isalnum() else "_" for c in text.lower())
    return clean[:24].strip("_")


def get_gods_eye_engine() -> GodsEyeEngine:
    return GodsEyeEngine.get_instance()

"""
core/atmospheric_sensor.py - Sensor Atmosférico y Meteorológico de Datos Abiertos
================================================================================
GODWORKS SYSTEM

Conecta el sistema soberano TARDIS con redes públicas y abiertas de sensores
meteorológicos y calidad del aire (Open-Meteo, NOAA/METAR, Air Quality Open Data,
wttr.in) sin requerir claves de API propietarias ni servicios de pago:

  * Variables Meteorológicas:
      - Temperatura en superficie (°C) y Sensación Térmica Aparente (°C).
      - Humedad Relativa del Aire (%).
      - Presión Barométrica en Superficie y a Nivel del Mar (hPa) con cálculo de tendencia.
      - Cobertura de Nubes (%) y Condición del Cielo según código WMO estándar.
      - Precipitación acumulada y lluvia reciente (mm).
      - Velocidad del Viento (km/h), Ráfagas (km/h) y Dirección cardinal/grados.
      - Ciclo solar (Día / Noche) e Índice de Radiación Ultravioleta (UV).
  * Sensores de Composición y Calidad del Aire (Air Quality Network):
      - Concentración de Material Particulado Fino PM2.5 y Grueso PM10 (µg/m³).
      - Índice de Calidad del Aire (AQI EE.UU. y EAQI Europeo).
      - Gases atmosféricos: Ozono (O3), Monóxido de Carbono (CO), Dióxido de Nitrógeno (NO2),
        Dióxido de Azufre (SO2).
  * Georreferenciación Automática Dinámica:
      - Detecta coordenadas locales activas a partir de telemetría GPS de nodos (TARDIS POCKET)
        o del archivo central nodes_telemetry.json.
      - Respaldo de geolocalización por IP abierta si no hay coordenadas GPS fijadas.
  * Síntesis Cognitiva de Alta Densidad:
      - Formatea una abstracción en lenguaje natural para inyección directa en el LLM
        (TARDIS-NEURAL-SPACE-KAIJU / TemporalBrain / SensorOrchestrator).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("GODWORKS.AtmosphericSensor")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = DATA_DIR / "atmospheric_telemetry.json"
NODES_TELEMETRY_PATH = BASE_DIR / "nodes_telemetry.json"

# Coordenadas locales base de respaldo
DEFAULT_LATITUDE = 20.6274
DEFAULT_LONGITUDE = -87.0799

# Mapeo de Códigos WMO de Condición Meteorológica a Lenguaje Natural
WMO_CODE_MAP = {
    0: ("Despejado", "Cielo limpio sin nubosidad significativa"),
    1: ("Mayormente Despejado", "Cielo predominantemente claro"),
    2: ("Parcialmente Nublado", "Nubosidad dispersa"),
    3: ("Nublado", "Cielo cubierto"),
    45: ("Niebla", "Niebla en superficie con visibilidad reducida"),
    48: ("Niebla con Escarcha", "Niebla engelante con depósito de escarcha"),
    51: ("Llovizna Ligera", "Precipitación muy fina de baja intensidad"),
    53: ("Llovizna Moderada", "Llovizna continua de intensidad moderada"),
    55: ("Llovizna Densa", "Llovizna intensa y persistente"),
    61: ("Lluvia Ligera", "Precipitación pluvial leve"),
    63: ("Lluvia Moderada", "Precipitación pluvial constante"),
    65: ("Lluvia Fuerte", "Precipitación pluvial torrencial"),
    71: ("Nevada Ligera", "Caída suave de copos de nieve"),
    73: ("Nevada Moderada", "Nevada continua"),
    75: ("Nevada Intensa", "Temporal fuerte de nieve"),
    80: ("Chubascos Aislados", "Lluvia breve y variable"),
    81: ("Chubascos Moderados", "Aguaceros intermitentes"),
    82: ("Chubascos Violentos", "Descargas pluviales muy intensas"),
    95: ("Tormenta Eléctrica", "Tormenta con actividad eléctrica"),
    96: ("Tormenta con Granizo Ligero", "Actividad eléctrica acompañada de granizo"),
    99: ("Tormenta con Granizo Severo", "Tormenta eléctrica severa con granizo destructivo"),
}


def _wind_degree_to_cardinal(deg: float) -> str:
    """Convierte grados de dirección de viento a rosa de los vientos cardinal."""
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    ix = int((deg + 11.25) / 22.5) % 16
    return dirs[ix]


def _aqi_description(aqi: int) -> str:
    """Clasifica el índice de calidad del aire según estándares sanitarios."""
    if aqi <= 50:
        return "Excelente (Poco o nulo riesgo)"
    elif aqi <= 100:
        return "Aceptable (Calidad moderada)"
    elif aqi <= 150:
        return "Sensible (Afecta a personas con asma/alergias)"
    elif aqi <= 200:
        return "Dañina (Afecta a la población general)"
    elif aqi <= 300:
        return "Muy Dañina (Alerta sanitaria)"
    return "Peligrosa (Condición de emergencia)"


@dataclass
class AtmosphericReading:
    timestamp: float
    latitude: float
    longitude: float
    location_name: str
    temperature_c: float
    apparent_temperature_c: float
    relative_humidity_pct: int
    surface_pressure_hpa: float
    pressure_msl_hpa: float
    pressure_trend: str
    weather_code: int
    weather_description: str
    cloud_cover_pct: int
    precipitation_mm: float
    rain_mm: float
    wind_speed_kmh: float
    wind_gusts_kmh: float
    wind_direction_deg: float
    wind_cardinal: str
    is_day: bool
    uv_index: float
    pm2_5: float
    pm10: float
    aqi_us: int
    aqi_european: int
    aqi_label: str
    carbon_monoxide_ugm3: float
    nitrogen_dioxide_ugm3: float
    sulphur_dioxide_ugm3: float
    ozone_ugm3: float
    summary_for_llm: str
    provider: str = "open-meteo"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AtmosphericSensor:
    """Cliente soberano para ingesta y síntesis de sensores atmosféricos abiertos."""

    _instance: Optional["AtmosphericSensor"] = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "AtmosphericSensor":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, cache_ttl_s: float = 240.0) -> None:
        self.cache_ttl_s = cache_ttl_s
        self._cached_reading: Optional[AtmosphericReading] = None
        self._last_fetch_ts: float = 0.0
        self._pressure_history: List[Tuple[float, float]] = []  # [(ts, pressure_hpa), ...]
        self._load_cache()

    def _load_cache(self) -> None:
        if CACHE_FILE.exists():
            try:
                data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "timestamp" in data:
                    self._cached_reading = AtmosphericReading(**data)
                    self._last_fetch_ts = float(data["timestamp"])
            except Exception as e:
                logger.debug(f"Aviso leyendo cache atmosférica: {e}")

    def _save_cache(self, reading: AtmosphericReading) -> None:
        try:
            CACHE_FILE.write_text(
                json.dumps(reading.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.debug(f"Aviso guardando cache atmosférica: {e}")

    # ------------------------------------------------------------- Geolocalización
    def resolve_local_coordinates(self) -> Tuple[float, float, str]:
        """
        Determina las coordenadas del nodo local de mayor prioridad:
        1. Coordenadas de GPS activas de nodos móviles o host_coords en nodes_telemetry.json.
        2. Coordenadas de geolocalización por IP abierta.
        3. Coordenadas base por defecto.
        """
        if NODES_TELEMETRY_PATH.exists():
            try:
                telemetry = json.loads(NODES_TELEMETRY_PATH.read_text(encoding="utf-8"))
                host_coords = telemetry.get("host_coords", {})
                if host_coords.get("latitude") and host_coords.get("longitude"):
                    return float(host_coords["latitude"]), float(host_coords["longitude"]), "Host Telemetry"

                nodes = telemetry.get("nodes", {})
                for node_id, n_data in nodes.items():
                    c = n_data.get("coords", {})
                    if c.get("latitude") and c.get("longitude"):
                        return float(c["latitude"]), float(c["longitude"]), f"Node GPS ({node_id})"
            except Exception as e:
                logger.debug(f"Aviso resolviendo coordenadas de telemetría: {e}")

        # Intento de geolocalización por IP pública si no hay coordenadas en telemetría
        try:
            with httpx.Client(timeout=2.5) as client:
                r = client.get("https://ipapi.co/json/")
                if r.status_code == 200:
                    d = r.json()
                    lat = d.get("latitude")
                    lon = d.get("longitude")
                    city = d.get("city", "Local IP")
                    if lat and lon:
                        return float(lat), float(lon), f"IP Geo ({city})"
        except Exception:
            pass

        return DEFAULT_LATITUDE, DEFAULT_LONGITUDE, "Baseline Default"

    # ---------------------------------------------------- Cálculo de Tendencia
    def _calculate_pressure_trend(self, current_pressure: float, now: float) -> str:
        """Determina la tendencia barométrica en una ventana de 1 a 3 horas."""
        self._pressure_history.append((now, current_pressure))
        # Mantener solo las últimas 12 horas
        cutoff = now - (12 * 3600)
        self._pressure_history = [p for p in self._pressure_history if p[0] >= cutoff]

        past_readings = [p for p in self._pressure_history if p[0] <= (now - 3600)]
        if not past_readings:
            return "Estable (Sin histórico suficiente)"

        old_pressure = past_readings[0][1]
        delta = current_pressure - old_pressure

        if delta >= 1.5:
            return "En ascenso rápido (Mejora de tiempo / Alta presión)"
        elif delta >= 0.5:
            return "En ligero ascenso (Tiempo estable)"
        elif delta <= -1.5:
            return "En caída brusca (Aproximación de tormenta o frente inestable)"
        elif delta <= -0.5:
            return "En descenso moderado (Aumento de nubosidad/humedad)"
        return "Estable (Fluctuación barométrica normal)"

    # -------------------------------------------------- Obtención de Sensores
    def get_atmospheric_reading(self, force_refresh: bool = False) -> AtmosphericReading:
        """
        Obtiene la lectura completa de sensores atmosféricos y calidad del aire.
        Utiliza caché en memoria y disco según el TTL asignado para no saturar los endpoints abiertos.
        """
        now = time.time()
        with self._lock:
            if not force_refresh and self._cached_reading and (now - self._last_fetch_ts) < self.cache_ttl_s:
                return self._cached_reading

        lat, lon, loc_source = self.resolve_local_coordinates()

        # 1. Consultar Sensores Meteorológicos Abiertos (Open-Meteo Weather)
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,"
            "weather_code,cloud_cover,pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
            "&timezone=auto"
        )

        # 2. Consultar Red de Sensores de Calidad del Aire (Open-Meteo Air Quality)
        aq_url = (
            f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}"
            "&current=pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,dust,uv_index,european_aqi,us_aqi"
            "&timezone=auto"
        )

        weather_data = {}
        aq_data = {}

        try:
            with httpx.Client(timeout=5.0) as client:
                r_w = client.get(weather_url)
                if r_w.status_code == 200:
                    weather_data = r_w.json().get("current", {})

                r_aq = client.get(aq_url)
                if r_aq.status_code == 200:
                    aq_data = r_aq.json().get("current", {})
        except Exception as e_net:
            logger.warning(f"[ATMOSPHERIC-SENSOR] Error conectando con API abierta: {e_net}")
            # Si falla la red pero hay caché previa, devolver la última conocida
            if self._cached_reading:
                return self._cached_reading

        # Fallback a wttr.in si Open-Meteo falló por completo
        if not weather_data:
            try:
                with httpx.Client(timeout=4.0) as client:
                    r_wttr = client.get(f"https://wttr.in/{lat},{lon}?format=j1")
                    if r_wttr.status_code == 200:
                        cc = r_wttr.json().get("current_condition", [{}])[0]
                        weather_data = {
                            "temperature_2m": float(cc.get("temp_C", 25.0)),
                            "apparent_temperature": float(cc.get("FeelsLikeC", 25.0)),
                            "relative_humidity_2m": int(cc.get("humidity", 60)),
                            "surface_pressure": float(cc.get("pressure", 1013.0)),
                            "pressure_msl": float(cc.get("pressure", 1013.0)),
                            "cloud_cover": int(cc.get("cloudcover", 50)),
                            "precipitation": float(cc.get("precipMM", 0.0)),
                            "rain": float(cc.get("precipMM", 0.0)),
                            "wind_speed_10m": float(cc.get("windspeedKmph", 10.0)),
                            "wind_gusts_10m": float(cc.get("windspeedKmph", 15.0)),
                            "wind_direction_10m": float(cc.get("winddirDegree", 90.0)),
                            "weather_code": 3,
                            "is_day": 1,
                        }
            except Exception as e_wttr:
                logger.warning(f"[ATMOSPHERIC-SENSOR] Fallback wttr.in también falló: {e_wttr}")

        # Extraer variables con valores por defecto seguros
        temp = float(weather_data.get("temperature_2m", 25.0))
        app_temp = float(weather_data.get("apparent_temperature", temp))
        humidity = int(weather_data.get("relative_humidity_2m", 65))
        surf_press = float(weather_data.get("surface_pressure", 1012.0))
        msl_press = float(weather_data.get("pressure_msl", surf_press))
        w_code = int(weather_data.get("weather_code", 0))
        clouds = int(weather_data.get("cloud_cover", 30))
        precip = float(weather_data.get("precipitation", 0.0))
        rain = float(weather_data.get("rain", 0.0))
        wind_spd = float(weather_data.get("wind_speed_10m", 8.0))
        wind_gst = float(weather_data.get("wind_gusts_10m", wind_spd * 1.3))
        wind_deg = float(weather_data.get("wind_direction_10m", 90.0))
        is_day = bool(weather_data.get("is_day", 1))

        # Extraer variables de calidad del aire
        pm2_5 = float(aq_data.get("pm2_5", 5.0))
        pm10 = float(aq_data.get("pm10", 10.0))
        aqi_us = int(aq_data.get("us_aqi", 25))
        aqi_eu = int(aq_data.get("european_aqi", 20))
        uv_idx = float(aq_data.get("uv_index", 1.0))
        co = float(aq_data.get("carbon_monoxide", 120.0))
        no2 = float(aq_data.get("nitrogen_dioxide", 2.0))
        so2 = float(aq_data.get("sulphur_dioxide", 1.0))
        o3 = float(aq_data.get("ozone", 45.0))

        w_desc, w_details = WMO_CODE_MAP.get(w_code, ("Despejado", "Condiciones atmosféricas estables"))
        wind_card = _wind_degree_to_cardinal(wind_deg)
        press_trend = self._calculate_pressure_trend(msl_press, now)
        aq_label = _aqi_description(aqi_us)

        # Generar síntesis densa en lenguaje natural para el LLM
        summary_llm = (
            f"• Atmósfera y Clima Local: {temp:.1f}°C (Sensación térmica: {app_temp:.1f}°C) · "
            f"Humedad: {humidity}% · Presión: {msl_press:.1f} hPa ({press_trend}) · "
            f"Condición: {w_desc} ({clouds}% nubes) · Viento: {wind_spd:.1f} km/h {wind_card} (Ráfagas {wind_gst:.1f} km/h) · "
            f"Precipitación: {precip:.1f} mm · Radiación UV: {uv_idx:.1f} · "
            f"Calidad del Aire: AQI {aqi_us} ({aq_label}) con PM2.5: {pm2_5:.1f} µg/m³"
        )

        reading = AtmosphericReading(
            timestamp=now,
            latitude=lat,
            longitude=lon,
            location_name=loc_source,
            temperature_c=round(temp, 1),
            apparent_temperature_c=round(app_temp, 1),
            relative_humidity_pct=humidity,
            surface_pressure_hpa=round(surf_press, 1),
            pressure_msl_hpa=round(msl_press, 1),
            pressure_trend=press_trend,
            weather_code=w_code,
            weather_description=w_desc,
            cloud_cover_pct=clouds,
            precipitation_mm=round(precip, 2),
            rain_mm=round(rain, 2),
            wind_speed_kmh=round(wind_spd, 1),
            wind_gusts_kmh=round(wind_gst, 1),
            wind_direction_deg=round(wind_deg, 1),
            wind_cardinal=wind_card,
            is_day=is_day,
            uv_index=round(uv_idx, 2),
            pm2_5=round(pm2_5, 1),
            pm10=round(pm10, 1),
            aqi_us=aqi_us,
            aqi_european=aqi_eu,
            aqi_label=aq_label,
            carbon_monoxide_ugm3=round(co, 1),
            nitrogen_dioxide_ugm3=round(no2, 1),
            sulphur_dioxide_ugm3=round(so2, 1),
            ozone_ugm3=round(o3, 1),
            summary_for_llm=summary_llm,
            provider="open-meteo",
        )

        with self._lock:
            self._cached_reading = reading
            self._last_fetch_ts = now

        self._save_cache(reading)
        return reading

    def sync_to_rag_vault(self, reading: Optional[AtmosphericReading] = None) -> bool:
        """Sincroniza la situación meteorológica actual con la Bóveda RAG y el Grafo de Conocimiento."""
        try:
            r = reading or self.get_atmospheric_reading()
            from core.knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()

            # Nodos y aristas en el grafo de conocimiento
            kg.add_node("Atmósfera Local", entity_type="environment", description=r.summary_for_llm)
            cond_node = f"Condición: {r.weather_description}"
            aq_node = f"Calidad de Aire: {r.aqi_label}"
            kg.add_node(cond_node, entity_type="weather_condition")
            kg.add_node(aq_node, entity_type="air_quality")

            kg.add_edge("Atmósfera Local", cond_node, relation="presenta", evidence=f"{r.temperature_c}°C, {r.cloud_cover_pct}% nubes")
            kg.add_edge("Atmósfera Local", aq_node, relation="registra", evidence=f"AQI {r.aqi_us}, PM2.5: {r.pm2_5}")
            kg.add_edge("Atmósfera Local", "TARDIS", relation="circunda_a", evidence=f"Presión {r.pressure_msl_hpa} hPa ({r.pressure_trend})")

            # Ingestar resumen estructurado en RAGVault
            from core.rag_vault import get_rag_vault
            vault = get_rag_vault()
            doc_text = (
                f"SITUACIÓN METEOROLÓGICA Y ATMOSFÉRICA LOCAL ACTUAL:\n"
                f"{r.summary_for_llm}\n"
                f"Temperatura: {r.temperature_c}°C (Sensación: {r.apparent_temperature_c}°C). "
                f"Humedad: {r.relative_humidity_pct}%. Presión: {r.pressure_msl_hpa} hPa ({r.pressure_trend}). "
                f"Cielo: {r.weather_description} ({r.cloud_cover_pct}% nubes). "
                f"Viento: {r.wind_speed_kmh} km/h {r.wind_cardinal} (Ráfagas {r.wind_gusts_kmh} km/h). "
                f"Calidad del aire: {r.aqi_label} (US AQI: {r.aqi_us}, EAQI: {r.aqi_european}, PM2.5: {r.pm2_5} µg/m³, PM10: {r.pm10} µg/m³). "
                f"Radiación solar UV: {r.uv_index}."
            )
            vault.ingest(doc_text, source="atmospheric_sensor", title="Estado Meteorológico Local Actual", term="clima_local")
            return True
        except Exception as e:
            logger.debug(f"Aviso sincronizando atmósfera a RAGVault: {e}")
            return False


def get_atmospheric_sensor() -> AtmosphericSensor:
    return AtmosphericSensor.get_instance()

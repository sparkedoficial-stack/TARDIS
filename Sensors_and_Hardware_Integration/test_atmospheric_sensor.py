"""
tests/test_atmospheric_sensor.py - Validación Completa del Sensor Atmosférico y Meteorológico Abierto
"""

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.atmospheric_sensor import (
    AtmosphericReading,
    AtmosphericSensor,
    _aqi_description,
    _wind_degree_to_cardinal,
    get_atmospheric_sensor,
)
from core.kaiju_cognitive_orchestrator import KaijuCognitiveOrchestrator
from core.sensor_orchestrator import SensorOrchestrator


class TestAtmosphericSensor(unittest.TestCase):
    def setUp(self):
        self.sensor = AtmosphericSensor(cache_ttl_s=1.0)

    def test_wind_degree_conversion(self):
        self.assertEqual(_wind_degree_to_cardinal(0), "N")
        self.assertEqual(_wind_degree_to_cardinal(90), "E")
        self.assertEqual(_wind_degree_to_cardinal(180), "S")
        self.assertEqual(_wind_degree_to_cardinal(270), "W")
        self.assertEqual(_wind_degree_to_cardinal(45), "NE")

    def test_aqi_description(self):
        self.assertIn("Excelente", _aqi_description(25))
        self.assertIn("Aceptable", _aqi_description(75))
        self.assertIn("Sensible", _aqi_description(120))
        self.assertIn("Dañina", _aqi_description(180))
        self.assertIn("Peligrosa", _aqi_description(350))

    def test_pressure_trend_calculation(self):
        now = time.time()
        # Inicial
        t1 = self.sensor._calculate_pressure_trend(1013.0, now - 7200)
        # Caída brusca de 2 hPa
        t2 = self.sensor._calculate_pressure_trend(1011.0, now)
        self.assertIn("caída brusca", t2.lower())

        # Ascenso rápido de 2 hPa
        self.sensor._pressure_history = [(now - 7200, 1010.0)]
        t3 = self.sensor._calculate_pressure_trend(1012.5, now)
        self.assertIn("ascenso rápido", t3.lower())

    def test_resolve_coordinates_fallback(self):
        lat, lon, src = self.sensor.resolve_local_coordinates()
        self.assertIsInstance(lat, float)
        self.assertIsInstance(lon, float)
        self.assertIsInstance(src, str)

    @patch("httpx.Client.get")
    def test_get_atmospheric_reading_mocked(self, mock_get):
        # Mock de Open-Meteo Weather
        mock_weather_resp = MagicMock()
        mock_weather_resp.status_code = 200
        mock_weather_resp.json.return_value = {
            "current": {
                "temperature_2m": 24.5,
                "apparent_temperature": 26.0,
                "relative_humidity_2m": 70,
                "surface_pressure": 1014.0,
                "pressure_msl": 1014.5,
                "weather_code": 2,
                "cloud_cover": 40,
                "precipitation": 0.0,
                "rain": 0.0,
                "wind_speed_10m": 12.0,
                "wind_gusts_10m": 18.0,
                "wind_direction_10m": 90.0,
                "is_day": 1,
            }
        }

        # Mock de Open-Meteo Air Quality
        mock_aq_resp = MagicMock()
        mock_aq_resp.status_code = 200
        mock_aq_resp.json.return_value = {
            "current": {
                "pm10": 12.0,
                "pm2_5": 5.0,
                "us_aqi": 22,
                "european_aqi": 15,
                "uv_index": 2.5,
                "carbon_monoxide": 150.0,
                "nitrogen_dioxide": 2.0,
                "sulphur_dioxide": 1.0,
                "ozone": 50.0,
            }
        }

        mock_get.side_effect = [mock_weather_resp, mock_aq_resp]

        reading = self.sensor.get_atmospheric_reading(force_refresh=True)
        self.assertEqual(reading.temperature_c, 24.5)
        self.assertEqual(reading.relative_humidity_pct, 70)
        self.assertEqual(reading.weather_description, "Parcialmente Nublado")
        self.assertEqual(reading.aqi_us, 22)
        self.assertIn("Atmósfera y Clima Local", reading.summary_for_llm)
        self.assertIn("24.5°C", reading.summary_for_llm)

    def test_sensor_orchestrator_integration(self):
        orch = SensorOrchestrator.get_instance()
        sit = orch.get_abstract_situation(force_refresh=True)
        self.assertIn("atmospheric", sit)
        self.assertIn("dense_summary", sit)
        self.assertIn("Atmósfera y Clima Local", sit["dense_summary"])

    def test_kaiju_cognitive_orchestrator_integration(self):
        ko = KaijuCognitiveOrchestrator.get_instance()
        atmos = ko.get_atmospheric_state()
        self.assertIn("temperature_c", atmos)
        self.assertIn("summary_for_llm", atmos)

        # Verificar compilación a IR
        ir = ko.compile_to_inter_ai_ir(
            user_prompt="¿Cuál es el estado del clima?",
            active_expert="Expert_TemporalCausality",
            atmospheric_summary=atmos["summary_for_llm"]
        )
        self.assertIn("[LOCAL_ATMOSPHERIC_TELEMETRY]", ir)
        self.assertIn("Atmósfera y Clima Local", ir)

    def test_sync_to_rag_vault(self):
        ok = self.sensor.sync_to_rag_vault()
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()

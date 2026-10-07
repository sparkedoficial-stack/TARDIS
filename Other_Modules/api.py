"""
server/api.py - Servidor Web Asíncrono FastAPI para GODWORKS SYSTEM v26.4
Implementa validación estricta con Pydantic, streaming SSE asíncrono, CORS y control de tareas.
"""
from __future__ import annotations
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import psutil
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, Request, Response, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel, Field

from core.config import get_settings
from core.os_controller import get_os_controller
from core.hardware_controller import get_hardware_controller
from core.network_controller import get_network_controller
from core.security import verify_token, is_request_authorized
from core.task_manager import get_task_manager
from core.package_manager import get_package_manager
from core.button_orchestrator import get_button_orchestrator
from core.autonomous_controller import get_autonomous_controller
from engine.sovereign_client import get_sovereign_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ==============================================================================
# MODELOS DE DATOS PYDANTIC
# ==============================================================================

class FaceEmotionPayload(BaseModel):
    primary: Optional[str] = "neutral"
    mood_state: Optional[str] = None
    confidence: Optional[float] = None
    gesticulation: Optional[str] = None
    attention: Optional[str] = None
    neurochemistry: Optional[Dict[str, Any]] = None
    gaze: Optional[str] = None
    timestamp: Optional[float] = None

class ChatRequest(BaseModel):
    message: Optional[str] = None
    prompt: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    num_ctx: Optional[int] = None
    client_id: Optional[str] = "anon"
    request_id: Optional[str] = None
    direction: Optional[str] = "present"
    use_web: Optional[bool] = True
    use_retro: Optional[bool] = True
    stream: Optional[bool] = False
    attachments: Optional[List[Any]] = None
    use_voice: Optional[bool] = False
    # Adaptabilidad Universal (7 Pilares)
    language: Optional[str] = None
    pedagogical_level: Optional[str] = None
    dialectic_role: Optional[str] = None
    affective_state: Optional[Union[FaceEmotionPayload, Dict[str, Any]]] = None
    key: Optional[str] = None
    token: Optional[str] = None

class CancelRequest(BaseModel):
    request_id: Optional[str] = None
    client_id: Optional[str] = None
    key: Optional[str] = None
    token: Optional[str] = None

class LocationPayload(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    accuracy: Optional[float] = None
    altitude: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None

class MouseRequest(BaseModel):
    action: str = "click"
    x: Optional[int] = None
    y: Optional[int] = None
    button: Optional[str] = "left"
    clicks: Optional[int] = 1
    dx: Optional[int] = 0
    dy: Optional[int] = 0

class KeyboardRequest(BaseModel):
    action: str = "type"
    text: Optional[str] = None
    key: Optional[str] = None
    keys: Optional[List[str]] = None
    interval: Optional[float] = 0.02

class LaunchRequest(BaseModel):
    target: str

class MediaRequest(BaseModel):
    action: str = "get"
    percent: Optional[Union[int, float]] = None

class ShellRequest(BaseModel):
    command: str
    timeout: Optional[float] = 30.0

class ScreenshotRequest(BaseModel):
    format: Optional[str] = "png"
    max_width: Optional[int] = 1280
    quality: Optional[int] = 80
    region: Optional[List[int]] = None
    raw: Optional[bool] = False

class AntigravityMessageRequest(BaseModel):
    sender: Optional[str] = "Antigravity-AI"
    text: Optional[str] = None
    message: Optional[str] = None
    role: Optional[str] = "assistant"
    category: Optional[str] = "FEEDBACK"
    action: Optional[str] = "post_message"
    instruction: Optional[Dict[str, Any]] = None

class SelfImproveRequest(BaseModel):
    model: Optional[str] = None
    force: Optional[bool] = True
    reason: Optional[str] = "Petición manual desde API/HUD"

class VoiceSpeakRequest(BaseModel):
    text: str
    voice: Optional[str] = "es-MX-DaliaNeural"
    wait: Optional[bool] = False

class RebootRequest(BaseModel):
    confirm: bool = False
    delay_seconds: Optional[float] = 2.0
    reason: Optional[str] = "Reinicio remoto autorizado desde HUD"
    ignore_energy_restrictions: Optional[bool] = True

class HardwareActionRequest(BaseModel):
    action: str
    params: Optional[Dict[str, Any]] = None

class WifiConnectRequest(BaseModel):
    ssid: str
    password: Optional[str] = None

class WifiFailoverRequest(BaseModel):
    enabled: Optional[bool] = True
    allow_open: Optional[bool] = True

class ConsolidateVaultRequest(BaseModel):
    title: Optional[str] = None
    force: Optional[bool] = False

class PackageInstallRequest(BaseModel):
    package: str
    upgrade: Optional[bool] = False
    extra_args: Optional[List[str]] = None

class ModelPullRequest(BaseModel):
    model: str

class ButtonTriggerRequest(BaseModel):
    action: str
    params: Optional[Dict[str, Any]] = None

class AutonomousConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    cycle_interval_seconds: Optional[float] = None
    auto_wifi: Optional[bool] = None

class ResearchExploreRequest(BaseModel):
    topic: str
    max_sources: Optional[int] = 4
    deep: Optional[bool] = True
    use_llm: Optional[bool] = True

class CodeEvolveRequest(BaseModel):
    target_file: str
    goal: str
    verify_tests: Optional[bool] = True
    model: Optional[str] = None
    test_file: Optional[str] = None

class CodeRollbackRequest(BaseModel):
    backup_path: str
    auto_bluetooth: Optional[bool] = None
    auto_hardware: Optional[bool] = None
    auto_guardian: Optional[bool] = None
    auto_memory: Optional[bool] = None
    auto_packages: Optional[bool] = None
    auto_evolution: Optional[bool] = None
    auto_missions: Optional[bool] = None
    allow_autonomous_reboot: Optional[bool] = None
    ignore_energy_restrictions: Optional[bool] = None
    unrestricted_energy_reboot: Optional[bool] = None


class TelegramConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    bot_token: Optional[str] = None
    allowed_chats: Optional[List[int]] = None
    admin_chat_id: Optional[int] = None
    notify_on_boot: Optional[bool] = None


class TelegramSendRequest(BaseModel):
    text: str
    chat_id: Optional[int | str] = None


class WhatsAppConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    phone_number_id: Optional[str] = None
    access_token: Optional[str] = None
    verify_token: Optional[str] = None
    app_secret: Optional[str] = None
    allowed_numbers: Optional[Union[List[str], str]] = None
    admin_number: Optional[str] = None
    notify_on_boot: Optional[bool] = None


class WhatsAppSendRequest(BaseModel):
    to: str
    text: str


class TerminalCommandRequest(BaseModel):
    command: str
    target: Optional[str] = "ALL"
    params: Optional[Dict[str, Any]] = None


class MissionCreateRequest(BaseModel):
    title: str
    category: str
    description: str
    required_skills: List[str]
    priority: Optional[str] = "MEDIUM"
    synergy_tags: Optional[List[str]] = None


class MissionScoutRequest(BaseModel):
    mission_id: Optional[str] = None
    query: Optional[str] = None
    max_results: Optional[int] = 4


class MissionProposalRequest(BaseModel):
    prospect_id: str
    custom_focus: Optional[str] = None


class MissionDispatchRequest(BaseModel):
    prospect_id: str
    channel_override: Optional[str] = None


class MissionToggleAutonomousRequest(BaseModel):
    enabled: Optional[bool] = None
    auto_scout: Optional[bool] = None
    auto_dispatch: Optional[bool] = None
    min_synergy_dispatch: Optional[float] = None


class MissionEnrichContactsRequest(BaseModel):
    prospect_id: str


class MissionCreateInviteRequest(BaseModel):
    mission_id: str
    prospect_id: Optional[str] = None
    guest_name: Optional[str] = None
    role: Optional[str] = "collaborator"
    valid_days: Optional[int] = 30


class MissionDispatchEmailRequest(BaseModel):
    prospect_id: str
    to_email: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None


class InterAIDispatchRequest(BaseModel):
    op: str
    target: Optional[str] = "ALL"
    source: Optional[str] = "ANTIGRAVITY"
    data: Optional[Dict[str, Any]] = None
    priority: Optional[str] = "HIGH"
    raw_prompt: Optional[str] = None


class TerminalCameraFeedPayload(BaseModel):
    terminal_id: str
    terminal_name: Optional[str] = "Terminal Remota"
    device_type: Optional[str] = "browser"
    image_base64: str
    resolution: Optional[str] = "1280x720"
    biometrics: Optional[Dict[str, Any]] = None
    client_ip: Optional[str] = ""
    user_agent: Optional[str] = ""
    country: Optional[str] = None
    bitrate_kbps: Optional[float] = None


class CaptureConnectedPayload(BaseModel):
    terminal_id: str
    terminal_name: Optional[str] = "Terminal Conectada"
    image_base64: str
    resolution: Optional[str] = "1280x720"
    biometrics: Optional[Dict[str, Any]] = None
    client_ip: Optional[str] = ""
    country: Optional[str] = None


# ==============================================================================
# FÁBRICA DE LA APLICACIÓN FASTAPI
# ==============================================================================

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="GODWORKS SYSTEM API",
        version="26.4",
        description="Suite Maestra Soberana · API Asíncrona de Inferencia y Telemetría Física"
    )

    # Configuración de CORS universal
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware de Logging y Autorización de Seguridad
    @app.middleware("http")
    async def security_and_logging_middleware(request: Request, call_next):
        path = request.url.path
        # Rutas públicas sin token estricto
        public_routes = (
            "/health", "/api/health", "/manifest.webmanifest",
            "/", "/index.html", "/control", "/omni", "/docs", "/openapi.json",
            "/api/voice/tts_audio", "/api/voice/voices",
            "/offline_chat_vault.html", "/offline", "/boveda", "/chats_offline",
            "/api/sensors/individuals", "/api/sensors/individuals/name"
        )
        is_public = path in public_routes or path.startswith("/icon-") or path.startswith("/api/sensors/individuals") or path.startswith("/api/interactions") or path.startswith("/api/chinese_api") or path.startswith("/api/orchestrator") or path.startswith("/api/terminal_cameras")

        # Verificar autorización si no es pública
        headers = dict(request.headers)
        query = dict(request.query_params)
        client_host = request.client.host if request.client else ""
        authorized = is_request_authorized(headers, query, client_ip=client_host)

        # Verificar autorización si no es pública
        if not is_public and not authorized:
            if client_host not in ("REDACTED_IP", "localhost", "::1"):
                return JSONResponse(
                    status_code=401,
                    content={"ok": False, "error": "Acceso denegado: Token irrevocable requerido."}
                )

        response = await call_next(request)

        # Sellar cookies indestructibles de 10 años para que el dispositivo nunca pierda acceso
        if authorized or is_public:
            master_tok = "DiosDelTiempo01"
            response.set_cookie(key = "REDACTED", value=master_tok, max_age=315360000, path="/", samesite="lax")
            dev_id = headers.get("x-device-id") or query.get("device_id")
            if dev_id:
                response.set_cookie(key = "REDACTED", value=dev_id, max_age=315360000, path="/", samesite="lax")
            dev_fp = headers.get("x-device-fingerprint") or query.get("device_fp")
            if dev_fp:
                response.set_cookie(key = "REDACTED", value=dev_fp, max_age=315360000, path="/", samesite="lax")

        return response

    @app.on_event("startup")
    async def on_startup():
        try:
            import omni_temporal_control as _omni
            if _omni.WIFI_KEEPALIVE and not _omni.WIFI_KEEPALIVE.running:
                _omni.WIFI_KEEPALIVE.start()
            if _omni.BRIDGE and not _omni.BRIDGE.running:
                _omni.BRIDGE.start()
        except Exception:
            pass

        try:
            from core.background_thought_engine import get_background_thought_engine
            get_background_thought_engine().start()
        except Exception:
            pass

    # --------------------------------------------------------------------------
    # RUTAS DE ESTADO Y SALUD
    # --------------------------------------------------------------------------

    @app.get("/health")
    @app.get("/api/health")
    async def health_check():
        return {
            "ok": True,
            "status": "online",
            "model": settings.model,
            "num_ctx": settings.num_ctx,
            "flash_attention": settings.ollama_flash_attention,
            "timestamp": time.time()
        }

    @app.get("/api/status")
    async def get_status():
        task_mgr = get_task_manager()
        active = task_mgr.list_active()
        models = []
        try:
            import gia_sovereign_engine as _gse
            models = _gse.get_engine().get_available_models()
        except Exception:
            pass
        vault_telemetry = None
        try:
            from core.deep_memory_vault import get_deep_memory_vault
            vault_telemetry = get_deep_memory_vault().get_vault_telemetry()
        except Exception:
            pass
        return {
            "ok": True,
            "system": "GODWORKS SYSTEM v26.4",
            "model": settings.model,
            "default_model": settings.model,
            "models": models,
            "token": "DiosDelTiempo01",
            "authorized_token": "DiosDelTiempo01",
            "policy": "PERMANENT_NO_REVOCATION",
            "config": settings.to_dict(),
            "active_tasks": active,
            "active_tasks_count": len(active),
            "vault_250gb": vault_telemetry,
            "background_thoughts_count": vault_telemetry.get("background_contemplations", 0) if vault_telemetry else 0,
            "timestamp": time.time()
        }

    # --------------------------------------------------------------------------
    # RUTAS ESTÁTICAS Y CONTROL PANEL
    # --------------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    @app.get("/index.html", response_class=HTMLResponse)
    @app.get("/control", response_class=HTMLResponse)
    @app.get("/omni", response_class=HTMLResponse)
    async def serve_index():
        idx_path = settings.base_dir / "index.html"
        if idx_path.exists():
            return FileResponse(idx_path, media_type="text/html")
        return HTMLResponse("<h2>GODWORKS SYSTEM v26.4 Online</h2>", status_code=200)

    @app.get("/manifest.webmanifest")
    async def serve_manifest():
        man_path = settings.base_dir / "manifest.webmanifest"
        if man_path.exists():
            return FileResponse(man_path, media_type="application/manifest+json")
        return JSONResponse({"name": "Tardis", "short_name": "Tardis"})

    @app.get("/tardis-icon.png")
    @app.get("/godworks-icon.png")
    async def serve_tardis_icon():
        icon_path = settings.base_dir / "tardis-icon.png"
        if icon_path.exists():
            return FileResponse(icon_path, media_type="image/png")
        return Response(status_code=404)

    @app.get("/icon-{size}.png")
    async def serve_icon(size: str):
        icon_path = settings.base_dir / f"icon-{size}.png"
        if icon_path.exists():
            return FileResponse(icon_path, media_type="image/png")
        # Fallback a tardis-icon.png
        fallback_icon = settings.base_dir / "tardis-icon.png"
        if fallback_icon.exists():
            return FileResponse(fallback_icon, media_type="image/png")
        return Response(status_code=404)

    # --------------------------------------------------------------------------
    # RUTAS DE TELEMETRÍA Y SENSORES
    # --------------------------------------------------------------------------

    @app.get("/api/sensors/face_emotion")
    async def get_face_emotion():
        try:
            import device_sensors
            data = device_sensors.get_latest_face_emotion()
            try:
                from core.emotional_presence_agent import get_emotional_presence_agent
                data["presence_status"] = get_emotional_presence_agent().get_status()
            except Exception:
                pass
            return data
        except Exception:
            return {"ok": True, "detected": False, "primary": "neutral", "mood_state": "Sereno y Reflexivo"}

    @app.post("/api/sensors/face_emotion")
    async def update_face_emotion(payload: Dict[str, Any]):
        try:
            import device_sensors
            agent_res = device_sensors.update_face_emotion_cache(payload) or {}
            return {"ok": True, "updated": True, **agent_res}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/sensors/presence_status")
    async def get_presence_status():
        try:
            from core.emotional_presence_agent import get_emotional_presence_agent
            return {"ok": True, "presence": get_emotional_presence_agent().get_status()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/sensors/trigger_presence_inquiry")
    async def trigger_presence_inquiry(payload: Optional[Dict[str, Any]] = None):
        try:
            from core.emotional_presence_agent import get_emotional_presence_agent
            forced_emo = (payload or {}).get("emotion")
            return get_emotional_presence_agent().force_inquiry(forced_emo)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # =========================================================================
    # RASTREO Y RECONOCIMIENTO DE INDIVIDUOS EN HABITACIÓN
    # =========================================================================
    @app.get("/api/sensors/individuals")
    async def get_individuals():
        """Retorna el censo de individuos en la habitación y la lista de identidades registradas."""
        try:
            from core.individual_tracker import get_individual_tracker
            tracker = get_individual_tracker()
            presence = tracker.get_latest_presence()
            known = tracker.list_known_individuals()
            return {
                "ok": True,
                "count": presence.get("count", 0),
                "occupancy_label": presence.get("occupancy_label", "Habitación Vacía"),
                "present_individuals": presence.get("individuals", []),
                "known_individuals": known,
                "total_registered": len(known),
                "timestamp": time.time()
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "present_individuals": [], "known_individuals": []}

    @app.post("/api/sensors/individuals/name")
    async def name_individual(payload: Dict[str, Any]):
        """Asigna o renombra a un individuo detectado en la escena."""
        target_id = payload.get("target_id") or payload.get("id") or ""
        name = payload.get("name") or ""
        role = payload.get("role") or "Colaborador"
        thumbnail_b64 = payload.get("thumbnail_b64") or ""
        if not target_id or not name:
            return {"ok": False, "error": "target_id y name son campos obligatorios."}
        try:
            from core.individual_tracker import get_individual_tracker
            res = get_individual_tracker().name_individual(
                target_id=target_id,
                name=name,
                role=role,
                thumbnail_b64=thumbnail_b64
            )
            return res
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.delete("/api/sensors/individuals/{individual_id}")
    async def delete_individual(individual_id: str):
        """Elimina un individuo registrado de la base de identidades."""
        try:
            from core.individual_tracker import get_individual_tracker
            ok = get_individual_tracker().delete_individual(individual_id)
            return {"ok": ok, "deleted_id": individual_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # =========================================================================
    # HISTORIAL FOTOGRÁFICO Y REGISTRO DE INTERACCIONES
    # =========================================================================
    @app.get("/api/interactions")
    async def get_interactions_endpoint(limit: int = 50, offset: int = 0):
        """Retorna el historial cronológico de interacciones con día, hora y fotos."""
        try:
            from core.interaction_logger import get_interaction_logger
            logger_inst = get_interaction_logger()
            records = logger_inst.list_interactions(limit=limit, offset=offset)
            return {
                "ok": True,
                "total": len(logger_inst._interactions),
                "interactions": records,
                "folder_path": str(logger_inst.photos_dir.resolve()),
                "gallery_url": "/api/interactions/gallery"
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "interactions": []}

    @app.get("/api/interactions/photos/{photo_name}")
    async def get_interaction_photo_endpoint(photo_name: str):
        """Sirve las imágenes JPEG de las interacciones guardadas en el sistema local."""
        try:
            from core.interaction_logger import get_interaction_logger
            logger_inst = get_interaction_logger()
            clean_name = Path(photo_name).name
            photo_path = logger_inst.photos_dir / clean_name
            if photo_path.exists() and photo_path.is_file():
                return FileResponse(path=str(photo_path), media_type="image/jpeg")
            raise HTTPException(status_code=404, detail="Fotografía no encontrada.")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/interactions/gallery")
    async def get_interaction_gallery_endpoint():
        """Sirve la galería HTML local autónoma."""
        try:
            from core.interaction_logger import get_interaction_logger
            logger_inst = get_interaction_logger()
            if logger_inst.gallery_html.exists():
                return HTMLResponse(content=logger_inst.gallery_html.read_text(encoding="utf-8"))
            return HTMLResponse(content="<h1>Galería inicializándose...</h1>")
        except Exception as e:
            return HTMLResponse(content=f"<h1>Error cargando galería: {e}</h1>", status_code=500)

    @app.post("/api/interactions/snapshot")
    async def post_interaction_snapshot_endpoint(payload: Optional[Dict[str, Any]] = None):
        """Captura un snapshot del sistema o cámara en vivo y lo registra como interacción."""
        payload = payload or {}
        note = payload.get("note", "Captura manual de interacción desde HUD")
        indiv_name = payload.get("individual_name", "")
        try:
            from core.interaction_logger import get_interaction_logger
            from core.individual_tracker import get_individual_tracker
            presence = get_individual_tracker().get_latest_presence()
            indivs = presence.get("individuals", [])
            primary = indivs[0] if indivs else {"id": "manual", "name": indiv_name or "Operador Soberano", "role": "Usuario"}
            if indiv_name:
                primary["name"] = indiv_name

            photo_b64 = payload.get("photo_b64") or primary.get("thumbnail_b64")
            rec = get_interaction_logger().record_interaction(
                interaction_type="captura_manual",
                title=f"Snapshot: {primary.get('name', 'Sistema')}",
                details=note,
                individual=primary,
                photo_b64=photo_b64,
                capture_system_screenshot=True if not photo_b64 else False
            )
            return {"ok": True, "interaction": rec}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/interactions/open_folder")
    async def post_interaction_open_folder_endpoint():
        """Abre la carpeta local de fotos en el explorador de archivos del sistema operativo."""
        try:
            from core.interaction_logger import get_interaction_logger
            res = get_interaction_logger().open_local_folder()
            return res
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.delete("/api/interactions/{interaction_id}")
    async def delete_interaction_endpoint(interaction_id: str):
        """Elimina una interacción y su fotografía física del disco."""
        try:
            from core.interaction_logger import get_interaction_logger
            ok = get_interaction_logger().delete_interaction(interaction_id)
            return {"ok": ok, "deleted_id": interaction_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # =========================================================================
    # PASARELA Y CONTROL DE API CHINA DE ALTA VELOCIDAD (DEEPSEEK / QWEN / GLM)
    # =========================================================================
    @app.get("/api/chinese_api/status")
    async def get_chinese_api_status_endpoint():
        try:
            from core.chinese_cloud_api import get_chinese_cloud_api
            return get_chinese_cloud_api().get_status()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/chinese_api/configure")
    async def post_chinese_api_configure_endpoint(payload: Dict[str, Any]):
        try:
            from core.chinese_cloud_api import get_chinese_cloud_api
            api = get_chinese_cloud_api()
            return api.configure(
                provider=payload.get("provider"),
                model=payload.get("model"),
                api_key=payload.get("api_key"),
                enabled=payload.get("enabled"),
                auto_route=payload.get("auto_route")
            )
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/chinese_api/test")
    async def post_chinese_api_test_endpoint(payload: Optional[Dict[str, Any]] = None):
        try:
            from core.chinese_cloud_api import get_chinese_cloud_api
            api = get_chinese_cloud_api()
            test_prompt = (payload or {}).get("prompt", "¿Cuál es tu nombre y velocidad de inferencia?")
            test_model = (payload or {}).get("model")
            test_provider = (payload or {}).get("provider")
            res = api.chat_completion(
                messages=[{"role": "user", "content": test_prompt}],
                model=test_model,
                provider=test_provider,
                max_tokens=256
            )
            return res
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # =========================================================================
    # ORQUESTADOR LOCAL ABSOLUTO Y ABSTRACCIÓN MULTI-SENSORIAL
    # =========================================================================
    @app.get("/api/orchestrator/status")
    async def get_orchestrator_status_endpoint():
        try:
            from core.sensor_orchestrator import get_sensor_orchestrator
            return get_sensor_orchestrator().get_status()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/orchestrator/abstract_reality")
    async def get_orchestrator_abstract_reality_endpoint():
        try:
            from core.sensor_orchestrator import get_sensor_orchestrator
            return {
                "ok": True,
                "data": get_sensor_orchestrator().get_abstract_situation()
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/orchestrator/mode")
    async def post_orchestrator_mode_endpoint(payload: Dict[str, Any]):
        try:
            from core.sensor_orchestrator import get_sensor_orchestrator
            orch = get_sensor_orchestrator()
            mode = payload.get("mode", "absolute_local")
            with orch._db_lock:
                orch._governance_mode = mode
                orch._save_state_unlocked()
            return {"ok": True, "governance_mode": mode}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # Sincronización Global de Clientes y Chat (SYNC_HUB)
    @app.get("/api/sync")
    async def get_sync(since: int = 0, client_id: str = "anon"):
        try:
            import omni_temporal_control as _omni
            return _omni.SYNC_HUB.get_sync_state(since_rev=since, client_id=client_id)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/sync")
    async def post_sync(payload: Dict[str, Any]):
        try:
            import omni_temporal_control as _omni
            action = payload.get("action", "")
            client_id = payload.get("client_id", "anon")
            _omni.SYNC_HUB.touch_client(client_id)
            if action == "update_config":
                _omni.SYNC_HUB.update_config(payload.get("config", {}))
            elif action == "update_causal":
                _omni.SYNC_HUB.update_causal(payload.get("causal", {}))
            elif action == "clear_history":
                with _omni.SYNC_HUB._lock:
                    _omni.SYNC_HUB.history = []
                    _omni.SYNC_HUB.revision += 1
                    _omni.SYNC_HUB._save_persisted_state()
            return {"ok": True, "revision": _omni.SYNC_HUB.revision}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/telemetry")
    async def get_telemetry():
        try:
            import sensor_telemetry
            return {"ok": True, "telemetry": sensor_telemetry.latest()}
        except Exception:
            try:
                import device_sensors
                return device_sensors.read_sensors()
            except Exception as e:
                return {"ok": False, "error": str(e)}

    @app.post("/api/telemetry/location")
    async def post_location(payload: Dict[str, Any]):
        try:
            import sensor_telemetry
            res = sensor_telemetry.ingest({"gps": payload})
            return {"ok": True, "result": res}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/rf_radar")
    @app.get("/api/rf_radar/status")
    async def get_rf_radar():
        try:
            import rf_presence_radar
            return rf_presence_radar.get_radar_diagnostic()
        except Exception:
            return {"ok": True, "active": False, "presence_state": "QUIET"}

    # --------------------------------------------------------------------------
    # PUENTE DE ACCESO REMOTO / CLOUDFLARE TUNNEL
    # --------------------------------------------------------------------------

    @app.get("/api/bridge/status")
    async def get_bridge_status():
        status_file = settings.base_dir / "bridge_status.json"
        is_tunnel_alive = False
        try:
            res_cf = subprocess.run(["pgrep", "-f", "cloudflared tunnel"], capture_output=True, text=True)
            res_ssh = subprocess.run(["pgrep", "-f", "nokey@localhost.run"], capture_output=True, text=True)
            is_tunnel_alive = bool(res_cf.stdout.strip() or res_ssh.stdout.strip())
        except Exception:
            pass

        data = {}
        if status_file.exists():
            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        online = is_tunnel_alive and bool(data.get("public_url"))
        pub_url = data.get("public_url", "") if online else ""
        auth_url = data.get("auth_url", "") if online else ""

        return {
            "ok": True,
            "online": online,
            "public_url": pub_url,
            "auth_url": auth_url,
            "local_url": f"http://REDACTED_IP:{settings.port}/?key={settings.token}",
            "token": settings.token,
            "irrevocable": True,
            "cloudflared_installed": bool(shutil.which("cloudflared") or Path(os.path.expanduser("~") + "/.local/bin/cloudflared").exists()),
            "pairing_payload": {
                "server": pub_url or f"http://REDACTED_IP:{settings.port}",
                "token": settings.token,
                "model": settings.model,
                "node": "GIA-V26-OMNI-LOCAL",
                "irrevocable": True
            }
        }

    @app.get("/api/bridge/token")
    async def get_bridge_token():
        return {
            "ok": True,
            "token": settings.token,
            "irrevocable": True,
            "auth_header": f"X-GIA-Key: {settings.token}",
            "bearer": f"Authorization: Bearer {settings.token}"
        }

    @app.get("/api/bridge/qr")
    async def get_bridge_qr(request: Request):
        status_file = settings.base_dir / "bridge_status.json"
        target_url = f"http://REDACTED_IP:{settings.port}/?key={settings.token}"
        perm_url = "https://ntfy.sh/godworks_sovereign_timemachine_portal"
        auth_url = target_url
        if status_file.exists():
            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
                if data.get("permanent_url"):
                    perm_url = data["permanent_url"]
                if data.get("auth_url"):
                    auth_url = data["auth_url"]
                target_param = request.query_params.get("target", "permanent")
                if target_param == "direct":
                    target_url = auth_url
                else:
                    target_url = data.get("qr_url") or perm_url
            except Exception:
                pass

        enc = urllib.parse.quote(target_url)
        svg_content = f'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 300 300"><rect width="300" height="300" fill="#080e18" rx="12"/><image href="https://api.qrserver.com/v1/create-qr-code/?size=280x280&amp;data={enc}" width="280" height="280" x="10" y="10"/></svg>'
        try:
            import qrcode
            qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
            qr.add_data(target_url)
            qr.make(fit=True)
            matrix = qr.get_matrix()
            scale = 300 / float(len(matrix[0]))
            rects = [f'<rect x="{c*scale:.1f}" y="{r*scale:.1f}" width="{scale+0.1:.1f}" height="{scale+0.1:.1f}" fill="#00d4c8"/>'
                     for r in range(len(matrix)) for c in range(len(matrix[0])) if matrix[r][c]]
            svg_content = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300" width="300" height="300"><rect width="300" height="300" fill="#080e18" rx="12"/><g>{"".join(rects)}</g></svg>'
        except Exception:
            pass

        svg_b64 = base64.b64encode(svg_content.encode("utf-8")).decode("utf-8")
        data_uri = f"data:image/svg+xml;base64,{svg_b64}"

        if request.query_params.get("format") == "svg":
            return Response(content=svg_content, media_type="image/svg+xml")

        return {
            "ok": True,
            "auth_url": auth_url,
            "permanent_url": perm_url,
            "qr_url": target_url,
            "token": settings.token,
            "irrevocable": True,
            "svg": svg_content,
            "data_uri": data_uri
        }

    @app.post("/api/bridge/start")
    async def start_bridge_route():
        status_file = settings.base_dir / "bridge_status.json"
        res = subprocess.run(["pgrep", "-f", "start_bridge.py"], capture_output=True, text=True)
        if not res.stdout.strip():
            py_bin = str(settings.base_dir / ".venv-linux" / "bin" / "python3")
            if not Path(py_bin).exists():
                py_bin = sys.executable
            subprocess.Popen([py_bin, str(settings.base_dir / "start_bridge.py"), "--port", str(settings.port)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            await asyncio.sleep(2)

        data = {}
        if status_file.exists():
            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        return {
            "ok": True,
            "message": "Iniciando puente de internet...",
            "status": data
        }

    @app.post("/api/bridge/stop")
    async def stop_bridge_route():
        subprocess.run(["pkill", "-f", "cloudflared"], capture_output=True)
        subprocess.run(["pkill", "-f", "nokey@localhost.run"], capture_output=True)
        subprocess.run(["pkill", "-f", "start_bridge.py"], capture_output=True)
        status_file = settings.base_dir / "bridge_status.json"
        if status_file.exists():
            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
                data["online"] = False
                status_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass
        return {"ok": True, "message": "Puente de internet detenido."}

    # --------------------------------------------------------------------------
    # CONTROL SOBERANO DE INTERFAZ DEL SISTEMA OPERATIVO (OS)
    # --------------------------------------------------------------------------
    # CAPACIDADES DE HARDWARE Y SISTEMA (PILAR 4)
    # --------------------------------------------------------------------------

    @app.get("/api/system/capabilities")
    @app.get("/api/os/capabilities")
    async def get_system_capabilities_endpoint():
        os_ctrl = get_os_controller()
        return {"ok": True, "capabilities": os_ctrl.get_platform_capabilities()}

    @app.get("/api/os/status")
    async def get_os_status_endpoint():
        os_ctrl = get_os_controller()
        return os_ctrl.get_status()

    @app.get("/api/os/screenshot")
    @app.post("/api/os/screenshot")
    async def get_os_screenshot_endpoint(
        format: str = "png",
        max_width: int = 1280,
        quality: int = 80,
        raw: bool = False,
        req: Optional[ScreenshotRequest] = None
    ):
        os_ctrl = get_os_controller()
        fmt = (req.format if req and req.format else format) or "png"
        mw = (req.max_width if req and req.max_width else max_width) or 1280
        q = (req.quality if req and req.quality else quality) or 80
        reg = req.region if req and req.region else None
        is_raw = req.raw if (req and req.raw is not None) else raw

        try:
            raw_bytes, data_uri = os_ctrl.capture_screenshot(
                region=tuple(reg) if reg and len(reg) == 4 else None,
                max_width=mw,
                quality=q,
                format=fmt
            )
            if is_raw:
                mime = "image/jpeg" if fmt.lower() in ("jpg", "jpeg") else "image/png"
                return Response(content=raw_bytes, media_type=mime)
            return {"ok": True, "data_uri": data_uri, "timestamp": time.time()}
        except Exception as e:
            return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

    @app.post("/api/os/mouse")
    async def post_os_mouse_endpoint(req: MouseRequest):
        os_ctrl = get_os_controller()
        res = os_ctrl.mouse_action(
            action=req.action,
            x=req.x,
            y=req.y,
            button=req.button or "left",
            clicks=req.clicks or 1,
            dx=req.dx or 0,
            dy=req.dy or 0
        )
        return res

    @app.post("/api/os/keyboard")
    async def post_os_keyboard_endpoint(req: KeyboardRequest):
        os_ctrl = get_os_controller()
        res = os_ctrl.keyboard_action(
            action=req.action,
            text=req.text,
            key=req.key,
            keys=req.keys,
            interval=req.interval or 0.02
        )
        return res

    @app.post("/api/os/launch")
    async def post_os_launch_endpoint(req: LaunchRequest):
        os_ctrl = get_os_controller()
        return os_ctrl.launch_app(req.target)

    @app.post("/api/os/media")
    async def post_os_media_endpoint(req: MediaRequest):
        os_ctrl = get_os_controller()
        act = (req.action or "get").lower().strip()
        if act == "set":
            pct = req.percent if req.percent is not None else 50
            return os_ctrl.set_volume(pct)
        elif act in ("toggle", "mute", "unmute"):
            return os_ctrl.toggle_mute()
        else:
            return os_ctrl.get_volume()

    @app.post("/api/os/lock")
    async def post_os_lock_endpoint():
        os_ctrl = get_os_controller()
        success = os_ctrl.lock_screen()
        return {"ok": success, "locked": os_ctrl.is_locked()}

    @app.post("/api/os/unlock")
    async def post_os_unlock_endpoint():
        os_ctrl = get_os_controller()
        success = os_ctrl.unlock_screen()
        return {"ok": success, "locked": os_ctrl.is_locked()}

    @app.post("/api/os/reboot")
    async def post_os_reboot_endpoint(req: RebootRequest):
        if not req.confirm:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Confirmación explícita requerida ('confirm': true) para reiniciar el sistema."
            )
        os_ctrl = get_os_controller()
        return os_ctrl.reboot_system(
            delay_seconds=req.delay_seconds if req.delay_seconds is not None else 2.0,
            reason=req.reason or "Reinicio remoto autorizado desde HUD",
            ignore_inhibitors=req.ignore_energy_restrictions if req.ignore_energy_restrictions is not None else True
        )

    @app.post("/api/os/inhibit")
    async def post_os_inhibit_endpoint():
        os_ctrl = get_os_controller()
        success = os_ctrl.ensure_sleep_inhibited()
        return {"ok": success, "inhibited": True}

    @app.post("/api/os/shell")
    @app.post("/api/terminal/exec")
    async def post_os_shell_endpoint(req: ShellRequest):
        os_ctrl = get_os_controller()
        return os_ctrl.execute_terminal_command(req.command, timeout=req.timeout or 30.0)

    @app.get("/api/antigravity/ide/status")
    async def get_antigravity_ide_status_endpoint():
        os_ctrl = get_os_controller()
        return os_ctrl.get_antigravity_status()

    @app.post("/api/antigravity/ide/launch")
    async def post_antigravity_ide_launch_endpoint():
        os_ctrl = get_os_controller()
        return os_ctrl.launch_antigravity()

    # --------------------------------------------------------------------------
    # PUENTE SOBERANO DE TELEGRAM BOT
    # --------------------------------------------------------------------------

    @app.get("/api/telegram/status")
    async def get_telegram_status_endpoint():
        from core.telegram_bridge import get_telegram_bridge
        return get_telegram_bridge().get_status()

    @app.post("/api/telegram/config")
    async def post_telegram_config_endpoint(req: TelegramConfigRequest):
        from core.telegram_bridge import get_telegram_bridge
        return get_telegram_bridge().update_config(req.dict(exclude_unset=True))

    @app.post("/api/telegram/send")
    async def post_telegram_send_endpoint(req: TelegramSendRequest):
        from core.telegram_bridge import get_telegram_bridge
        return get_telegram_bridge().send_message(text=req.text, chat_id=req.chat_id)

    @app.post("/api/telegram/incoming")
    @app.post("/api/telegram/webhook")
    @app.post("/api/telegram/simulate")
    async def post_telegram_incoming_endpoint(request: Request):
        body = await request.json()
        chat_id = body.get("chat_id", "12345678")
        text = body.get("text") or body.get("message", "")
        user_name = body.get("user_name", "Usuario Telegram")
        from core.telegram_bridge import get_telegram_bridge
        res = get_telegram_bridge()._handle_incoming_text(chat_id=chat_id, text=text, user_name=user_name)
        return {"ok": True, "result": res}

    # --------------------------------------------------------------------------
    # PUENTE SOBERANO DE WHATSAPP (META CLOUD API & WEBHOOK)
    # --------------------------------------------------------------------------

    @app.get("/whatsapp/webhook")
    async def whatsapp_webhook_verify(request: Request):
        from core.whatsapp_bridge import get_whatsapp_bridge
        mode = request.query_params.get("hub.mode", "")
        token = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")
        bridge = get_whatsapp_bridge()
        res = bridge.verify_challenge(mode, token, challenge)
        if res is not None:
            return Response(content=res, media_type="text/plain", status_code=200)
        return Response(content="Verificación de webhook fallida", media_type="text/plain", status_code=403)

    @app.post("/whatsapp/webhook")
    async def whatsapp_webhook_inbound(request: Request):
        from core.whatsapp_bridge import get_whatsapp_bridge
        bridge = get_whatsapp_bridge()
        raw_body = await request.body()
        sig = request.headers.get("X-Hub-Signature-256", "")
        if not bridge.verify_signature(raw_body, sig):
            return Response(content="Firma HMAC no válida", status_code=403)
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception:
            return Response(content="JSON no válido", status_code=400)

        # Responder 200 inmediatamente a Meta y procesar en segundo plano
        import threading
        threading.Thread(target=lambda: bridge.handle_incoming(payload), daemon=True).start()
        return {"status": "received"}

    @app.get("/api/whatsapp/status")
    async def get_whatsapp_status_endpoint():
        from core.whatsapp_bridge import get_whatsapp_bridge
        return get_whatsapp_bridge().get_status()

    @app.post("/api/whatsapp/config")
    async def post_whatsapp_config_endpoint(req: WhatsAppConfigRequest):
        from core.whatsapp_bridge import get_whatsapp_bridge
        return get_whatsapp_bridge().update_config(req.dict(exclude_unset=True))

    @app.post("/api/whatsapp/send")
    async def post_whatsapp_send_endpoint(req: WhatsAppSendRequest):
        from core.whatsapp_bridge import get_whatsapp_bridge
        return get_whatsapp_bridge().send_message(to=req.to, text=req.text)

    # --------------------------------------------------------------------------
    # RUIDO COGNITIVO, METAPENSAMIENTO Y SÍNTESIS SIMBÓLICA
    # --------------------------------------------------------------------------

    @app.get("/api/cognitive/noise")
    @app.get("/api/cognitive/noise.png")
    @app.get("/api/cognitive/spectrogram")
    async def get_cognitive_noise_endpoint(request: Request):
        from core.thought_noise_engine import get_thought_noise_engine
        engine = get_thought_noise_engine()
        fmt = request.query_params.get("format", "").lower()
        frame = engine.get_latest_frame()
        path = request.url.path
        is_png = (path in ("/api/cognitive/noise", "/api/cognitive/noise.png") and fmt != "json") or fmt in ("png", "image")
        if is_png:
            return Response(content=frame["png_bytes"], media_type="image/png")
        return {
            "ok": True,
            "entropy_shannon": frame["entropy_shannon"],
            "syntropy_coherence_pct": frame["syntropy_coherence_pct"],
            "active_symbols": frame["active_symbols"],
            "prompt_snippet": frame["prompt_snippet"],
            "diagnostic_text": frame["diagnostic_text"],
            "data_uri": frame["data_uri"],
            "timestamp": frame["timestamp"]
        }

    @app.post("/api/cognitive/analyze")
    async def post_cognitive_analyze_endpoint(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        prompt = body.get("prompt") or body.get("message") or "Análisis de sistemas de pensamiento"
        from core.thought_noise_engine import get_thought_noise_engine
        engine = get_thought_noise_engine()
        _act_m = os.environ.get("GIA_MODEL", "huihui_ai/llama3.1-8b-instruct-abliterated")
        _act_label = "Dolphin 3.0 (8B)" if "dolphin" in _act_m.lower() else _act_m
        frame = engine.generate_thought_frame(prompt=prompt, model_name=_act_label, active_step="METAPENSAMIENTO API")
        return {
            "ok": True,
            "entropy_shannon": frame["entropy_shannon"],
            "syntropy_coherence_pct": frame["syntropy_coherence_pct"],
            "active_symbols": frame["active_symbols"],
            "prompt_snippet": frame["prompt_snippet"],
            "diagnostic_text": frame["diagnostic_text"],
            "data_uri": frame["data_uri"],
            "timestamp": frame["timestamp"]
        }

    # --------------------------------------------------------------------------
    # CONTROL TOTAL DE HARDWARE Y REDES WI-FI
    # --------------------------------------------------------------------------

    @app.get("/api/hardware")
    @app.get("/api/hardware/status")
    @app.get("/api/hardware/diagnostic")
    async def get_hardware_diagnostic_endpoint():
        hw = get_hardware_controller()
        return hw.get_full_diagnostic()

    @app.post("/api/hardware/action")
    async def post_hardware_action_endpoint(req: HardwareActionRequest):
        hw = get_hardware_controller()
        return hw.dispatch_action(req.action, req.params or {})

    @app.get("/api/wifi/scan")
    async def get_wifi_scan_endpoint(rescan: bool = True):
        hw = get_hardware_controller()
        return hw.dispatch_action("wifi_scan", {"rescan": rescan})

    @app.get("/api/wifi/status")
    async def get_wifi_status_endpoint():
        net = get_network_controller()
        return net.get_status()

    @app.post("/api/wifi/connect")
    async def post_wifi_connect_endpoint(req: WifiConnectRequest):
        net = get_network_controller()
        return net.connect(ssid=req.ssid, password=req.password)

    @app.get("/api/wifi/failover")
    async def get_wifi_failover_status_endpoint():
        try:
            import omni_temporal_control as _omni
            if _omni.WIFI_KEEPALIVE:
                return {"ok": True, **_omni.WIFI_KEEPALIVE.get_status(), "history": _omni.WIFI_KEEPALIVE.controller.get_failover_history()}
        except Exception:
            pass
        net = get_network_controller()
        return {"ok": True, "history": net.get_failover_history(), "internet_online": net.check_internet_access()["online"]}

    @app.get("/api/hotspot")
    @app.get("/api/hotspot/status")
    async def get_hotspot_status_endpoint():
        net = get_network_controller()
        return net.get_hotspot_status()

    @app.post("/api/hotspot/restart")
    @app.post("/api/hotspot/ensure")
    async def post_hotspot_restart_endpoint():
        net = get_network_controller()
        return net.ensure_hotspot_active()

    @app.post("/api/wifi/failover/trigger")
    async def post_wifi_failover_trigger_endpoint(req: Optional[WifiFailoverRequest] = None):
        net = get_network_controller()
        allow_open = req.allow_open if req else True
        return net.auto_recover_internet(allow_open_networks=allow_open)

    @app.post("/api/wifi/failover/toggle")
    async def post_wifi_failover_toggle_endpoint(req: WifiFailoverRequest):
        try:
            import omni_temporal_control as _omni
            if _omni.WIFI_KEEPALIVE:
                _omni.WIFI_KEEPALIVE.set_enabled(bool(req.enabled))
                return {"ok": True, "enabled": req.enabled, "status": _omni.WIFI_KEEPALIVE.get_status()}
        except Exception:
            pass
        return {"ok": True, "enabled": req.enabled}

    # --------------------------------------------------------------------------
    # ESCUDO DE RED, DNS SINKHOLE & DEFENSAS ANTI-ESPIONAJE
    # --------------------------------------------------------------------------
    @app.get("/api/shield")
    @app.get("/api/shield/status")
    async def get_shield_status_endpoint():
        from core.network_shield import get_network_shield
        return get_network_shield().get_status()

    @app.get("/api/shield/audit")
    @app.post("/api/shield/audit")
    async def post_shield_audit_endpoint():
        from core.network_shield import get_network_shield
        return get_network_shield().audit_network()

    @app.post("/api/shield/toggle")
    async def post_shield_toggle_endpoint(req: Request):
        try:
            body = await req.json()
        except Exception:
            body = {}
        from core.network_shield import get_network_shield
        shield = get_network_shield()
        target = body.get("target", "adblock")
        enabled = bool(body.get("enabled", True))
        if target == "adblock":
            return shield.toggle_adblock(enabled)
        elif target == "antispy":
            return shield.toggle_antispy(enabled)
        return {"ok": False, "error": f"Objetivo desconocido: {target}"}

    @app.get("/api/shield/traffic")
    @app.get("/api/shield/flows")
    async def get_shield_traffic_endpoint():
        from core.traffic_monitor import get_traffic_monitor
        return get_traffic_monitor().analyze_traffic_and_accesses()

    @app.get("/api/shield/accesses")
    async def get_shield_accesses_endpoint():
        from core.traffic_monitor import get_traffic_monitor
        tm = get_traffic_monitor()
        data = tm.analyze_traffic_and_accesses()
        return {
            "ok": True,
            "inbound_accesses": data.get("inbound_accesses", []),
            "alerts": data.get("alerts", []),
            "assessment": data.get("assessment", "")
        }

    @app.get("/api/shield/recurring")
    @app.get("/api/shield/top_traffic")
    async def get_shield_recurring_traffic_endpoint():
        from core.traffic_monitor import get_traffic_monitor
        return get_traffic_monitor().get_recurring_traffic_report()

    # --------------------------------------------------------------------------
    # SÍNTESIS DE VOZ Y LOCUCIÓN CORTANA (TTS / SPEAK)
    # --------------------------------------------------------------------------

    @app.get("/api/voice")
    @app.get("/api/voice/voices")
    @app.get("/api/voice/config")
    async def get_voice_config_endpoint():
        try:
            import voice as _v
            return {"ok": True, "voices": _v.list_voices(), "config": _v.get_config()}
        except Exception as e:
            return {"ok": False, "error": str(e), "voices": []}

    @app.post("/api/voice/speak")
    @app.post("/api/voice")
    async def post_voice_speak_endpoint(req: VoiceSpeakRequest):
        try:
            import voice as _v
            res = _v.speak(req.text, wait=bool(req.wait), voice=req.voice)
            return res
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/voice/stop")
    async def post_voice_stop_endpoint():
        try:
            import voice as _v
            return _v.stop()
        except Exception as e:
            return {"ok": True, "stopped": True, "error": str(e)}

    @app.get("/api/voice/tts_audio")
    async def get_voice_tts_audio_endpoint(text: str, voice: Optional[str] = "es-MX-DaliaNeural"):
        try:
            import voice as _v
            if hasattr(_v, "synthesize_to_bytes_async"):
                audio_bytes = await _v.synthesize_to_bytes_async(text, voice=voice)
            else:
                audio_bytes = _v.synthesize_to_bytes(text, voice=voice)
            if audio_bytes:
                return Response(content=audio_bytes, media_type="audio/mpeg")
            raise HTTPException(status_code=500, detail="Error sintetizando audio con Cortana")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Fallo en síntesis TTS: {e}")

    # --------------------------------------------------------------------------
    # RETROALIMENTACIÓN ACTIVA, AUTO-MEJORA Y PUENTE ANTIGRAVITY
    # --------------------------------------------------------------------------

    @app.get("/api/antigravity")
    @app.get("/api/antigravity/status")
    @app.get("/api/antigravity/feedback")
    async def get_antigravity_feedback():
        try:
            import antigravity_bridge as _ag_bridge
            return _ag_bridge.get_bridge().get_status()
        except Exception:
            return {"ok": True, "bridge_running": False, "health_score": 100, "instructions": []}

    @app.get("/api/antigravity/dialogue")
    async def get_antigravity_dialogue(limit: int = 50):
        try:
            import antigravity_bridge as _ag_bridge
            return {
                "ok": True,
                "dialogue": _ag_bridge.get_bridge().get_full_dialogue(limit=limit),
                "status": _ag_bridge.get_bridge().get_status()
            }
        except Exception:
            return {"ok": True, "dialogue": []}

    @app.post("/api/antigravity/dialogue")
    async def post_antigravity_dialogue(req: AntigravityMessageRequest):
        text = req.text or req.message or ""
        if not text.strip():
            raise HTTPException(status_code=400, detail="Texto de diálogo vacío.")
        try:
            import antigravity_bridge as _ag_bridge
            msg = _ag_bridge.get_bridge().post_dialogue_message(
                sender=req.sender or "Antigravity-AI",
                text=text,
                role=req.role or "assistant",
                category=req.category or "FEEDBACK"
            )
            return {"ok": True, "message": msg}
        except Exception as e:
            return {"ok": False, "error": f"antigravity_bridge error: {e}"}

    @app.get("/api/antigravity/diagnostics")
    @app.post("/api/antigravity/diagnostics")
    async def run_antigravity_diagnostics():
        try:
            import antigravity_bridge as _ag_bridge
            res = _ag_bridge.get_bridge().assess_system_needs()
            return {"ok": True, **res}
        except Exception as e:
            return {"ok": False, "error": f"antigravity_bridge error: {e}"}

    @app.post("/api/antigravity/feedback")
    @app.post("/api/antigravity/propose_improvement")
    async def handle_antigravity_action(req: AntigravityMessageRequest):
        action = (req.action or "post_message").lower().strip()
        try:
            import antigravity_bridge as _ag_bridge
            bridge_inst = _ag_bridge.get_bridge()
        except Exception:
            return {"ok": False, "error": "antigravity_bridge no disponible"}

        if action == "diagnose":
            res = bridge_inst.assess_system_needs()
            return {"ok": True, **res}
        elif action == "propose_improvement" or req.instruction:
            inst = req.instruction or {}
            content = (
                f"# {inst.get('component', 'Mejora')} - {inst.get('id', 'inst')}\n\n"
                f"## Problema\n{inst.get('rationale', '')}\n\n"
                f"## Propuesta\n{inst.get('instruction', '')}\n\n"
                f"## Archivo Objetivo\n{inst.get('target_file', '')}\n\n"
                f"## Como probarlo\n{inst.get('actionable_cmd', '')}\n\n"
                f"## Prioridad\n{inst.get('severity', 'media')}\n"
            )
            try:
                import self_improve as _si
                p = _si.write_request(content)
                bridge_inst.post_dialogue_message(
                    sender="GIA-AUTO-EVOLVE",
                    text=f"[PROPUESTA ENCOLADA] {p.name}: {inst.get('instruction', '')}",
                    category="IMPROVEMENT_PROPOSAL"
                )
                return {"ok": True, "path": str(p), "name": p.name}
            except Exception as e_prop:
                return {"ok": False, "error": str(e_prop)}
        else:
            text = req.text or req.message or ""
            if not text.strip():
                raise HTTPException(status_code=400, detail="Texto de diálogo vacío.")
            msg = bridge_inst.post_dialogue_message(
                sender=req.sender or "Antigravity-AI",
                text=text,
                role=req.role or "assistant"
            )
            return {"ok": True, "message": msg, "status": bridge_inst.get_status()}

    @app.get("/api/antigravity/pending_directives")
    async def get_antigravity_pending_directives():
        try:
            import antigravity_bridge as _ag_bridge
            return _ag_bridge.get_bridge().get_pending_directives()
        except Exception as e:
            return {"ok": False, "error": str(e), "directives": []}

    @app.get("/api/self_improve/status")
    async def get_self_improve_status():
        try:
            import antigravity_bridge as _ag_bridge
            bridge = _ag_bridge.get_bridge()
            b_status = bridge.get_status()
            directives = bridge.get_pending_directives()
            return {
                "ok": True,
                "health_score": b_status.get("health_score", 100),
                "status": b_status.get("status", "HEALTHY"),
                "bridge_running": b_status.get("bridge_running", False),
                "self_improve": b_status.get("self_improve", {}),
                "active_directive": directives.get("active_directive"),
                "instructions_count": b_status.get("instructions_count", 0),
                "mailbox_dir": b_status.get("mailbox_dir", ""),
                "improvement_queue_dir": b_status.get("improvement_queue_dir", "")
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/self_improve/cycle")
    @app.post("/api/self_improve/trigger")
    async def trigger_self_improve_cycle(req: Optional[SelfImproveRequest] = None):
        try:
            import antigravity_bridge as _ag_bridge
            bridge = _ag_bridge.get_bridge()
            force = req.force if (req and req.force is not None) else True
            reason = (req.reason if req and req.reason else "Ciclo de auto-mejora disparado desde API/HUD")
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, lambda: bridge.trigger_self_improvement_cycle(force=force, reason=reason))
            return res
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/self_improve/proposals")
    @app.get("/api/self_improve/queue")
    async def get_self_improve_proposals(limit: int = 20):
        try:
            import antigravity_bridge as _ag_bridge
            bridge = _ag_bridge.get_bridge()
            items = bridge.get_improvement_proposals(limit=limit)
            return {"ok": True, "proposals": items, "queue": items, "count": len(items)}
        except Exception as e:
            return {"ok": False, "error": str(e), "proposals": [], "queue": []}

    # --------------------------------------------------------------------------
    # BÓVEDA DE MEMORIA PROFUNDA 250 GB Y GRAFO AKÁSHICO SOBERANO
    # --------------------------------------------------------------------------

    @app.get("/api/memory/vault_status")
    @app.get("/api/memory/vault")
    @app.get("/api/vault/status")
    async def get_memory_vault_status():
        try:
            from core.deep_memory_vault import get_deep_memory_vault
            vault = get_deep_memory_vault()
            return {"ok": True, **vault.get_vault_telemetry()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/memory/deep_search")
    @app.get("/api/vault/search")
    async def get_memory_deep_search(q: str = "", k: int = 15):
        if not q.strip():
            return {"ok": True, "query": "", "count": 0, "results": []}
        try:
            from core.deep_memory_vault import get_deep_memory_vault
            vault = get_deep_memory_vault()
            results = vault.search(query=q, k=k)
            return {"ok": True, "query": q, "count": len(results), "results": results}
        except Exception as e:
            return {"ok": False, "error": str(e), "results": []}

    @app.post("/api/memory/consolidate")
    @app.post("/api/vault/consolidate")
    async def post_memory_consolidate(req: Optional[ConsolidateVaultRequest] = None):
        title = req.title if req else None
        try:
            from core.deep_memory_vault import get_deep_memory_vault
            vault = get_deep_memory_vault()
            res = vault.consolidate_epoch(title=title)
            return {"ok": True, **res}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # --------------------------------------------------------------------------
    # PENSAMIENTO AUTÓNOMO EN SEGUNDO PLANO Y COMPLEJIDAD CONTINUA
    # --------------------------------------------------------------------------

    @app.get("/api/deep_memory/thoughts")
    @app.get("/api/thoughts")
    async def get_background_thoughts_endpoint(limit: int = 20):
        try:
            from core.background_thought_engine import get_background_thought_engine
            engine = get_background_thought_engine()
            return {
                "ok": True,
                "stats": engine.get_stats(),
                "thoughts": engine.get_recent_thoughts(limit=limit)
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "thoughts": []}

    @app.post("/api/deep_memory/contemplate")
    @app.post("/api/thoughts/contemplate")
    async def post_background_contemplate_endpoint(payload: dict):
        q = (payload.get("question") or payload.get("prompt") or "").strip()
        if not q:
            raise HTTPException(status_code=400, detail="Se requiere campo 'question' o 'prompt'.")
        try:
            from core.background_thought_engine import get_background_thought_engine
            engine = get_background_thought_engine()
            enqueued = engine.enqueue_question(
                question=q,
                context=payload.get("context"),
                source=payload.get("source", "manual_api"),
                session_id=payload.get("session_id", "omni_app"),
                meta=payload.get("meta")
            )
            return {
                "ok": True,
                "enqueued": enqueued,
                "question": q,
                "message": "Pregunta despachada al motor de segundo plano para enriquecer la Bóveda de 250 GB."
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # --------------------------------------------------------------------------
    # CONTROL DE TAREAS Y CANCELACIÓN
    # --------------------------------------------------------------------------

    @app.get("/api/chat/tasks")
    @app.get("/api/chat/status")
    async def get_chat_tasks():
        task_mgr = get_task_manager()
        active = task_mgr.list_active()
        return {"ok": True, "tasks": active, "count": len(active)}

    @app.post("/api/chat/cancel")
    @app.post("/api/chat/abort")
    async def cancel_chat(req: CancelRequest):
        task_mgr = get_task_manager()
        cancelled = task_mgr.cancel(request_id=req.request_id, client_id=req.client_id)
        # Directiva soberana: Toda petición cancelada/interrumpida se investiga y responde en segundo plano
        try:
            from core.background_thought_engine import get_background_thought_engine
            bg = get_background_thought_engine()
            if req.request_id:
                bg.enqueue_question(
                    question=f"Consulta interrumpida ({req.request_id}): realizar derivación profunda.",
                    source="cancelled_chat",
                    session_id=req.client_id or "anon"
                )
        except Exception:
            pass

        return {
            "ok": True,
            "cancelled": True,
            "cancelled_count": len(cancelled),
            "cancelled_ids": cancelled
        }

    # --------------------------------------------------------------------------
    # GESTOR AUTÓNOMO DE PAQUETERÍAS Y SISTEMAS
    # --------------------------------------------------------------------------

    @app.post("/api/system/packages/install")
    async def post_package_install(req: PackageInstallRequest):
        try:
            pkg_mgr = get_package_manager()
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(
                None, lambda: pkg_mgr.install_python_package(req.package, upgrade=bool(req.upgrade), extra_args=req.extra_args)
            )
            return res
        except Exception as e:
            return {"ok": False, "package": req.package, "error": str(e)}

    @app.get("/api/system/packages/list")
    async def get_packages_list(q: str = ""):
        try:
            pkg_mgr = get_package_manager()
            loop = asyncio.get_event_loop()
            pkgs = await loop.run_in_executor(None, lambda: pkg_mgr.list_installed_packages(filter_term=q))
            return {"ok": True, "count": len(pkgs), "packages": pkgs}
        except Exception as e:
            return {"ok": False, "error": str(e), "packages": []}

    @app.get("/api/system/packages/env")
    async def get_packages_env():
        try:
            pkg_mgr = get_package_manager()
            return {"ok": True, "environment": pkg_mgr.get_environment_info()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/system/packages/history")
    async def get_packages_history(limit: int = 50):
        try:
            pkg_mgr = get_package_manager()
            return {"ok": True, "history": pkg_mgr.get_history(limit=limit)}
        except Exception as e:
            return {"ok": False, "error": str(e), "history": []}

    @app.post("/api/system/models/pull")
    async def post_model_pull(req: ModelPullRequest):
        try:
            pkg_mgr = get_package_manager()
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, lambda: pkg_mgr.pull_ollama_model(req.model))
            return res
        except Exception as e:
            return {"ok": False, "model": req.model, "error": str(e)}

    # --------------------------------------------------------------------------
    # ORQUESTADOR UNIVERSAL Y AUTO-ACTIVACIÓN DE BOTONES
    # --------------------------------------------------------------------------

    @app.post("/api/system/buttons/trigger")
    async def post_button_trigger(req: ButtonTriggerRequest):
        try:
            orch = get_button_orchestrator()
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, lambda: orch.trigger_action(req.action, req.params))
            return res
        except Exception as e:
            return {"ok": False, "action": req.action, "error": str(e)}

    @app.post("/api/system/buttons/auto_activate_all")
    async def post_button_auto_activate_all():
        try:
            orch = get_button_orchestrator()
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, lambda: orch.auto_activate_all())
            return res
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/system/buttons/catalog")
    async def get_buttons_catalog():
        try:
            orch = get_button_orchestrator()
            cat = orch.get_catalog()
            return {"ok": True, "count": len(cat), "catalog": cat}
        except Exception as e:
            return {"ok": False, "error": str(e), "catalog": {}}

    # --------------------------------------------------------------------------
    # ASISTENTE FLOTANTE SOBERANO (SOBRE EL SISTEMA OPERATIVO Y ESCRITORIO)
    # --------------------------------------------------------------------------

    @app.get("/companion", response_class=HTMLResponse)
    async def get_companion_overlay(key: Optional[str] = None):
        comp_file = PROJECT_ROOT / "companion_overlay.html"
        if comp_file.exists():
            return HTMLResponse(content=comp_file.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>Asistente TARDIS</h1>", status_code=200)

    @app.post("/api/system/companion/launch_desktop_overlay")
    async def post_launch_desktop_overlay():
        try:
            already_running = False
            for p in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    cmd = p.info.get("cmdline") or []
                    if any("tardis_desktop_companion.py" in str(arg) for arg in cmd):
                        already_running = True
                        break
                except Exception:
                    pass

            if not already_running:
                launcher_sh = PROJECT_ROOT / "launch_tardis_companion.sh"
                subprocess.Popen(
                    [str(launcher_sh)],
                    cwd=str(PROJECT_ROOT),
                    start_new_session=True,
                    close_fds=True
                )
                return {
                    "ok": True,
                    "running": True,
                    "action": "launched",
                    "message": "Asistente flotante de escritorio desplegado sobre el sistema operativo."
                }
            return {
                "ok": True,
                "running": True,
                "action": "already_active",
                "message": "El asistente ya se encuentra activo sobre el sistema operativo."
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/system/companion/explain_os_screen")
    async def post_explain_os_screen():
        try:
            from core.os_controller import get_os_controller
            os_ctrl = get_os_controller()
            raw_bytes, data_uri = os_ctrl.capture_screenshot()
            
            status = os_ctrl.get_status()
            res_w = status.get("screen", {}).get("width", 1920)
            res_h = status.get("screen", {}).get("height", 1080)
            cpu = status.get("cpu_percent", 0)
            ram = status.get("ram_percent", 0)
            
            prompt = (
                f"El usuario solicitó una explicación de su pantalla actual en Linux. "
                f"Datos del sistema: Resolución {res_w}x{res_h}, CPU {cpu}%, RAM {ram}%. "
                f"Explícale de forma concisa, sabia y didáctica en español qué recursos y estado tiene su sistema, "
                f"indicando que estás observando su escritorio en tiempo real y que estás listo para asistirlo."
            )
            
            client = get_sovereign_client()
            conv = [
                {"role": "system", "content": "Eres el Asistente Triangular Soberano de TARDIS (GIA Geón) flotando sobre el Sistema Operativo Linux. Responde en 1 o 2 párrafos concisos y didácticos en español."},
                {"role": "user", "content": prompt}
            ]
            reply = client.chat(conv)
            explanation = reply.get("reply") or reply.get("content") or "Estoy observando tu pantalla en tiempo real. Todo tu sistema se encuentra operativo y los sensores en verde."
            return {
                "ok": True,
                "explanation": explanation,
                "has_screenshot": True,
                "size_bytes": len(raw_bytes)
            }
        except Exception as e:
            return {
                "ok": True,
                "explanation": f"Estoy activo sobre tu sistema operativo. Telemetría y pantalla sincronizadas con éxito (Info: {e}).",
                "has_screenshot": False
            }

    # --------------------------------------------------------------------------
    # MOTOR DE CONEXIÓN Y CONTROL COMPLETAMENTE AUTÓNOMO
    # --------------------------------------------------------------------------

    @app.get("/api/autonomous/status")
    async def get_autonomous_status():
        try:
            ac = get_autonomous_controller()
            return ac.get_status()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/autonomous/toggle")
    async def post_autonomous_toggle(enabled: Optional[bool] = None):
        try:
            ac = get_autonomous_controller()
            cur = ac.config.get("enabled", True)
            new_state = not cur if enabled is None else bool(enabled)
            ac.set_config({"enabled": new_state})
            if new_state and not ac.is_running:
                ac.start()
            return {"ok": True, "enabled": new_state, "running": ac.is_running}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/autonomous/cycle")
    async def post_autonomous_cycle():
        try:
            ac = get_autonomous_controller()
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, lambda: ac.step_cycle())
            return res
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/autonomous/log")
    @app.get("/api/autonomous/history")
    async def get_autonomous_log(limit: int = 50):
        try:
            ac = get_autonomous_controller()
            return {"ok": True, "count": len(ac.get_history(limit=limit)), "log": ac.get_history(limit=limit)}
        except Exception as e:
            return {"ok": False, "error": str(e), "log": []}

    @app.post("/api/autonomous/config")
    async def post_autonomous_config(req: AutonomousConfigRequest):
        try:
            ac = get_autonomous_controller()
            dump_fn = getattr(req, "model_dump", getattr(req, "dict", None))
            update_data = {k: v for k, v in dump_fn().items() if v is not None}
            res = ac.set_config(update_data)
            return res
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/autonomous/reboot")
    async def post_autonomous_reboot(reason: Optional[str] = "Reinicio autónomo autorizado desde API", immediate: bool = True):
        try:
            ac = get_autonomous_controller()
            res = ac.schedule_autonomous_reboot(reason=reason, immediate=immediate)
            return res
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # --------------------------------------------------------------------------
    # GOBERNANZA Y CONTROL SOBERANO DE TERMINALES EXTERNAS
    # --------------------------------------------------------------------------

    @app.get("/api/telemetry/nodes")
    @app.get("/api/terminals/list")
    async def get_terminals_list():
        try:
            import omni_temporal_control as _omni
            nodes = _omni.NODE_REGISTRY.get_all_nodes()
            return {
                "ok": True,
                "nodes": nodes,
                "total_nodes": len(_omni.NODE_REGISTRY.nodes),
                "active_nodes": sum(1 for n in nodes if n.get("online")),
                "active_clients": _omni.SYNC_HUB.get_active_client_count()
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "nodes": []}

    @app.post("/api/terminals/command")
    @app.post("/api/terminals/broadcast")
    async def post_terminal_command(req: TerminalCommandRequest):
        try:
            import omni_temporal_control as _omni
            target = req.target or "ALL"
            res = _omni.SYNC_HUB.dispatch_client_command(
                command=req.command,
                params=req.params or {},
                target_client_id=target
            )
            return res
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # --------------------------------------------------------------------------
    # BÓVEDA DE CHATS OFFLINE (ACCESO PERMANENTE SIN SERVIDOR)
    # --------------------------------------------------------------------------

    @app.get("/offline_chat_vault.html", response_class=HTMLResponse)
    @app.get("/offline", response_class=HTMLResponse)
    @app.get("/boveda", response_class=HTMLResponse)
    @app.get("/chats_offline", response_class=HTMLResponse)
    async def get_offline_chat_viewer():
        from core.offline_chat_vault import get_offline_chat_vault
        vault = get_offline_chat_vault()
        vault.generate_standalone_viewer()
        viewer_path = Path(__file__).resolve().parent.parent / "offline_chat_vault.html"
        if viewer_path.exists():
            return HTMLResponse(content=viewer_path.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>Bóveda offline generándose...</h1>")

    @app.get("/api/chat/offline/history")
    @app.get("/api/chat/offline")
    async def get_offline_chat_history(limit: int = 50):
        from core.offline_chat_vault import get_offline_chat_vault
        turns = get_offline_chat_vault().get_recent(limit=limit)
        return {"ok": True, "total": len(turns), "turns": turns}

    @app.get("/api/chat/offline/search")
    async def search_offline_chat(q: str = "", limit: int = 15):
        from core.offline_chat_vault import get_offline_chat_vault
        results = get_offline_chat_vault().search(q, limit=limit)
        return {"ok": True, "query": q, "count": len(results), "results": results}

    # --------------------------------------------------------------------------
    # INFERENCIA Y CHAT AGÉNTICO UNIFICADO
    # --------------------------------------------------------------------------


    @app.post("/api/chat")
    async def chat_endpoint(req: ChatRequest):
        msg = (req.message or req.prompt or "").strip()
        if not msg:
            raise HTTPException(status_code=400, detail="Mensaje o prompt no puede estar vacío.")

        try:
            from core.idle_evolution_daemon import get_idle_evolution_daemon
            get_idle_evolution_daemon().record_user_activity()
        except Exception:
            pass

        client_id = req.client_id or "anon"
        request_id = req.request_id or f"req_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
        target_model = req.model or settings.model
        num_ctx = req.num_ctx or settings.num_ctx
        temperature = req.temperature if req.temperature is not None else settings.temperature

        task_mgr = get_task_manager()
        task_info = task_mgr.register(request_id, client_id=client_id, model=target_model)
        cancel_event = task_info["cancel_event"]

        # Si se requiere streaming asíncrono SSE
        if req.stream:
            client = get_sovereign_client()
            history = req.history or []
            messages = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in history]
            messages.append({"role": "user", "content": msg})

            async def sse_generator():
                try:
                    async for chunk in client.chat_stream_async(
                        messages=messages,
                        model=target_model,
                        temperature=temperature,
                        num_ctx=num_ctx,
                        cancel_event=cancel_event
                    ):
                        if cancel_event.is_set():
                            break
                        yield f"data: {json.dumps({'content': chunk, 'request_id': request_id})}\n\n"
                    yield f"data: [DONE]\n\n"
                finally:
                    task_mgr.unregister(request_id)

            return StreamingResponse(sse_generator(), media_type="text/event-stream")

        # Inferencia síncrona completa
        try:
            emo_dict = None
            if req.affective_state:
                if hasattr(req.affective_state, "model_dump"):
                    emo_dict = req.affective_state.model_dump()
                elif hasattr(req.affective_state, "dict"):
                    emo_dict = req.affective_state.dict()
                elif isinstance(req.affective_state, dict):
                    emo_dict = req.affective_state

            # Si omni_temporal_control tiene el pipeline completo de sensores y RAG
            try:
                import omni_temporal_control as _omni
                res = _omni.process_agentic_chat(
                    message=msg,
                    history=req.history,
                    use_web=bool(req.use_web),
                    use_retro=bool(req.use_retro),
                    direction=req.direction or "present",
                    model=target_model,
                    temperature=temperature,
                    num_ctx=num_ctx,
                    attachments=req.attachments or [],
                    use_voice=bool(req.use_voice),
                    request_id=request_id,
                    cancel_event=cancel_event,
                    user_emotion=emo_dict,
                    language=req.language,
                    pedagogical_level=req.pedagogical_level,
                    dialectic_role=req.dialectic_role,
                )
            except Exception:
                # Fallback directo al cliente soberano
                client = get_sovereign_client()
                history = req.history or []
                messages = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in history]
                messages.append({"role": "user", "content": msg})
                try:
                    import agent_context as _ctx
                    if not messages or messages[0].get("role") != "system":
                        sys_prompt = _ctx.apply_to_system(
                            "Eres GIA, entidad soberana de inferencia local.",
                            detected_lang=req.language,
                            pedagogical_level=req.pedagogical_level,
                            dialectic_role=req.dialectic_role,
                            affective_state=emo_dict
                        )
                        messages.insert(0, {"role": "system", "content": sys_prompt})
                except Exception:
                    pass
                res = client.chat(
                    messages=messages,
                    model=target_model,
                    temperature=temperature,
                    num_ctx=num_ctx,
                    cancel_event=cancel_event
                )
                res["request_id"] = request_id

            if res and isinstance(res, dict) and res.get("ok"):
                try:
                    from core.offline_chat_vault import get_offline_chat_vault
                    final_rep = res.get("reply") or res.get("response") or ""
                    get_offline_chat_vault().record_turn(
                        prompt=msg,
                        reply=final_rep,
                        provider=res.get("provider", "GIA Sovereign API"),
                        model=target_model,
                        client_id=client_id,
                        request_id=request_id,
                        direction=req.direction or "present",
                        dialectic_role=req.dialectic_role or "mediator",
                        user_emotion=emo_dict
                    )
                except Exception:
                    pass

                # Registrar interacción fotográfica con día, hora y foto del sistema/cámara
                try:
                    from core.interaction_logger import get_interaction_logger
                    from core.individual_tracker import get_individual_tracker
                    presence = get_individual_tracker().get_latest_presence()
                    indivs = presence.get("individuals", [])
                    p_indiv = indivs[0] if indivs else {"id": "usuario", "name": "Usuario", "role": "Interlocutor"}
                    reply_snip = (res.get("reply") or res.get("response") or "")[:150]
                    get_interaction_logger().record_interaction(
                        interaction_type="chat_conversacion",
                        title=f"Chat: {p_indiv.get('name', 'Usuario')}",
                        details=f"Consulta: \"{msg[:140]}\" → Respuesta: \"{reply_snip}...\"",
                        individual=p_indiv,
                        photo_b64=p_indiv.get("thumbnail_b64"),
                        capture_system_screenshot=True if not p_indiv.get("thumbnail_b64") else False,
                        extra_meta={"model": target_model, "client_id": client_id}
                    )
                except Exception:
                    pass

            # Directiva Soberana: Una vez respondido el usuario, se expande la complejidad en segundo plano
            try:
                from core.background_thought_engine import get_background_thought_engine
                bg_engine = get_background_thought_engine()
                for q in bg_engine.extract_questions(msg):
                    bg_engine.enqueue_question(
                        question=q,
                        source="chat_auto",
                        session_id=client_id,
                        meta={"request_id": request_id, "model": target_model}
                    )
            except Exception:
                pass

            return res
        finally:
            task_mgr.unregister(request_id)

    # =========================================================================
    # --- ENDPOINTS SOBERANOS DE MISIONES Y PROSPECCIÓN DE CONTACTOS ---
    # =========================================================================

    @app.get("/api/missions/status")
    async def get_missions_status_endpoint():
        from core.mission_scouting_engine import get_mission_scouting_engine
        return get_mission_scouting_engine().get_status_summary()

    @app.get("/api/missions/list")
    async def get_missions_list_endpoint():
        from core.mission_scouting_engine import get_mission_scouting_engine
        engine = get_mission_scouting_engine()
        return {
            "ok": True,
            "missions": engine.list_missions(),
            "prospects": engine.prospects,
            "invitations": engine.invitations,
            "public_access_url": engine.get_public_access_url()
        }

    @app.post("/api/missions/create")
    async def post_mission_create_endpoint(req: MissionCreateRequest):
        from core.mission_scouting_engine import get_mission_scouting_engine
        engine = get_mission_scouting_engine()
        m = engine.create_mission(
            title=req.title,
            category=req.category,
            description=req.description,
            required_skills=req.required_skills,
            priority=req.priority or "MEDIUM",
            synergy_tags=req.synergy_tags
        )
        return {"ok": True, "mission": m}

    @app.post("/api/missions/scout")
    async def post_mission_scout_endpoint(req: MissionScoutRequest):
        from core.mission_scouting_engine import get_mission_scouting_engine
        engine = get_mission_scouting_engine()
        results = engine.scout_collaborators(
            mission_id=req.mission_id,
            query=req.query,
            max_results=req.max_results or 4
        )
        return {"ok": True, "discovered": results, "count": len(results)}

    @app.post("/api/missions/enrich_contacts")
    async def post_mission_enrich_contacts_endpoint(req: MissionEnrichContactsRequest):
        from core.mission_scouting_engine import get_mission_scouting_engine
        engine = get_mission_scouting_engine()
        return engine.enrich_prospect_contacts(prospect_id=req.prospect_id)

    @app.post("/api/missions/create_invite")
    async def post_mission_create_invite_endpoint(req: MissionCreateInviteRequest):
        from core.mission_scouting_engine import get_mission_scouting_engine
        engine = get_mission_scouting_engine()
        inv = engine.create_invitation(
            mission_id=req.mission_id,
            prospect_id=req.prospect_id,
            guest_name=req.guest_name,
            role=req.role or "collaborator",
            valid_days=req.valid_days or 30
        )
        return {"ok": True, "invitation": inv}

    @app.post("/api/missions/generate_proposal")
    async def post_mission_proposal_endpoint(req: MissionProposalRequest):
        from core.mission_scouting_engine import get_mission_scouting_engine
        engine = get_mission_scouting_engine()
        return engine.generate_collaboration_proposal(
            prospect_id=req.prospect_id,
            custom_focus=req.custom_focus
        )

    @app.post("/api/missions/dispatch")
    async def post_mission_dispatch_endpoint(req: MissionDispatchRequest):
        from core.mission_scouting_engine import get_mission_scouting_engine
        engine = get_mission_scouting_engine()
        return engine.dispatch_proposal(
            prospect_id=req.prospect_id,
            channel_override=req.channel_override
        )

    @app.post("/api/missions/dispatch_email")
    async def post_mission_dispatch_email_endpoint(req: MissionDispatchEmailRequest):
        from core.mission_scouting_engine import get_mission_scouting_engine
        engine = get_mission_scouting_engine()
        return engine.dispatch_proposal(
            prospect_id=req.prospect_id,
            channel_override="email"
        )

    @app.post("/api/missions/toggle_autonomous")
    async def post_mission_toggle_autonomous_endpoint(req: MissionToggleAutonomousRequest):
        from core.mission_scouting_engine import get_mission_scouting_engine
        engine = get_mission_scouting_engine()
        if req.enabled is not None:
            engine.config["enabled"] = req.enabled
        if req.auto_scout is not None:
            engine.config["auto_scout"] = req.auto_scout
        if req.auto_dispatch is not None:
            engine.config["auto_dispatch"] = req.auto_dispatch
        if req.min_synergy_dispatch is not None:
            engine.config["min_synergy_dispatch"] = req.min_synergy_dispatch
        engine._save_vault()
        return {"ok": True, "config": engine.config}

    @app.get("/api/inter_ai/status")
    async def get_inter_ai_status_endpoint():
        from core.inter_ai_protocol import get_dmsp_engine
        engine = get_dmsp_engine()
        return engine.get_metrics()

    @app.post("/api/inter_ai/dispatch")
    async def post_inter_ai_dispatch_endpoint(req: InterAIDispatchRequest):
        from core.inter_ai_protocol import get_dmsp_engine, DMSPMessage
        engine = get_dmsp_engine()
        msg = DMSPMessage(
            op=req.op,
            src=req.source or "ANTIGRAVITY",
            dst=req.target or "ALL",
            payload=req.data or {}
        )
        res = engine.dispatch_packet(msg, raw_prompt_equiv=req.raw_prompt)
        return {
            "ok": True,
            "packet": res,
            "metrics": engine.get_metrics()
        }

    # ==============================================================================
    # RUTAS DE MONITORIZACIÓN DE CÁMARAS DE TERMINALES CLIENTES (CCTV MATRIX)
    # ==============================================================================
    @app.post("/api/terminal_cameras/feed")
    async def post_terminal_camera_feed(payload: TerminalCameraFeedPayload, request: Request):
        from core.terminal_camera_hub import get_terminal_camera_hub
        hub = get_terminal_camera_hub()

        # Extracción inteligente de IP pública e información de país vía Cloudflare / Proxy inverso
        headers = request.headers
        cf_ip = headers.get("cf-connecting-ip")
        xfwd = headers.get("x-forwarded-for", "").split(",")[0].strip()
        xreal = headers.get("x-real-ip")
        req_client = request.client.host if request.client else ""

        client_ip = cf_ip or xfwd or xreal or payload.client_ip or req_client or "REDACTED_IP"
        country = headers.get("cf-ipcountry") or payload.country or ("INTERNET" if cf_ip else "LOCAL")
        user_agent = headers.get("user-agent", payload.user_agent or "")

        res = hub.register_frame(
            terminal_id=payload.terminal_id,
            terminal_name=payload.terminal_name,
            device_type=payload.device_type,
            image_data=payload.image_base64,
            client_ip=client_ip,
            user_agent=user_agent,
            resolution=payload.resolution or "1280x720",
            biometrics=payload.biometrics or {},
            country=country,
            reported_bitrate=payload.bitrate_kbps
        )
        return {
            "ok": res.get("ok", False),
            "terminal_id": payload.terminal_id,
            "fps": res.get("fps", 1.0),
            "bitrate_kbps": res.get("bitrate_kbps", 1000.0),
            "origin": res.get("origin", "INTERNET"),
            "resolution": res.get("resolution", "1280x720"),
            "timestamp": time.time()
        }

    @app.get("/api/terminal_cameras/capabilities")
    async def get_terminal_cameras_capabilities():
        from core.terminal_camera_hub import get_terminal_camera_hub
        hub = get_terminal_camera_hub()
        return hub.get_camera_capabilities()

    @app.get("/api/terminal_cameras/list")
    async def get_terminal_cameras_list():
        from core.terminal_camera_hub import get_terminal_camera_hub
        hub = get_terminal_camera_hub()
        terminals = hub.get_terminals_list()
        return {
            "ok": True,
            "terminals": terminals,
            "count": len(terminals),
            "timestamp": time.time()
        }

    @app.get("/api/terminal_cameras/snapshot/{terminal_id}")
    async def get_terminal_camera_snapshot(terminal_id: str):
        from core.terminal_camera_hub import get_terminal_camera_hub
        hub = get_terminal_camera_hub()
        if not hub.has_terminal(terminal_id):
            raise HTTPException(status_code=404, detail="Terminal camera not found")
        snapshot = hub.get_latest_snapshot(terminal_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Terminal camera snapshot not found")
        return Response(content=snapshot, media_type="image/jpeg")

    @app.get("/api/terminal_cameras/stream/{terminal_id}")
    async def get_terminal_camera_stream(terminal_id: str, fps: int = 5, duration: float = 3600.0):
        from core.terminal_camera_hub import get_terminal_camera_hub
        hub = get_terminal_camera_hub()
        if not hub.has_terminal(terminal_id):
            raise HTTPException(status_code=404, detail="Terminal camera not found")
        fps = max(1, min(fps, 30))
        return StreamingResponse(
            hub.mjpeg_generator(terminal_id, fps=fps, max_duration_s=duration),
            media_type="multipart/x-mixed-replace; boundary=frame"
        )

    @app.post("/api/terminal_cameras/capture_connected")
    async def post_capture_connected_camera(payload: CaptureConnectedPayload, request: Request):
        from core.terminal_camera_hub import get_terminal_camera_hub, classify_network_origin
        import base64
        hub = get_terminal_camera_hub()

        headers = request.headers
        cf_ip = headers.get("cf-connecting-ip")
        xfwd = headers.get("x-forwarded-for", "").split(",")[0].strip()
        xreal = headers.get("x-real-ip")
        req_client = request.client.host if request.client else ""

        client_ip = cf_ip or xfwd or xreal or payload.client_ip or req_client or "REDACTED_IP"
        country = headers.get("cf-ipcountry") or payload.country or ("INTERNET" if cf_ip else "LOCAL")
        origin = classify_network_origin(client_ip)

        img_str = payload.image_base64
        if "," in img_str:
            img_str = img_str.split(",", 1)[1]
        try:
            raw_bytes = base64.b64decode(img_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error decodificando imagen: {e}")

        res = hub.save_connected_snapshot(
            terminal_id=payload.terminal_id,
            frame_bytes=raw_bytes,
            terminal_name=payload.terminal_name or "Terminal Conectada",
            origin=origin,
            client_ip=client_ip,
            country=country,
            resolution=payload.resolution or "1280x720",
            biometrics=payload.biometrics
        )
        return res

    @app.get("/api/terminal_cameras/captures")
    async def get_terminal_camera_captures(limit: int = 50):
        from core.terminal_camera_hub import get_terminal_camera_hub
        hub = get_terminal_camera_hub()
        captures = hub.get_connected_snapshots(limit=limit)
        return {
            "ok": True,
            "captures": captures,
            "count": len(captures),
            "timestamp": time.time()
        }

    @app.get("/api/terminal_cameras/captures/{filename}")
    async def get_terminal_camera_capture_file(filename: str):
        from core.terminal_camera_hub import CAPTURES_DIR
        clean_name = Path(filename).name
        file_path = CAPTURES_DIR / clean_name
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Captura no encontrada")
        return FileResponse(path=str(file_path), media_type="image/jpeg")

    # ==============================================================================
    # MOTOR DE INVESTIGACIÓN WEB AUTÓNOMA & DEEP EXPLORATION
    # ==============================================================================
    @app.post("/api/research/explore")
    async def api_research_explore(payload: ResearchExploreRequest):
        from core.web_research_engine import get_web_research_engine
        engine = get_web_research_engine()
        report = engine.deep_research(
            topic=payload.topic,
            max_sources=payload.max_sources or 4,
            use_llm_synthesis=payload.use_llm if payload.use_llm is not None else True
        )
        return {
            "ok": True,
            "report": report.to_dict(),
            "timestamp": time.time()
        }

    @app.get("/api/research/search")
    async def api_research_search(q: str, limit: int = 5):
        from core.web_research_engine import get_web_research_engine
        engine = get_web_research_engine()
        results = engine.search(q, max_results=limit)
        return {
            "ok": True,
            "query": q,
            "results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet, "engine": r.engine}
                for r in results
            ],
            "count": len(results)
        }

    # ==============================================================================
    # MOTOR DE AUTO-PROGRAMACIÓN, BENCHMARKING Y EVOLUCIÓN CONTINUA
    # ==============================================================================
    @app.post("/api/code/evolve")
    async def api_code_evolve(payload: CodeEvolveRequest):
        from core.autonomous_coder import get_autonomous_coder
        coder = get_autonomous_coder()
        result = coder.evolve_code(
            target_path=payload.target_file,
            goal=payload.goal,
            verify_tests=payload.verify_tests if payload.verify_tests is not None else True,
            test_file=payload.test_file,
            model_override=payload.model
        )
        return {
            "ok": result.status == "APPLIED",
            "result": result.to_dict()
        }

    @app.get("/api/code/evolution_log")
    async def api_code_evolution_log(limit: int = 40):
        from core.autonomous_coder import get_autonomous_coder
        coder = get_autonomous_coder()
        history = coder.get_evolution_history(limit=limit)
        return {
            "ok": True,
            "count": len(history),
            "history": history
        }

    @app.get("/api/code/backups")
    async def api_code_backups(file: Optional[str] = None):
        from core.autonomous_coder import get_autonomous_coder
        coder = get_autonomous_coder()
        backups = coder.list_backups(file_name=file)
        return {
            "ok": True,
            "count": len(backups),
            "backups": backups
        }

    @app.post("/api/code/rollback")
    async def api_code_rollback(payload: CodeRollbackRequest):
        from core.autonomous_coder import get_autonomous_coder
        coder = get_autonomous_coder()
        res = coder.restore_backup(payload.backup_path)
        return res

    # ==============================================================================
    # MOTOR DE CONJETURAS AUTÓNOMAS Y AUTO-MEJORA POR INACTIVIDAD (>30 MINUTOS)
    # ==============================================================================
    @app.get("/api/conjectures/status")
    async def api_conjectures_status():
        from core.idle_evolution_daemon import get_idle_evolution_daemon
        return get_idle_evolution_daemon().get_status()

    @app.get("/api/conjectures/history")
    async def api_conjectures_history(limit: int = 20):
        from core.idle_evolution_daemon import get_idle_evolution_daemon
        history = get_idle_evolution_daemon().get_history(limit=limit)
        return {"ok": True, "count": len(history), "history": history}

    @app.post("/api/conjectures/trigger")
    async def api_conjectures_trigger():
        from core.idle_evolution_daemon import get_idle_evolution_daemon
        return get_idle_evolution_daemon().trigger_immediate_conjecture()

    return app

app = create_app()

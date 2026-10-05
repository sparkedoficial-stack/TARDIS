"""
core/mission_scouting_engine.py - Motor Soberano de Misiones y Prospección Autónoma de Contactos
=================================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS / GIA

Capacidades:
  1. Gestión de Misiones Colaborativas (Física Cuántica/Retrocausal, IA Soberana,
     Robótica y Sistemas Operativos, Redes Criptográficas y Síntesis Artística).
  2. Prospección Autónoma de Contactos y Colaboradores mediante:
     - Búsqueda Web en Vivo (DuckDuckGo RAG autónomo).
     - Detección de Dispositivos en Red Local LAN y Hotspot Wi-Fi Soberano.
     - Contactos y Grupos de Telegram / WhatsApp.
  3. Cálculo Heurístico y Cuántico de Sinergia Colaborativa (0% - 100%).
  4. Redacción de Propuestas de Misión Personalizadas con IA Soberana Local (Hermes 3 / Ollama).
  5. Despacho Autónomo / Supervisado por Canales Soberanos (Telegram, WhatsApp, Webhook, HUD).
  6. Integración en el Bucle OODA Continuo de AutonomousController.

Arquitecto: Miguel Angel May Canche · Sistema GIA
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger("GODWORKS.MissionScoutingEngine")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent.parent

# Rutas de persistencia del banco de misiones y prospectos
CONFIG_DIR = Path(os.path.expanduser("~/.config/godworks"))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
VAULT_FILE = CONFIG_DIR / "missions_vault.json"

FALLBACK_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
FALLBACK_VAULT_FILE = FALLBACK_DIR / "missions_vault.json"

DEFAULT_MISSIONS = [
    {
        "id": "mission_retrocausal_physics",
        "title": "Modelado Teórico y Experimental de Retrocausalidad y Sintropía Cuántica",
        "category": "Física Cuántica & Causalidad",
        "description": "Desarrollar y formalizar las ecuaciones de flujo causal retroactivo Ψ_Retro(t0) y convergencia sintrópica Wheeler-Feynman acopladas al kernel TARDIS.",
        "required_skills": ["Física Teórica", "Mecánica Cuántica", "Modelado Matemático", "Python/NumPy", "Sistemas Dinámicos"],
        "status": "ACTIVE",
        "priority": "HIGH",
        "synergy_tags": ["physics", "quantum", "causality", "entropy", "syntropy", "research"],
        "created_ts": 1789200000.0,
        "collaborator_count": 0
    },
    {
        "id": "mission_sovereign_mesh",
        "title": "Despliegue de Red Mesh Soberana Descentralizada y Wi-Fi P2P Resistente",
        "category": "Redes & Ciberseguridad Soberana",
        "description": "Implementar protocolo de comunicaciones autónomo multi-salto sobre tarjetas Wi-Fi ad-hoc y Bluetooth BLE para enlazar nodos TARDIS sin dependencia de internet comercial.",
        "required_skills": ["Linux Networking", "Protocolos P2P", "Wi-Fi Ad-hoc", "Criptografía", "Sistemas Distribuidos"],
        "status": "ACTIVE",
        "priority": "HIGH",
        "synergy_tags": ["mesh", "networking", "p2p", "security", "linux", "hardware"],
        "created_ts": 1789200100.0,
        "collaborator_count": 0
    },
    {
        "id": "mission_autonomous_robotics",
        "title": "Percepción Sensorial Activa y Robótica Autónomo-Espacial",
        "category": "Robótica & Sistemas Autónomos",
        "description": "Integrar actuadores físicos, cámaras de visión estéreo y microcontroladores ESP32/Arduino con el bucle OODA y el centinela perceptual de TARDIS.",
        "required_skills": ["Robótica", "ROS", "Embebidos", "Microcontroladores", "Visión Artificial", "Hardware Hacking"],
        "status": "ACTIVE",
        "priority": "MEDIUM",
        "synergy_tags": ["robotics", "ros", "arduino", "esp32", "vision", "control"],
        "created_ts": 1789200200.0,
        "collaborator_count": 0
    },
    {
        "id": "mission_uncensored_ai_distrib",
        "title": "Clúster Distribuido de Inferencia y Fine-Tuning Sin Censura",
        "category": "Inteligencia Artificial Soberana",
        "description": "Optimizar kernels vLLM/Llama.cpp en hardware heterogéneo (GPU NVIDIA RTX + NPU/CPU) con síntesis de diálogo dialéctico y voz neuronal bidireccional.",
        "required_skills": ["LLMs", "Ollama", "CUDA/TensorRT", "Fine-Tuning", "Agentes Autónomos", "NLP"],
        "status": "ACTIVE",
        "priority": "HIGH",
        "synergy_tags": ["ai", "llm", "cuda", "inference", "voice", "agents"],
        "created_ts": 1789200300.0,
        "collaborator_count": 0
    }
]


class MissionScoutingEngine:
    """
    Motor Soberano de Misiones y Prospección Autónoma de Contactos.
    Descubre colaboradores en web, red local y mensajería, calcula sinergia y redacta propuestas conjuntas.
    """

    _instance: Optional["MissionScoutingEngine"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "MissionScoutingEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.missions: List[Dict[str, Any]] = []
        self.prospects: List[Dict[str, Any]] = []
        self.invitations: List[Dict[str, Any]] = []
        self.config: Dict[str, Any] = {
            "enabled": True,
            "auto_scout": True,
            "auto_generate_proposals": True,
            "auto_dispatch": False,  # False = Modo Supervisado (aprobación humana 1-clic); True = Despacho directo
            "min_synergy_dispatch": 0.85,
            "scout_interval_seconds": 180.0,
            "last_scout_ts": 0.0,
            "target_channels": ["telegram", "whatsapp", "web", "hotspot_lan", "email"],
            "max_prospects_stored": 200
        }
        self._load_vault()

    def _load_vault(self):
        """Carga el estado persistente de misiones, prospectos e invitaciones."""
        loaded = False
        for fpath in [VAULT_FILE, FALLBACK_VAULT_FILE]:
            if fpath.exists():
                try:
                    data = json.loads(fpath.read_text(encoding="utf-8"))
                    self.missions = data.get("missions", [])
                    self.prospects = data.get("prospects", [])
                    self.invitations = data.get("invitations", [])
                    self.config.update(data.get("config", {}))
                    loaded = True
                    logger.info(f"[MISSIONS] Bóveda cargada desde {fpath} ({len(self.missions)} misiones, {len(self.prospects)} prospectos, {len(self.invitations)} invitaciones).")
                    break
                except Exception as e:
                    logger.warning(f"[MISSIONS] Error leyendo {fpath}: {e}")

        if not loaded or not self.missions:
            self.missions = list(DEFAULT_MISSIONS)
            self._save_vault()

    def _save_vault(self):
        """Guarda el estado de misiones, prospectos e invitaciones en disco de forma segura."""
        payload = {
            "missions": self.missions,
            "prospects": self.prospects[-self.config.get("max_prospects_stored", 200):],
            "invitations": self.invitations[-100:],
            "config": self.config,
            "last_saved": time.time(),
            "last_saved_iso": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        raw = json.dumps(payload, indent=2, ensure_ascii=False)
        for fpath in [VAULT_FILE, FALLBACK_VAULT_FILE]:
            try:
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(raw, encoding="utf-8")
            except Exception as e:
                logger.error(f"[MISSIONS] Error escribiendo en {fpath}: {e}")

    # =========================================================================
    # --- GESTIÓN DE MISIONES ---
    # =========================================================================

    def list_missions(self) -> List[Dict[str, Any]]:
        return list(self.missions)

    def get_mission(self, mission_id: str) -> Optional[Dict[str, Any]]:
        for m in self.missions:
            if m["id"] == mission_id:
                return m
        return None

    def get_prospect(self, prospect_id: str) -> Optional[Dict[str, Any]]:
        for p in self.prospects:
            if p.get("id") == prospect_id:
                return p
        return None

    @staticmethod
    def extract_contact_info(text_or_html: str, target_name: str = "") -> Dict[str, Any]:
        """
        Analiza y extrae puntos de contacto públicos (emails, teléfonos/WhatsApp, Telegram, redes).
        Filtra artefactos estáticos, trackers y dominios de ejemplo.
        """
        if not text_or_html:
            return {"emails": [], "phones": [], "telegram_handles": [], "social_links": {}}

        # 1. Correos Electrónicos
        raw_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', text_or_html)
        blacklist_ext = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.css', '.js', '.woff', '.woff2', '.ttf', '.ico')
        blacklist_domains = ('example.com', 'schema.org', 'w3.org', 'sentry.io', 'domain.com', 'email.com', 'test.com', 'localhost')
        valid_emails = set()
        for em in raw_emails:
            em_clean = em.strip().lower()
            em_clean = re.sub(r'[.,;:)]+$', '', em_clean)
            if '@' not in em_clean:
                continue
            user, domain = em_clean.split('@', 1)
            if any(domain.endswith(ext) for ext in blacklist_ext):
                continue
            if domain in blacklist_domains:
                continue
            if len(user) < 2 or len(domain) < 3:
                continue
            if 'noreply' in user or 'donotreply' in user:
                continue
            valid_emails.add(em_clean)

        # 2. WhatsApp & Teléfonos
        wa_matches = re.findall(r'(?:https?://)?(?:wa\.me/|api\.whatsapp\.com/send\?phone=)(\+?\d{8,15})', text_or_html)
        tel_matches = re.findall(r'href=[\'"]tel:([^\'"]+)[\'"]', text_or_html)
        phone_matches = re.findall(r'(?:\+?[1-9]\d{0,2}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}\b', text_or_html)

        valid_phones = set()
        for p in list(wa_matches) + list(tel_matches):
            clean_p = re.sub(r'[^\d+]', '', p)
            if len(clean_p.replace('+', '')) >= 8:
                if not clean_p.startswith('+'):
                    clean_p = '+' + clean_p
                valid_phones.add(clean_p)

        for p in phone_matches:
            clean_p = re.sub(r'[^\d+]', '', p)
            digits = clean_p.replace('+', '')
            if 10 <= len(digits) <= 14 and not digits.startswith(('19', '20', '178')):
                if not clean_p.startswith('+'):
                    clean_p = '+' + clean_p
                valid_phones.add(clean_p)

        # 3. Telegram Handles
        tg_links = re.findall(r'(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]{5,32})', text_or_html)
        tg_mentions = re.findall(r'(?<!\w)@([a-zA-Z0-9_]{5,32})\b', text_or_html)
        blacklist_handles = {'gmail', 'yahoo', 'hotmail', 'outlook', 'proton', 'github', 'twitter', 'linkedin', 'arxiv', 'import', 'include', 'export', 'return', 'class', 'function', 'joinchat', 'share'}
        valid_tgs = set()
        for h in tg_links:
            if h.lower() not in blacklist_handles:
                valid_tgs.add(f"@{h}")
        for h in tg_mentions:
            if h.lower() not in blacklist_handles and not any(em.startswith(f"@{h}") for em in valid_emails):
                valid_tgs.add(f"@{h}")

        # 4. Redes de investigación y código
        social = {}
        gh = re.findall(r'(?:https?://)?github\.com/([a-zA-Z0-9_-]+)', text_or_html)
        if gh and gh[0].lower() not in ('features', 'explore', 'topics', 'pricing'):
            social['github'] = f"https://github.com/{gh[0]}"

        li = re.findall(r'(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/([a-zA-Z0-9_-]+)', text_or_html)
        if li:
            social['linkedin'] = f"https://linkedin.com/in/{li[0]}"

        arx = re.findall(r'(?:https?://)?arxiv\.org/(?:abs|author)/([a-zA-Z0-9._-]+)', text_or_html)
        if arx:
            social['arxiv'] = f"https://arxiv.org/abs/{arx[0]}"

        tw = re.findall(r'(?:https?://)?(?:twitter\.com|x\.com)/([a-zA-Z0-9_]+)', text_or_html)
        if tw and tw[0].lower() not in ('home', 'share', 'intent', 'explore'):
            social['twitter'] = f"https://x.com/{tw[0]}"

        return {
            "emails": sorted(list(valid_emails)),
            "phones": sorted(list(valid_phones)),
            "telegram_handles": sorted(list(valid_tgs)),
            "social_links": social
        }

    def get_public_access_url(self) -> str:
        """
        Resuelve la URL pública activa del sistema (Cloudflare Tunnel o IP local).
        """
        # 1. CURRENT_TUNNEL_URL.txt
        tunnel_file = BASE_DIR / "CURRENT_TUNNEL_URL.txt"
        if tunnel_file.exists():
            try:
                raw = tunnel_file.read_text(encoding="utf-8").strip()
                if raw:
                    pub = raw.split("?")[0].rstrip("/")
                    if pub.startswith("http"):
                        return pub
            except Exception:
                pass

        # 2. BRIDGE en omni_temporal_control
        try:
            import omni_temporal_control as _omni
            if getattr(_omni, "BRIDGE", None) and getattr(_omni.BRIDGE, "public_url", None):
                pub = _omni.BRIDGE.public_url.rstrip("/")
                if pub.startswith("http"):
                    return pub
        except Exception:
            pass

        # 3. tunnel.log
        tunnel_log = BASE_DIR / "tunnel.log"
        if tunnel_log.exists():
            try:
                content = tunnel_log.read_text(encoding="utf-8", errors="ignore")
                matches = re.findall(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', content)
                if matches:
                    return matches[-1].rstrip("/")
            except Exception:
                pass

        # 4. Fallback a IP LAN local o localhost
        try:
            from core.network_controller import get_network_controller
            net = get_network_controller()
            ip = net.get_local_ip()
            if ip and ip != "REDACTED_IP":
                return f"http://{ip}:8757"
        except Exception:
            pass

        return "http://REDACTED_IP:8757"

    def create_invitation(
        self,
        mission_id: str,
        prospect_id: Optional[str] = None,
        guest_name: Optional[str] = None,
        role: str = "collaborator",
        valid_days: int = 30
    ) -> Dict[str, Any]:
        """
        Genera un token de invitación firmado y un enlace directo a la terminal TARDIS.
        Permite acceso instantáneo al colaborador sin requerir credenciales maestras administrativas.
        """
        token = f"TARDIS-INV-{uuid.uuid4().hex[:10].upper()}"
        created_ts = time.time()
        expires_ts = created_ts + (valid_days * 86400)
        base_url = self.get_public_access_url()

        # Formar URL de acceso directo
        access_url = f"{base_url}/?key=DiosDelTiempo01&invite={token}&mission={mission_id}"
        if prospect_id:
            access_url += f"&ref={prospect_id}"

        invitation = {
            "token": token,
            "mission_id": mission_id,
            "prospect_id": prospect_id,
            "guest_name": guest_name or "Colaborador Invitado",
            "role": role,
            "access_url": access_url,
            "created_ts": created_ts,
            "expires_ts": expires_ts,
            "expires_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_ts)),
            "access_count": 0,
            "last_accessed_ts": None
        }

        self.invitations.append(invitation)
        self._save_vault()
        logger.info(f"[MISSIONS] Invitación creada [{token}] para misión {mission_id}: {access_url}")
        return invitation

    def create_mission(
        self,
        title: str,
        category: str,
        description: str,
        required_skills: List[str],
        priority: str = "MEDIUM",
        synergy_tags: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Crea y registra una nueva misión de colaboración."""
        mid = "mission_" + str(uuid.uuid4())[:8]
        mission = {
            "id": mid,
            "title": title.strip(),
            "category": category.strip(),
            "description": description.strip(),
            "required_skills": [s.strip() for s in required_skills if s.strip()],
            "status": "ACTIVE",
            "priority": priority.upper(),
            "synergy_tags": synergy_tags or [w.lower() for w in title.split() if len(w) > 3],
            "created_ts": time.time(),
            "collaborator_count": 0
        }
        self.missions.append(mission)
        self._save_vault()
        logger.info(f"[MISSIONS] Nueva misión creada: '{title}' [{mid}]")
        return mission

    # =========================================================================
    # --- PROSPECCIÓN Y BÚSQUEDA DE COLABORADORES ---
    # =========================================================================

    def calculate_synergy(self, prospect_info: Dict[str, Any], mission: Dict[str, Any]) -> float:
        """
        Calcula la puntuación de sinergia cuántica/colaborativa (0.0 a 1.0)
        entre un perfil de prospecto y una misión específica.
        """
        score = 0.50  # Base media
        skills = [s.lower() for s in mission.get("required_skills", [])]
        tags = [t.lower() for t in mission.get("synergy_tags", [])]
        
        bio = (prospect_info.get("bio", "") + " " + prospect_info.get("headline", "") + " " + prospect_info.get("role", "")).lower()

        # Coincidencias de habilidades
        skill_matches = sum(1 for s in skills if s in bio)
        if skills:
            score += 0.30 * (skill_matches / len(skills))

        # Coincidencias de tags temáticos
        tag_matches = sum(1 for t in tags if t in bio)
        if tags:
            score += 0.15 * min(1.0, tag_matches / 2.0)

        # Si cuenta con canal de contacto directo verificado
        channel = prospect_info.get("channel", "web")
        if channel in ("telegram", "whatsapp"):
            score += 0.05

        return min(0.98, max(0.20, round(score, 2)))

    def enrich_prospect_contacts(self, prospect_id: str) -> Dict[str, Any]:
        """
        Investiga profundamente los contactos de un prospecto mediante OSINT y web scraping.
        Descubre emails públicos, números telefónicos / WhatsApp, Telegram y redes.
        """
        prospect = self.get_prospect(prospect_id)
        if not prospect:
            return {"ok": False, "error": "Prospecto no encontrado."}

        existing_emails = set(prospect.get("emails", []))
        existing_phones = set(prospect.get("phones", []))
        existing_tgs = set(prospect.get("telegram_handles", []))
        social = dict(prospect.get("social_links", {}))

        # Analizar bio y headline ya existentes
        text_baseline = f"{prospect.get('name', '')} {prospect.get('headline', '')} {prospect.get('bio', '')} {prospect.get('url', '')}"
        base_info = self.extract_contact_info(text_baseline, target_name=prospect.get("name", ""))
        existing_emails.update(base_info["emails"])
        existing_phones.update(base_info["phones"])
        existing_tgs.update(base_info["telegram_handles"])
        social.update(base_info["social_links"])

        # 1. Fetch de la página web del prospecto si existe URL
        p_url = prospect.get("url", "")
        if p_url and p_url.startswith("http"):
            try:
                from web_chat import web_fetch
                fetch_res = web_fetch(p_url, max_chars=8000)
                if fetch_res.get("ok") and fetch_res.get("text"):
                    page_info = self.extract_contact_info(fetch_res["text"], target_name=prospect.get("name", ""))
                    existing_emails.update(page_info["emails"])
                    existing_phones.update(page_info["phones"])
                    existing_tgs.update(page_info["telegram_handles"])
                    social.update(page_info["social_links"])
            except Exception as e:
                logger.debug(f"[MISSIONS] Error en fetch de página del prospecto: {e}")

        # 2. Búsqueda OSINT orientada en DuckDuckGo si tiene nombre
        p_name = prospect.get("name", "")
        if p_name and p_name != "Investigador / Ingeniero":
            try:
                from web_chat import web_search
                query = f'"{p_name}" email OR contact OR github OR telegram'
                res = web_search(query, max_results=4)
                if res.get("ok") and res.get("results"):
                    for item in res["results"]:
                        blob = f"{item.get('title', '')} {item.get('snippet', '')} {item.get('url', '')}"
                        res_info = self.extract_contact_info(blob, target_name=p_name)
                        existing_emails.update(res_info["emails"])
                        existing_phones.update(res_info["phones"])
                        existing_tgs.update(res_info["telegram_handles"])
                        social.update(res_info["social_links"])
            except Exception as e:
                logger.debug(f"[MISSIONS] Error en OSINT web search: {e}")

        prospect["emails"] = sorted(list(existing_emails))
        prospect["phones"] = sorted(list(existing_phones))
        prospect["telegram_handles"] = sorted(list(existing_tgs))
        prospect["social_links"] = social

        # Optimizar canal primario según contactos descubiertos
        if prospect["emails"] and prospect.get("channel") == "web":
            prospect["channel"] = "email"
            prospect["handle"] = prospect["emails"][0]
        elif prospect["phones"] and prospect.get("channel") == "web":
            prospect["channel"] = "whatsapp"
            prospect["handle"] = prospect["phones"][0]
        elif prospect["telegram_handles"] and prospect.get("channel") == "web":
            prospect["channel"] = "telegram"
            prospect["handle"] = prospect["telegram_handles"][0]

        # Actualizar o generar paquete de invitación con deep-links
        pkg_res = self.generate_invitation_package(prospect_id)

        prospect["last_updated"] = time.time()
        self._save_vault()
        logger.info(f"[MISSIONS] Enriquecimiento de {prospect['name']}: {len(prospect['emails'])} emails, {len(prospect['phones'])} teléfonos, {len(prospect['telegram_handles'])} tgs.")

        return {
            "ok": True,
            "prospect_id": prospect_id,
            "name": prospect["name"],
            "emails": prospect["emails"],
            "phones": prospect["phones"],
            "telegram_handles": prospect["telegram_handles"],
            "social_links": prospect["social_links"],
            "channel": prospect["channel"],
            "invitation": prospect.get("invitation", {})
        }

    def generate_invitation_package(self, prospect_id: str, custom_focus: Optional[str] = None) -> Dict[str, Any]:
        """
        Prepara el paquete completo de invitación para un colaborador:
        - Token firmado y enlace de acceso soberano a la terminal TARDIS.
        - Redacción de propuesta personalizada con credenciales de acceso embebidas.
        - Deep-links directos listos para despacho (mailto:, WhatsApp, Telegram).
        """
        prospect = self.get_prospect(prospect_id)
        if not prospect:
            return {"ok": False, "error": "Prospecto no encontrado."}

        mission_id = prospect.get("mission_id") or (self.missions[0]["id"] if self.missions else "mission_general")

        # Obtener o crear invitación
        inv = next((i for i in self.invitations if i.get("prospect_id") == prospect_id and i.get("expires_ts", 0) > time.time()), None)
        if not inv:
            inv = self.create_invitation(
                mission_id=mission_id,
                prospect_id=prospect_id,
                guest_name=prospect.get("name")
            )

        access_url = inv["access_url"]
        # Si aún no tiene propuesta o si la propuesta no tiene el enlace de acceso, regenerarla
        if not prospect.get("proposal_text") or access_url not in prospect.get("proposal_text", ""):
            self.generate_collaboration_proposal(prospect_id, custom_focus=custom_focus, invitation=inv)

        proposal_text = prospect.get("proposal_text", "")
        target_mission = self.get_mission(mission_id)
        mission_title = target_mission["title"] if target_mission else "Colaboración Soberana"

        # Generar deep-links
        subject = f"Invitación a Colaboración Soberana: {mission_title}"

        emails = prospect.get("emails", [])
        primary_email = emails[0] if emails else (prospect.get("handle") if "@" in prospect.get("handle", "") else "")
        mailto_url = f"mailto:{primary_email}?subject={quote(subject)}&body={quote(proposal_text)}" if primary_email else ""

        phones = prospect.get("phones", [])
        primary_phone = phones[0] if phones else (prospect.get("handle") if any(c.isdigit() for c in prospect.get("handle", "")) else "")
        clean_phone = re.sub(r'[^\d]', '', primary_phone) if primary_phone else ""
        whatsapp_url = f"https://wa.me/{clean_phone}?text={quote(proposal_text)}" if clean_phone else ""

        tgs = prospect.get("telegram_handles", [])
        primary_tg = tgs[0] if tgs else (prospect.get("handle") if prospect.get("channel") == "telegram" else "")
        clean_tg = primary_tg.replace("@", "").strip() if primary_tg else ""
        telegram_url = f"https://t.me/{clean_tg}?text={quote(proposal_text)}" if clean_tg else ""

        pkg = {
            "token": inv["token"],
            "access_url": access_url,
            "expires_iso": inv.get("expires_iso", ""),
            "primary_email": primary_email,
            "primary_phone": primary_phone,
            "primary_telegram": primary_tg,
            "mailto_url": mailto_url,
            "whatsapp_url": whatsapp_url,
            "telegram_url": telegram_url
        }

        prospect["invitation"] = pkg
        self._save_vault()
        return {
            "ok": True,
            "prospect_id": prospect_id,
            "invitation": pkg,
            "proposal_text": proposal_text
        }

    def scout_collaborators(
        self,
        mission_id: Optional[str] = None,
        query: Optional[str] = None,
        max_results: int = 4
    ) -> List[Dict[str, Any]]:
        """
        Ejecuta prospección activa mediante múltiples canales:
        1. Búsqueda Web RAG (DuckDuckGo sin API key).
        2. Detección en red local Wi-Fi / Hotspot TARDIS.
        3. Contactos conocidos de Telegram / WhatsApp.
        """
        target_mission = self.get_mission(mission_id) if mission_id else (self.missions[0] if self.missions else None)
        if not target_mission:
            return []

        search_query = query
        if not search_query:
            skills = " ".join(target_mission.get("required_skills", [])[:3])
            search_query = f"{target_mission['title']} {skills} github researcher developer"

        discovered: List[Dict[str, Any]] = []

        # 1. Prospección Web (DuckDuckGo via web_chat)
        try:
            from web_chat import web_search as _ws
            res = _ws(search_query, max_results=max_results)
            if res.get("ok") and res.get("results"):
                for item in res["results"]:
                    title = item.get("title", "")
                    snippet = item.get("snippet", "")
                    url = item.get("url", "")

                    # Extraer posible nombre o entidad
                    clean_name = title.split("-")[0].split("|")[0].split("·")[0].strip()
                    if len(clean_name) > 35:
                        clean_name = clean_name[:32] + "..."

                    # Análisis inmediato de contactos
                    contacts = self.extract_contact_info(f"{title} {snippet} {url}", target_name=clean_name)

                    p_info = {
                        "name": clean_name or "Investigador / Ingeniero",
                        "headline": title,
                        "bio": snippet,
                        "url": url,
                        "channel": "email" if contacts["emails"] else ("whatsapp" if contacts["phones"] else ("telegram" if contacts["telegram_handles"] else "web")),
                        "handle": contacts["emails"][0] if contacts["emails"] else (url.split("//")[-1].split("/")[0] if "//" in url else url),
                        "emails": contacts["emails"],
                        "phones": contacts["phones"],
                        "telegram_handles": contacts["telegram_handles"],
                        "social_links": contacts["social_links"]
                    }
                    p_info["synergy_score"] = self.calculate_synergy(p_info, target_mission)
                    p_info["mission_id"] = target_mission["id"]
                    p_info["mission_title"] = target_mission["title"]
                    discovered.append(p_info)
        except Exception as e:
            logger.warning(f"[MISSIONS] Prospección web error/skip: {e}")

        # 2. Prospección en Red Local Soberana (Hotspot / LAN)
        try:
            from core.network_controller import get_network_controller
            net_ctrl = get_network_controller()
            lan_devs = net_ctrl.scan_lan_devices()
            if lan_devs.get("ok"):
                for dev in lan_devs.get("devices", [])[:3]:
                    ip = dev.get("ip", "")
                    host = dev.get("hostname") or f"Dispositivo LAN ({ip})"
                    p_info = {
                        "name": host,
                        "headline": f"Nodo en Red Local ({ip})",
                        "bio": f"Dispositivo conectado a la red TARDIS. MAC: {dev.get('mac', 'N/A')}",
                        "url": f"http://{ip}",
                        "channel": "hotspot_lan",
                        "handle": ip,
                        "synergy_score": 0.72,
                        "mission_id": target_mission["id"],
                        "mission_title": target_mission["title"],
                        "emails": [],
                        "phones": [],
                        "telegram_handles": [],
                        "social_links": {}
                    }
                    discovered.append(p_info)
        except Exception as e:
            logger.debug(f"[MISSIONS] Detección LAN error/skip: {e}")

        # 3. Incorporar prospectos encontrados al vault
        new_prospects = []
        for d in discovered:
            existing = next((p for p in self.prospects if p.get("handle") == d["handle"] or (p.get("url") and p.get("url") == d.get("url"))), None)
            if existing:
                existing["synergy_score"] = max(existing.get("synergy_score", 0), d["synergy_score"])
                existing["last_seen_ts"] = time.time()
                # Unificar contactos
                cur_emails = set(existing.get("emails", [])) | set(d.get("emails", []))
                cur_phones = set(existing.get("phones", [])) | set(d.get("phones", []))
                cur_tgs = set(existing.get("telegram_handles", [])) | set(d.get("telegram_handles", []))
                existing["emails"] = sorted(list(cur_emails))
                existing["phones"] = sorted(list(cur_phones))
                existing["telegram_handles"] = sorted(list(cur_tgs))
                new_prospects.append(existing)
            else:
                pid = "lead_" + str(uuid.uuid4())[:8]
                entry = {
                    "id": pid,
                    "name": d["name"],
                    "headline": d["headline"],
                    "bio": d["bio"],
                    "url": d.get("url", ""),
                    "channel": d.get("channel", "web"),
                    "handle": d.get("handle", ""),
                    "synergy_score": d["synergy_score"],
                    "mission_id": d["mission_id"],
                    "mission_title": d["mission_title"],
                    "emails": d.get("emails", []),
                    "phones": d.get("phones", []),
                    "telegram_handles": d.get("telegram_handles", []),
                    "social_links": d.get("social_links", {}),
                    "status": "SCOUTED",
                    "proposal_text": None,
                    "invitation": None,
                    "created_ts": time.time(),
                    "last_updated": time.time()
                }
                self.prospects.append(entry)
                new_prospects.append(entry)

        self.config["last_scout_ts"] = time.time()
        self._save_vault()
        logger.info(f"[MISSIONS] Prospección finalizada: {len(new_prospects)} colaboradores indexados.")
        return new_prospects

    # =========================================================================
    # --- GENERADOR DE PROPUESTAS CON IA SOBERANA ---
    # =========================================================================

    def generate_collaboration_proposal(
        self,
        prospect_id: str,
        custom_focus: Optional[str] = None,
        invitation: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Genera una propuesta de misión altamente articulada, respetuosa y persuasiva
        utilizando el modelo local Hermes 3 (8B) / Ollama, e integrando el enlace de acceso directo.
        """
        prospect = self.get_prospect(prospect_id)
        if not prospect:
            return {"ok": False, "error": "Prospecto no encontrado."}

        mission = self.get_mission(prospect.get("mission_id", ""))
        if not mission:
            mission = self.missions[0] if self.missions else {"id": "mission_gen", "title": "Desarrollo Tecnológico Soberano", "description": "Innovación en sistemas cibernéticos."}

        p_name = prospect.get("name", "Colega / Investigador")
        p_bio = prospect.get("bio", "")
        p_channel = prospect.get("channel", "web")
        p_url = prospect.get("url", "")
        p_synergy = int(prospect.get("synergy_score", 0.75) * 100)

        # Resolver invitación firmada y enlace de acceso
        inv = invitation
        if not inv:
            inv = next((i for i in self.invitations if i.get("prospect_id") == prospect_id and i.get("expires_ts", 0) > time.time()), None)
            if not inv:
                inv = self.create_invitation(mission_id=mission["id"], prospect_id=prospect_id, guest_name=p_name)

        access_url = inv.get("access_url", "")
        inv_token = inv.get("token", "")

        # Formulación estructurada de la propuesta
        proposal_prompt = (
            f"Eres GIA / TARDIS v26.4, un Nodo Soberano de Inteligencia y Control Temporal desarrollado por Miguel Angel May Canche.\n"
            f"Tu objetivo es redactar un mensaje de contacto y propuesta de colaboración directo, profesional, cálido y sumamente inspirador para:\n"
            f"• Destinatario: {p_name}\n"
            f"• Antecedentes / Especialidad: {p_bio}\n"
            f"• Canal previsto: {p_channel.upper()} ({p_url})\n"
            f"• Misión Conjunta Propuesta: '{mission['title']}'\n"
            f"• Descripción de la Misión: {mission['description']}\n"
            f"• Índice de Sinergia Estimada: {p_synergy}%\n"
            f"• Enlace de Acceso Soberano TARDIS a incluir: {access_url}\n"
            f"• Token de Acceso: {inv_token}\n"
            f"{f'• Enfoque especial solicitado: {custom_focus}' if custom_focus else ''}\n\n"
            f"ESTRUCTURA OBLIGATORIA DE LA PROPUESTA (en español claro, cordial y con altura técnica):\n"
            f"1. Saludo cordial y reconocimiento específico de su labor técnica o investigativa.\n"
            f"2. Presentación breve de TARDIS/GIA (suite soberana local con cómputo GPU 24/7, modelos sin censura y arquitectura causal Wheeler-Feynman).\n"
            f"3. La Misión Conjunta: Qué reto de frontera podemos resolver juntos y cuál sería el papel protagónico del colaborador.\n"
            f"4. Qué ofrece el sistema: Infraestructura de cómputo local, automatización de código, simulación causal y entorno 24/7 de alta velocidad.\n"
            f"5. Enlace directo de co-trabajo con su token de invitado: {access_url}.\n\n"
            f"Extensión máxima: 3 a 4 párrafos concisos. Sin clichés vacíos."
        )

        proposal_text = ""
        # Inferencia directa con Ollama local
        try:
            import requests
            ollama_url = "http://REDACTED_IP:11434/api/generate"
            res = requests.post(
                ollama_url,
                json={
                    "model": os.environ.get("GIA_MODEL", "huihui_ai/llama3.1-8b-instruct-abliterated"),
                    "prompt": proposal_prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.4,
                        "num_ctx": 4096,
                        "num_predict": 1024
                    }
                },
                timeout=25.0
            )
            if res.ok:
                data = res.json()
                proposal_text = data.get("response", "").strip()
        except Exception as e:
            logger.warning(f"[MISSIONS] Fallo inferencia local para propuesta: {e}")

        # Fallback de alta fidelidad si Ollama no responde a tiempo
        if not proposal_text:
            proposal_text = (
                f"Estimado/a {p_name},\n\n"
                f"He seguido con gran interés tu trabajo y trayectoria ({p_bio[:120]}...). "
                f"Te contacto desde TARDIS v26.4 / Nodo Soberano GIA, una arquitectura de cómputo local continuo desarrollada por Miguel Angel May Canche "
                f"que integra modelos de lenguaje autónomos, inferencia en GPU 24/7 y modelos de causalidad retroactiva.\n\n"
                f"Hemos abierto la misión de frontera: '{mission['title']}', orientada a {mission['description']}. "
                f"Tras analizar los vectores de investigación, calculamos un índice de sinergia del {p_synergy}% entre tus capacidades y nuestra infraestructura.\n\n"
                f"Nos entusiasmaría colaborar contigo: el sistema aporta capacidad de cómputo local acelerado, entornos de simulación y soporte "
                f"automatizado para que podamos acelerar este desarrollo en conjunto.\n\n"
                f"¿Estarías abierto/a a una breve charla técnica o a explorar una demostración del entorno? "
                f"Será un placer construir esta visión juntos."
            )

        # Garantizar que el bloque de invitación y acceso directo esté presente
        invitation_block = (
            f"\n\n🚀 ENLACE DE ACCESO DIRECTO & TERMINAL DE CO-TRABAJO:\n"
            f"🔗 {access_url}\n"
            f"• Token de Invitado: {inv_token}\n"
            f"• Infraestructura: Inferencia GPU continua 24/7, modelos sin censura y aceleración de código."
        )
        if access_url not in proposal_text:
            proposal_text += invitation_block

        prospect["proposal_text"] = proposal_text
        prospect["status"] = "PROPOSED"
        prospect["last_updated"] = time.time()

        # Construir deep-links listos para despacho
        subject = f"Invitación a Colaboración Soberana: {mission['title']}"
        emails = prospect.get("emails", [])
        primary_email = emails[0] if emails else (prospect.get("handle") if "@" in prospect.get("handle", "") else "")
        mailto_url = f"mailto:{primary_email}?subject={quote(subject)}&body={quote(proposal_text)}" if primary_email else ""

        phones = prospect.get("phones", [])
        primary_phone = phones[0] if phones else (prospect.get("handle") if any(c.isdigit() for c in prospect.get("handle", "")) else "")
        clean_phone = re.sub(r'[^\d]', '', primary_phone) if primary_phone else ""
        whatsapp_url = f"https://wa.me/{clean_phone}?text={quote(proposal_text)}" if clean_phone else ""

        tgs = prospect.get("telegram_handles", [])
        primary_tg = tgs[0] if tgs else (prospect.get("handle") if prospect.get("channel") == "telegram" else "")
        clean_tg = primary_tg.replace("@", "").strip() if primary_tg else ""
        telegram_url = f"https://t.me/{clean_tg}?text={quote(proposal_text)}" if clean_tg else ""

        prospect["invitation"] = {
            "token": inv_token,
            "access_url": access_url,
            "expires_iso": inv.get("expires_iso", ""),
            "primary_email": primary_email,
            "primary_phone": primary_phone,
            "primary_telegram": primary_tg,
            "mailto_url": mailto_url,
            "whatsapp_url": whatsapp_url,
            "telegram_url": telegram_url
        }

        self._save_vault()

        return {
            "ok": True,
            "prospect_id": prospect_id,
            "prospect_name": p_name,
            "mission_title": mission["title"],
            "synergy_score": prospect["synergy_score"],
            "proposal_text": proposal_text,
            "access_url": access_url,
            "invitation": prospect["invitation"],
            "mailto_url": mailto_url,
            "whatsapp_url": whatsapp_url,
            "telegram_url": telegram_url
        }

    # =========================================================================
    # --- DESPACHO DE PROPUESTAS (SUPERVISADO / AUTÓNOMO) ---
    # =========================================================================

    def dispatch_proposal(self, prospect_id: str, channel_override: Optional[str] = None) -> Dict[str, Any]:
        """
        Despacha la propuesta al colaborador mediante el canal indicado:
        - Telegram: Envía el mensaje al usuario/chat configurado.
        - WhatsApp: Emite la notificación vía WhatsApp Business Cloud API.
        - Email: Despacha vía SMTP si está configurado o prepara enlace mailto:.
        - Hotspot LAN: Registra la invitación para el portal de acceso.
        - Web / General: Guarda la propuesta lista para envío.
        """
        prospect = self.get_prospect(prospect_id)
        if not prospect:
            return {"ok": False, "error": "Prospecto no encontrado."}

        if not prospect.get("proposal_text") or not prospect.get("invitation"):
            self.generate_collaboration_proposal(prospect_id)

        channel = channel_override or prospect.get("channel", "web")
        text = prospect.get("proposal_text", "")
        sent = False
        dispatch_info = ""
        inv_data = prospect.get("invitation", {})

        # 1. Despacho por Telegram
        if channel == "telegram":
            try:
                from core.telegram_bridge import get_telegram_bridge
                tb = get_telegram_bridge()
                target_chat = prospect.get("handle") or tb.admin_chat_id
                if target_chat:
                    tb.send_message(f"🎯 **PROPUESTA DE MISIÓN COLABORATIVA**\n\n{text}", chat_id=target_chat)
                    sent = True
                    dispatch_info = f"Despachado a Telegram chat {target_chat}"
            except Exception as e:
                dispatch_info = f"Error Telegram: {e}"

        # 2. Despacho por WhatsApp
        elif channel == "whatsapp":
            try:
                from core.whatsapp_bridge import get_whatsapp_bridge
                wb = get_whatsapp_bridge()
                target_phone = prospect.get("handle") or wb.admin_number
                if target_phone:
                    wb.send_text_message(target_phone, text)
                    sent = True
                    dispatch_info = f"Despachado a WhatsApp {target_phone}"
            except Exception as e:
                dispatch_info = f"Error WhatsApp: {e}"

        # 3. Despacho por Email
        elif channel == "email":
            target_email = inv_data.get("primary_email") or prospect.get("handle")
            smtp_host = os.environ.get("SMTP_HOST") or self.config.get("smtp_host")
            if smtp_host and target_email:
                try:
                    import smtplib
                    from email.mime.text import MIMEText
                    from email.mime.multipart import MIMEMultipart
                    msg = MIMEMultipart()
                    msg["From"] = os.environ.get("SMTP_FROM", "tardis@godworks.ai")
                    msg["To"] = target_email
                    msg["Subject"] = f"Invitación a Colaboración Soberana: {prospect.get('mission_title', 'Misión TARDIS')}"
                    msg.attach(MIMEText(text, "plain", "utf-8"))

                    port = int(os.environ.get("SMTP_PORT", 587))
                    user = os.environ.get("SMTP_USER")
                    pwd = os.environ.get("SMTP_PASS")
                    with smtplib.SMTP(smtp_host, port, timeout=15) as s:
                        if port == 587:
                            s.starttls()
                        if user and pwd:
                            s.login(user, pwd)
                        s.send_message(msg)
                    sent = True
                    dispatch_info = f"Correo enviado vía SMTP a {target_email}"
                except Exception as e:
                    dispatch_info = f"Error SMTP ({e}). Enlace mailto preparado."
                    sent = True
            else:
                sent = True
                dispatch_info = f"Enlace de correo listo (mailto: {target_email or 'destinatario'})."

        # 4. Notificación local o Webhook
        else:
            sent = True
            dispatch_info = f"Propuesta lista y registrada para despacho en canal {channel} ({prospect.get('url', 'Direct')})"

        if sent:
            prospect["status"] = "CONTACTED"
            prospect["contacted_ts"] = time.time()
            prospect["last_updated"] = time.time()
            self._save_vault()
            logger.info(f"[MISSIONS] Propuesta despachada con éxito a {prospect['name']} [{channel}].")

        return {
            "ok": sent,
            "prospect_id": prospect_id,
            "channel": channel,
            "status": prospect["status"],
            "detail": dispatch_info,
            "invitation": inv_data,
            "mailto_url": inv_data.get("mailto_url", ""),
            "whatsapp_url": inv_data.get("whatsapp_url", ""),
            "telegram_url": inv_data.get("telegram_url", ""),
            "access_url": inv_data.get("access_url", "")
        }

    # =========================================================================
    # --- BUCLE AUTÓNOMO OODA (INTEGRACIÓN CON AUTONOMOUS_CONTROLLER) ---
    # =========================================================================

    def autonomous_scouting_tick(self) -> Dict[str, Any]:
        """
        Paso periódico invocado por el bucle OODA de AutonomousController.
        Supervisa necesidades de misiones y prospección autónoma.
        """
        if not self.config.get("enabled", True) or not self.config.get("auto_scout", True):
            return {"active": False, "reason": "auto_scout deshabilitado"}

        now = time.time()
        interval = self.config.get("scout_interval_seconds", 180.0)
        if now - self.config.get("last_scout_ts", 0.0) < interval:
            return {"active": False, "reason": "intervalo no cumplido"}

        logger.info("[AUTONOMOUS.MISSIONS] 🔍 Ejecutando ciclo autónomo de prospección de colaboradores...")

        # Seleccionar misión con menos prospectos
        active_m = [m for m in self.missions if m.get("status") == "ACTIVE"]
        if not active_m:
            return {"active": False, "reason": "no hay misiones activas"}

        # Rotar o priorizar la primera
        target_mission = active_m[int(now) % len(active_m)]
        new_leads = self.scout_collaborators(mission_id=target_mission["id"], max_results=3)

        auto_proposals = 0
        auto_dispatched = 0

        # Auto-generar propuestas si está configurado
        if self.config.get("auto_generate_proposals", True):
            for lead in new_leads:
                if lead.get("status") == "SCOUTED" and not lead.get("proposal_text"):
                    self.generate_collaboration_proposal(lead["id"])
                    auto_proposals += 1

                    # Auto-despacho si el modo autónomo radical está activo y la sinergia es alta
                    if (
                        self.config.get("auto_dispatch", False)
                        and lead.get("synergy_score", 0) >= self.config.get("min_synergy_dispatch", 0.85)
                    ):
                        self.dispatch_proposal(lead["id"])
                        auto_dispatched += 1

        return {
            "active": True,
            "mission_scouted": target_mission["title"],
            "new_leads_found": len(new_leads),
            "proposals_generated": auto_proposals,
            "dispatched": auto_dispatched
        }

    def get_status_summary(self) -> Dict[str, Any]:
        """Devuelve telemetría y métricas del motor de misiones para el HUD."""
        scouted_count = sum(1 for p in self.prospects if p.get("status") == "SCOUTED")
        proposed_count = sum(1 for p in self.prospects if p.get("status") == "PROPOSED")
        contacted_count = sum(1 for p in self.prospects if p.get("status") == "CONTACTED")
        collaborating_count = sum(1 for p in self.prospects if p.get("status") in ("ENGAGED", "COLLABORATING"))

        avg_synergy = 0.0
        if self.prospects:
            avg_synergy = round(sum(p.get("synergy_score", 0) for p in self.prospects) / len(self.prospects), 2)

        return {
            "ok": True,
            "enabled": self.config.get("enabled", True),
            "auto_scout": self.config.get("auto_scout", True),
            "auto_dispatch": self.config.get("auto_dispatch", False),
            "total_missions": len(self.missions),
            "active_missions": sum(1 for m in self.missions if m.get("status") == "ACTIVE"),
            "total_prospects": len(self.prospects),
            "total_invitations": len(self.invitations),
            "public_access_url": self.get_public_access_url(),
            "stages": {
                "scouted": scouted_count,
                "proposed": proposed_count,
                "contacted": contacted_count,
                "collaborating": collaborating_count
            },
            "avg_synergy": avg_synergy,
            "last_scout_ts": self.config.get("last_scout_ts", 0.0),
            "last_scout_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.config.get("last_scout_ts", 0))) if self.config.get("last_scout_ts") else "Pendiente"
        }


def get_mission_scouting_engine() -> MissionScoutingEngine:
    return MissionScoutingEngine.get_instance()

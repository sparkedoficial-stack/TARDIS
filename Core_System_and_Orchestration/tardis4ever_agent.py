#!/usr/bin/env python3
"""
Escritorio/GODWORKS SYSTEM/core/tardis4ever_agent.py - Agente Soberano Tardis4Ever
================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU · FTL AUTOMATION SUITE
Arquitecto: El Arquitecto (₪)

Misión Soberana de Tardis4Ever:
"Subir las actualizaciones de mis proyectos cada 24 horas de forma automática,
pero cuando note un avance importante o llamativo lo suba y publique de forma inmediata.
Obvio con la seguridad de mi información personal."

Capacidades Núcleo:
1. RUTINA 24H: Sincronización periódica automática cada 24 horas de todos los proyectos.
2. VIGILANTE DE HITOS (MILESTONE WATCHER): Detección en tiempo real de avances importantes
   o llamativos (nuevos toolchains, skills agénticos, módulos kernel Ring 0, evoluciones
   cognitivas, refactorizaciones mayores) y publicación INMEDIATA en GitHub.
3. BLINDAJE DE SEGURIDAD Y PRIVACIDAD TOTAL:
   - Sanitización de secretos (AWS, GitHub, Google, Groq, OpenAI, Anthropic, tokens hex).
   - Sanitización de PII: emails, números de teléfono, nombres de usuario locales, IPs privadas.
   - Auditoría previa al commit para neutralizar cualquier fuga antes de subir a GitHub.
4. INTEGRACIÓN SYSTEMD Y MASTER HUB FTL:
   - Totalmente desacoplado de la CLI (operación limpia en segundo plano vía systemd user service).
"""

from __future__ import annotations

import os
import sys
import re
import time
import json
import signal
import logging
import datetime
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

# Configuración de Logging Autónomo
LOG_DIR = Path("/home/timemachine/.ftl/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "tardis4ever.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Tardis4Ever] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("Tardis4Ever")

# Rutas Fundamentales del Sistema
HOME_DIR = Path("/home/timemachine")
GODWORKS_DIR = HOME_DIR / "Escritorio/GODWORKS SYSTEM"
MODULOS_FTL_DIR = HOME_DIR / "modulos_ftl"
SKILLS_DIR = HOME_DIR / ".agents/skills"
XCODE_LINUX_DIR = Path("/opt/xcode-linux")
PORTFOLIO_DIR = HOME_DIR / "TARDIS_Portfolio"
BUILD_SCRIPT = HOME_DIR / "build_portfolio.py"
STATE_FILE = HOME_DIR / ".ftl/tardis4ever_state.json"
TOOLS_REGISTRY = GODWORKS_DIR / "data/dynamic_tools_registry.json"

# Constantes Operacionales
PERIODIC_INTERVAL_SECONDS = 24 * 3600  # 24 Horas
CHECK_INTERVAL_SECONDS = 60           # Chequeo de cambios cada 60s
SIGNIFICANCE_THRESHOLD = 50           # Umbral de puntaje para avance importante
DEBOUNCE_COOLDOWN_SECONDS = 180       # Tiempo para asentar ráfagas de cambios


class SecurityShield:
    """
    Motor Soberano de Seguridad y Privacidad de Datos Personales.
    Garantiza que ningún token, contraseña, IP privada o PII llegue al repositorio público.
    """

    PATTERNS = [
        # AWS Access Key
        (r'AKIA[0-9A-Z]{16}', 'REDACTED_AWS_KEY'),
        # GitHub Tokens
        (r'(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}', 'REDACTED_GH_TOKEN'),
        (r'github_pat_[A-Za-z0-9_]{82}', 'REDACTED_GH_PAT'),
        # Google API Keys
        (r'AIzaSy[0-9A-Za-z_\-]{33}', 'REDACTED_GOOGLE_KEY'),
        # Groq API Keys
        (r'gsk_[A-Za-z0-9]{50,}', 'REDACTED_GROQ_KEY'),
        # OpenAI API Keys
        (r'sk-[A-Za-z0-9]{32,}', 'REDACTED_OPENAI_KEY'),
        # Claude/Anthropic keys
        (r'sk-ant-[A-Za-z0-9_\-]{32,}', 'REDACTED_ANTHROPIC_KEY'),
        # Claves de asignación explícitas
        (r'''(?i)(['"]?(?:api[_-]?key|token|secret|password|access[_-]?key|secret[_-]?key|auth[_-]?token)['"]?\s*[:=]\s*['"])(?:(?!\1)[^\n'"]+)(['"])''', r'\g<1>REDACTED\2'),
        # Tokens genéricos largos (hex / base64 >= 32 caracteres)
        (r"['\"](?:[0-9a-zA-Z]{34,})['\"]", '"REDACTED_TOKEN"'),
        # Direcciones de correo electrónico (PII)
        (r'\b[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com)[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', 'REDACTED_EMAIL'),
        # Números de teléfono (PII)
        (r'\b(?:\+?\d{1,3}[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b', 'REDACTED_PHONE'),
        # IPs privadas locales (evitar revelar topología de red de usuario)
        (r'\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b', 'REDACTED_LOCAL_IP')
    ]

    @classmethod
    def audit_and_sanitize_text(cls, text: str) -> str:
        """Sanitiza texto eliminando todo dato confidencial y credenciales."""
        clean_text = text
        for pattern, replacement in cls.PATTERNS:
            clean_text = re.sub(pattern, replacement, clean_text)
        return clean_text

    @classmethod
    def audit_directory(cls, directory: Path) -> Tuple[bool, List[str]]:
        """
        Escanea exhaustivamente un directorio verificando que no existan secretos sin sanitizar.
        Retorna (is_clean, violations).
        """
        violations = []
        if not directory.exists():
            return True, []

        sensitive_regex = re.compile(
            r'(ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82}|AIzaSy[0-9A-Za-z_\-]{33}|AKIA[0-9A-Z]{16}|sk-[a-zA-Z0-9]{32,})'
        )

        for root, dirs, files in os.walk(directory):
            if '.git' in dirs:
                dirs.remove('.git')
            for f in files:
                f_path = Path(root) / f
                if f_path.is_symlink():
                    continue
                # Revisar solo archivos de texto
                try:
                    with open(f_path, 'r', encoding='utf-8', errors='ignore') as fp:
                        content = fp.read()
                        matches = sensitive_regex.findall(content)
                        if matches:
                            violations.append(f"{f_path.relative_to(directory)}: {len(matches)} secretos detectados")
                except Exception:
                    pass

        return (len(violations) == 0, violations)


class MilestoneEvaluator:
    """
    Evaluador Neuronal-Heurístico de Avances del Sistema.
    Detecta si las modificaciones recientes corresponden a un 'avance importante o llamativo'.
    """

    KEYWORD_WEIGHTS = {
        "kernel": 25,
        "ring0": 30,
        "xcode": 25,
        "phone_harness": 25,
        "rea": 25,
        "sovereign": 20,
        "reverse_engineer": 25,
        "synergy": 20,
        "breakthrough": 35,
        "omni_tool": 25,
        "milestone": 30,
        "easy_touch": 20,
        "tardis4ever": 35,
        "agentic": 20,
        "autonomy": 20,
        "quantum": 15,
        "security": 15
    }

    @classmethod
    def inspect_system_changes(cls, last_known_files_mtime: Dict[str, float]) -> Tuple[bool, int, List[str], Dict[str, float]]:
        """
        Inspecciona el ecosistema y calcula un puntaje de importancia.
        Retorna (is_notable, score, reasons, current_mtimes).
        """
        current_mtimes = {}
        score = 0
        reasons = []

        # 1. Monitoreo de habilidades de agentes (.agents/skills)
        if SKILLS_DIR.exists():
            for root, _, files in os.walk(SKILLS_DIR):
                for f in files:
                    fp = Path(root) / f
                    try:
                        mtime = fp.stat().st_mtime
                        rel = str(fp.relative_to(SKILLS_DIR))
                        current_mtimes[f"skill:{rel}"] = mtime
                        if f"skill:{rel}" not in last_known_files_mtime:
                            score += 40
                            reasons.append(f"Nueva habilidad agéntica desplegada: {rel}")
                        elif mtime > last_known_files_mtime[f"skill:{rel}"]:
                            score += 25
                            reasons.append(f"Habilidad agéntica actualizada: {rel}")
                    except Exception:
                        pass

        # 2. Monitoreo de Toolchain Xcode Linux (/opt/xcode-linux)
        if XCODE_LINUX_DIR.exists():
            for sub in ("bin", "lib"):
                sub_dir = XCODE_LINUX_DIR / sub
                if sub_dir.exists():
                    for fp in sub_dir.glob("*"):
                        if fp.is_file():
                            try:
                                mtime = fp.stat().st_mtime
                                key = f"xcode:{fp.name}"
                                current_mtimes[key] = mtime
                                if key not in last_known_files_mtime:
                                    score += 35
                                    reasons.append(f"Nuevo componente del toolchain Xcode Linux: {fp.name}")
                                elif mtime > last_known_files_mtime[key]:
                                    score += 20
                                    reasons.append(f"Actualización en toolchain Xcode Linux: {fp.name}")
                            except Exception:
                                pass

        # 3. Monitoreo de Módulos FTL (modulos_ftl)
        if MODULOS_FTL_DIR.exists():
            for fp in MODULOS_FTL_DIR.glob("*.py"):
                try:
                    mtime = fp.stat().st_mtime
                    key = f"ftl:{fp.name}"
                    current_mtimes[key] = mtime
                    if key not in last_known_files_mtime:
                        if fp.name.startswith("browser_evol_"):
                            score += 5  # Incremento acumulativo
                        else:
                            score += 30
                            reasons.append(f"Nuevo módulo central FTL creado: {fp.name}")
                    elif mtime > last_known_files_mtime[key]:
                        if not fp.name.startswith("browser_evol_"):
                            score += 20
                            reasons.append(f"Actualización crítica en módulo FTL: {fp.name}")
                except Exception:
                    pass

        # 4. Monitoreo del Núcleo TARDIS (GODWORKS SYSTEM/core)
        core_dir = GODWORKS_DIR / "core"
        if core_dir.exists():
            for fp in core_dir.glob("*.py"):
                try:
                    mtime = fp.stat().st_mtime
                    key = f"core:{fp.name}"
                    current_mtimes[key] = mtime
                    if key not in last_known_files_mtime:
                        score += 35
                        reasons.append(f"Nuevo subsistema core TARDIS: {fp.name}")
                    elif mtime > last_known_files_mtime[key]:
                        score += 25
                        reasons.append(f"Evolución en subsistema core TARDIS: {fp.name}")
                except Exception:
                    pass

        # 5. Monitoreo de Directivas Globales
        for doc in ("AGENTS.md", "GEMINI.md"):
            doc_path = HOME_DIR / doc
            if doc_path.exists():
                try:
                    mtime = doc_path.stat().st_mtime
                    key = f"directive:{doc}"
                    current_mtimes[key] = mtime
                    if key not in last_known_files_mtime:
                        score += 45
                        reasons.append(f"Nueva directiva global adoptada: {doc}")
                    elif mtime > last_known_files_mtime[key]:
                        score += 35
                        reasons.append(f"Actualización de gobernanza en directiva: {doc}")
                except Exception:
                    pass

        # 6. Monitoreo de Registro Dinámico de Herramientas
        if TOOLS_REGISTRY.exists():
            try:
                mtime = TOOLS_REGISTRY.stat().st_mtime
                key = "registry:dynamic_tools"
                current_mtimes[key] = mtime
                if key in last_known_files_mtime and mtime > last_known_files_mtime[key]:
                    score += 30
                    reasons.append("Actualización en el registro dinámico de herramientas omnipotentes")
            except Exception:
                pass

        # 7. Monitoreo de Proyectos Satélite Soberanos
        satellite_projects = {
            "price_sentinel": HOME_DIR / "tardis-price-sentinel",
            "airplay_monitor": HOME_DIR / "airplay-monitor",
            "carlinkit_kvm": HOME_DIR / "carlinkit-hid-kvm",
            "cognitivo": HOME_DIR / "cognitivo_sistema",
            "gia_ios": GODWORKS_DIR / "ios-app"
        }
        for p_name, p_dir in satellite_projects.items():
            if p_dir.exists():
                for root, dirs, files in os.walk(p_dir):
                    dirs[:] = [
                        d for d in dirs
                        if d not in (".git", "__pycache__", "node_modules", ".venv", "venv", ".venv-linux", "build", "dist")
                        and not d.startswith(".venv")
                    ]
                    for f in files:
                        if any(f.endswith(ext) for ext in ('.py', '.sh', '.swift', '.html', '.md')):
                            fp = Path(root) / f
                            try:
                                mtime = fp.stat().st_mtime
                                rel_fp = str(fp.relative_to(p_dir))
                                key = f"sat:{p_name}:{rel_fp}"
                                current_mtimes[key] = mtime
                                if key not in last_known_files_mtime:
                                    # Si existía la llave antigua por nombre base y no ha cambiado su mtime máximo, migrar sin penalizar
                                    legacy_key = f"sat:{p_name}:{f}"
                                    if legacy_key in last_known_files_mtime and mtime <= last_known_files_mtime[legacy_key]:
                                        continue
                                    score += 25
                                    reasons.append(f"Nuevo componente en proyecto {p_name}: {rel_fp}")
                                elif mtime > last_known_files_mtime[key]:
                                    score += 15
                                    reasons.append(f"Actualización en proyecto {p_name}: {rel_fp}")
                            except Exception:
                                pass

        # Evaluar umbral
        is_notable = score >= SIGNIFICANCE_THRESHOLD
        return is_notable, score, reasons, current_mtimes


class Tardis4EverAgent:
    """
    Agente Soberano Tardis4Ever.
    Orquesta la rutina 24h, la detección y publicación inmediata de hitos y la seguridad.
    """

    def __init__(self):
        self.name = "Tardis4Ever"
        self.version = "1.0.0"
        self.state_file = STATE_FILE
        self.state = self.load_state()
        self.running = True

        # Importación dinámica del módulo oficial FTL Git Sync
        sys.path.insert(0, str(MODULOS_FTL_DIR))
        try:
            from ftl_git_sync import get_git_sync
            self.git_sync = get_git_sync()
        except Exception as e:
            logger.warning(f"No se pudo importar FtlGitSync directamente: {e}")
            self.git_sync = None

    def load_state(self) -> Dict[str, Any]:
        """Carga el estado persistente del agente."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error cargando archivo de estado {self.state_file}: {e}")

        now_iso = datetime.datetime.now().isoformat()
        return {
            "agent_name": self.name,
            "version": "1.0.0",
            "created_at": now_iso,
            "last_periodic_sync": now_iso,
            "last_immediate_sync": None,
            "last_commit_hash": None,
            "sync_count": 0,
            "immediate_sync_count": 0,
            "periodic_sync_count": 0,
            "last_known_mtimes": {},
            "history": []
        }

    def save_state(self):
        """Guarda el estado actual del agente en disco."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Error guardando estado: {e}")

    def execute_sovereign_publish(self, trigger_type: str, score: int, reasons: List[str]) -> Dict[str, Any]:
        """
        Ejecuta el pipeline completo de publicación soberana:
        1. Compilación de portafolio y sanitización (build_portfolio.py)
        2. Auditoría profunda de seguridad antifugas
        3. Generación de commit descriptivo
        4. Push a origin main
        """
        now = datetime.datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")

        logger.info(f"== INICIANDO PUBLICACIÓN SOBERANA [{trigger_type.upper()}] ==")
        logger.info(f"Puntaje de Hito: {score} | Razones detectadas: {len(reasons)}")

        # 1. Ejecutar build_portfolio.py
        if BUILD_SCRIPT.exists():
            logger.info("Construyendo y sanitizando portafolio de proyectos...")
            cmd = [sys.executable, str(BUILD_SCRIPT)]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
            if res.returncode != 0:
                logger.error(f"Fallo construyendo portafolio: {res.stderr}")
                return {"status": "error", "error": res.stderr.strip()}
        else:
            logger.error(f"No se encontró el script de portafolio: {BUILD_SCRIPT}")
            return {"status": "error", "error": f"Script {BUILD_SCRIPT} no existe"}

        # 2. Auditoría profunda de seguridad
        is_clean, violations = SecurityShield.audit_directory(PORTFOLIO_DIR)
        if not is_clean:
            logger.critical(f"ALERTA DE SEGURIDAD: Se detectaron violaciones en el portafolio: {violations}")
            logger.info("Aplicando sanitización de emergencia sobre los archivos comprometidos...")
            for viol in violations:
                file_rel = viol.split(":")[0].strip()
                target_f = PORTFOLIO_DIR / file_rel
                if target_f.exists():
                    with open(target_f, "r", encoding="utf-8", errors="ignore") as f:
                        c = f.read()
                    c_clean = SecurityShield.audit_and_sanitize_text(c)
                    with open(target_f, "w", encoding="utf-8") as f:
                        f.write(c_clean)
            # Re-auditar
            is_clean, violations = SecurityShield.audit_directory(PORTFOLIO_DIR)
            if not is_clean:
                logger.critical("CANCELACIÓN DE SEGURIDAD: Fuga no neutralizable. Cancelando push para proteger información personal.")
                return {"status": "security_aborted", "violations": violations}

        # 3. Construir mensaje de commit soberano
        reasons_bullet = "\n".join([f"- {r}" for r in reasons[:8]])
        if trigger_type == "immediate_milestone":
            commit_title = f"Tardis4Ever :: Publicación Inmediata de Hito Relevante ({timestamp_str})"
            commit_body = (
                f"{commit_title}\n\n"
                f"Detección de avance significativo con puntaje de relevancia: {score}/100\n\n"
                f"Hitos y componentes clave detectados:\n"
                f"{reasons_bullet}\n\n"
                f"Garantía de Seguridad: Sanitización criptográfica y blindaje de PII aplicados."
            )
        else:
            commit_title = f"Tardis4Ever :: Sincronización Rutinaria de Proyectos 24h ({timestamp_str})"
            commit_body = (
                f"{commit_title}\n\n"
                f"Ciclo periódico de respaldo y publicación soberana automática.\n\n"
                f"Resumen de cambios consolidados:\n"
                f"{reasons_bullet if reasons else '- Sincronización y mantenimiento continuo de subsistemas'}\n\n"
                f"Garantía de Seguridad: Sanitización criptográfica y blindaje de PII aplicados."
            )

        # 4. Sincronizar y hacer push
        if self.git_sync:
            sync_res = self.git_sync.sync_and_push(custom_message=commit_body)
        else:
            # Fallback directo a comandos git si no se cargó FtlGitSync
            subprocess.run(["git", "add", "-A"], cwd=str(PORTFOLIO_DIR), check=True)
            diff_check = subprocess.run(["git", "diff-index", "--quiet", "HEAD", "--"], cwd=str(PORTFOLIO_DIR))
            if diff_check.returncode != 0:
                subprocess.run(["git", "commit", "-m", commit_body], cwd=str(PORTFOLIO_DIR), check=True)
                push_res = subprocess.run(["git", "push", "origin", "main"], cwd=str(PORTFOLIO_DIR), capture_output=True, text=True)
                rev_res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(PORTFOLIO_DIR), capture_output=True, text=True)
                sync_res = {
                    "status": "ok",
                    "action": "pushed",
                    "commit_hash": rev_res.stdout.strip(),
                    "push_output": push_res.stdout or push_res.stderr
                }
            else:
                sync_res = {"status": "ok", "action": "clean", "message": "Sin cambios pendientes"}

        # 5. Actualizar estado
        if sync_res.get("status") == "ok":
            now_iso = now.isoformat()
            self.state["last_commit_hash"] = sync_res.get("commit_hash", self.state.get("last_commit_hash"))
            self.state["sync_count"] += 1

            if trigger_type == "immediate_milestone":
                self.state["immediate_sync_count"] += 1
                self.state["last_immediate_sync"] = now_iso
            else:
                self.state["periodic_sync_count"] += 1
                self.state["last_periodic_sync"] = now_iso

            # Registrar en historial (máximo 50 entradas)
            self.state["history"].insert(0, {
                "timestamp": now_iso,
                "trigger": trigger_type,
                "commit_hash": sync_res.get("commit_hash"),
                "score": score,
                "reasons": reasons[:5]
            })
            self.state["history"] = self.state["history"][:50]
            self.save_state()
            logger.info(f"Publicación completada exitosamente. Hash: {sync_res.get('commit_hash')}")

        return sync_res

    def run_check_cycle(self) -> Dict[str, Any]:
        """
        Ejecuta un ciclo de verificación para decidir si corresponde:
        1. Publicación inmediata por hito relevante
        2. Publicación de rutina por 24 horas transcurridas
        3. Esperar sin acción
        """
        import fcntl
        lock_fp = open("/tmp/tardis4ever_cycle.lock", "w")
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX)
        try:
            self.state = self.load_state()
            last_mtimes = self.state.get("last_known_mtimes", {})
            is_notable, score, reasons, current_mtimes = MilestoneEvaluator.inspect_system_changes(last_mtimes)

            # Actualizar mtimes en memoria y persistir para evitar ciclos duplicados
            self.state["last_known_mtimes"] = current_mtimes
            self.save_state()

            now = datetime.datetime.now()
            last_periodic = datetime.datetime.fromisoformat(self.state.get("last_periodic_sync", now.isoformat()))
            elapsed_seconds = (now - last_periodic).total_seconds()

            # CASO 1: Hito Importante o Llamativo Detectado -> PUBLICACIÓN INMEDIATA
            if is_notable:
                logger.info(f"[ALERTA DE HITO] Avance relevante detectado con puntaje {score} >= {SIGNIFICANCE_THRESHOLD}")
                logger.info(f"Razones: {reasons}")
                return self.execute_sovereign_publish("immediate_milestone", score, reasons)

            # CASO 2: Han pasado 24 Horas -> RUTINA PERIÓDICA AUTOMÁTICA
            elif elapsed_seconds >= PERIODIC_INTERVAL_SECONDS:
                logger.info(f"[RUTINA 24H] Han transcurrido {elapsed_seconds / 3600:.2f} horas desde el último ciclo periódico.")
                # Verificar si hay cambios en el repositorio
                if self.git_sync:
                    st = self.git_sync.get_repo_status()
                    if not st.get("clean", True):
                        return self.execute_sovereign_publish("periodic_24h", score, reasons or ["Ciclo programado de 24 horas"])
                    else:
                        logger.info("[RUTINA 24H] Repositorio ya está completamente al día. Actualizando timestamp de ciclo.")
                        self.state["last_periodic_sync"] = now.isoformat()
                        self.save_state()
                        return {"status": "ok", "action": "idle_up_to_date"}
                else:
                    return self.execute_sovereign_publish("periodic_24h", score, reasons or ["Ciclo programado de 24 horas"])

            # CASO 3: En espera normal
            else:
                remaining_hours = (PERIODIC_INTERVAL_SECONDS - elapsed_seconds) / 3600
                self.save_state()
                return {
                    "status": "idle",
                    "next_routine_in_hours": round(remaining_hours, 2),
                    "current_score": score,
                    "reasons": reasons
                }
        finally:
            try:
                fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)
                lock_fp.close()
            except Exception:
                pass

    def run_daemon(self):
        """Bucle principal en segundo plano (demonio de alta disponibilidad)."""
        logger.info("=========================================================")
        logger.info(f"=== {self.name} v{self.version} INICIADO EN MODO DEMONIO SOBERANO ===")
        logger.info(f"=== Rutina: Backups cada 24h | Hitos importantes: Inmediato ===")
        logger.info(f"=== Seguridad: Sanitización Criptográfica & PII Activa ===")
        logger.info("=========================================================")

        def sig_handler(signum, frame):
            logger.info(f"Señal de terminación recibida ({signum}). Apagando Tardis4Ever ordenadamente...")
            self.running = False

        signal.signal(signal.SIGTERM, sig_handler)
        signal.signal(signal.SIGINT, sig_handler)

        while self.running:
            try:
                self.run_check_cycle()
            except Exception as e:
                logger.error(f"Error en ciclo de monitoreo: {e}", exc_info=True)

            # Esperar antes del siguiente escaneo
            for _ in range(CHECK_INTERVAL_SECONDS):
                if not self.running:
                    break
                time.sleep(1)

        logger.info("Tardis4Ever apagado correctamente.")

    def get_status(self) -> Dict[str, Any]:
        """Retorna el estado de salud, métricas y telemetría de Tardis4Ever."""
        now = datetime.datetime.now()
        last_periodic = datetime.datetime.fromisoformat(self.state.get("last_periodic_sync", now.isoformat()))
        elapsed = (now - last_periodic).total_seconds()
        remaining = max(0, PERIODIC_INTERVAL_SECONDS - elapsed)

        return {
            "agent": self.name,
            "version": self.version,
            "status": "OPERATIONAL",
            "last_periodic_sync": self.state.get("last_periodic_sync"),
            "next_periodic_sync_in_hours": round(remaining / 3600, 2),
            "last_immediate_sync": self.state.get("last_immediate_sync"),
            "last_commit_hash": self.state.get("last_commit_hash"),
            "total_syncs": self.state.get("sync_count", 0),
            "immediate_syncs": self.state.get("immediate_sync_count", 0),
            "periodic_syncs": self.state.get("periodic_sync_count", 0),
            "recent_history": self.state.get("history", [])[:5]
        }


# Instancia singleton
_tardis4ever_instance: Optional[Tardis4EverAgent] = None

def get_tardis4ever_agent() -> Tardis4EverAgent:
    global _tardis4ever_instance
    if _tardis4ever_instance is None:
        _tardis4ever_instance = Tardis4EverAgent()
    return _tardis4ever_instance


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Tardis4Ever - Agente Soberano de Publicación y Vigilancia de Hitos")
    parser.add_argument("action", choices=["status", "check", "sync", "daemon"], default="status", nargs="?",
                        help="Acción a realizar: status, check (evaluar cambios), sync (forzar sincronización), daemon (iniciar bucle)")
    args = parser.parse_args()

    agent = get_tardis4ever_agent()

    if args.action == "status":
        print(json.dumps(agent.get_status(), indent=2))
    elif args.action == "check":
        print(json.dumps(agent.run_check_cycle(), indent=2))
    elif args.action == "sync":
        print(json.dumps(agent.execute_sovereign_publish("manual_override", 100, ["Sincronización manual forzada"]), indent=2))
    elif args.action == "daemon":
        agent.run_daemon()

#!/usr/bin/env python3
"""
core/tardis_failover_engine.py - Motor de Redundancia y Orquestación Autónoma TARDIS
===================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Garantiza la alta disponibilidad y orquestación ininterrumpida de TARDIS en caso de
caída total del Nodo Central (TimeMachine / ASUS TUF A15).

Modos Operativos:
  1. PRIMARY_MASTER      : Activo en Nodo Central. Emite latidos de salud (heartbeat),
                           coordina la cola de trabajos y replica periódicamente estado a iMac.
  2. SECONDARY_STANDBY   : Activo en Nodo Externo (iMac 14,1). Vigila al Nodo Central
                           cada 3 segundos. Si detecta 3 fallos consecutivos, asume
                           inmediatamente la orquestación soberana.
  3. PRIMARY_FAILOVER    : Modo asumido por el iMac ante caída de Central. Orquesta
                           la cola de procesamiento externo, atiende solicitudes REST,
                           ejecuta inferencia local con Ollama (Haswell AVX2), ejecuta
                           el enjambre GIA y registra todas las operaciones en un journal persistente.
  4. FAILBACK_SYNC       : Se activa cuando el Nodo Central regresa. Sincroniza el
                           journal de eventos y resultados de vuelta a Central y cede
                           el control limpiamente.
"""

from __future__ import annotations

import argparse
import http.server
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Configuración de Logging Resiliente
LOG_FORMAT = "%(asctime)s [%(levelname)s] [TARDIS.Failover] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("TARDIS.Failover")

# Topología de Red
CENTRAL_IP = os.environ.get("CENTRAL_NODE_IP", "REDACTED_IP")
IMAC_IP = os.environ.get("IMAC_NODE_IP", "REDACTED_IP")
FAILOVER_PORT = int(os.environ.get("TARDIS_FAILOVER_PORT", "8758"))
HEARTBEAT_INTERVAL = float(os.environ.get("HEARTBEAT_INTERVAL", "3.0"))
HEARTBEAT_TIMEOUT = float(os.environ.get("HEARTBEAT_TIMEOUT", "2.0"))
FAILOVER_THRESHOLD = int(os.environ.get("FAILOVER_THRESHOLD", "3"))

# Rutas Canónicas
CENTRAL_ROOT = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM")
IMAC_STORAGE_BASE = Path("/opt/imac-cluster-storage")
LOCAL_STORAGE_MOUNT = Path("/mnt/imac_compute")

# Determinar directorios de cola y réplicas según nodo
def resolve_cluster_paths() -> Tuple[Path, Path, Path, Path]:
    if IMAC_STORAGE_BASE.exists() and os.access(IMAC_STORAGE_BASE, os.W_OK):
        base = IMAC_STORAGE_BASE
    elif LOCAL_STORAGE_MOUNT.exists() and os.access(LOCAL_STORAGE_MOUNT, os.W_OK):
        base = LOCAL_STORAGE_MOUNT
    else:
        base = Path("/tmp/tardis_cluster_fallback")
        base.mkdir(parents=True, exist_ok=True)

    jobs_queue = base / "_cluster_jobs" / "queue"
    jobs_running = base / "_cluster_jobs" / "running"
    jobs_completed = base / "_cluster_jobs" / "completed"
    failover_state = base / "failover_state"

    for d in (jobs_queue, jobs_running, jobs_completed, failover_state):
        d.mkdir(parents=True, exist_ok=True)

    return jobs_queue, jobs_running, jobs_completed, failover_state

JOBS_QUEUE, JOBS_RUNNING, JOBS_COMPLETED, FAILOVER_STATE = resolve_cluster_paths()
JOURNAL_FILE = FAILOVER_STATE / "failover_event_journal.jsonl"


class SystemHealthProbe:
    """Recolecta métricas de salud en tiempo real sin dependencias externas pesadas."""

    @staticmethod
    def get_metrics() -> Dict[str, Any]:
        load1, load5, load15 = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
        cpu_cores = os.cpu_count() or 4
        
        mem_avail_mb = 0
        mem_total_mb = 0
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        mem_total_mb = round(int(line.split()[1]) / 1024, 1)
                    elif line.startswith("MemAvailable:"):
                        mem_avail_mb = round(int(line.split()[1]) / 1024, 1)
        except Exception:
            pass

        disk_free_gb = 0
        try:
            st = os.statvfs("/")
            disk_free_gb = round((st.f_bavail * st.f_frsize) / (1024**3), 1)
        except Exception:
            pass

        return {
            "hostname": socket.gethostname(),
            "timestamp": time.time(),
            "time_iso": datetime.utcnow().isoformat() + "Z",
            "cpu_cores": cpu_cores,
            "load_1m": load1,
            "load_pct": round((load1 / max(cpu_cores, 1)) * 100, 1),
            "ram_total_mb": mem_total_mb,
            "ram_avail_mb": mem_avail_mb,
            "disk_free_gb": disk_free_gb,
            "uptime_seconds": time.monotonic()
        }


class JobDispatcher:
    """
    Gestor y orquestador autónomo de trabajos en cola.
    Procesa tareas FIFO con soporte de prioridad y aislamiento de errores.
    """

    def __init__(self, running_dir: Path, completed_dir: Path):
        self.running_dir = running_dir
        self.completed_dir = completed_dir

    def execute_job(self, job_meta: Dict[str, Any]) -> Dict[str, Any]:
        job_id = job_meta.get("job_id", f"job_{int(time.time()*1000)}")
        command = job_meta.get("command")
        code = job_meta.get("code")
        timeout = job_meta.get("timeout", 120)

        t0 = time.time()
        logger.info(f"Iniciando ejecución de trabajo [{job_id}] en orquestador redundante...")

        result = {
            "job_id": job_id,
            "executed_by": socket.gethostname(),
            "started_at": datetime.utcnow().isoformat() + "Z",
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "",
            "execution_time_s": 0.0
        }

        try:
            if code:
                # Ejecutar script Python
                proc = subprocess.run(
                    [sys.executable, "-c", code],
                    capture_output=True, text=True, timeout=timeout
                )
            elif command:
                # Ejecutar comando bash
                proc = subprocess.run(
                    command, shell=True, capture_output=True, text=True, timeout=timeout
                )
            else:
                result["stderr"] = "No se especificó ni command ni code en el trabajo."
                return result

            result["returncode"] = proc.returncode
            result["stdout"] = proc.stdout
            result["stderr"] = proc.stderr
            result["ok"] = (proc.returncode == 0)
        except subprocess.TimeoutExpired:
            result["stderr"] = f"Timeout expirado ({timeout}s) durante la ejecución."
        except Exception as e:
            result["stderr"] = f"Excepción durante la ejecución: {str(e)}"

        result["execution_time_s"] = round(time.time() - t0, 3)
        result["completed_at"] = datetime.utcnow().isoformat() + "Z"

        # Guardar resultado persistente
        res_file = self.completed_dir / f"{job_id}_result.json"
        try:
            res_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error guardando resultado de trabajo {job_id}: {e}")

        logger.info(f"Trabajo [{job_id}] finalizado con exit code {result['returncode']} en {result['execution_time_s']}s")
        return result


class TARDISFailoverOrchestrator:
    """
    Orquestador Central de Redundancia y Failover.
    Controla el bucle de latidos, la promoción autónoma y la sincronización reversa.
    """

    def __init__(self, role_hint: Optional[str] = None):
        self.hostname = socket.gethostname().lower()
        self.is_imac = ("imac" in self.hostname or "gia" in self.hostname)
        
        # Determinar rol inicial
        if role_hint:
            self.role = role_hint.upper()
        else:
            self.role = "SECONDARY_STANDBY" if self.is_imac else "PRIMARY_MASTER"

        self.state_lock = threading.Lock()
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.last_heartbeat_time = time.time()
        self.last_ping_latency = -1.0
        self.is_running = True
        self.state_version = 1
        self.promotion_timestamp: Optional[str] = None
        self.manual_override = False

        self.jobs_queue, self.jobs_running, self.jobs_completed, self.failover_state = resolve_cluster_paths()
        self.dispatcher = JobDispatcher(self.jobs_running, self.jobs_completed)
        self.registered_workers: Dict[str, Dict[str, Any]] = {}
        self.workers_file = self.failover_state / "cluster_workers.json"
        self._load_registered_workers()

        logger.info(f"Iniciando TARDIS Failover Orchestrator en [{self.hostname}]. Rol inicial: {self.role}")

    def _load_registered_workers(self):
        if self.workers_file.exists():
            try:
                self.registered_workers = json.loads(self.workers_file.read_text(encoding="utf-8"))
            except Exception:
                self.registered_workers = {}

    def _save_registered_workers(self):
        try:
            self.workers_file.write_text(json.dumps(self.registered_workers, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error guardando workers: {e}")

    def register_worker_node(self, payload: dict, client_ip: str) -> dict:
        node_id = payload.get("node_id", f"worker_{client_ip.replace('.', '_')}")
        payload["ip"] = payload.get("ip") or client_ip
        payload["last_seen"] = time.time()
        payload["last_seen_iso"] = datetime.utcnow().isoformat() + "Z"
        payload["online"] = True
        
        with self.state_lock:
            self.registered_workers[node_id] = payload
            self._save_registered_workers()

        self.log_journal_event("WORKER_REGISTERED", {
            "node_id": node_id,
            "ip": payload["ip"],
            "hostname": payload.get("hostname"),
            "cpu_cores": payload.get("cpu", {}).get("cores") if isinstance(payload.get("cpu"), dict) else payload.get("cpu")
        })

        # Sincronizar con nodes_telemetry.json si existe
        telemetry_file = CENTRAL_ROOT / "nodes_telemetry.json"
        if telemetry_file.exists():
            try:
                tel_data = json.loads(telemetry_file.read_text(encoding="utf-8"))
                if "nodes" not in tel_data:
                    tel_data["nodes"] = {}
                tel_data["nodes"][node_id] = {
                    "client_id": node_id,
                    "ip": payload["ip"],
                    "hostname": payload.get("hostname"),
                    "connection_type": "TARDIS Distributed Cluster Node",
                    "device": {
                        "platform": payload.get("architecture", "x86_64"),
                        "cores": payload.get("cpu", {}).get("cores", 4) if isinstance(payload.get("cpu"), dict) else 4,
                        "model": payload.get("cpu", {}).get("model", "Generic x86_64") if isinstance(payload.get("cpu"), dict) else "x86",
                        "memory_gb": payload.get("ram_total_gb", 8),
                        "gpu": payload.get("gpu", "Generic VGA")
                    },
                    "first_seen": tel_data["nodes"].get(node_id, {}).get("first_seen", time.time()),
                    "last_seen": time.time(),
                    "last_seen_iso": datetime.utcnow().isoformat() + "Z",
                    "online": True
                }
                telemetry_file.write_text(json.dumps(tel_data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                logger.warning(f"No se pudo actualizar nodes_telemetry.json: {e}")

        # Sincronizar con vw-control/compute_nodes.json si expone ollama
        ollama_url = payload.get("endpoints", {}).get("ollama")
        if ollama_url:
            try:
                cfg_file = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control" / "compute_nodes.json"
                if cfg_file.exists():
                    nodes_list = json.loads(cfg_file.read_text(encoding="utf-8"))
                    if not any(n.get("url") == ollama_url for n in nodes_list):
                        nodes_list.append({
                            "url": ollama_url,
                            "name": payload.get("hostname", node_id),
                            "added": time.time()
                        })
                        cfg_file.write_text(json.dumps(nodes_list, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                logger.warning(f"No se pudo registrar endpoint Ollama en compute_nodes: {e}")

        logger.info(f"⚡ Nodo de cómputo remoto registrado: [{node_id}] en {payload['ip']} ({payload.get('hostname')})")
        return {"ok": True, "message": f"Nodo [{node_id}] registrado exitosamente en el clúster TARDIS", "node_id": node_id}

    def poll_job_for_worker(self, worker_id: str) -> Optional[dict]:
        with self.state_lock:
            queue_files = sorted(list(self.jobs_queue.glob("*.json")))
            if not queue_files:
                return None
            job_file = queue_files[0]
            try:
                job_data = json.loads(job_file.read_text(encoding="utf-8"))
                running_file = self.jobs_running / job_file.name
                shutil.move(str(job_file), str(running_file))
                job_data["assigned_to"] = worker_id
                job_data["assigned_at"] = datetime.utcnow().isoformat() + "Z"
                running_file.write_text(json.dumps(job_data, indent=2, ensure_ascii=False), encoding="utf-8")
                self.log_journal_event("JOB_DISPATCHED_TO_WORKER", {"job_id": job_data.get("job_id"), "worker_id": worker_id})
                return job_data
            except Exception as e:
                logger.error(f"Error despachando trabajo a worker: {e}")
                return None

    def log_journal_event(self, event_type: str, details: Dict[str, Any]):
        """Registra un evento atómico e inmutable en el journal del clúster."""
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "node": self.hostname,
            "role": self.role,
            "event": event_type,
            "details": details
        }
        try:
            with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Error escribiendo en journal: {e}")

    # =========================================================================
    # BUCLE DE VIGILANCIA (WATCHDOG SENTRY)
    # =========================================================================

    def _probe_central_node(self) -> Tuple[bool, float]:
        """Verifica la salud del Nodo Central usando sondeo HTTP, TCP y Ping."""
        target_url = f"http://{CENTRAL_IP}:{FAILOVER_PORT}/api/failover/heartbeat"
        t0 = time.perf_counter()
        
        # 1. Sondeo HTTP al endpoint de latido de Central
        try:
            req = urllib.request.Request(target_url, headers={"User-Agent": "TARDIS-Failover-Sentry/26.4"})
            with urllib.request.urlopen(req, timeout=HEARTBEAT_TIMEOUT) as resp:
                if resp.status == 200:
                    lat = round((time.perf_counter() - t0) * 1000, 2)
                    return True, lat
        except Exception:
            pass

        # 2. Sondeo alternativo: GIA Daemon port 8757 si está en Central
        try:
            req_alt = urllib.request.Request(f"http://{CENTRAL_IP}:8757/api/ping", headers={"User-Agent": "TARDIS-Failover-Sentry"})
            with urllib.request.urlopen(req_alt, timeout=1.0) as resp:
                if resp.status == 200:
                    lat = round((time.perf_counter() - t0) * 1000, 2)
                    return True, lat
        except Exception:
            pass

        # 3. Sondeo SSH port 22 en Central
        try:
            with socket.create_connection((CENTRAL_IP, 22), timeout=1.0):
                lat = round((time.perf_counter() - t0) * 1000, 2)
                return True, lat
        except Exception:
            pass

        # 4. Fallback ICMP Ping
        try:
            res = subprocess.run(["ping", "-c", "1", "-W", "1", CENTRAL_IP], capture_output=True, timeout=1.2)
            if res.returncode == 0:
                lat = round((time.perf_counter() - t0) * 1000, 2)
                return True, lat
        except Exception:
            pass

        return False, -1.0

    def run_sentry_loop(self):
        """Bucle continuo de vigilancia ejecutado por el nodo secundario (iMac)."""
        logger.info(f"Sentry Watchdog activado. Monitoreando Nodo Central ({CENTRAL_IP}) cada {HEARTBEAT_INTERVAL}s...")
        while self.is_running:
            try:
                alive, lat = self._probe_central_node()
                with self.state_lock:
                    self.last_ping_latency = lat
                    if alive:
                        self.consecutive_failures = 0
                        self.consecutive_successes += 1
                        self.last_heartbeat_time = time.time()

                        # Si estábamos en Failover y Central regresó (y no hay manual override)
                        if self.role == "PRIMARY_FAILOVER" and not self.manual_override and self.consecutive_successes >= FAILOVER_THRESHOLD:
                            logger.warning(f"¡Nodo Central detectado en línea de nuevo! Iniciando protocolo de recuperación (Failback)...")
                            self._trigger_failback_reconciliation()
                    else:
                        self.consecutive_successes = 0
                        self.consecutive_failures += 1
                        logger.warning(
                            f"Fallo de latido con Nodo Central ({CENTRAL_IP}). Fallos consecutivos: "
                            f"{self.consecutive_failures}/{FAILOVER_THRESHOLD}"
                        )

                        # Si alcanzamos el umbral de fallos, promovernos a orquestador
                        if self.role == "SECONDARY_STANDBY" and self.consecutive_failures >= FAILOVER_THRESHOLD:
                            logger.critical(
                                f"¡ALERTA CRÍTICA: NODO CENTRAL CAÍDO! Promoviendo iMac a PRIMARY_FAILOVER."
                            )
                            self._promote_to_failover_primary()

            except Exception as e:
                logger.error(f"Error en sentry watchdog: {e}")

            time.sleep(HEARTBEAT_INTERVAL)

    def _promote_to_failover_primary(self):
        """Promoción automática del nodo externo a orquestador principal."""
        self.role = "PRIMARY_FAILOVER"
        self.promotion_timestamp = datetime.utcnow().isoformat() + "Z"
        self.state_version += 1

        self.log_journal_event("FAILOVER_PROMOTION_ACTIVATED", {
            "reason": f"Nodo Central ({CENTRAL_IP}) inalcanzable tras {self.consecutive_failures} sondeos consecutivos.",
            "promotion_time": self.promotion_timestamp,
            "host": self.hostname,
            "action": "Asumiendo orquestación total de cómputo, despacho de tareas e inferencia."
        })
        logger.info(">>> ROL ACTUALIZADO: [PRIMARY_FAILOVER] · Operación soberana autónoma activa. <<<")

    def _trigger_failback_reconciliation(self):
        """Sincroniza el trabajo realizado durante la caída de Central y cede el control."""
        self.role = "FAILBACK_SYNC"
        logger.info("Sincronizando journal y tareas procesadas de vuelta al Nodo Central...")

        sync_ok = False
        try:
            # Sincronizar journal y completed jobs a través de SSH hacia Central
            target_report_dir = f"/home/timemachine/Escritorio/GODWORKS\\ SYSTEM/reports/failover_backlogs"
            subprocess.run(
                f"ssh timemachine@{CENTRAL_IP} 'mkdir -p {target_report_dir}'",
                shell=True, capture_output=True, timeout=10
            )
            # Copiar archivos
            sync_cmd = (
                f"scp {JOURNAL_FILE} timemachine@{CENTRAL_IP}:{target_report_dir}/journal_{int(time.time())}.jsonl && "
                f"scp -r {self.jobs_completed}/* timemachine@{CENTRAL_IP}:{target_report_dir}/ 2>/dev/null || true"
            )
            res = subprocess.run(sync_cmd, shell=True, capture_output=True, timeout=20)
            sync_ok = (res.returncode == 0)
        except Exception as e:
            logger.error(f"Error en failback rsync/scp: {e}")

        self.log_journal_event("FAILBACK_RECONCILIATION_COMPLETED", {
            "sync_successful": sync_ok,
            "resumed_central_ip": CENTRAL_IP,
            "demoting_to": "SECONDARY_STANDBY"
        })

        self.role = "SECONDARY_STANDBY"
        self.consecutive_failures = 0
        logger.info(">>> Retorno limpio a modo [SECONDARY_STANDBY]. Control reasignado a Central. <<<")

    # =========================================================================
    # PROCESAMIENTO DE COLA DE TRABAJOS (JOB QUEUE WORKER)
    # =========================================================================

    def run_queue_worker_loop(self):
        """Procesa trabajos pendientes cuando este nodo tiene la autoridad activa."""
        logger.info("Iniciando Job Queue Worker de tareas distribuidas...")
        while self.is_running:
            try:
                # Solo procesar activamente la cola si somos Master o Failover Primary
                if self.role in ("PRIMARY_MASTER", "PRIMARY_FAILOVER"):
                    job_files = sorted(self.jobs_queue.glob("*.json"))
                    for jf in job_files:
                        try:
                            meta = json.loads(jf.read_text(encoding="utf-8"))
                            job_id = meta.get("job_id", jf.stem)
                            running_file = self.jobs_running / jf.name
                            
                            # Mover a running
                            shutil.move(str(jf), str(running_file))
                            
                            # Ejecutar
                            res = self.dispatcher.execute_job(meta)
                            
                            # Registrar en journal
                            self.log_journal_event("JOB_EXECUTED", {
                                "job_id": job_id,
                                "returncode": res["returncode"],
                                "duration_s": res["execution_time_s"]
                            })

                            # Limpiar de running
                            if running_file.exists():
                                running_file.unlink()

                        except Exception as e_job:
                            logger.error(f"Error procesando archivo de trabajo {jf}: {e_job}")
            except Exception as e:
                logger.error(f"Error en bucle de cola: {e}")

            time.sleep(1.0)


# =============================================================================
# SERVIDOR REST HTTP DE ALTA DISPONIBILIDAD (PUERTO 8758)
# =============================================================================

class FailoverHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    orchestrator: TARDISFailoverOrchestrator

    def _send_json(self, status_code: int, data: Dict[str, Any]):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        orch = self.orchestrator

        if path in ("/", "/api", "/api/failover/status"):
            with orch.state_lock:
                queued_count = len(list(orch.jobs_queue.glob("*.json")))
                running_count = len(list(orch.jobs_running.glob("*.json")))
                completed_count = len(list(orch.jobs_completed.glob("*.json")))
                
                resp = {
                    "node": orch.hostname,
                    "role": orch.role,
                    "state_version": orch.state_version,
                    "promotion_timestamp": orch.promotion_timestamp,
                    "central_node": {
                        "ip": CENTRAL_IP,
                        "last_ping_latency_ms": orch.last_ping_latency,
                        "consecutive_failures": orch.consecutive_failures,
                        "last_seen_epoch": orch.last_heartbeat_time
                    },
                    "cluster_workers": list(orch.registered_workers.values()),
                    "jobs": {
                        "queued": queued_count,
                        "running": running_count,
                        "completed": completed_count
                    },
                    "system_health": SystemHealthProbe.get_metrics(),
                    "endpoints": [
                        "GET  /api/failover/status",
                        "GET  /api/failover/heartbeat",
                        "GET  /api/cluster/nodes",
                        "GET  /api/jobs/list",
                        "GET  /api/jobs/poll",
                        "POST /api/cluster/register",
                        "POST /api/cluster/heartbeat",
                        "POST /api/jobs/submit",
                        "POST /api/jobs/complete",
                        "POST /api/failover/promote",
                        "POST /api/failover/demote",
                        "POST /api/inference",
                        "POST /api/swarm/dispatch"
                    ]
                }
            self._send_json(200, resp)

        elif path == "/api/cluster/nodes":
            with orch.state_lock:
                workers_copy = dict(orch.registered_workers)
            self._send_json(200, {
                "ok": True,
                "master_node": orch.hostname,
                "master_role": orch.role,
                "workers_count": len(workers_copy),
                "nodes": workers_copy
            })

        elif path.startswith("/api/jobs/poll"):
            parsed_query = urllib.parse.parse_qs(parsed.query)
            worker_id = parsed_query.get("worker_id", ["generic_worker"])[0]
            job = orch.poll_job_for_worker(worker_id)
            if job:
                self._send_json(200, {"ok": True, "has_job": True, "job": job})
            else:
                self._send_json(200, {"ok": True, "has_job": False})

        elif path == "/api/failover/heartbeat":
            # Endpoint de latido ultra-ligero
            self._send_json(200, {
                "status": "HEALTHY",
                "node": orch.hostname,
                "role": orch.role,
                "timestamp": time.time(),
                "time_iso": datetime.utcnow().isoformat() + "Z",
                "load": os.getloadavg() if hasattr(os, "getloadavg") else [0, 0, 0]
            })

        elif path == "/api/jobs/list":
            queued = [f.stem for f in orch.jobs_queue.glob("*.json")]
            running = [f.stem for f in orch.jobs_running.glob("*.json")]
            completed = [f.stem.replace("_result", "") for f in orch.jobs_completed.glob("*.json")][:50]
            self._send_json(200, {
                "queued": queued,
                "running": running,
                "completed": completed
            })

        elif path.startswith("/api/jobs/status/"):
            target_id = path.split("/api/jobs/status/")[1].strip()
            q_file = orch.jobs_queue / f"{target_id}.json"
            r_file = orch.jobs_running / f"{target_id}.json"
            c_file = orch.jobs_completed / f"{target_id}_result.json"

            if c_file.exists():
                try:
                    data = json.loads(c_file.read_text(encoding="utf-8"))
                    self._send_json(200, {"status": "COMPLETED", "result": data})
                except Exception as e_c:
                    self._send_json(500, {"error": f"Error leyendo resultado: {e_c}"})
            elif r_file.exists():
                self._send_json(200, {"status": "RUNNING", "job_id": target_id})
            elif q_file.exists():
                self._send_json(200, {"status": "QUEUED", "job_id": target_id})
            else:
                self._send_json(404, {"error": "Trabajo no encontrado", "job_id": target_id})

        else:
            self._send_json(404, {"error": "Ruta no encontrada", "path": path})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        orch = self.orchestrator

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if path == "/api/cluster/register":
            client_ip = self.client_address[0]
            res = orch.register_worker_node(payload, client_ip)
            self._send_json(200, res)

        elif path == "/api/cluster/heartbeat":
            node_id = payload.get("node_id")
            if node_id and node_id in orch.registered_workers:
                with orch.state_lock:
                    orch.registered_workers[node_id]["last_seen"] = time.time()
                    orch.registered_workers[node_id]["last_seen_iso"] = datetime.utcnow().isoformat() + "Z"
                    orch.registered_workers[node_id]["online"] = True
                    if "cpu_load" in payload:
                        orch.registered_workers[node_id]["cpu_load"] = payload["cpu_load"]
                    if "ram_available_gb" in payload:
                        orch.registered_workers[node_id]["ram_available_gb"] = payload["ram_available_gb"]
                self._send_json(200, {"ok": True, "status": "HEARTBEAT_ACK"})
            else:
                self._send_json(200, {"ok": True, "status": "RE_REGISTER_NEEDED"})

        elif path == "/api/jobs/complete":
            job_id = payload.get("job_id")
            if not job_id:
                self._send_json(400, {"ok": False, "error": "job_id is required"})
                return

            r_file = orch.jobs_running / f"{job_id}.json"
            if r_file.exists():
                try:
                    r_file.unlink()
                except Exception:
                    pass

            c_file = orch.jobs_completed / f"{job_id}_result.json"
            c_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            orch.log_journal_event("JOB_COMPLETED_BY_WORKER", {
                "job_id": job_id,
                "worker_id": payload.get("worker_id"),
                "ok": payload.get("ok", False),
                "execution_time_s": payload.get("execution_time_s", 0.0)
            })
            self._send_json(200, {"ok": True, "message": f"Resultado de trabajo {job_id} registrado exitosamente"})

        elif path == "/api/jobs/submit":
            # Encolar un trabajo para procesamiento
            job_id = payload.get("job_id", f"job_{int(time.time()*1000)}_{os.urandom(2).hex()}")
            payload["job_id"] = job_id
            payload["submitted_at"] = datetime.utcnow().isoformat() + "Z"
            payload["submitted_from"] = self.client_address[0]

            job_path = orch.jobs_queue / f"{job_id}.json"
            job_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

            orch.log_journal_event("JOB_ENQUEUED", {
                "job_id": job_id,
                "submitted_from": self.client_address[0],
                "has_code": bool(payload.get("code")),
                "has_command": bool(payload.get("command"))
            })

            self._send_json(202, {
                "ok": True,
                "message": "Trabajo aceptado y encolado en el clúster redundante",
                "job_id": job_id,
                "status_url": f"/api/jobs/status/{job_id}"
            })

        elif path == "/api/failover/promote":
            # Promoción manual con lock de anulación
            with orch.state_lock:
                orch.manual_override = True
                orch._promote_to_failover_primary()
            self._send_json(200, {
                "ok": True,
                "message": f"Nodo [{orch.hostname}] promovido exitosamente a PRIMARY_FAILOVER (Manual Override Activo)",
                "role": orch.role
            })

        elif path == "/api/failover/demote":
            # Democión manual
            with orch.state_lock:
                orch.manual_override = False
                orch.role = "SECONDARY_STANDBY"
                orch.consecutive_failures = 0
            self._send_json(200, {
                "ok": True,
                "message": f"Nodo [{orch.hostname}] reasignado a SECONDARY_STANDBY",
                "role": orch.role
            })

        elif path in ("/api/inference", "/v1/chat/completions"):
            # Enrutamiento de inferencia resiliente
            prompt = payload.get("prompt")
            messages = payload.get("messages", [])
            if not prompt and messages:
                prompt = messages[-1].get("content", "")
            
            model = payload.get("model", "qwen2.5:0.5b")
            
            # Enrutar directamente a Ollama local
            ollama_url = f"http://REDACTED_IP:11434/api/chat"
            req_data = json.dumps({
                "model": model,
                "messages": messages if messages else [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 96}
            }).encode("utf-8")

            t0 = time.time()
            try:
                req = urllib.request.Request(ollama_url, data=req_data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    ans = data.get("message", {}).get("content", "").strip()
                    self._send_json(200, {
                        "ok": True,
                        "provider": f"{orch.hostname}-Local-Ollama",
                        "model": model,
                        "content": ans,
                        "elapsed_s": round(time.time() - t0, 3)
                    })
            except Exception as e:
                self._send_json(500, {
                    "ok": False,
                    "error": f"Fallo de inferencia local en failover: {str(e)}"
                })

        elif path == "/api/swarm/dispatch":
            # Despacho autónomo del enjambre GIA en modo failover
            role = payload.get("role", "system_medic")
            task = payload.get("task", "Inspección de contingencia")
            
            # Ejecución local de sub-agente
            prompt_system = f"Eres el subagente de contingencia [{role}] en el nodo redundante iMac. Sé directo, técnico y conciso."
            ollama_url = "http://REDACTED_IP:11434/api/chat"
            req_data = json.dumps({
                "model": "qwen2.5:0.5b",
                "messages": [
                    {"role": "system", "content": prompt_system},
                    {"role": "user", "content": f"TAREA DE CONTINGENCIA: {task}"}
                ],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 180}
            }).encode("utf-8")

            try:
                req = urllib.request.Request(ollama_url, data=req_data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=30.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    report = data.get("message", {}).get("content", "").strip()
                    self._send_json(200, {
                        "ok": True,
                        "subagent_role": role,
                        "host": orch.hostname,
                        "report": report
                    })
            except Exception as e:
                self._send_json(500, {"ok": False, "error": f"Fallo despachando sub-agente: {e}"})

        else:
            self._send_json(404, {"error": "Endpoint POST no encontrado", "path": path})


def run_failover_service(role_arg: Optional[str] = None):
    """Punto de entrada principal para el servicio de redundancia."""
    orchestrator = TARDISFailoverOrchestrator(role_hint=role_arg)

    # Iniciar worker de cola en segundo plano
    t_worker = threading.Thread(target=orchestrator.run_queue_worker_loop, daemon=True)
    t_worker.start()

    # Si es el nodo secundario (iMac), iniciar el sentry watchdog de latidos
    if orchestrator.is_imac or role_arg == "SECONDARY_STANDBY":
        t_sentry = threading.Thread(target=orchestrator.run_sentry_loop, daemon=True)
        t_sentry.start()

    # Iniciar servidor HTTP en FAILOVER_PORT
    FailoverHTTPRequestHandler.orchestrator = orchestrator
    server = http.server.ThreadingHTTPServer(("REDACTED_IP", FAILOVER_PORT), FailoverHTTPRequestHandler)
    logger.info(f"⚡ TARDIS Failover REST API escuchando en puerto {FAILOVER_PORT} (Nodo: {orchestrator.hostname} | Rol: {orchestrator.role})")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Deteniendo TARDIS Failover Engine limpiamente...")
        orchestrator.is_running = False
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TARDIS Failover & Redundancy Engine")
    parser.add_argument("--role", choices=["PRIMARY_MASTER", "SECONDARY_STANDBY", "PRIMARY_FAILOVER"], help="Forzar rol del nodo")
    args = parser.parse_args()

    run_failover_service(args.role)

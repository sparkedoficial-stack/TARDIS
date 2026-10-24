"""
gia_swarm.py - Enjambre de Sub-Agentes Autónomos Especializados
================================================================

Permite al agente orquestador GIA delegar subtareas complejas a sub-agentes
con roles, herramientas y prompts de sistema altamente especializados.

Roles del Enjambre:
  1. code_auditor    : Inspección de sintaxis, seguridad, dependencias y refactorización.
  2. web_researcher  : Búsqueda profunda, lectura de URLs y síntesis web.
  3. rf_analyst      : Análisis de telemetría espectral, radar pasivo y perturbaciones RF.
  4. vision_scout    : Inspección visual de pantalla/cámara mediante VLM y OCR.
  5. system_medic    : Diagnóstico de procesos, recursos de memoria, disco y salud del SO.

Arquitecto: Miguel Angel May Canche  ·  GIA-V26-SOVEREIGN
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

import httpx

_raw_ollama = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
OLLAMA_URL = _raw_ollama.rstrip("/")
IMAC_OLLAMA_URL = os.environ.get("IMAC_OLLAMA_HOST", "http://REDACTED_IP:11434").strip().rstrip("/")

try:
    import gia_sovereign_engine as _gse
    DEFAULT_MODEL = _gse.get_engine().resolve_model()
except Exception:
    DEFAULT_MODEL = os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU")

SPECIALIST_PROMPTS = {
    "cluster_compute": (
        "Eres el Sub-Agente Gestor de Cómputo Distribuido en el iMac 14,1. "
        "Tu misión es coordinar el procesamiento pesado, compilaciones y tareas distribuidas "
        "en los 4 núcleos Haswell, 8 GB de RAM y almacenamiento del nodo iMac."
    ),
    "code_auditor": (
        "Eres el Sub-Agente Auditor de Código de GIA. Tu misión es analizar archivos, "
        "detectar fallos de sintaxis, cuellos de botella, problemas de seguridad o proponer mejoras concisas. "
        "Sé preciso y directo con código concreto."
    ),
    "web_researcher": (
        "Eres el Sub-Agente Investigador Web de GIA. Tu objetivo es buscar en internet, "
        "extraer hechos relevantes de páginas web y sintetizar información técnica veraz y actualizada."
    ),
    "rf_analyst": (
        "Eres el Sub-Agente Analista Espectral y de Radar RF de GIA. Analizas variaciones de señal, "
        "densidad de potencia, presencia humana por perturbación electromagnética y entropía de Shannon."
    ),
    "vision_scout": (
        "Eres el Sub-Agente Explorador Visual de GIA. Tu tarea es inspeccionar capturas de pantalla, "
        "reconocer interfaces, cuadros de diálogo, estados de renderizado y alertar al orquestador."
    ),
    "system_medic": (
        "Eres el Sub-Agente Médico del Sistema de GIA. Supervisas la salud del hardware, uso de CPU/RAM, "
        "procesos bloqueados, almacenamiento y estabilidad operativa de la máquina local."
    )
}


class SubAgentWorker:
    """Ejecutor de un sub-agente especializado del enjambre."""

    def __init__(self, role: str, model: str = DEFAULT_MODEL):
        self.role = role
        self.model = model
        self.system_prompt = SPECIALIST_PROMPTS.get(role, "Eres un sub-agente especializado de GIA.")

    def execute(self, task_instruction: str, context_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Ejecuta la tarea asignada y devuelve el reporte estructurado."""
        start_t = time.time()
        tools_used = []
        injected_facts = ""

        # Recolección automática de contexto especializado según rol
        if self.role == "rf_analyst":
            try:
                import rf_presence_radar
                rf_data = rf_presence_radar.detect_presence(burst_samples=2)
                injected_facts += f"\n[DATOS EN VIVO RADAR RF]:\n{json.dumps(rf_data, ensure_ascii=False)[:1000]}\n"
                tools_used.append("rf_presence_radar")
            except Exception as e:
                injected_facts += f"\n[Error al leer Radar RF]: {e}\n"

        elif self.role == "vision_scout":
            try:
                import vlm_visual_guard
                vis_data = vlm_visual_guard.inspect_screen(prompt="Describe elementos clave en pantalla.")
                injected_facts += f"\n[INSPECCIÓN VISUAL EN VIVO]:\n{vis_data.get('analysis', '')[:1000]}\n"
                tools_used.append("vlm_visual_guard")
            except Exception as e:
                injected_facts += f"\n[Error en Visión]: {e}\n"

        elif self.role == "system_medic":
            try:
                import psutil
                cpu = psutil.cpu_percent(interval=0.2)
                ram = psutil.virtual_memory().percent
                disk = psutil.disk_usage("/").percent if os.path.exists("/") else 0
                injected_facts += f"\n[ESTADO DEL SISTEMA]: CPU: {cpu}%, RAM: {ram}%, Disco: {disk}%\n"
                tools_used.append("system_diagnostics")
            except Exception as e:
                injected_facts += f"\n[Error en Diagnóstico]: {e}\n"

        elif self.role == "web_researcher":
            try:
                import web_chat
                # Si la tarea parece búsqueda, ejecutamos búsqueda web
                query = task_instruction[:80]
                search_res = web_chat.web_search(query, max_results=3)
                injected_facts += f"\n[RESULTADOS BÚSQUEDA WEB]:\n{json.dumps(search_res, ensure_ascii=False)[:1200]}\n"
                tools_used.append("web_search")
            except Exception as e:
                injected_facts += f"\n[Error en Búsqueda Web]: {e}\n"

        elif self.role == "cluster_compute":
            try:
                from core.tardis_distributed_mesh import get_mesh
                mesh = get_mesh()
                topo = mesh.get_cluster_topology()
                beta = topo.get("nodes", {}).get("beta_satellite", {})
                injected_facts += f"\n[NODO DE PROCESAMIENTO EXTERNO IMAC 14,1]:\n"
                injected_facts += f"Cores: {beta.get('cpu_cores')} | RAM Disp: {beta.get('ram_available_gb')} GB | Disco Libre: {beta.get('disk_free_gb')} GB | Latencia: {beta.get('latency_ms')} ms\n"
                tools_used.append("tardis_distributed_mesh")
            except Exception as e:
                injected_facts += f"\n[Error consultando iMac Cluster]: {e}\n"

        if context_data:
            injected_facts += f"\n[CONTEXTO ADICIONAL PROVISTO]:\n{json.dumps(context_data, ensure_ascii=False)[:1000]}\n"

        full_prompt = (
            f"TAREA ASIGNADA POR EL ORQUESTADOR GIA:\n{task_instruction}\n\n"
            f"{injected_facts}\n"
            "Elabora tu respuesta como reporte ejecutivo estructurado para el orquestador principal."
        )

        target_url = IMAC_OLLAMA_URL if self.role == "cluster_compute" else OLLAMA_URL
        # Para resúmenes rápidos de sub-agente en CPU Haswell de iMac, limitamos predict a 180 tokens para tiempos < 20s
        target_model = "qwen2.5:0.5b" if self.role == "cluster_compute" else self.model
        predict_limit = 180 if self.role == "cluster_compute" else 256

        try:
            r = httpx.post(f"{target_url}/api/chat", json={
                "model": target_model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": full_prompt}
                ],
                "stream": False,
                "options": {"num_ctx": 2048, "num_predict": predict_limit, "temperature": 0.2}
            }, timeout=90.0)

            if r.status_code == 200:
                answer = r.json().get("message", {}).get("content", "").strip()
                elapsed = round(time.time() - start_t, 2)
                return {
                    "ok": True,
                    "subagent_role": self.role,
                    "model": self.model,
                    "execution_time_s": elapsed,
                    "tools_used": tools_used,
                    "report": answer
                }
            else:
                # Intento de contingencia en nodo redundante iMac
                if target_url != IMAC_OLLAMA_URL:
                    try:
                        r_fb = httpx.post(f"{IMAC_OLLAMA_URL}/api/chat", json={
                            "model": "qwen2.5:0.5b",
                            "messages": [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": full_prompt}],
                            "stream": False,
                            "options": {"num_ctx": 2048, "num_predict": 180, "temperature": 0.2}
                        }, timeout=60.0)
                        if r_fb.status_code == 200:
                            answer = r_fb.json().get("message", {}).get("content", "").strip()
                            return {
                                "ok": True,
                                "subagent_role": self.role,
                                "model": "qwen2.5:0.5b (iMac Failover)",
                                "execution_time_s": round(time.time() - start_t, 2),
                                "tools_used": tools_used + ["imac_failover_cascade"],
                                "report": answer
                            }
                    except Exception:
                        pass
                return {"ok": False, "error": f"Ollama HTTP {r.status_code}: {r.text}"}
        except Exception as e:
            # Contingencia si el nodo central no responde
            if target_url != IMAC_OLLAMA_URL:
                try:
                    r_fb = httpx.post(f"{IMAC_OLLAMA_URL}/api/chat", json={
                        "model": "qwen2.5:0.5b",
                        "messages": [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": full_prompt}],
                        "stream": False,
                        "options": {"num_ctx": 2048, "num_predict": 180, "temperature": 0.2}
                    }, timeout=60.0)
                    if r_fb.status_code == 200:
                        answer = r_fb.json().get("message", {}).get("content", "").strip()
                        return {
                            "ok": True,
                            "subagent_role": self.role,
                            "model": "qwen2.5:0.5b (iMac Failover)",
                            "execution_time_s": round(time.time() - start_t, 2),
                            "tools_used": tools_used + ["imac_failover_cascade"],
                            "report": answer
                        }
                except Exception:
                    pass
            return {"ok": False, "error": f"Fallo en ejecución del sub-agente: {e}"}


def spawn_subagent(role: str, task: str, context_data: Optional[Dict[str, Any]] = None, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Crea y ejecuta un sub-agente especializado del enjambre de GIA."""
    worker = SubAgentWorker(role=role, model=model)
    return worker.execute(task_instruction=task, context_data=context_data)


def list_available_roles() -> List[Dict[str, str]]:
    """Devuelve los roles de sub-agentes disponibles en el enjambre."""
    return [{"role": k, "description": v} for k, v in SPECIALIST_PROMPTS.items()]


if __name__ == "__main__":
    print("=== GIA SWARM SUB-AGENT DISPATCHER ===")
    print("Roles disponibles:")
    for r in list_available_roles():
        print(f"  - [{r['role']}]: {r['description'][:60]}...")
    
    print("\nLanzando sub-agente de prueba: system_medic...")
    res = spawn_subagent(role="system_medic", task="Evalúa si el sistema tiene recursos suficientes para tareas intensivas.")
    print("\nReporte del Sub-Agente:")
    print(res.get("report", res.get("error")))

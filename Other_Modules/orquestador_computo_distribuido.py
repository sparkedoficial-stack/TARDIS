"""
modulos_ftl/orquestador_computo_distribuido.py - Módulo FTL de Orquestación Multi-Sistema
=========================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Permite invocar el clúster heterogéneo (Estación Local + iMac 14,1 + Capa Frontier)
desde el Master Hub FTL y las interfaces soberanas.
"""

import sys
from pathlib import Path

BASE_DIR = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM").resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.tardis_distributed_mesh import get_mesh


class OrquestadorComputoDistribuido:
    """
    Módulo oficial para MasterHub FTL.
    Expone la potencia de cómputo del clúster heterogéneo a todo el ecosistema TARDIS.
    """

    def __init__(self):
        self.mesh = get_mesh()

    def run(self, action: str = "status", payload: str = None) -> dict:
        """
        Ejecuta acciones sobre la malla distribuida:
        - 'distribute': Divide y distribuye una tarea entre Alfa (TimeMachine) y Beta (Mac 14,1).
        - 'status' / 'telemetry': Retorna topología y métricas combinadas del clúster.
        - 'utilization': Muestra la ocupación de CPU/RAM de ambos equipos.
        - 'batch': Ejecuta cómputo por lotes particionado entre ambos procesadores.
        - 'exec_imac': Ejecuta comando bash o script en el iMac.
        - 'infer_imac': Ejecuta inferencia en el modelo Ollama del iMac.
        - 'audit': Realiza una auditoría cruzada paralela.
        - 'offload_vault': Sincroniza snapshot de la bóveda en el disco de 1 TB del iMac.
        """
        if action == "distribute":
            task = payload or "Análisis multi-sistema de causalidad temporal y estabilidad de red."
            return self.mesh.split_and_distribute_task(task)
        elif action in ("status", "telemetry"):
            return self.mesh.get_cluster_topology()
        elif action == "utilization":
            return self.mesh.get_cluster_utilization()
        elif action == "batch":
            code = "return item * 2"
            items = list(range(10))
            if isinstance(payload, dict):
                code = payload.get("code", code)
                items = payload.get("items", items)
            return self.mesh.distribute_batch_compute(code, items)
        elif action == "exec_imac":
            cmd = payload or "uptime"
            return self.mesh.execute_remote_cmd(cmd)
        elif action == "infer_imac":
            prompt = payload or "Reporta tu disponibilidad para cómputo distribuido."
            return self.mesh.run_imac_inference(prompt)
        elif action == "audit":
            q = payload or "¿Cuáles son los tres pilares de la entropía de Shannon?"
            return self.mesh.parallel_cross_audit(q)
        elif action == "offload_vault":
            subpath = payload or "ftl_auto_snapshot"
            return self.mesh.offload_vault_backup(subpath)
        else:
            return {
                "ok": False,
                "error": f"Acción desconocida '{action}'. Acciones válidas: distribute, status, utilization, batch, exec_imac, infer_imac, audit, offload_vault"
            }

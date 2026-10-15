#!/usr/bin/env python3
import sys
import logging
from pathlib import Path

# Añadir la ruta core al sistema para importar
WORKSPACE_DIR = Path(__file__).resolve().parent
sys.path.append(str(WORKSPACE_DIR))
try:
    from core.tardis_glm_brain import GLMParallelBrain
except ImportError:
    logging.error("No se pudo importar GLMParallelBrain. Asegúrese de que el módulo core/tardis_glm_brain.py exista.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [TARDIS-ORCHESTRATOR] - %(message)s')
logger = logging.getLogger("Parallel-Orchestrator")

def invoke_parallel_brain(query: str):
    """
    Función de API local para que los modelos de la suite GODWORKS (TARDIS, Kaiju, etc.)
    puedan despachar tareas complejas al modelo GLM-5.2 a través del motor Colibri.
    """
    logger.info("Iniciando conexión con el Cerebro Paralelo (GLM-5.2)...")
    
    brain = GLMParallelBrain(str(WORKSPACE_DIR))
    brain.check_installation()
    
    logger.info("Delegando tarea de alta complejidad (MoE) al nodo paralelo.")
    response = brain.orchestrate_task(query)
    return response

if __name__ == "__main__":
    if len(sys.argv) > 1:
        task_query = " ".join(sys.argv[1:])
    else:
        task_query = "Inicializar subsistema de razonamiento pesado paralelo."
        
    print(f"\n[QUERY] {task_query}")
    result = invoke_parallel_brain(task_query)
    print("\n[RESULTADO DEL CEREBRO PARALELO]")
    print(result)

import hashlib
import time
from typing import Dict, Any, Optional

class SistemaContextualTARDIS:
    def __init__(self):
        # Diccionario maestro para almacenar los hilos de conversación y sus contextos
        self.hilos_activos: Dict[str, Dict[str, Any]] = {}

    def _generar_huella_causal(self, mensaje: Dict[str, Any]) -> str:
        """
        Genera una 'huella causal' (causal footprint) única basándose en la entropía 
        del mensaje y metadatos temporales, útil cuando no hay un ID explícito.
        """
        texto = mensaje.get('texto', '')
        metadatos = mensaje.get('metadatos', str(time.time()))
        entropia_cruda = f"{texto}|{metadatos}".encode('utf-8')
        return hashlib.sha3_256(entropia_cruda).hexdigest()[:16]

    def identificacion_de_contexto(self, mensaje: Dict[str, Any]) -> str:
        """
        Analiza un mensaje entrante, extrae el ID, número de teléfono o calcula
        una huella causal para asignar y mantener el contexto en un hilo multiusuario.
        
        Retorna el identificador de contexto (context_id) anclado al mensaje.
        """
        # 1. Extracción de identificadores primarios
        id_usuario = mensaje.get("id_usuario")
        numero_telefonico = mensaje.get("numero_telefonico")
        
        # 2. Resolución de la clave de anclaje (Context ID)
        if id_usuario:
            context_id = f"UID_{id_usuario}"
        elif numero_telefonico:
            context_id = f"TEL_{numero_telefonico}"
        else:
            # 3. Si es una entidad no identificada (anónima), creamos su huella causal
            huella = self._generar_huella_causal(mensaje)
            context_id = f"CAUSAL_{huella}"
            
        # 4. Inicialización de la matriz de contexto si la entidad es nueva
        if context_id not in self.hilos_activos:
            self.hilos_activos[context_id] = {
                "historial_mensajes": [],
                "anclaje_temporal": time.time(),
                "ultima_interaccion": time.time(),
                "parametros_memoria": {}
            }
            print(f"[TARDIS] Nuevo nodo de contexto creado: {context_id}")
            
        # 5. Integración del mensaje al hilo temporal de la entidad
        self.hilos_activos[context_id]["historial_mensajes"].append(mensaje)
        self.hilos_activos[context_id]["ultima_interaccion"] = time.time()
        
        return context_id

    def obtener_contexto(self, context_id: str) -> Optional[Dict[str, Any]]:
        """Recupera la memoria contextual completa de una entidad."""
        return self.hilos_activos.get(context_id)

# --- EJECUCIÓN DE PRUEBA ---
if __name__ == "__main__":
    tardis_ctx = SistemaContextualTARDIS()
    
    # Simulación de mensajes entrantes de distintos orígenes
    msg_1 = {"id_usuario": "Arquitecto_Omega", "texto": "Iniciando secuencia."}
    msg_2 = {"numero_telefonico": "+529841234567", "texto": "¿Cuál es el estatus?"}
    msg_3 = {"texto": "Mensaje interceptado sin remitente, posible anomalía.", "metadatos": "sector_7G"}
    
    # Procesamiento
    id_1 = tardis_ctx.identificacion_de_contexto(msg_1)
    id_2 = tardis_ctx.identificacion_de_contexto(msg_2)
    id_3 = tardis_ctx.identificacion_de_contexto(msg_3)
    
    print("\n[TARDIS] Nodos de Contexto Activos:")
    for ctx, datos in tardis_ctx.hilos_activos.items():
        print(f" -> {ctx} | Mensajes procesados: {len(datos['historial_mensajes'])}")

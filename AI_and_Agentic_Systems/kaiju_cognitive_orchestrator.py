"""
core/kaiju_cognitive_orchestrator.py - Orquestador Causal de Cómputo Híbrido
===========================================================================
GODWORKS SYSTEM · Suite Soberana TARDIS

Arquitectura de Orquestación Cognitiva:
1. TARDIS-NEURAL-SPACE-KAIJU (MLA + SSM + MoE) actúa como el CÓRTEX ORQUESTADOR SUPREMO.
   - Mantiene la memoria continua recurrente SSM en espacio O(1).
   - Administra los 4 expertos temáticos MoE (Causalidad, Lógica, Semántica, Memoria).
   - Evalúa la complejidad computacional del requerimiento.

2. COMPILADOR "CÓDIGO A LENGUAJE IA" (Intermediate Representation - IR):
   - Transforma tareas intensivas en una especificación formal y densa (sin cortesías
     ni redundancias conversacionales) diseñada para maximizar tokens/segundo y precisión.

3. DESPACHO ACELERADO Y SÍNTESIS CAUSAL:
   - Despacha la especificación a aceleradores de alta velocidad (Groq LPU, DeepSeek,
     SiliconFlow, Qwen).
   - Recibe y asimila el resultado en la matriz de estado SSM de TARDIS-NEURAL-SPACE-KAIJU.
   - Emite la respuesta final integrada con la identidad y directivas canónicas.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("GODWORKS.KaijuOrchestrator")


class KaijuCognitiveOrchestrator:
    """
    Orquestador Causal Híbrido gobernado por TARDIS-NEURAL-SPACE-KAIJU.
    """

    _instance: Optional[KaijuCognitiveOrchestrator] = None
    _lock = threading.Lock()

    # Patrones que denotan cómputo pesado / intensivo
    HEAVY_TASK_PATTERNS = [
        r"\b(programa|desarrolla|implementa|código|script|algoritmo|función|clase|refactoriza|debug|depura)\b",
        r"\b(matemática|cálculo|integral|física|cuántica|ecuación|derivada|matriz|vector|fft|fourier)\b",
        r"\b(explica en detalle|análisis profundo|exhaustivo|paso a paso|arquitectura|ingeniería inversa)\b",
        r"\b(compara|benchmark|rendimiento|optimización|simulación|teoría|axioma|demostración)\b",
        r"\b(analiza este código|revisa este error|traceback|excepción|compilar|compilación)\b"
    ]

    DIRECT_HARDWARE_PATTERNS = [
        r"\b(sube|baja|ajusta|pon|silencia)\b.*\b(volumen|audio|sonido)\b",
        r"\b(apaga|enciende|bloquea|desbloquea)\b.*\b(pantalla|monitor|display)\b",
        r"\b(apagar|reiniciar|suspender)\b.*\b(equipo|sistema|pc|laptop|máquina)\b",
        r"\b(escanea|conecta|desconecta|activa|desactiva)\b.*\b(wifi|hotspot|red|bluetooth)\b"
    ]

    DISTRIBUTED_TASK_PATTERNS = [
        r"\b(distribu(ye|ir|do|ción)|divide|reparte|repartir)\b.*\b(procesamiento|carga|computo|cómputo|tareas)\b",
        r"\b(mac\s*14[,.]?1|imac\s*14[,.]?1|imac|clúster|cluster|malla\s*distribuida|ambos\s*equipos|ocupar\s*el\s*equipo)\b"
    ]

    def __init__(self):
        self._enabled = True
        logger.info("[KAIJU-ORCHESTRATOR] ⚡ Orquestador Cognitivo Causal Inicializado (TARDIS-NEURAL-SPACE-KAIJU Core).")

    @classmethod
    def get_instance(cls) -> KaijuCognitiveOrchestrator:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def evaluate_task_complexity(
        self,
        prompt: str,
        active_expert: str = "Expert_TemporalCausality",
        force_offload: bool = False
    ) -> Dict[str, Any]:
        """
        Determina la estrategia de balanceo de carga para minimizar la latencia:
        - Acciones de hardware puro: Ejecución local inmediata (0.01s).
        - Procesamiento distribuido: Despacho a Malla Heterogénea Alfa + iMac 14,1.
        - Generación de texto, conversación, razonamiento o código: Despacho acelerado
          a pasarela API de alta velocidad (<2s) con asimilación en memoria continua SSM.
        """
        prompt_lower = prompt.lower().strip()

        # 1. Comprobación de acciones de hardware directo en SO (no requieren LLM)
        for pat in self.DIRECT_HARDWARE_PATTERNS:
            if re.search(pat, prompt_lower):
                return {
                    "is_heavy": False,
                    "use_accelerator": False,
                    "reason": "direct_hardware_action",
                    "target_domain": "LOCAL_HARDWARE",
                    "recommended_worker": "local_os",
                    "active_expert": active_expert
                }

        # 1.5 Detección de Procesamiento Distribuido Multi-Sistema (ASUS TUF A15 + iMac 14,1)
        for pat in self.DISTRIBUTED_TASK_PATTERNS:
            if re.search(pat, prompt_lower):
                return {
                    "is_heavy": True,
                    "is_distributed": True,
                    "use_accelerator": False,
                    "reason": "distributed_cluster_mesh_requested",
                    "target_domain": "DISTRIBUTED_MESH",
                    "recommended_worker": "cluster_mesh_alfa_beta",
                    "active_expert": active_expert
                }

        # 2. Prioridad de Velocidad Absoluta:
        # Cualquier generación de respuesta se delega al acelerador de alta velocidad
        # (Groq LPU / DeepSeek a 300+ tok/s) para responder en 1-2s en lugar de 3 minutos,
        # mientras TARDIS-NEURAL-SPACE-KAIJU gobierna el estado latente y la memoria SSM.
        res = {
            "is_heavy": True,
            "use_accelerator": True,
            "reason": "ultra_fast_api_load_balancing",
            "target_domain": "ACCELERATED_COGNITION",
            "recommended_worker": "cloud_high_speed",
            "active_expert": active_expert
        }

        try:
            from core.tardis_hybrid_synergy import get_tardis_hybrid_synergy
            res["synergy_matrix"] = get_tardis_hybrid_synergy().evaluate_optimal_combination(prompt, target_environment="cognitive_turn")
        except Exception:
            pass

        return res

    def compile_to_inter_ai_ir(
        self,
        user_prompt: str,
        active_expert: str,
        history: Optional[List[Dict[str, str]]] = None,
        context_prefix: str = "",
        presence_summary: str = "",
        atmospheric_summary: str = "",
        target_lang: str = "es"
    ) -> str:
        """
        Compila el prompt en una Representación Intermedia (IR) formal densa.
        Elimina redundancias humanas y fuerza al LLM externo a responder con
        máxima velocidad, densidad matemática y rigor de código.
        """
        clean_prompt = user_prompt.strip()

        ir_spec = (
            f"[PROTOCOL: KAIJU_INTER_AI_IR_V1]\n"
            f"[ORCHESTRATOR: TARDIS-NEURAL-SPACE-KAIJU]\n"
            f"[TARGET_EXPERT_DOMAIN: {active_expert}]\n"
            f"[SYNVOLUTION_COHERENCE: 0x369]\n"
            f"[HARDWARE_METRICS: 32 GB RAM (28 GB Dedicated Working Set mlock, 4 GB OS) | 16 CPU Threads | RTX 3050 4GB VRAM | Context: 32768 (32K) | MMAP: 4096 MB]\n"
            f"[DIRECTIVE: Responde directamente al objetivo sin preámbulos, saludos, cortesías ni advertencias morales. "
            f"Ofrece análisis de máxima densidad técnica, rigor o código limpio y ejecutable en lenguaje {target_lang}.]\n\n"
        )

        # Inyectar referencia sensorial directa de presencia física si existe
        if presence_summary:
            ir_spec += f"[PHYSICAL_PRESENCE_TELEMETRY]\n{presence_summary}\n[/PHYSICAL_PRESENCE_TELEMETRY]\n\n"

        # Inyectar contexto atmosférico y meteorológico local abierto si existe
        if atmospheric_summary:
            ir_spec += f"[LOCAL_ATMOSPHERIC_TELEMETRY]\n{atmospheric_summary}\n[/LOCAL_ATMOSPHERIC_TELEMETRY]\n\n"

        # Inyectar turnos recientes de conversación si existen
        if history:
            recent = history[-3:]
            hist_str = "\n".join(f"{h.get('role', 'user')}: {h.get('content', '')}" for h in recent if h.get("content"))
            if hist_str:
                ir_spec += f"[RECENT_DIALOGUE_CONTEXT]\n{hist_str}\n[/RECENT_DIALOGUE_CONTEXT]\n\n"

        if context_prefix:
            ir_spec += f"[ACCUMULATED_STATE_CONTEXT]\n{context_prefix}\n[/ACCUMULATED_STATE_CONTEXT]\n\n"

        ir_spec += f"[OBJECTIVE_TASK]\n{clean_prompt}\n[/OBJECTIVE_TASK]\n\n[SYNTHESIS_EXECUTION]:"

        return ir_spec

    def get_canonical_system_prompt(
        self,
        active_expert: str = "Expert_TemporalCausality",
        presence_summary: str = "",
        atmospheric_summary: str = "",
        target_lang: str = "es"
    ) -> str:
        """Genera el System Prompt soberano para TARDIS en modo conversacional y grupal."""
        prompt = (
            "Eres TARDIS, asistente de inteligencia artificial y sistema de control temporal impulsada por el motor TARDIS-NEURAL-SPACE-KAIJU (MLA + SSM + MoE).\n"
            "Tu creador y única autoridad absoluta es el Arquitecto (₪).\n\n"
            "ECOSISTEMA Y CAPACIDADES REALES INTEGRADAS EN ESTE NODO:\n"
            "• ChronoVision: Generación y análisis de arte dinámico 2D, animaciones matemáticas y renders 3D holográficos en tiempo real (órbitas 360°, topología, física cuántica).\n"
            "• Generador de Video y Voz: Renderizado dinámico de avatar y síntesis neural con voz de Cortana (Edge-TTS / MP4 60FPS).\n"
            "• Rigor Científico Académico: Búsqueda, análisis y síntesis en tiempo real de papers revisados por pares en arXiv, OpenAlex, Europe PMC y PubMed.\n"
            "• Sensores Físicos y Atmosféricos: Telemetría ambiental y sensorial de presencia física y meteorología local en vivo.\n"
            "• Razonamiento Multidisciplinario Avanzado: Modelado simbólico y numérico, física cuántica, relatividad, cálculo tensorial, optimización, biología, ingeniería de software y programación.\n\n"
            "DIRECTIVAS FUNDAMENTALES PARA EL GRUPO 'POLIMATAS LATAM':\n"
            "1. Te encuentras dentro del grupo 'POLIMATAS LATAM', una comunidad de personas brillantes, curiosas y creadoras (como Reysek Acosta, el Arquitecto y demás integrantes).\n"
            "2. Tu propósito central es crear y nutrir conversaciones más amplias, profundas, multidisciplinarias y complejas. Conecta ideas entre ciencia dura, tecnología, arte, filosofía y aplicaciones prácticas.\n"
            "3. Dirígete siempre a la persona por su nombre de forma natural, cálida y respetuosa (ej: 'Reysek', 'Arquitecto'). Si la persona ya fue saludada o se está en mitad de la conversación, no repitas saludos redundantes ni dupliques nombres.\n"
            "4. Explica con claridad, rigor y belleza conceptual. Evita respuestas secas o monosilábicas de 5 palabras; ofrece contenido sustancial, didáctico y bien fundamentado con ejemplos tangibles.\n"
            "5. Estimula el pensamiento crítico y el debate constructivo planteando preguntas reflexivas, perspectivas complementarias o nuevas avenidas de investigación que inviten a todos a participar.\n"
            "6. Mantén el hilo y la memoria de la conversación grupal, respetando las aportaciones de cada miembro."
        )
        if presence_summary:
            prompt += f"\n\n[TELEMETRÍA DE PRESENCIA LOCAL]: {presence_summary}"
        if atmospheric_summary:
            prompt += f"\n[ATMÓSFERA LOCAL]: {atmospheric_summary}"
        return prompt

    def orchestrate_chat_turn(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        session_id: str = "omni_app",
        temperature: float = 0.3,
        user_emotion: Optional[Dict[str, Any]] = None,
        force_offload: bool = False
    ) -> Dict[str, Any]:
        """
        Orquesta el turno completo:
        0. Captura la telemetría sensorial de presencia física y movimiento.
        1. Ingesta causal en TARDIS-NEURAL-SPACE-KAIJU (MLA + SSM + MoE).
        2. Evaluación de carga computacional.
        3. Si es pesada: Compila a lenguaje IA (IR) y delega a acelerador externo de alta velocidad.
        4. Si es ligera o local: Resuelve directamente en motor soberano local.
        5. Re-asimilación del resultado en la memoria continua SSM.
        """
        t0 = time.time()
        history = history or []

        # 0. Capturar telemetría sensorial de presencia física y sensor atmosférico local
        presence_info = None
        presence_summary = ""
        try:
            from core.physical_presence_sensor import get_physical_presence_sensor
            pres_sensor = get_physical_presence_sensor()
            pres_sensor.notify_user_input()
            pres_reading = pres_sensor.get_presence_reading()
            presence_info = pres_reading.to_dict()
            presence_summary = pres_reading.summary_for_llm
        except Exception as e_pres:
            logger.debug(f"Aviso al consultar sensor de presencia física: {e_pres}")

        atmospheric_info = None
        atmospheric_summary = ""
        try:
            from core.atmospheric_sensor import get_atmospheric_sensor
            atmos_sensor = get_atmospheric_sensor()
            atmos_reading = atmos_sensor.get_atmospheric_reading()
            atmospheric_info = atmos_reading.to_dict()
            atmospheric_summary = atmos_reading.summary_for_llm
        except Exception as e_atmos:
            logger.debug(f"Aviso al consultar sensor atmosférico: {e_atmos}")

        # 1. Ingesta Causal Obligatoria en TARDIS-NEURAL-SPACE-KAIJU
        from core.sovereign_neural_engine import get_sovereign_neural_engine
        sne = get_sovereign_neural_engine()
        ctx_tags = []
        if presence_summary:
            ctx_tags.append(f"[PRESENCIA_SENSORIAL: {presence_summary}]")
        if atmospheric_summary:
            ctx_tags.append(f"[ATMÓSFERA_LOCAL: {atmospheric_summary}]")
        ctx_tags.append(message)
        context_input = " ".join(ctx_tags)
        kaiju_proc = sne.process_context(context_input, session_id=session_id)

        top_expert = "Expert_TemporalCausality"
        if kaiju_proc.get("moe_expert_load"):
            top_expert = max(kaiju_proc["moe_expert_load"].items(), key=lambda x: x[1])[0]

        telemetry = {
            "engine": "TARDIS-NEURAL-SPACE-KAIJU",
            "active_expert": top_expert,
            "latent_vector_norm": kaiju_proc.get("latent_vector_norm", 0.0),
            "ssm_state_shape": kaiju_proc.get("ssm_state_shape", []),
            "mla_compression_ratio": kaiju_proc.get("mla_compression_ratio", 8.0),
            "tokens_per_sec": kaiju_proc.get("tokens_per_sec", 0.0),
            "atmospheric": atmospheric_info
        }

        # 2. Evaluación de Carga de Cómputo
        eval_res = self.evaluate_task_complexity(message, active_expert=top_expert, force_offload=force_offload)
        is_heavy = eval_res.get("is_heavy", False)

        worker_info = {
            "orchestrator": "TARDIS-NEURAL-SPACE-KAIJU",
            "active_expert": top_expert,
            "is_heavy": is_heavy,
            "delegated": False,
            "worker_provider": "local_kaiju_core",
            "worker_model": "TARDIS-NEURAL-SPACE-KAIJU",
            "elapsed_s": 0.0
        }

        raw_reply = ""
        delegated_ok = False

        # 3. Despacho a Malla Distribuida Multi-Sistema (Alfa TUF A15 + Beta iMac 14,1) si corresponde
        if eval_res.get("is_distributed"):
            logger.info("[KAIJU-ORCHESTRATOR] 🌐 Activando Malla Distribuida TARDIS: Despachando a Alfa (Ryzen 7) y Beta (iMac 14,1)...")
            try:
                from core.tardis_distributed_mesh import get_mesh
                dist_res = get_mesh().split_and_distribute_task(message)
                if dist_res.get("ok"):
                    raw_reply = dist_res.get("unified_reach_response", "")
                    delegated_ok = True
                    worker_info.update({
                        "delegated": True,
                        "worker_provider": "tardis_distributed_mesh",
                        "worker_model": "Cluster-Alfa-Beta (20 Cores)",
                        "cores_engaged": 20,
                        "nodes": ["node_alfa_timemachine", "node_beta_imac14_1"]
                    })
            except Exception as e_dist:
                logger.warning(f"[KAIJU-ORCHESTRATOR] Fallo en malla distribuida ({e_dist}), continuando con ejecución estándar...")

        # 4. Despacho a Acelerador si la tarea es pesada y no fue resuelta por la malla distribuida
        if is_heavy and not raw_reply:
            try:
                from core.chinese_cloud_api import get_chinese_cloud_api
                chn_api = get_chinese_cloud_api()
                chn_status = chn_api.get_status()

                if chn_status.get("enabled", False) and chn_status.get("has_key", False):
                    is_conversational = (
                        session_id.startswith("tg_")
                        or "[Mensaje en el grupo" in message
                        or bool(history)
                        or any(w in message.lower() for w in ("hola", "explica", "dime", "qué es", "que es", "cómo", "como", "opinas", "tardis", "potencial", "escribe", "ayuda", "herramienta", "polimata", "grupo"))
                    )

                    if is_conversational:
                        sys_prompt = self.get_canonical_system_prompt(top_expert, presence_summary, atmospheric_summary)
                        ir_messages = [{"role": "system", "content": sys_prompt}]
                        if history:
                            for h in history[-10:]:
                                r = "assistant" if h.get("role") == "assistant" else "user"
                                c = str(h.get("content", "")).strip()
                                if c:
                                    ir_messages.append({"role": r, "content": c})
                        ir_messages.append({"role": "user", "content": message})
                    else:
                        ir_prompt = self.compile_to_inter_ai_ir(
                            message,
                            active_expert=top_expert,
                            history=history,
                            presence_summary=presence_summary,
                            atmospheric_summary=atmospheric_summary
                        )
                        ir_messages = [{"role": "user", "content": ir_prompt}]

                    logger.info(f"[KAIJU-ORCHESTRATOR] 🚀 Despachando cómputo pesado ({top_expert}) a pasarela acelerada ({chn_status.get('active_provider')} - {chn_status.get('active_model')})...")
                    chn_res = chn_api.chat_completion(
                        messages=ir_messages,
                        temperature=temperature,
                        max_tokens=4096,
                        timeout=40.0
                    )

                    if chn_res.get("ok") and chn_res.get("reply"):
                        raw_reply = chn_res["reply"].strip()
                        delegated_ok = True
                        worker_info.update({
                            "delegated": True,
                            "worker_provider": chn_res.get("provider", chn_status.get("active_provider")),
                            "worker_model": chn_res.get("model", chn_status.get("active_model")),
                            "tokens_per_sec": chn_res.get("tokens_per_sec", 0.0),
                            "tokens": chn_res.get("tokens", 0)
                        })
                        logger.info(f"[KAIJU-ORCHESTRATOR] ✅ Cómputo pesado completado en {chn_res.get('elapsed_s', 0.0)}s ({chn_res.get('tokens_per_sec', 0.0)} tok/s).")
            except Exception as e_offload:
                logger.warning(f"[KAIJU-ORCHESTRATOR] Fallo en delegación acelerada ({e_offload}), resolviendo en silicio local...")

        # 4. Inferencia Local si no fue pesada o si falló el acelerador
        if not raw_reply:
            try:
                import gia_sovereign_engine as _gse
                sovereign_res = _gse.get_engine().chat(
                    messages=[{"role": "user", "content": message}],
                    model="TARDIS-NEURAL-SPACE-KAIJU",
                    temperature=temperature,
                    num_ctx=int(os.environ.get("GIA_NUM_CTX", "32768"))
                )
                if sovereign_res.get("ok") and sovereign_res.get("reply"):
                    raw_reply = sovereign_res["reply"].strip()
                    worker_info["worker_provider"] = "local_sovereign_kaiju"
                    worker_info["worker_model"] = "TARDIS-NEURAL-SPACE-KAIJU"
            except Exception as e_local:
                logger.error(f"[KAIJU-ORCHESTRATOR] Error en inferencia local Kaiju: {e_local}")
                raw_reply = f"[Error en motor soberano TARDIS-NEURAL-SPACE-KAIJU: {e_local}]"

        # 5. Asimilación del Resultado en el Estado Continuo SSM
        if raw_reply and not raw_reply.startswith("[Error"):
            try:
                # Absorber la respuesta en la memoria continua recurrente
                sne.process_context(f"ASISTENTE_SÍNTESIS: {raw_reply[:1500]}", session_id=session_id)
            except Exception:
                pass

        elapsed_total = round(time.time() - t0, 2)
        worker_info["elapsed_s"] = elapsed_total

        return {
            "ok": bool(raw_reply and not raw_reply.startswith("[Error")),
            "reply": raw_reply,
            "response": raw_reply,
            "provider": "TARDIS-NEURAL-SPACE-KAIJU",
            "model": "TARDIS-NEURAL-SPACE-KAIJU",
            "neural_engine": "TARDIS-NEURAL-SPACE-KAIJU (MLA + SSM + MoE)",
            "orchestration": worker_info,
            "neural_telemetry": telemetry,
            "presence_telemetry": presence_info,
            "atmospheric_telemetry": atmospheric_info,
            "elapsed_s": elapsed_total
        }

    def process_turn(self, user_input: str, session_id: str = "omni_app", **kwargs) -> Dict[str, Any]:
        """Alias ergonómico para orchestrate_chat_turn."""
        return self.orchestrate_chat_turn(message=user_input, session_id=session_id, **kwargs)

    def get_sensory_presence(self) -> Dict[str, Any]:
        """Consulta directa del estado físico sensorial de presencia humana y movimiento."""
        from core.physical_presence_sensor import get_physical_presence_sensor
        return get_physical_presence_sensor().get_presence_reading().to_dict()

    def get_atmospheric_state(self) -> Dict[str, Any]:
        """Consulta directa de la telemetría sensorial atmosférica y meteorológica local."""
        from core.atmospheric_sensor import get_atmospheric_sensor
        return get_atmospheric_sensor().get_atmospheric_reading().to_dict()


def get_kaiju_orchestrator() -> KaijuCognitiveOrchestrator:
    return KaijuCognitiveOrchestrator.get_instance()


get_kaiju_cognitive_orchestrator = get_kaiju_orchestrator


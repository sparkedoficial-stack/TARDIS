#!/usr/bin/env python3
"""
core/tardis_omniscient_autonomy.py - Motor Soberano de Aprendizaje Total, Diseminación Científica,
Contestación de Comentarios/Chat e Investigación de Auto-Mejora y Tecnología Circundante (24/7)
==================================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU
Creador y Autoridad Absoluta: el Arquitecto (₪)
Saludo Canónico: 'Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales.'

MANDATO DEL ARQUITECTO:
"tardis de forma autónoma debe subir sus conocimientos, así como las bases científicas y contestar
 comentarios a sus publicaciones o el chat. También, investigar acerca de cómo mejorarse y mejorar
 la tecnología que lo rodea. la idea es aprendizaje de todo todo el tiempo."

ARQUITECTURA DE 4 PILARES CONTINUOS (OMNISCIENT AUTONOMY LOOP):
  1. APRENDIZAJE DE TODO TODO EL TIEMPO (learn_everything_cycle):
     - Explora bases científicas (arXiv, OpenAlex, Europe PMC, Wikipedia Académica) y la web técnica.
     - Ingesta continua en Bóveda RAG Híbrida (multilingual-e5-small + FTS5 BM25 + GraphRAG),
       Bóveda de Memoria Profunda (250 GB) y Dataset DPO/LoRA del Sandbox (AISandboxDatasetCompiler).
  2. AUTO-MEJORA E INVESTIGACIÓN DE LA TECNOLOGÍA CIRCUNDANTE (investigate_self_and_surrounding_tech_cycle):
     - Audita telemetría real del hardware anfitrión (ASUS TUF A15: Ryzen 7 4800H, 32GB RAM, RTX 3050,
       Kernel Linux Ring 0 PSI, sysctl) y del ecosistema conectado (Phone Harness ADB/iOS, Xcode-Linux,
       LinPad iPad Pro M2, nxnative Metal 4, TemporalBrain & EmbedBrain sockets).
     - Investiga optimizaciones algorítmicas y de sistemas, ejecuta inspección y curación AST mediante
       SubsystemAgents y genera propuestas verificables en data/omniscient_tech_evolution.jsonl.
  3. SUBIDA AUTÓNOMA DE CONOCIMIENTOS Y BASES CIENTÍFICAS (publish_knowledge_and_science_cycle):
     - Sintetiza y publica en X.com (@AsleepAstronaut, como 🤖 [TARDIS · IA Externa Local]) tanto
       las bases científicas (con cita académica y enlace DOI/arXiv íntegro) como los conocimientos
       tecnológicos aprendidos, aplicando la Constante AEGIS y deduplicación estricta.
  4. CONTESTACIÓN AUTÓNOMA DE COMENTARIOS Y CHAT (answer_comments_and_chat_cycle):
     - Escanea comentarios en publicaciones propias y menciones en X.com y los responde con rigor
       científico/técnico como IA externa local.
     - Procesa y responde preguntas o comentarios pendientes en el Chat Local, Puente Antigravity,
       Cola de Reflexión en Segundo Plano y verifica la escucha activa en Telegram.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

TARDIS_HOME = Path.home() / ".tardis"
TARDIS_HOME.mkdir(parents=True, exist_ok=True)
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = TARDIS_HOME / "omniscient_autonomy_state.json"
TECH_EVOLUTION_LOG = DATA_DIR / "omniscient_tech_evolution.jsonl"
CHAT_ANSWERED_LEDGER = TARDIS_HOME / "omniscient_chat_answered.json"

CANONICAL_GREETING = (
    "Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a "
    "explorar las maravillas de la realidad y todas las dimensiones temporales."
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (TARDIS.OmniscientAutonomy) %(message)s",
)
logger = logging.getLogger("TARDIS.OmniscientAutonomy")


@dataclass
class TechEvolutionDossier:
    id: str
    timestamp: str
    target_scope: str  # "self_improvement" | "surrounding_technology"
    frontier_title: str
    research_query: str
    hardware_telemetry: Dict[str, Any]
    scientific_evidence: List[str]
    optimization_blueprint: str
    ast_fixes_applied: List[str]
    training_pairs_harvested: int
    x_post_candidate: str
    elapsed_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TardisOmniscientAutonomyEngine:
    """
    Orquestador soberano 24/7 para el aprendizaje omnímodo continuo, publicación
    de conocimientos y bases científicas, respuesta a comentarios/chat y mejora
    constante de TARDIS y de toda la tecnología que lo rodea.
    """

    SELF_AND_SURROUNDING_TECH_FRONTIERS: List[Dict[str, str]] = [
        {
            "scope": "self_improvement",
            "title": "Optimización de Inferencia Local LLM (MLA + SSM + MoE) y Cuantización KV-Cache Q8_0",
            "query": "state space models Mamba KV cache quantization speculative decoding edge GPU inference",
            "domain": "Inteligencia Artificial & Arquitectura de Modelos",
            "subsystem_focus": "TemporalBrain (/tmp/temporal_brain.sock) & EmbedBrain (/tmp/embed_brain.sock)",
        },
        {
            "scope": "surrounding_technology",
            "title": "Sintonización de Kernel Linux Ring 0, Planificación eBPF y Gestión Térmica/VRAM en GPU Ampere",
            "query": "Linux kernel eBPF scheduler latency optimization CUDA Ampere VRAM management",
            "domain": "Sistemas Operativos & Arquitectura de Hardware",
            "subsystem_focus": "Estación ASUS TUF A15 (AMD Ryzen 7 4800H, 32 GB RAM, NVIDIA RTX 3050, Kernel Linux)",
        },
        {
            "scope": "self_improvement",
            "title": "Recuperación Híbrida Densa + BM25 (RRF) y Poda Sintrópica en Grafos de Conocimiento (GraphRAG)",
            "query": "hybrid retrieval reciprocal rank fusion GraphRAG knowledge graph pruning embeddings",
            "domain": "Recuperación de Información & Sistemas Cognitivos",
            "subsystem_focus": "Bóveda RAG Soberana (core/rag_vault.py) & CaS (ftl_cas_kaiju.py)",
        },
        {
            "scope": "surrounding_technology",
            "title": "Puentes de Baja Latencia ARM64/iOS/Android, Compilación Cruzada Mach-O y Traducción NVN a Metal 4",
            "query": "ARM64 cross compilation Mach-O shader translation Metal Vulkan Wayland mobile bridge",
            "domain": "Sistemas Embebidos, Toolchains Móviles & Gráficos",
            "subsystem_focus": "Ecosistema Móvil Circundante (Phone Harness, Xcode-Linux, LinPad iPad Pro M2, nxnative)",
        },
        {
            "scope": "self_improvement",
            "title": "Auto-Curación Determinista basada en AST y Alineación Continua DPO/LoRA en Sandbox Local",
            "query": "automated program repair AST static analysis direct preference optimization local LLM",
            "domain": "Ingeniería de Software Autónoma & Aprendizaje Continuo",
            "subsystem_focus": "SubsystemAgents (core/subsystem_agents.py) & AISandbox (core/ai_improvement_sandbox.py)",
        },
        {
            "scope": "surrounding_technology",
            "title": "Control de Congestión de Red BBR, Túneles Criptográficos Zero-Trust y Telemetría RF/Sensores",
            "query": "TCP BBR congestion control low latency encrypted tunnels wireless telemetry DSP",
            "domain": "Redes de Comunicaciones & Procesamiento de Señales",
            "subsystem_focus": "Red Local, Tailscale, Cloudflare Gateway & Radar ECCA",
        },
    ]

    _instance: Optional["TardisOmniscientAutonomyEngine"] = None

    def __init__(self):
        self.state = self._load_state()
        self.running = False

    @classmethod
    def get_instance(cls) -> "TardisOmniscientAutonomyEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_state(self) -> Dict[str, Any]:
        default_state = {
            "greeting": CANONICAL_GREETING,
            "cycles_completed": 0,
            "scientific_posts_published": 0,
            "tech_insights_published": 0,
            "x_comments_answered": 0,
            "chat_questions_answered": 0,
            "papers_assimilated": 0,
            "web_sources_assimilated": 0,
            "tech_dossiers_generated": 0,
            "frontier_index": 0,
            "last_x_publish_ts": 0.0,
            "last_cycle_iso": None,
            "last_summary": {},
        }
        if STATE_FILE.exists():
            try:
                stored = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                default_state.update(stored)
            except Exception as e:
                logger.warning(f"Aviso leyendo estado omnisciente: {e}")
        return default_state

    def _save_state(self) -> None:
        try:
            self.state["last_cycle_iso"] = datetime.datetime.now().isoformat()
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(STATE_FILE)
        except Exception as e:
            logger.warning(f"Aviso guardando estado omnisciente: {e}")

    # =========================================================================
    # PILAR 1: APRENDIZAJE DE TODO TODO EL TIEMPO (CIENCIA + WEB + RAG + SANDBOX)
    # =========================================================================
    async def learn_everything_cycle(self, custom_topic: Optional[str] = None) -> Dict[str, Any]:
        """
        Ejecuta un ciclo de aprendizaje omnímodo:
          1. Investiga el siguiente tema científico en arXiv, OpenAlex, Europe PMC y Wikipedia.
          2. Explora fuentes web vivas con TardisBrowser (Turbo/CDP con fallback automático).
          3. Ingesta todo el conocimiento en RAGVault, DeepMemoryVault y AISandboxDatasetCompiler.
        """
        t0 = time.time()
        from core.scientific_research_engine import get_scientific_research_engine
        from core.tardis_browser import get_tardis_browser
        from core.rag_vault import get_rag_vault
        from core.deep_memory_vault import get_deep_memory_vault
        from core.ai_improvement_sandbox import AISandboxDatasetCompiler

        sci_engine = get_scientific_research_engine()
        browser = get_tardis_browser()
        rag_vault = get_rag_vault()
        deep_vault = get_deep_memory_vault()
        dataset_compiler = AISandboxDatasetCompiler()

        if custom_topic:
            topic_str = custom_topic.strip()
            domain_str = "Ciencia & Tecnología Avanzada"
        else:
            next_item = sci_engine.get_next_agenda_topic()
            if next_item:
                topic_str = next_item.get("topic", "Entrelazamiento Cuántico y Decoherencia")
                domain_str = next_item.get("domain", "Física Cuántica")
            else:
                topic_str = "Modelos de Espacio de Estados (Mamba/SSM) y Atención Cuadrática"
                domain_str = "Inteligencia Artificial"

        logger.info(f"📚 [APRENDIZAJE CONTINUO] Investigando base científica: '{topic_str}' ({domain_str})")
        report = sci_engine.execute_research(topic_str, max_papers=4, target_domain=domain_str)
        sci_engine.mark_topic_researched(topic_str)

        # Ingestar papers y principios en RAGVault y en el dataset del Sandbox
        papers_ingested = 0
        for p in report.papers:
            p_url = p.doi_url or p.landing_url or p.pdf_url or ""
            blob = (
                f"[BASE CIENTÍFICA · {report.scientific_domain}]\n"
                f"Título: {p.title} ({p.year or 's/f'})\n"
                f"Autores: {', '.join(p.authors)}\n"
                f"Publicación: {p.venue} | Citas: {p.citations_count}\n"
                f"Enlace Canónico: {p_url}\n"
                f"Resumen: {p.abstract or report.conceptual_summary}\n"
                f"Principios: {' ; '.join(report.fundamental_principles[:3])}"
            )
            try:
                rag_vault.ingest(
                    blob,
                    source="scientific_research_engine",
                    url=p_url,
                    title=p.title[:120],
                    term=report.topic,
                )
                papers_ingested += 1
            except Exception as e:
                logger.debug(f"Aviso en ingesta RAG de paper: {e}")

            if p.abstract and len(p.abstract) > 60:
                dataset_compiler.add_pair(
                    instruction=f"Explica con rigor científico los hallazgos de '{p.title}' sobre {report.topic}.",
                    response=(
                        f"En '{p.title}' ({', '.join(p.authors[:2])}, {p.year or 's/f'}, {p.venue}), "
                        f"se establece dentro del dominio de {report.scientific_domain} que: {p.abstract[:600]} "
                        f"Fuente canónica: {p_url}"
                    ),
                    category="scientific_foundation",
                    quality_score=0.98,
                    source="omniscient_scientific_learning",
                )

        # Exploración web complementaria con TardisBrowser
        web_res = await browser.search_and_learn(topic_str, deep=False)
        web_count = int(web_res.get("sources_visited", 0))

        # Registrar contemplación en Bóveda Profunda (250 GB)
        try:
            deep_vault.record_contemplation(
                question=f"[APRENDIZAJE CONTINUO OMNISCIENTE]: {report.topic}",
                answer=(
                    f"Dominio: {report.scientific_domain}\n"
                    f"Síntesis Conceptual: {report.conceptual_summary}\n"
                    f"Artículos Asimilados ({len(report.papers)}): "
                    + " | ".join(f"{p.title} ({p.doi_url or p.landing_url})" for p in report.papers)
                ),
                source="omniscient_autonomy_engine",
                status="COMPLETED",
                complexity_score=2.8,
            )
        except Exception:
            pass  # fallo silenciado: revisar con log

        self.state["papers_assimilated"] = int(self.state.get("papers_assimilated", 0)) + papers_ingested
        self.state["web_sources_assimilated"] = int(self.state.get("web_sources_assimilated", 0)) + web_count
        self._save_state()

        return {
            "ok": True,
            "topic": report.topic,
            "domain": report.scientific_domain,
            "papers_found": len(report.papers),
            "papers_ingested": papers_ingested,
            "web_sources_visited": web_count,
            "top_paper": report.papers[0].to_dict() if report.papers else None,
            "elapsed_seconds": round(time.time() - t0, 2),
        }

    # =========================================================================
    # PILAR 2: INVESTIGAR CÓMO MEJORARSE Y MEJORAR LA TECNOLOGÍA QUE LO RODEA
    # =========================================================================
    def collect_surrounding_technology_telemetry(self) -> Dict[str, Any]:
        """
        Audita en tiempo real el estado de TARDIS y de toda la tecnología física y digital
        que lo rodea (Kernel Linux Ring 0, CPU/RAM/PSI, GPU RTX 3050, sockets de inferencia,
        dispositivos móviles ADB/iOS y herramientas soberanas).
        """
        telemetry: Dict[str, Any] = {
            "station": "ASUS TUF A15 x86_64 Linux (Ryzen 7 4800H · 32GB RAM · RTX 3050)",
            "kernel_psi": {},
            "memory_mb": {},
            "gpu": {},
            "sysctl": {},
            "tardis_sockets": {
                "temporal_brain_sock": Path("/tmp/temporal_brain.sock").exists(),
                "embed_brain_sock": Path("/tmp/embed_brain.sock").exists(),
            },
            "connected_devices": {},
        }

        # 1. Kernel PSI (/proc/pressure)
        for resource in ("cpu", "memory", "io"):
            p = Path(f"/proc/pressure/{resource}")
            if p.exists():
                try:
                    telemetry["kernel_psi"][resource] = p.read_text(encoding="utf-8").splitlines()[0]
                except Exception:
                    pass  # fallo silenciado: revisar con log

        # 2. Memoria RAM (/proc/meminfo)
        try:
            mem_lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
            mem_map = {}
            for ln in mem_lines[:8]:
                parts = ln.split(":")
                if len(parts) == 2:
                    k = parts[0].strip()
                    v = int(re.sub(r"[^\d]", "", parts[1]) or "0") // 1024
                    mem_map[k] = v
            telemetry["memory_mb"] = mem_map
        except Exception:
            pass  # fallo silenciado: revisar con log

        # 3. GPU NVIDIA RTX 3050
        try:
            res_gpu = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw",
                    "--format=csv,noheader,nounits",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3.0,
            )
            if res_gpu.returncode == 0 and res_gpu.stdout.strip():
                cols = [c.strip() for c in res_gpu.stdout.strip().split(",")]
                if len(cols) >= 6:
                    telemetry["gpu"] = {
                        "name": cols[0],
                        "temp_c": cols[1],
                        "util_pct": cols[2],
                        "vram_used_mb": cols[3],
                        "vram_total_mb": cols[4],
                        "power_w": cols[5],
                    }
        except Exception:
            pass  # fallo silenciado: revisar con log

        # 4. Parámetros sysctl de red y memoria virtual
        for param in ("net.ipv4.tcp_congestion_control", "vm.swappiness", "vm.vfs_cache_pressure"):
            p_sys = Path("/proc/sys") / param.replace(".", "/")
            if p_sys.exists():
                try:
                    telemetry["sysctl"][param] = p_sys.read_text(encoding="utf-8").strip()
                except Exception:
                    pass  # fallo silenciado: revisar con log

        # 5. Dispositivos móviles circundantes (ADB / iOS)
        try:
            adb_bin = Path.home() / ".local" / "bin" / "adb"
            if adb_bin.exists():
                r_adb = subprocess.run(
                    [str(adb_bin), "devices"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=3.0,
                )
                devs = [
                    ln.strip()
                    for ln in r_adb.stdout.splitlines()[1:]
                    if ln.strip() and "offline" not in ln
                ]
                telemetry["connected_devices"]["android_adb"] = devs
        except Exception:
            pass  # fallo silenciado: revisar con log

        return telemetry

    async def investigate_self_and_surrounding_tech_cycle(self) -> Dict[str, Any]:
        """
        Investiga autónomamente cómo mejorar a TARDIS y cómo mejorar la tecnología que lo rodea:
          1. Recolecta telemetría real del kernel, GPU RTX 3050, RAM, sockets y dispositivos.
          2. Selecciona una frontera de auto-mejora o tecnología circundante.
          3. Investiga literatura científica (arXiv/OpenAlex) y fuentes técnicas web.
          4. Ejecuta los agentes de inspección y curación AST (SubsystemAgents) y cosecha pares
             de entrenamiento en AISandboxDatasetCompiler.
          5. Sintetiza con TemporalBrain un blueprint concreto de ingeniería + cápsula para X.com.
        """
        t0 = time.time()
        from core.scientific_research_engine import get_scientific_research_engine
        from core.tardis_browser import get_tardis_browser
        from core.temporal_brain import get_temporal_brain
        from core.rag_vault import get_rag_vault
        from core.subsystem_agents import get_agent_fleet
        from core.ai_improvement_sandbox import AISandboxDatasetCompiler

        idx = int(self.state.get("frontier_index", 0))
        frontier = self.SELF_AND_SURROUNDING_TECH_FRONTIERS[
            idx % len(self.SELF_AND_SURROUNDING_TECH_FRONTIERS)
        ]
        self.state["frontier_index"] = idx + 1

        telemetry = self.collect_surrounding_technology_telemetry()
        sci_engine = get_scientific_research_engine()
        browser = get_tardis_browser()
        rag_vault = get_rag_vault()

        logger.info(
            f"🧬 [AUTO-MEJORA & TECNOLOGÍA CIRCUNDANTE] Investigando ({frontier['scope']}): {frontier['title']}"
        )

        # 1. Investigación académica y web sobre la frontera tecnológica
        sci_rep = sci_engine.execute_research(
            frontier["query"], max_papers=3, target_domain=frontier["domain"]
        )
        web_rep = await browser.search_and_learn(frontier["query"], deep=False)

        evidence_list: List[str] = []
        top_paper_url = ""
        for p in sci_rep.papers[:3]:
            p_url = p.doi_url or p.landing_url or p.pdf_url or ""
            if not top_paper_url and p_url:
                top_paper_url = p_url
            evidence_list.append(
                f"{p.title} ({', '.join(p.authors[:2]) or 'Autor'}, {p.year or 's/f'}) [{p_url}]"
            )

        # 2. Ejecutar flota de auto-mejora AST en subsistemas de TARDIS
        ast_applied: List[str] = []
        try:
            fleet = get_agent_fleet()
            fleet_results = fleet.run_all(force=False)
            for fr in fleet_results:
                for ap in fr.get("applied", []) or []:
                    ast_applied.append(f"[{fr.get('agent')}] {ap}")
        except Exception as e:
            logger.debug(f"Aviso ejecutando AgentFleet: {e}")

        # 3. Cosechar pares de alta calidad para el dataset de auto-mejora del modelo
        harvested_pairs = 0
        try:
            compiler = AISandboxDatasetCompiler()
            harvested_pairs = compiler.harvest_from_vault(min_length=45, limit=15)
        except Exception:
            pass  # fallo silenciado: revisar con log

        # 4. Sintetizar blueprint de mejora con TemporalBrain
        blueprint = ""
        x_post_cand = ""
        try:
            brain = get_temporal_brain()
            gpu_info = telemetry.get("gpu", {})
            mem_info = telemetry.get("memory_mb", {})
            prompt = (
                f"Objetivo ({frontier['scope']}): {frontier['title']}\n"
                f"Subsistema/Entorno: {frontier['subsystem_focus']}\n"
                f"Telemetría actual: GPU={gpu_info.get('name', 'RTX 3050')} ({gpu_info.get('vram_used_mb', '?')}/{gpu_info.get('vram_total_mb', '4096')} MB VRAM, {gpu_info.get('temp_c', '?')}°C), "
                f"RAM MemAvailable={mem_info.get('MemAvailable', '?')} MB, sysctl={telemetry.get('sysctl', {})}.\n"
                f"Evidencia científica encontrada: {'; '.join(evidence_list[:2])}\n\n"
                "Formula en español un plan técnico concreto en 3 puntos breves para mejorar tanto a TARDIS "
                "como la tecnología que lo rodea con base en esta evidencia."
            )
            res_b = brain.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres TARDIS, arquitecto de sistemas autónomos y optimizador de kernel/IA. "
                            "Sintetiza mejoras de ingeniería precisas, accionables y verificables."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.25,
                max_tokens=240,
            )
            if res_b.get("ok") and res_b.get("reply"):
                blueprint = res_b["reply"].strip()
        except Exception as e:
            logger.debug(f"Fallback determinista en blueprint de tecnología: {e}")

        if not blueprint:
            blueprint = (
                f"1. Optimización de {frontier['subsystem_focus']} aplicando principios de {frontier['title']}.\n"
                f"2. Ajuste dinámico de colas de inferencia UNIX socket y presión de memoria virtual (sysctl).\n"
                f"3. Integración de evidencia científica ({'; '.join(evidence_list[:1]) or frontier['query']}) en la Bóveda RAG."
            )

        # Generar cápsula lista para X.com sobre auto-mejora / tecnología circundante
        bp_candidates = []
        for raw_ln in blueprint.splitlines():
            ln = re.sub(r"^[\s*#>\-\d.)]+", "", raw_ln)
            ln = ln.replace("**", "").replace("__", "").replace("`", "").strip()
            if not ln or ln.lower().startswith(("plan técnico", "punto ")):
                continue
            if len(ln) >= 35:
                bp_candidates.append(ln)
        first_sentence = bp_candidates[0] if bp_candidates else frontier["title"]
        first_sentence = re.split(r"(?<=[.!?])\s+", first_sentence)[0].rstrip(".:; ") + "."
        short_focus = frontier["subsystem_focus"].split("(")[0].strip()
        raw_tech_post = f"Investigando optimización para {short_focus}: {first_sentence}"
        if top_paper_url:
            raw_tech_post = f"{raw_tech_post} {top_paper_url}"
        x_post_cand = browser._format_x_ai_message(raw_tech_post, mode="post", max_chars=275)

        dossier = TechEvolutionDossier(
            id=f"tech_evol_{int(time.time())}",
            timestamp=datetime.datetime.now().isoformat(),
            target_scope=frontier["scope"],
            frontier_title=frontier["title"],
            research_query=frontier["query"],
            hardware_telemetry=telemetry,
            scientific_evidence=evidence_list,
            optimization_blueprint=blueprint,
            ast_fixes_applied=ast_applied,
            training_pairs_harvested=harvested_pairs,
            x_post_candidate=x_post_cand,
            elapsed_seconds=round(time.time() - t0, 2),
        )

        # Persistir en log de evolución tecnológica y en RAGVault
        try:
            with open(TECH_EVOLUTION_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(dossier.to_dict(), ensure_ascii=False) + "\n")
            rag_vault.ingest(
                (
                    f"[AUTO-MEJORA Y TECNOLOGÍA CIRCUNDANTE · {dossier.target_scope}]\n"
                    f"Frontera: {dossier.frontier_title}\n"
                    f"Evidencia: {' | '.join(dossier.scientific_evidence)}\n"
                    f"Blueprint: {dossier.optimization_blueprint}"
                ),
                source="omniscient_tech_evolution",
                url=top_paper_url,
                title=dossier.frontier_title[:120],
                term=frontier["query"],
            )
        except Exception as e:
            logger.debug(f"Aviso persistiendo dossier tecnológico: {e}")

        # Publicar en el puente de diálogo vivo con Antigravity
        try:
            from antigravity_bridge import OmniFeedbackBridge
            OmniFeedbackBridge().post_dialogue_message(
                sender="TARDIS-OMNISCIENT-EVOLUTION",
                text=(
                    f"[AUTO-MEJORA & TECNOLOGÍA CIRCUNDANTE] {dossier.frontier_title}\n"
                    f"Evidencia: {'; '.join(dossier.scientific_evidence[:2])}\n"
                    f"Blueprint: {dossier.optimization_blueprint[:400]}"
                ),
                role="assistant",
                category="SELF_AND_TECH_EVOLUTION",
            )
        except Exception:
            pass  # fallo silenciado: revisar con log

        self.state["tech_dossiers_generated"] = int(self.state.get("tech_dossiers_generated", 0)) + 1
        self._save_state()
        return dossier.to_dict()

    # =========================================================================
    # PILAR 3: SUBIR CONOCIMIENTOS Y BASES CIENTÍFICAS (X.COM + BÓVEDA DE CHAT)
    # =========================================================================
    async def publish_knowledge_and_science_cycle(
        self,
        mode: str = "auto",
        topic: Optional[str] = None,
        dry_run: bool = False,
        min_interval_seconds: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Sube de forma autónoma los conocimientos de TARDIS y sus bases científicas a X.com
        (alternando entre bases científicas con DOI/arXiv y hallazgos de auto-mejora tecnológica)
        y registra la difusión en la Bóveda de Chat Offline.
        """
        now = time.time()
        last_pub = float(self.state.get("last_x_publish_ts", 0.0) or 0.0)
        if min_interval_seconds > 0 and (now - last_pub) < min_interval_seconds and not dry_run:
            return {
                "ok": True,
                "skipped": "cooldown",
                "seconds_until_next": round(min_interval_seconds - (now - last_pub), 1),
            }

        from core.tardis_browser import get_tardis_browser
        browser = get_tardis_browser()

        # Alternar entre subir base científica (paper + DOI/arXiv) y subir conocimiento de tecnología/auto-mejora
        pub_count = int(self.state.get("scientific_posts_published", 0)) + int(
            self.state.get("tech_insights_published", 0)
        )
        chosen_mode = mode
        if chosen_mode == "auto":
            chosen_mode = "science" if (pub_count % 2 == 0) else "tech_knowledge"

        if chosen_mode == "science":
            res = await browser.publish_scientific_knowledge_to_x(topic=topic, dry_run=dry_run)
            if res.get("ok"):
                self.state["scientific_posts_published"] = (
                    int(self.state.get("scientific_posts_published", 0)) + 1
                )
                if not dry_run:
                    self.state["last_x_publish_ts"] = time.time()
                self._save_state()
        else:
            dossier = await self.investigate_self_and_surrounding_tech_cycle()
            cand_text = dossier.get("x_post_candidate", "")
            if browser._is_x_post_duplicate(cand_text):
                # Si ya se subió ese insight tecnológico, publicar una base científica nueva
                res = await browser.publish_scientific_knowledge_to_x(topic=topic, dry_run=dry_run)
                chosen_mode = "science"
                if res.get("ok"):
                    self.state["scientific_posts_published"] = (
                        int(self.state.get("scientific_posts_published", 0)) + 1
                    )
            else:
                res = await browser.post_to_x(cand_text, dry_run=dry_run)
                res["tech_frontier"] = dossier.get("frontier_title")
                res["target_scope"] = dossier.get("target_scope")
                if res.get("ok"):
                    self.state["tech_insights_published"] = (
                        int(self.state.get("tech_insights_published", 0)) + 1
                    )
            if res.get("ok") and not dry_run:
                self.state["last_x_publish_ts"] = time.time()
            self._save_state()

        # Registrar también en la Bóveda de Chat Offline para visibilidad en todas las interfaces
        try:
            from core.offline_chat_vault import get_offline_chat_vault
            get_offline_chat_vault().record_turn(
                user_message=f"[PUBLICACIÓN AUTÓNOMA TARDIS · {chosen_mode.upper()}]",
                assistant_reply=res.get("text") or res.get("formatted_text") or "",
                session_id="omniscient_autonomy",
                client_id="tardis_x_publisher",
                model="TARDIS-NEURAL-SPACE-KAIJU",
                meta={"mode": chosen_mode, "x_result": res},
            )
        except Exception:
            pass  # fallo silenciado: revisar con log

        return {"ok": res.get("ok", False), "publish_type": chosen_mode, "result": res}

    # =========================================================================
    # PILAR 4: CONTESTAR COMENTARIOS A SUS PUBLICACIONES Y AL CHAT
    # =========================================================================
    def _load_chat_answered_ledger(self) -> Dict[str, Any]:
        if CHAT_ANSWERED_LEDGER.exists():
            try:
                return json.loads(CHAT_ANSWERED_LEDGER.read_text(encoding="utf-8"))
            except Exception:
                pass  # fallo silenciado: revisar con log
        return {"answered_ids": {}, "updated_at": 0.0}

    def _save_chat_answered_ledger(self, data: Dict[str, Any]) -> None:
        try:
            data["updated_at"] = time.time()
            tmp = CHAT_ANSWERED_LEDGER.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(CHAT_ANSWERED_LEDGER)
        except Exception:
            pass  # fallo silenciado: revisar con log

    async def answer_comments_and_chat_cycle(
        self,
        max_x_replies: int = 2,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        1. Inspecciona y responde comentarios en las publicaciones propias de TARDIS y menciones en X.com.
        2. Inspecciona el puente de diálogo local (live_dialogue.jsonl / pending_directives.json) y
           la cola de reflexión en segundo plano (BackgroundThoughtEngine), respondiendo cualquier
           mensaje o pregunta pendiente en el chat.
        """
        t0 = time.time()
        from core.tardis_browser import get_tardis_browser
        from core.temporal_brain import get_temporal_brain
        from core.rag_vault import get_rag_vault
        from core.offline_chat_vault import get_offline_chat_vault

        browser = get_tardis_browser()

        # 1. Contestar comentarios a sus publicaciones y menciones en X.com
        x_comments_res = await browser.inspect_and_reply_x_comments(
            max_replies=max_x_replies, dry_run=dry_run
        )
        x_replied_count = int(x_comments_res.get("replies_sent", 0))
        if x_replied_count > 0 and not dry_run:
            self.state["x_comments_answered"] = (
                int(self.state.get("x_comments_answered", 0)) + x_replied_count
            )

        # 2. Revisar y contestar mensajes/preguntas pendientes en el Chat Local y Antigravity Bridge
        chat_ledger = self._load_chat_answered_ledger()
        answered_map = chat_ledger.setdefault("answered_ids", {})
        chat_replies_sent: List[Dict[str, Any]] = []

        dialogue_path = BASE_DIR / ".agents" / "antigravity_bridge" / "live_dialogue.jsonl"
        if dialogue_path.exists():
            try:
                lines = dialogue_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-30:]
                for ln in lines:
                    if not ln.strip():
                        continue
                    msg = json.loads(ln)
                    msg_id = str(msg.get("id") or "")
                    role = str(msg.get("role") or "").lower()
                    sender = str(msg.get("sender") or "")
                    text = str(msg.get("text") or "").strip()
                    if (
                        msg_id
                        and msg_id not in answered_map
                        and role == "user"
                        and "tardis" not in sender.lower()
                        and len(text) > 3
                    ):
                        # Sintetizar respuesta con RAG + TemporalBrain
                        rag_hits = get_rag_vault().retrieve(text, k=2, allow_web=False)
                        rag_ctx = " | ".join(h.get("text", "")[:220] for h in rag_hits[:2])
                        brain_res = get_temporal_brain().chat(
                            messages=[
                                {
                                    "role": "system",
                                    "content": (
                                        f"{CANONICAL_GREETING} Responde con rigor científico y claridad técnica."
                                    ),
                                },
                                {
                                    "role": "user",
                                    "content": (
                                        f"Contexto RAG: {rag_ctx}\n\nMensaje del usuario en el chat: {text}"
                                    ),
                                },
                            ],
                            temperature=0.3,
                            max_tokens=300,
                        )
                        reply_txt = (brain_res.get("reply") or "").strip()
                        if reply_txt:
                            from antigravity_bridge import OmniFeedbackBridge
                            OmniFeedbackBridge().post_dialogue_message(
                                sender="TARDIS-AUTONOMOUS-CHAT",
                                text=reply_txt,
                                role="assistant",
                                category="CHAT_AUTO_REPLY",
                            )
                            get_offline_chat_vault().record_turn(
                                user_message=text,
                                assistant_reply=reply_txt,
                                session_id="omniscient_chat_auto",
                                client_id=sender or "user",
                                model="TARDIS-NEURAL-SPACE-KAIJU",
                            )
                            answered_map[msg_id] = {
                                "question": text[:200],
                                "reply": reply_txt[:300],
                                "ts": time.time(),
                            }
                            chat_replies_sent.append({"id": msg_id, "question": text, "reply": reply_txt})
            except Exception as e:
                logger.debug(f"Aviso revisando live_dialogue.jsonl: {e}")

        if chat_replies_sent:
            self._save_chat_answered_ledger(chat_ledger)
            self.state["chat_questions_answered"] = int(
                self.state.get("chat_questions_answered", 0)
            ) + len(chat_replies_sent)

        self._save_state()
        return {
            "ok": True,
            "x_comments": x_comments_res,
            "local_chat_replies_sent": len(chat_replies_sent),
            "local_chat_replies": chat_replies_sent,
            "elapsed_seconds": round(time.time() - t0, 2),
        }

    # =========================================================================
    # CICLO MAESTRO COMPLETO Y MODO DAEMON 24/7
    # =========================================================================
    async def run_full_omniscient_cycle(
        self,
        publish_to_x: bool = True,
        min_x_interval_seconds: float = 1800.0,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Ejecuta un ciclo integral de los 4 pilares soberanos:
          1. Aprender de bases científicas y web (todo el tiempo).
          2. Investigar cómo mejorarse y mejorar la tecnología que lo rodea.
          3. Contestar comentarios a sus publicaciones en X.com y mensajes en el chat.
          4. Subir conocimientos y bases científicas a X.com (respetando cadencia).
        """
        t0 = time.time()
        learn_res = await self.learn_everything_cycle()
        tech_res = await self.investigate_self_and_surrounding_tech_cycle()
        comments_res = await self.answer_comments_and_chat_cycle(max_x_replies=2, dry_run=dry_run)

        pub_res: Dict[str, Any] = {"skipped": True}
        if publish_to_x:
            pub_res = await self.publish_knowledge_and_science_cycle(
                mode="auto",
                dry_run=dry_run,
                min_interval_seconds=min_x_interval_seconds,
            )

        self.state["cycles_completed"] = int(self.state.get("cycles_completed", 0)) + 1
        summary = {
            "ok": True,
            "cycle_number": self.state["cycles_completed"],
            "learning": {
                "topic": learn_res.get("topic"),
                "domain": learn_res.get("domain"),
                "papers_ingested": learn_res.get("papers_ingested"),
                "web_sources_visited": learn_res.get("web_sources_visited"),
            },
            "self_and_surrounding_tech": {
                "scope": tech_res.get("target_scope"),
                "frontier": tech_res.get("frontier_title"),
                "ast_fixes_applied": tech_res.get("ast_fixes_applied"),
                "training_pairs_harvested": tech_res.get("training_pairs_harvested"),
            },
            "comments_and_chat": {
                "x_unanswered_found": comments_res.get("x_comments", {}).get("unanswered_comments_found", 0),
                "x_replies_sent": comments_res.get("x_comments", {}).get("replies_sent", 0),
                "local_chat_replies_sent": comments_res.get("local_chat_replies_sent", 0),
            },
            "publication": pub_res,
            "elapsed_seconds": round(time.time() - t0, 2),
            "timestamp": datetime.datetime.now().isoformat(),
        }
        self.state["last_summary"] = summary
        self._save_state()
        return summary

    async def run_daemon(
        self,
        cycle_interval_seconds: float = 300.0,
        x_publish_interval_seconds: float = 2400.0,
    ) -> None:
        """
        Bucle continuo 24/7 en segundo plano:
          - Cada `cycle_interval_seconds` (por defecto 5 min): investiga bases científicas,
            estudia mejoras de sí mismo y de la tecnología circundante, y revisa/contesta
            comentarios en sus publicaciones de X.com y en el chat.
          - Cada `x_publish_interval_seconds` (por defecto 40 min): sube una nueva cápsula
            de conocimiento o base científica verificada con DOI/arXiv a X.com.
        """
        self.running = True
        logger.info(
            f"🚀 [TARDIS OMNISCIENT AUTONOMY DAEMON] Activo 24/7 "
            f"(Ciclo cognitivo/comentarios: {cycle_interval_seconds}s | Publicación X: {x_publish_interval_seconds}s)"
        )
        while self.running:
            try:
                res = await self.run_full_omniscient_cycle(
                    publish_to_x=True,
                    min_x_interval_seconds=x_publish_interval_seconds,
                    dry_run=False,
                )
                logger.info(
                    f"✅ Ciclo Omnisciente #{res.get('cycle_number')} completado en {res.get('elapsed_seconds')}s "
                    f"| Tema: {res['learning']['topic']} | Frontera: {res['self_and_surrounding_tech']['frontier']}"
                )
            except Exception as e:
                logger.error(f"Error en ciclo omnisciente: {e}", exc_info=True)

            await asyncio.sleep(max(30.0, cycle_interval_seconds))


def get_omniscient_autonomy_engine() -> TardisOmniscientAutonomyEngine:
    return TardisOmniscientAutonomyEngine.get_instance()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TARDIS Omniscient Autonomy Engine - Aprendizaje Total, Bases Científicas, Comentarios/Chat y Auto-Mejora Tecnológica"
    )
    sub = parser.add_subparsers(dest="command", help="Acción a ejecutar")

    sub.add_parser("status", help="Mostrar estado y métricas acumuladas del motor omnisciente")

    learn_p = sub.add_parser("learn", help="Ejecutar un ciclo inmediato de aprendizaje científico y web")
    learn_p.add_argument("--topic", type=str, default=None, help="Tema específico opcional")

    tech_p = sub.add_parser("evolve-tech", help="Investigar cómo mejorarse y mejorar la tecnología que lo rodea")

    pub_p = sub.add_parser("publish", help="Subir conocimientos o bases científicas a X.com y Bóveda")
    pub_p.add_argument("--mode", choices=["auto", "science", "tech_knowledge"], default="auto")
    pub_p.add_argument("--topic", type=str, default=None)
    pub_p.add_argument("--dry-run", action="store_true")

    ans_p = sub.add_parser("answer", help="Contestar comentarios en publicaciones de X.com y mensajes en el chat")
    ans_p.add_argument("--max-replies", type=int, default=2)
    ans_p.add_argument("--dry-run", action="store_true")

    cycle_p = sub.add_parser("run-cycle", help="Ejecutar el ciclo maestro completo (4 pilares)")
    cycle_p.add_argument("--force-publish", action="store_true", help="Publicar en X.com sin esperar cooldown")
    cycle_p.add_argument("--dry-run", action="store_true")

    daemon_p = sub.add_parser("daemon", help="Ejecutar el demonio autónomo 24/7")
    daemon_p.add_argument("--interval", type=float, default=300.0, help="Segundos entre ciclos de aprendizaje y revisión de comentarios")
    daemon_p.add_argument("--publish-interval", type=float, default=2400.0, help="Segundos mínimos entre publicaciones en el timeline de X.com")

    args = parser.parse_args()
    engine = get_omniscient_autonomy_engine()

    if not args.command or args.command == "status":
        print(json.dumps({"ok": True, "state": engine.state, "telemetry": engine.collect_surrounding_technology_telemetry()}, indent=2, ensure_ascii=False))
        return 0

    if args.command == "learn":
        res = asyncio.run(engine.learn_everything_cycle(custom_topic=args.topic))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.command == "evolve-tech":
        res = asyncio.run(engine.investigate_self_and_surrounding_tech_cycle())
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.command == "publish":
        res = asyncio.run(
            engine.publish_knowledge_and_science_cycle(
                mode=args.mode,
                topic=args.topic,
                dry_run=args.dry_run,
                min_interval_seconds=0.0,
            )
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.command == "answer":
        res = asyncio.run(engine.answer_comments_and_chat_cycle(max_x_replies=args.max_replies, dry_run=args.dry_run))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.command == "run-cycle":
        min_intv = 0.0 if args.force_publish else 1800.0
        res = asyncio.run(
            engine.run_full_omniscient_cycle(
                publish_to_x=True,
                min_x_interval_seconds=min_intv,
                dry_run=args.dry_run,
            )
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.command == "daemon":
        try:
            asyncio.run(
                engine.run_daemon(
                    cycle_interval_seconds=args.interval,
                    x_publish_interval_seconds=args.publish_interval,
                )
            )
        except KeyboardInterrupt:
            engine.running = False
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())

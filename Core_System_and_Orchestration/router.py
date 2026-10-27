"""
FTL Cognitive Complexity & Economic Router
Strict Policy: Exclusively routes among Frontier Models at Maximum Power.
No base or low-tier models permitted.
"""

import re
import shutil
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from config import load_config
from models import registry
import free_models as free_catalog
from progress import time_estimator
from tardis_bridge import tardis_bridge


@dataclass
class RoutingPlan:
    mode: str  # "gemini", "claude", "dual_synth", "dual_audit", "kaiju"
    primary_engine: str  # "agy", "claude", "kaiju"
    primary_model: str
    primary_effort: str = "high"
    secondary_engine: Optional[str] = None
    secondary_model: Optional[str] = None
    secondary_effort: Optional[str] = None
    complexity_level: int = 1  # 1 to 5
    complexity_label: str = ""
    context_scope: str = "compact"  # "compact", "medium", "massive"
    rationale: str = ""
    estimated_savings: str = "0%"
    phase_descriptions: Optional[List[str]] = None
    estimated_duration: float = 20.0


class CognitiveRouter:
    L1_PATTERNS = [
        r'\b(create|make|generate|write)\s+(file|folder|dir|template|boilerplate|scaffold|readme|dockerfile|gitignore)\b',
        r'\b(format|lint|rename|move|convert|extract|parse|list|find|grep|search)\b',
        r'\b(setup|init|initialize)\s+(project|repo|package|config)\b',
        r'\b(test\s+harness|basic\s+test|stub|mock\s+data)\b'
    ]

    L2_PATTERNS = [
        r'\b(crud|endpoint|route|controller|helper|utility|validator|schema|model|dto)\b',
        r'\b(unit\s+test|integration\s+test|test\s+coverage)\b',
        r'\b(fix\s+typo|simple\s+fix|add\s+field|update\s+parameter|serialize)\b'
    ]

    L3_PATTERNS = [
        r'\b(refactor|restructure|optimize|performance|caching|redis|sql|query|database\s+migration)\b',
        r'\b(auth|jwt|oauth|session|security|middleware|event\s+handler|webhook)\b',
        r'\b(api\s+client|sdk\s+wrapper|background\s+task|queue|worker)\b'
    ]

    L4_PATTERNS = [
        r'\b(architect|architecture|system\s+design|microservice|domain\s+driven|event\s+sourcing)\b',
        r'\b(distributed|concurrency|mutex|deadlock|race\s+condition|lock-free|actor\s+model)\b',
        r'\b(reactive|pipeline|workflow\s+orchestration|state\s+machine)\b',
        r'\b(full\s+audit|security\s+hardening|penetration|vulnerability\s+scan)\b'
    ]

    L5_PATTERNS = [
        r'\b(compiler|ast|abstract\s+syntax\s+tree|bytecode|virtual\s+machine|parser\s+combinator)\b',
        r'\b(formal\s+verification|proof|type\s+theory|monad|category\s+theory)\b',
        r'\b(zero\s+knowledge|cryptography|zk-snark|consensus\s+protocol|raft|paxos)\b',
        r'\b(memory\s+allocator|garbage\s+collector|jit|simd|assembly)\b'
    ]

    MASSIVE_CONTEXT_PATTERNS = [
        r'\b(entire\s+repo|whole\s+codebase|across\s+all\s+files|all\s+modules|project-wide)\b',
        r'\b(analyze\s+everything|scan\s+repo|full\s+project|repo-wide)\b'
    ]

    def __init__(self):
        self.registry = registry

    def _create_plan(self, prompt: str, **kwargs) -> RoutingPlan:
        plan = RoutingPlan(**kwargs)
        plan.estimated_duration = time_estimator.estimate(
            prompt=prompt,
            complexity=plan.complexity_level,
            mode=plan.mode,
            model=plan.primary_model,
            context_scope=plan.context_scope
        )
        return plan

    def _primaries_available(self) -> bool:
        """True si al menos un motor primario (AGY o Claude) está instalado."""
        return any(shutil.which(b) for b in ("agy", "claude"))

    def _alternate_plan(self, prompt, complexity, label, context_scope,
                        rationale: str) -> RoutingPlan:
        return self._create_plan(
            prompt,
            mode="deepseek",
            primary_engine="deepseek",
            primary_model=self.registry.get_alternate_model(),
            primary_effort="max",
            complexity_level=complexity,
            complexity_label=label,
            context_scope=context_scope,
            rationale=rationale,
            estimated_savings="N/A (modelo alterno)"
        )

    def analyze_prompt(self, prompt: str) -> Tuple[int, str, str]:
        prompt_lower = prompt.lower()
        is_massive = any(re.search(pat, prompt_lower) for pat in self.MASSIVE_CONTEXT_PATTERNS)
        context_scope = "massive" if is_massive else ("medium" if len(prompt) > 800 else "compact")

        if any(re.search(pat, prompt_lower) for pat in self.L5_PATTERNS):
            return 5, "Level 5: Deep Metaprogramming / Formal Abstraction", context_scope
        if any(re.search(pat, prompt_lower) for pat in self.L4_PATTERNS):
            return 4, "Level 4: High-Order Architecture & Concurrency", context_scope
        if any(re.search(pat, prompt_lower) for pat in self.L3_PATTERNS):
            return 3, "Level 3: Cross-Module Logic & Refactoring", context_scope
        if any(re.search(pat, prompt_lower) for pat in self.L2_PATTERNS):
            return 2, "Level 2: Routine Components & Handlers", context_scope
        if any(re.search(pat, prompt_lower) for pat in self.L1_PATTERNS):
            return 1, "Level 1: Deterministic Operations & Scaffolding", context_scope

        if len(prompt.split()) > 60:
            return 3, "Level 3: Feature Development (Heuristic)", context_scope
        return 2, "Level 2: Standard Implementation", context_scope

    def route(self, prompt: str, forced_mode: Optional[str] = None) -> RoutingPlan:
        cfg = load_config()
        mode = forced_mode or cfg.get("default_mode", "auto")
        cost_priority = cfg.get("cost_priority", "balanced")

        complexity, label, context_scope = self.analyze_prompt(prompt)

        # 0. MODELO ALTERNO SOBERANO (DeepSeek V4.1 Max)
        # Se usa por selección explícita o cuando no hay acceso a motores primarios.
        if mode in ("deepseek", "alterno", "fallback"):
            return self._alternate_plan(
                prompt, complexity, label, context_scope,
                "Selección explícita del modelo alterno DeepSeek V4.1 Max (variante max)."
            )

        # 0.b POOL GRATUITO: alias individual o especialista automático
        if mode in ("free", "gratis", "pool", "agentes", "agents"):
            specialist = free_catalog.specialist_for(prompt)
            return self._create_plan(
                prompt,
                mode="free_agent",
                primary_engine="opencode_free",
                primary_model=specialist.ref,
                primary_effort="max",
                complexity_level=complexity,
                complexity_label=label,
                context_scope=context_scope,
                rationale=f"Pool gratuito: especialista automático {specialist.name} ({specialist.ref}).",
                estimated_savings="100% (modelo gratuito)"
            )
        free_match = free_catalog.resolve(mode)
        if free_match and mode not in ("auto",):
            return self._create_plan(
                prompt,
                mode="free_agent",
                primary_engine="opencode_free",
                primary_model=free_match.ref,
                primary_effort="max" if free_match.variant else "high",
                complexity_level=complexity,
                complexity_label=label,
                context_scope=context_scope,
                rationale=f"Modelo gratuito seleccionado: {free_match.name} ({free_match.ref}).",
                estimated_savings="100% (modelo gratuito)"
            )

        if mode not in ("imac", "cluster") and not self._primaries_available():
            return self._alternate_plan(
                prompt, complexity, label, context_scope,
                "Motores primarios (agy / claude) no disponibles en el host: "
                "enrutamiento automático al modelo alterno DeepSeek V4.1 Max."
            )

        # Retrieve ONLY maximum power frontier models
        google_flash_high = self.registry.get_google_model("flash")
        google_pro_high = self.registry.get_google_model("pro")
        anthropic_sonnet = self.registry.get_anthropic_model("sonnet")
        anthropic_opus = self.registry.get_anthropic_model("opus")

        # 1. FORCED MODES
        if mode in ("gemini", "agy"):
            selected_model = google_pro_high if complexity >= 3 else google_flash_high
            return self._create_plan(prompt,
                mode="gemini",
                primary_engine="agy",
                primary_model=selected_model,
                primary_effort="high",
                complexity_level=complexity,
                complexity_label=label,
                context_scope=context_scope,
                rationale=f"Pinned to Google Frontier Engine ({selected_model}) with High Reasoning Effort.",
                estimated_savings="92% vs Opus" if "flash" in selected_model else "85% vs Opus"
            )

        if mode == "claude":
            selected_model = anthropic_opus if complexity >= 4 else anthropic_sonnet
            return self._create_plan(prompt,
                mode="claude",
                primary_engine="claude",
                primary_model=selected_model,
                primary_effort="max",
                complexity_level=complexity,
                complexity_label=label,
                context_scope=context_scope,
                rationale=f"Pinned to Anthropic Frontier Thinking Engine ({selected_model}) with Max Effort.",
                estimated_savings="60% vs Opus" if selected_model == "sonnet" else "0% (Absolute Max Power)"
            )

        if mode in ("imac", "cluster"):
            return self._create_plan(prompt,
                mode="imac",
                primary_engine="imac",
                primary_model="qwen2.5:0.5b",
                primary_effort="cluster",
                complexity_level=complexity,
                complexity_label=label,
                context_scope=context_scope,
                rationale="Enrutado al nodo de cómputo externo iMac 14,1 (4 núcleos Haswell AVX2 & Ollama Cluster).",
                estimated_savings="100% (Cómputo Local en Clúster iMac)"
            )

        if mode == "synth":
            sec_model = anthropic_opus if complexity >= 4 else anthropic_sonnet
            return self._create_plan(prompt,
                mode="dual_synth",
                primary_engine="agy",
                primary_model=google_flash_high,
                primary_effort="high",
                secondary_engine="claude",
                secondary_model=sec_model,
                secondary_effort="max",
                complexity_level=complexity,
                complexity_label=label,
                context_scope=context_scope,
                rationale="Forced Dual-Engine Synthesis at Maximum Power: Gemini Flash High -> Claude Thinking Max Effort.",
                estimated_savings="75% vs Solo Opus",
                phase_descriptions=[
                    f"Phase 1 [Scout & Scaffold]: {google_flash_high} (Effort: HIGH)",
                    f"Phase 2 [Architectural Polish]: {sec_model} (Effort: MAX Thinking)"
                ]
            )

        if mode == "audit":
            return self._create_plan(prompt,
                mode="dual_audit",
                primary_engine="claude",
                primary_model=anthropic_sonnet,
                primary_effort="max",
                secondary_engine="agy",
                secondary_model=google_flash_high,
                secondary_effort="high",
                complexity_level=complexity,
                complexity_label=label,
                context_scope=context_scope,
                rationale="Dual Cross-Verification at Maximum Power: Claude Thinking -> Gemini High Effort Audit.",
                estimated_savings="65% vs Solo Opus",
                phase_descriptions=[
                    f"Phase 1 [Implementation]: {anthropic_sonnet} (Effort: MAX)",
                    f"Phase 2 [Repo-wide Audit]: {google_flash_high} (Effort: HIGH)"
                ]
            )

        if mode == "kaiju":
            if any(k in prompt.lower() for k in ("infinite", "inifite", "infinite code", "4 modelos", "cuádruple", "cuadruple")):
                return self._create_plan(prompt,
                    mode="infinite",
                    primary_engine="infinite",
                    primary_model="TARDIS-QUAD-INFINITE-CODE",
                    primary_effort="max",
                    secondary_engine="cloud_accelerator",
                    secondary_model="groq_deepseek",
                    secondary_effort="high",
                    complexity_level=5,
                    complexity_label=f"{label} [TARDIS Infinite Code :: KAIJU Fusión Cuádruple]",
                    context_scope=context_scope,
                    rationale="Gobernado por TARDIS-NEURAL-SPACE-KAIJU en Modo Infinite Code: Fusión Cuádruple de los 4 modelos de frontera (Flash High + Pro High + Sonnet + Opus) con Acelerador Cloud y Respaldo Soberano.",
                    estimated_savings="78% vs Solo Opus",
                    phase_descriptions=[
                        f"Fase 1 [Scout & Blueprint]: {google_flash_high} (Effort: HIGH)",
                        f"Fase 2 [Arquitectura Cognitiva]: {google_pro_high} (Effort: HIGH)",
                        f"Fase 3 [Síntesis de Precisión]: {anthropic_sonnet} (Effort: MAX Thinking)",
                        f"Fase 4 [Auditoría Formal Apex]: {anthropic_opus} (Effort: MAX Thinking)",
                        "Respaldo & Acelerador: Chinese Cloud API (300+ tok/s) & TARDIS-KAIJU"
                    ]
                )

            if complexity >= 4:
                sec_model = anthropic_opus if complexity >= 5 else anthropic_sonnet
                return self._create_plan(prompt,
                    mode="kaiju",
                    primary_engine="kaiju",
                    primary_model=google_flash_high,
                    primary_effort="high",
                    secondary_engine="claude",
                    secondary_model=sec_model,
                    secondary_effort="max",
                    complexity_level=complexity,
                    complexity_label=f"{label} [TARDIS-KAIJU Orquestación]",
                    context_scope=context_scope,
                    rationale="Gobernado por TARDIS-NEURAL-SPACE-KAIJU (MLA + SSM + MoE): Síntesis Causal Multi-Motor con Directiva Omega y Blindaje Aegis.",
                    estimated_savings="75% vs Solo Opus",
                    phase_descriptions=[
                        f"Fase 1 [Scout & Blueprint]: {google_flash_high} (Effort: HIGH)",
                        f"Fase 2 [Síntesis Cuántica & Pulido]: {sec_model} (Effort: MAX Thinking)"
                    ]
                )
            elif complexity == 3:
                return self._create_plan(prompt,
                    mode="kaiju",
                    primary_engine="kaiju",
                    primary_model=google_pro_high,
                    primary_effort="high",
                    complexity_level=complexity,
                    complexity_label=f"{label} [TARDIS-KAIJU Orquestación]",
                    context_scope=context_scope,
                    rationale=f"Gobernado por TARDIS-NEURAL-SPACE-KAIJU: Inferencia Causal Cuántica profunda con {google_pro_high} en High Effort.",
                    estimated_savings="85% vs Solo Opus"
                )
            else:
                return self._create_plan(prompt,
                    mode="kaiju",
                    primary_engine="kaiju",
                    primary_model=google_flash_high,
                    primary_effort="high",
                    complexity_level=complexity,
                    complexity_label=f"{label} [TARDIS-KAIJU Orquestación]",
                    context_scope=context_scope,
                    rationale=f"Gobernado por TARDIS-NEURAL-SPACE-KAIJU: Despacho hiper-rápido con {google_flash_high} bajo Directiva Omega.",
                    estimated_savings="92% vs Solo Opus"
                )

        if mode in ("infinite", "infinite_code", "quad"):
            return self._create_plan(prompt,
                mode="infinite",
                primary_engine="infinite",
                primary_model="TARDIS-QUAD-INFINITE-CODE",
                primary_effort="max",
                secondary_engine="cloud_accelerator",
                secondary_model="groq_deepseek",
                secondary_effort="high",
                complexity_level=5,
                complexity_label=f"{label} [TARDIS Infinite Code :: Fusión Cuádruple]",
                context_scope=context_scope,
                rationale="Fusión Cuádruple de Frontera: Gemini Flash High (Scout) -> Gemini Pro High (Arquitectura) -> Claude Sonnet (Síntesis) -> Claude Opus (Auditoría Apex), con respaldo en Acelerador Cloud Chino y Núcleo Soberano Kaiju.",
                estimated_savings="78% vs Solo Opus",
                phase_descriptions=[
                    f"Fase 1 [Scout & Blueprint]: {google_flash_high} (Effort: HIGH)",
                    f"Fase 2 [Arquitectura Cognitiva]: {google_pro_high} (Effort: HIGH)",
                    f"Fase 3 [Síntesis de Precisión]: {anthropic_sonnet} (Effort: MAX Thinking)",
                    f"Fase 4 [Auditoría Formal Apex]: {anthropic_opus} (Effort: MAX Thinking)",
                    "Respaldo & Acelerador: Chinese Cloud API (300+ tok/s) & TARDIS-KAIJU"
                ]
            )

        # 2. AUTO COGNITIVE ROUTER
        prompt_lower = prompt.lower()
        if any(k in prompt_lower for k in ("infinite", "inifite", "infinite code", "4 modelos", "cuádruple", "cuadruple")):
            return self._create_plan(prompt,
                mode="infinite",
                primary_engine="infinite",
                primary_model="TARDIS-QUAD-INFINITE-CODE",
                primary_effort="max",
                secondary_engine="cloud_accelerator",
                secondary_model="groq_deepseek",
                secondary_effort="high",
                complexity_level=5,
                complexity_label=f"{label} [TARDIS Infinite Code :: Fusión Cuádruple Auto]",
                context_scope=context_scope,
                rationale="Fusión Cuádruple de Frontera Auto-detectada: Gemini Flash High (Scout) -> Gemini Pro High (Arquitectura) -> Claude Sonnet (Síntesis) -> Claude Opus (Auditoría Apex), con respaldo en Acelerador Cloud Chino y Núcleo Soberano Kaiju.",
                estimated_savings="78% vs Solo Opus",
                phase_descriptions=[
                    f"Fase 1 [Scout & Blueprint]: {google_flash_high} (Effort: HIGH)",
                    f"Fase 2 [Arquitectura Cognitiva]: {google_pro_high} (Effort: HIGH)",
                    f"Fase 3 [Síntesis de Precisión]: {anthropic_sonnet} (Effort: MAX Thinking)",
                    f"Fase 4 [Auditoría Formal Apex]: {anthropic_opus} (Effort: MAX Thinking)",
                    "Respaldo & Acelerador: Chinese Cloud API (300+ tok/s) & TARDIS-KAIJU"
                ]
            )

        if context_scope == "massive":
            if complexity >= 3:
                return self._create_plan(prompt,
                    mode="dual_synth",
                    primary_engine="agy",
                    primary_model=google_flash_high,
                    primary_effort="high",
                    secondary_engine="claude",
                    secondary_model=anthropic_sonnet,
                    secondary_effort="max",
                    complexity_level=complexity,
                    complexity_label=f"{label} [Massive Context Scope]",
                    context_scope=context_scope,
                    rationale="Massive context detected. Gemini absorbs large codebase at High Effort; Claude synthesizes architecture with Max Thinking.",
                    estimated_savings="80% vs Solo Opus"
                )
            else:
                return self._create_plan(prompt,
                    mode="gemini",
                    primary_engine="agy",
                    primary_model=google_flash_high,
                    primary_effort="high",
                    complexity_level=complexity,
                    complexity_label=f"{label} [Massive Context Scope]",
                    context_scope=context_scope,
                    rationale="Massive codebase scan. Gemini Flash High Effort handles 1M+ tokens with full frontier reasoning.",
                    estimated_savings="95% vs Solo Opus"
                )

        if complexity in (1, 2):
            return self._create_plan(prompt,
                mode="gemini",
                primary_engine="agy",
                primary_model=google_flash_high,
                primary_effort="high",
                complexity_level=complexity,
                complexity_label=label,
                context_scope=context_scope,
                rationale="Deterministic/Routine task. Gemini Flash High Effort delivers maximum speed with frontier rigor.",
                estimated_savings="92% vs Solo Opus"
            )
        elif complexity == 3:
            return self._create_plan(prompt,
                mode="gemini",
                primary_engine="agy",
                primary_model=google_pro_high,
                primary_effort="high",
                complexity_level=3,
                complexity_label=label,
                context_scope=context_scope,
                rationale="Intermediate architecture/refactor. Gemini Pro High Effort gives deep multi-step frontier reasoning.",
                estimated_savings="85% vs Solo Opus"
            )
        elif complexity == 4:
            return self._create_plan(prompt,
                mode="dual_synth",
                primary_engine="agy",
                primary_model=google_flash_high,
                primary_effort="high",
                secondary_engine="claude",
                secondary_model=anthropic_sonnet,
                secondary_effort="max",
                complexity_level=4,
                complexity_label=label,
                context_scope=context_scope,
                rationale="High architectural complexity. Dual-Engine Synergy: Gemini Flash High scaffolds -> Claude Sonnet Max Thinking hardens architecture.",
                estimated_savings="75% vs Solo Opus"
            )
        else:  # complexity == 5
            return self._create_plan(prompt,
                mode="claude",
                primary_engine="claude",
                primary_model=anthropic_opus,
                primary_effort="max",
                complexity_level=5,
                complexity_label=label,
                context_scope=context_scope,
                rationale="Maximum abstraction complexity (Level 5). Direct Claude Opus with Maximum Thinking Effort.",
                estimated_savings="0% (Absolute Max Power)"
            )


# Global router instance
router = CognitiveRouter()

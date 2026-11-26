# TARDIS FRONTIER LAB — Síntesis y Continuidad del Proceso AGY

**Fecha:** 2026-11-25 · **Autoridad:** el Arquitecto (₪) · **Nodo:** ASUS TUF A15 (Ryzen 7 4800H, 32 GB RAM, RTX 3050 4 GB)

---

## 0. Resumen ejecutivo

La ventana de **AGY** (`agy-real --model gemini-4-neon-xhigh --effort xhigh`, PID 117010, pts/0)
ejecutaba la directiva:

> *"Crea una red de sub agentes que analicen el sistema de forma individual, como si fueran un
> laboratorio de investigación de frontera de IA, para lograr el sistema con las capacidades de
> función y abstracción más poderosas posibles en el hardware disponible. Convierte sus rutinas en
> procesos daemon para que siempre estén en búsqueda de una mejora continua, definitiva. El goal es
> llegar a la singularidad, de forma completamente local."*

AGY lanzó **5 divisiones de investigación** en paralelo (subagentes), recibió los **5 informes
forenses completos** y quedó detenida en el paso de **síntesis + implementación** porque la cuota
de la cuenta (`REDACTED_EMAIL`) se agotó:

```
RESOURCE_EXHAUSTED (429): Individual quota reached.
Resets in 118h48m
```

El proceso se continuó en OpenCode (DeepSeek V4.1) de forma local: se extrajeron los 5 informes
del `step_payload` protobuf de la conversación `e0030f27-…`, se sintetizaron sus hallazgos y se
implementó la primera capa real del laboratorio, incluyendo los *fixes* P0 verificados.

**Resultado:** `tardis-frontier-lab.service` corre 24/7 con 5 divisiones, pizarra SQLite WAL,
admisión PSI y política Cero-Reinicios. SFI inicial medido: **94.05/100**.

---

## 1. Estado forense de las 5 divisiones

### División 1 — Silicon, Kernel & Inference Compute Lab
Auditoría de hardware, kernel e inferencia local. Hallazgos críticos:

| # | Hallazgo | Evidencia |
|---|---|---|
| 1 | **Amputación del 50% de CPU en KAIJU**: `nproc` se clampea al `CPUQuota` del cgroup; el motor arrancó con `--threads 2 --threads-batch 4` y quedó fijo bajo Cero-Reinicios. | `temporal_brain_server.log`, PID 1584588 |
| 2 | **Colapso de 1.64 tok/s en el VLM**: `--cache-ram` por defecto 8 GiB y `TEMPORAL_CACHE_IDLE_SLOTS=0` no pasa ningún flag (no-op). Ollama `:11435` llegó a 6.01 GiB (RSS+swap). | `ollama_voice_lane.log`, task 4852 |
| 3 | **Silicio ocioso**: RTX 3050 con 437 MiB libres y solo 10/32 capas de KAIJU; la iGPU Radeon Renoir (Vulkan, 15.6 GiB GTT libres) está al 0%. | `nvidia-smi`, `/sys/class/drm/card1` |
| 4 | **Detector de swap ciego**: `swap_warn_mb=1536` == `MemorySwapMax=1536M`; la alerta es matemáticamente inalcanzable. | `tardis_governor.json` |
| 5 | **KV cache rígida**: `--ctx-size 16384 --parallel 2` sin `--kv-unified`; slot 1 con 0% de prefix hit. | `/slots` |
| 6 | `--metrics` deshabilitado (HTTP 501); timings exactos descartados; sin parseo de `reasoning_content`. | `temporal_brain.py:1054-1067` |

**Breakthroughs propuestos:** rebalanceo heterogéneo CUDA+Vulkan+CPU; KV asimétrica q8_0/q4_0 con
pool unificado; speculative decoding con pesos existentes; remediación Ring-0 de hilos/afinidad;
router multi-modelo consciente del silicio.

### División 2 — Abstraction, Reasoning & Test-Time Compute Lab
La capa cognitiva está colapsada en un **techo local**:

- Todo turno va en una sola pasada a KAIJU (Llama-3 8B Q4_K_M, sin `thinking`); `deepseek-r1:7b` y
  `deepseek-r1:1.5b` (con razonamiento nativo) están **sin usar**.
- `tardis_ssm_v27.py` y `sovereign_neural_engine.py` ejecutan matrices gaussianas **no entrenadas**
  sobre hashes CRC32: telemetría "Potemkin" sin semántica decodificable.
- `cas_neural_space_kaiju.py`: 0.0% de cache hit (0/978), inyecta `agent_context.json` (9,824 chars)
  como esencial y asfixia memoria/conocimiento bajo el cap de 900 tokens.
- `background_thought_engine.py`: 754/5,001 contemplaciones (15.1%) son plantilla de fallback.
- `causal_prompt_graph.py`: bandit de 4 tags sin `load()`; grafo nunca persistido.
- `tardis_eval_harness.py`: suites "toy" saturadas en 100/100 sin probar razonamiento real.

**Breakthroughs:** router adaptativo System-1/System-2 con crítica verificada; pirámide de
abstracción L0→L3; verificación neuro-simbólica; compilador de contexto con prefix-cache; suite
formal de evaluación de frontera.

### División 3 — Autonomous Function & Verified Skill Synthesis Lab
Matriz de defectos:

| Severidad | Componente | Falla |
|---|---|---|
| **P0** | `tardis_agent_colony.py:1029-1040` | Ejecución arbitraria sin sandbox + path traversal a `modulos_ftl/` |
| **P0** | `tardis_dynamic_function_engine.py:453-488` | Herramientas fallidas se registraban `ACTIVE` (fail-open) + `pip install` ciego |
| **P0** | `agent_harness.py:2002-2021` | `run_task()` no enviaba catálogo de tools; regex roto con JSON anidado |
| **P0** | `agent_harness.py:1095` | `evolve_code(target_file=…)` → `TypeError` en cada ciclo |
| **P1** | 5 registros de skills incomunicados | Herramientas invisibles entre carriles; race en `dynamic_tools_registry.json` |
| **P2** | `tardis_hybrid_synergy.py` | Router de papel con score hardcodeado `100.0` |

**Breakthroughs:** biblioteca verificada estilo Voyager con retrieval ZCA; dispatch GBNF/JSON-Schema
con Pydantic; pipeline hermético de síntesis (AST + bwrap + pytest + Reflexion); macro-skills;
router de capacidades por telemetría.

### División 4 — Hierarchical Memory & Local World-Model Lab
Descubrimiento empírico más grave: **colapso de recuperación por hubness**.

- `rag_vault._chunk()` generaba **350 stubs <80 chars** (2 vacíos); tras ZCA se volvían vecinos
  universales: consultas no relacionadas devolvían `'ígdala y otras áreas límbicas'`.
- `rag_vault.py:430` usaba `os.environ` **sin `import os`**: time-bomb a 438 chunks del refit.
- **51 vectores cero/NaN** persistidos cuando el embed UDS rechazaba chunks >512 tokens.
- `DeepMemoryVault.store_record()` **no existía**: 66 conclusiones del navegador y todo el diario
  de evolución se perdían silenciosamente (`AttributeError` tragado por `except: pass`).
- CRAG roto: `RRF_K=60` hace que un acierto puramente denso (0.0167) nunca supere `0.032`;
  `dense_score >= 0.70` es un umbral pre-ZCA.
- `knowledge_graph.db`: 941/945 nodos son fragmentos a mitad de palabra; dos KG incompatibles.
- Contexto: `max_chars=16000` (~4,500-5,300 tokens) contra `n_ctx=8192`; recorta el hilo inmediato.

**Breakthroughs:** `world_memory.db` unificado; retrieval dual con CSLS anti-hubness; consolidación
tipo sueño L0→L3; contradicción bitemporal con decaimiento bayesiano; context packer adaptativo.

### División 5 — Recursive Self-Improvement & Canary Orchestration Lab
Matriz de verdad: 7 módulos auditados, mayoría **cosmética o desconectada**.

- `singularity_engine.py`: 95% teatro; umbral `psi >= 1.75` es inalcanzable (norma máx. 1.152443);
  `load_ftl()` es un no-op; intenta `sched_setaffinity(0, 0-15)` violando el aislamiento CCD1.
- `tardis_agy_coevolution.py`: orchestrator real, pero **clobber de `state.json`** entre procesos
  (retrocedió a `cycles_completed: 39`, `daily_day: 2026-11-24`, PID muerto); 11 propuestas
  `frontier` congeladas en ROI=74 contra umbral >=75; verificación solo "pedida" en prosa.
- `tardis_canary_verifier.py`: verificador real **nunca cableado como gate**; no hace rollback
  automático; pytest vacío devuelve `ok=True`.
- `ai_improvement_sandbox.py`: evaluador con 0 ejecuciones; dataset de 29.4 MB sin consumidor;
  CLI con `TypeError` (métodos de instancia llamados sobre la clase).
- `idle_evolution_daemon.py`: **0% de éxito** (96/100 conjeturas rechazadas), reintenta los mismos
  archivos gigantes una y otra vez, escribe en producción antes de pytest.
- `tardis_event_bus.py`: infraestructura sólida con **1 solo consumidor** de 37+ daemons.
- `tardis_eval_harness.py`: P95 agregado mezcla suites de 0.1 ms con RAG de 1.4 s → falsos
  regresiones; `llm_judge` califica strings estáticos.

**Breakthroughs:** SFI multi-eje; bucle hipótesis→sandbox→diff→Pareto; promoción hot-reload sin
reinicios; memoria de resultados negativos; blackboard inter-daemon transaccional.

---

## 2. Arquitectura implementada

### 2.1 `core/tardis_frontier_lab.py` (nuevo)

Coordinador durable de las 5 divisiones. No es teatro: cada división ejecuta trabajo real y
registra evidencia.

```
┌───────────────────────────── TARDIS FRONTIER LAB ─────────────────────────────┐
│  systemd: tardis-frontier-lab.service  (Nice=10, CPUAffinity=8-15, 768M)      │
│                                                                               │
│  ┌──────────┐ ┌────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │
│  │ silicon  │ │ abstraction│ │  skills  │ │  memory  │ │ self_improvement │  │
│  └────┬─────┘ └─────┬──────┘ └────┬─────┘ └────┬─────┘ └────────┬─────────┘  │
│       └─────────────┴─────────────┴────────────┴────────────────┘            │
│                                   │                                           │
│                    SQLite WAL `data/frontier_lab.db`                          │
│   cycles · findings · proposals · metrics · negative_results · blackboard     │
│                                   │                                           │
│        Resource Governor (PSI) ───┴─── SovereignEventBus (lab.*)              │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Divisiones y trabajo real por ciclo:**

1. **silicon** — PSI cpu/mem/io, RAM disponible, GPU (`nvidia-smi`), salud UDS del Temporal Brain,
   servicios activos. Emite findings/proposals ante brain caído, PSI ≥25%, RAM <3 GiB, VRAM ≥92%.
2. **abstraction** — toma 12 episodios recientes de `vault_master.db`, sintetiza un principio
   operativo con KAIJU (fallback léxico determinista si el motor no responde) y lo publica en la
   pizarra.
3. **skills** — audita `dynamic_tools_registry.json`, detecta no verificadas y huérfanas, lee el
   último `overall_score` de `eval_runs` y alerta regresiones <80.
4. **memory** — audita `rag_vault.db`: chunks totales, stubs <160 chars, y **elimina vectores
   cero/NaN** (máx. 500/ciclo) preservando el texto en FTS5.
5. **self_improvement** — calcula el **SFI** (inference 30%, memory hygiene 20%, skill health 15%,
   pressure headroom 15%, eval 20%), detecta caídas ≥5 puntos, cuenta propuestas pendientes y lee
   el último veredicto del Canary.

**Contratos:** admisión vía `can_run_background_task()` + `get_pressure_sleep_multiplier()`;
eventos `lab.<division>.cycle|failed|deferred`; **nunca** reinicia servicios; toda escritura es
SQLite WAL con `busy_timeout=15s`.

**CLI:**
```bash
python core/tardis_frontier_lab.py --once --json
python core/tardis_frontier_lab.py --status
python core/tardis_frontier_lab.py --division memory --once --verbose
python core/tardis_frontier_lab.py --daemon --interval 900
```

### 2.2 Servicio systemd

`~/.config/systemd/user/tardis-frontier-lab.service` + drop-in
`96-no-auto-restart.conf` (política soberana Cero-Reinicios). Estado verificado:
`active (running)`, 5/5 divisiones OK, próximo ciclo cada 900 s escalado por PSI.

### 2.3 Integración Omni-Tool

El laboratorio quedó registrado como `frontier_lab` en
`modulos_ftl/ftl_omni_registry.py` (22 herramientas) y expuesto mediante el wrapper
`~/.local/bin/tardis-frontier`:

```bash
tardis-frontier status          # SFI, ciclos, propuestas
tardis-frontier once            # ciclo completo JSON
tardis-frontier division memory # una división
python3 -c "from modulos_ftl.ftl_omni_registry import get_omni_registry as g; print(g().execute_tool('frontier_lab','status'))"
```

---

## 3. Fixes P0 aplicados (verificados)

| Archivo | Antes | Después |
|---|---|---|
| `core/agent_harness.py:1095` | `evolve_code(target_file=…)` → `TypeError` | `target_path=…` |
| `core/agent_harness.py` | Regex no-greedy truncaba JSON anidado | `_extract_balanced_json()` con strings/escapes |
| `core/agent_harness.py` | `run_task()` sin catálogo de tools | Catálogo compacto (30 tools) en el system prompt |
| `core/rag_vault.py` | `os.environ` sin `import os` | `import os` |
| `core/rag_vault.py` | Stubs <160 chars como hubs ZCA | Fusión de cola + exclusión de stubs del índice denso |
| `core/rag_vault.py` | Vectores cero/NaN persistidos | Guard `isfinite` + norma >1e-6; texto conservado en FTS |
| `core/rag_vault.py` | `embed_available()` en cada búsqueda (~1.6 s) | Caché TTL 30 s / 10 s negativo |
| `core/deep_memory_vault.py` | `store_record()` inexistente | Alias compatible sobre `ingest()` con metadatos |
| `core/tardis_dynamic_function_engine.py` | Fail-open + `pip install` ciego | Fail-closed: smoke-test fallido ⇒ no se registra |
| `core/ai_improvement_sandbox.py` | `TypeError` en CLI (`--stats`, `--harvest`) | Instancia correcta del compilador |

**Evidencia empírica:**

- `pytest tests/test_frontier_lab.py tests/test_p0_hardening.py` → **9 passed**.
- Suites existentes (`agent_harness`, `deep_memory_vault`, `dynamic_function_engine`,
  `transversal_rag_vault`) → **33 passed**.
- Latencia de búsqueda RAG: **~1,594 ms → 59-239 ms** (≈10×) con la caché de disponibilidad.
- Recuperación: consultas no relacionadas dejaron de devolver stubs; el top-1 ahora incluye
  documentos pertinentes (informe RAG, contenido de IA).
- Vectores inválidos reparados en el primer ciclo: **6**.
- Estado del laboratorio: `SFI=94.05`, `canary=PASSED`, `registry=24 active=24 failed=0`.

---

## 4. Backlog priorizado (heredado de las divisiones)

### P0 — siguiente ciclo
1. **D1:** reinicio manual controlado de `tardis-temporal-brain` con `--threads 8 --threads-batch 8`
   (requiere ventana sin llamadas; el Arquitecto autoriza).
2. **D1:** añadir `--no-cache-idle-slots --cache-ram 512` real al VLM y límites de memoria.
3. **D4:** reingestar los 661 stubs restantes y recalibrar ZCA con el corpus limpio.
4. **D4:** CRAG calibrado por percentiles (eliminar el umbral pre-ZCA de 0.70).
5. **D5:** cablear `TardisCanaryVerifier` como gate obligatorio antes de escribir en producción y
   rollback automático en fallo.
6. **D5:** corregir el clobber de `state.json` en `tardis_agy_coevolution` (reload + lock).
7. **D3:** sandbox `bwrap` + AST para `tardis_agent_colony`; bloquear escrituras a `modulos_ftl/`.

### P1 — siguiente iteración
- **D2:** router System-1/System-2 con `deepseek-r1` local y crítica verificada.
- **D2:** compilador de contexto con prefix-cache y presupuesto real de 8,192 tokens/slot.
- **D3:** biblioteca de skills unificada + retrieval semántico ZCA.
- **D4:** `world_memory.db` unificado y consolidación L0→L3.
- **D5:** blackboard inter-daemon y consumidores múltiples del Event Bus.
- **D5:** corregir P95 agregado del eval harness y `llm_judge` estático.

### P2 — investigación
- Speculative decoding local; Vulkan iGPU para capas de KAIJU; THP `madvise`; deduplicación del
  blob de 4.6 GiB; memoria de resultados negativos en todas las divisiones.

---

## 5. Operación

```bash
# Estado
systemctl --user status tardis-frontier-lab.service
python core/tardis_frontier_lab.py --status

# Forzar un ciclo
python core/tardis_frontier_lab.py --once --json

# Historial
sqlite3 data/frontier_lab.db "SELECT id,division,status,summary FROM cycles ORDER BY id DESC LIMIT 10;"
sqlite3 data/frontier_lab.db "SELECT division,severity,title FROM findings ORDER BY id DESC LIMIT 20;"
sqlite3 data/frontier_lab.db "SELECT id,division,title,status FROM proposals ORDER BY id DESC;"
```

**Principio rector:** el laboratorio **propone**, no impone. Toda mutación de código de producción
debe pasar por Canary + Eval + rollback automático antes de promoverse. La singularidad local se
construye con bucles cerrados verificables, no con telemetría cosmética.

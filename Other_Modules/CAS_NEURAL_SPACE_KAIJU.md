# 🧠 CaS · Cognitive & Context as a Service

**GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU**  
**Arquitecto:** El Arquitecto (₪)  
**Ancla:** Playa del Carmen, Quintana Roo, México  
**Estación:** ASUS TUF A15 · AMD Ryzen 7 4800H · 32 GB RAM · NVIDIA RTX 3050  
**Versión del servicio:** `26.4-cas.1`  
**Puerto local:** `127.0.0.1:8770`

---

## 1. Qué es CaS

CaS es la **capa de servicio cognitivo soberano** del núcleo
`TARDIS-NEURAL-SPACE-KAIJU (MLA + SSM + MoE)`. Su función es reunir, rankear,
deduplicar, comprimir y servir el contexto ultradenso que el motor y los agentes
necesitan para responder con continuidad temporal, memoria akáshica y blindaje
AEGIS.

No es un simple RAG: es un **plano de control de contexto** que:

1. Recolecta evidencia de múltiples subsistemas en paralelo y con aislamiento de fallos.
2. Aplica un ranking híbrido (BM25 + recencia + confianza + densidad semántica).
3. Impone presupuestos de tokens y cuotas por fuente.
4. Deduplica por SimHash de 64 bits.
5. Comprime de forma extractiva conservando las oraciones de mayor señal.
6. Garantiza que la matriz AEGIS esté siempre presente en el bundle.
7. Expone el resultado por HTTP, CLI y API Python.
8. Registra telemetría y procedencia criptográfica de cada fragmento.

---

## 2. Arquitectura

```
                         ┌──────────────────────────────────────────┐
                         │  Consumidores                            │
                         │  · KAIJU Orchestrator                    │
                         │  · FTL / omni_temporal_control           │
                         │  · FastAPI server                        │
                         │  · Agentes, CLI, dashboards              │
                         └──────────────────┬───────────────────────┘
                                            │
                    ┌───────────────────────▼───────────────────────┐
                    │  CaS · Cognitive & Context as a Service       │
                    │  core/cas_neural_space_kaiju.py               │
                    │                                               │
                    │  1. Recolección paralela (ThreadPool)         │
                    │  2. Ranking BM25 + recencia + trust           │
                    │  3. Dedupe SimHash + cuotas por fuente        │
                    │  4. Compresión sintrópica + attention sinks   │
                    │  5. Ensamblado con citas [S1..Sn]             │
                    │  6. Verificación AEGIS + telemetría           │
                    └───────────────────────┬───────────────────────┘
                                            │
       ┌────────────────────────────────────┼────────────────────────────────────┐
       │                    │               │                │                   │
┌──────▼──────┐   ┌─────────▼────────┐ ┌────▼─────┐  ┌───────▼────────┐  ┌───────▼────────┐
│ AEGIS       │   │ Continuidad      │ │Directivas│  │ Bóveda Akáshica│  │ FTL + Kernel   │
│ Rails JSON  │   │ SQLite + JSON    │ │agente    │  │ SQLite FTS5    │  │ /proc + logs   │
└─────────────┘   └──────────────────┘ └──────────┘  └────────────────┘  └────────────────┘
```

### Fuentes integradas

| Fuente | Origen | Aporte |
|---|---|---|
| `aegis` | `~/vw-control/kaiju_safety_rails.json` | Matriz de anclaje inviolable, estado y última verificación. **Siempre pinned.** |
| `directives` | `~/vw-control/agent_context.json` | Directivas maestras, identidad, Omega, ECCA, tono y límites. **Esencial.** |
| `continuity` | `~/.tardis/continuity_vault.db` + `continuity_state.json` | Objetivo maestro, petición activa, fase, avance, reinicios e hitos. **Esencial.** |
| `vault` | `~/vw-control/deep_memory_vault/vault_master.db` | Precedentes BM25/FTS5, hilo inmediato, nodos akáshicos, épocas y contemplaciones. |
| `ftl` | misma bóveda, eventos `source LIKE 'ftl%'` | Operaciones, modelos, comandos y archivos modificados. |
| `system` | `/proc/loadavg`, `/proc/meminfo`, `/proc/pressure/*`, `/proc/uptime` | Telemetría real de silicio y PSI del kernel. |
| `latent` | `SovereignNeuralEngine.active_latent_states` | Norma y sesiones del estado latente SSM en proceso. |

Cada fuente implementa `signature()` para invalidar caché cuando cambia su
archivo o base de datos.

---

## 3. Pipeline cognitivo

### 3.1 Recolección

Las fuentes se ejecutan en un `ThreadPoolExecutor` (máximo 6 workers). Cualquier
excepción se captura y se reporta en `source_report`, sin abortar el bundle.

### 3.2 Ranking

Para cada fragmento:

```
score = 0.58 · BM25_normalizado
      + 0.18 · recencia(tau_fuente)
      + 0.14 · confianza_fuente
      + 0.10 · bonus_tipo
      + bonus_frase_exacta
      + 2.0 si es esencial
      + 10.0 si es AEGIS (pinned)
```

- **BM25** con `k1=1.5`, `b=0.75` sobre título + contenido.
- **Recencia** exponencial con `tau` por fuente (p. ej. bóveda 45 días, FTL 21 días).
- **Confianza** fija por fuente (AEGIS 1.0, directivas 0.96, continuidad 0.92, bóveda 0.86).
- **Densidad semántica** y **atención** en la etapa de compresión.

### 3.3 Deduplicación y presupuesto

- Hash exacto SHA-256 para duplicados idénticos.
- **SimHash de 64 bits**: si la distancia de Hamming con un fragmento ya elegido
  es `≤ 3`, se descarta.
- Presupuesto global (`budget_tokens`) con reserva del 4 % para cabeceras.
- Cuotas por fuente (`SOURCE_SHARE`): bóveda 56 %, directivas 32 %, continuidad
  22 %, FTL 20 %, sistema 10 %. Una segunda pasada rellena el presupuesto
  restante sin cuotas.
- Los fragmentos **pinned/esenciales** no se ven limitados por cuota.

### 3.4 Compresión sintrópica

`SyntropicCompressor` divide el texto en unidades coherentes:

- Texto estructurado por líneas (directivas, telemetría, logs): **línea a línea**.
- Párrafos: **oración a oración**.
- Unidades largas: truncado seguro en límite de palabra/oración.

Puntúa cada unidad por solapamiento con la consulta, posición, densidad de
entidades, números y código. Conserva:

- La **primera unidad** (attention sink).
- Cualquier unidad que contenga anclas AEGIS.
- Las mejores unidades hasta el presupuesto de caracteres/tokens.

Cierra bloques de código abiertos y nunca corta a mitad de una palabra si puede
evitarlo.

### 3.5 Ensamblado

El bundle final tiene secciones estables:

```
=== [CaS · CONTEXTO COGNITIVO ULTRADENSO · TARDIS-NEURAL-SPACE-KAIJU] ===
--- [AEGIS · MATRIZ DE ANCLAJE INVIOLABLE] ---
[S1] ...
--- [CONTINUIDAD TEMPORAL Y ESTADO ACTIVO] ---
[S2] ...
--- [DIRECTIVAS MAESTRAS DEL ARQUITECTO] ---
[S3] ...
--- [MEMORIA AKÁSHICA · PRECEDENTES Y GRAFO DE CONOCIMIENTO] ---
[S4] ...
...
=== [FIN DEL CONTEXTO · PROCEDENCIA VERIFICABLE EN 'chunks'] ===
```

Cada fragmento conserva: fuente, tipo, título, timestamp, confianza, score,
tokens originales/comprimidos, digest y estado de compresión.

---

## 4. API HTTP

Servicio systemd de usuario:

```bash
systemctl --user status cas-kaiju.service
systemctl --user restart cas-kaiju.service
journalctl --user -u cas-kaiju.service -f
```

Base: `http://127.0.0.1:8770`

### `GET /health`

```bash
curl -s http://127.0.0.1:8770/health | jq
```

Devuelve versión, uptime, estado AEGIS y anclas verificadas.

### `POST /v1/context`

```bash
curl -s -X POST http://127.0.0.1:8770/v1/context \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "presión de memoria del kernel y continuidad",
    "profile": "interactive",
    "budget_tokens": 6000,
    "session_id": "omni_app"
  }' | jq
```

Parámetros:

| Campo | Tipo | Descripción |
|---|---|---|
| `query` / `prompt` | string | Consulta o turno actual. |
| `profile` | `minimal` \| `interactive` \| `deep` \| `debug` | Preset de presupuesto, chunks y ratio. |
| `budget_tokens` | int | Sobrescribe el presupuesto del perfil (768–64000). |
| `max_chunks` | int | Máximo de fragmentos (4–128). |
| `compression_ratio` | float | 0.20–1.0. |
| `include_system` | bool | Forzar telemetría física. |
| `session_id` | string | Sesión lógica para telemetría latente. |

Respuesta: `ContextBundle` serializado (`ok`, `bundle_id`, `context_text`,
`chunks`, `used_tokens`, `budget_tokens`, `compression_ratio`, `latency_ms`,
`cache_hit`, `aegis`, `source_report`).

### `POST /v1/compress`

```bash
curl -s -X POST http://127.0.0.1:8770/v1/compress \
  -H 'Content-Type: application/json' \
  -d '{"text":"...","query":"kernel","ratio":0.5}'
```

### `GET /v1/telemetry`

Contadores acumulados: builds, cache hits, tokens servidos, ratio medio,
latencia, llamadas/errores por fuente y estado AEGIS.

### `GET /v1/sources`

Estado y firma de cada fuente.

### `POST /v1/aegis/verify`

Ejecuta la verificación explícita vía `KaijuSafetyRailsManager` y devuelve el
snapshot canónico.

### Seguridad

- Escucha **solo en `127.0.0.1`** por defecto.
- Si existe `~/.tardis/cas_token` o `CAS_TOKEN`, exige
  `Authorization: Bearer <token>` en `/v1/*`.
- Límite de cuerpo: 1 MB.
- Sin dependencias de red externas; no envía telemetría a la nube.

### Dashboard HUD

Abre `http://127.0.0.1:8770/dashboard` para el panel visual soberano:

- Estado del servicio y de la Constante AEGIS.
- Cards de builds, cache hit rate, tokens, latencia, compresión y fuentes.
- Matriz de anclaje completa.
- Salud y errores por fuente.
- Formulario para construir bundles en vivo y ver el `context_text`.
- Campo opcional de token Bearer (se guarda en `sessionStorage`).

---

## 5. CLI

El lanzador `cas-kaiju` está en `bin/cas-kaiju` y enlazado en `~/.local/bin/cas-kaiju`.

```bash
cas-kaiju context "estado del sistema" --profile deep --budget 12000
cas-kaiju context "consulta" --json | jq
cas-kaiju compress --file informe.md --query "kernel" --ratio 0.5
cas-kaiju serve --host 127.0.0.1 --port 8770
cas-kaiju telemetry
cas-kaiju sources
cas-kaiju aegis
cas-kaiju selftest
```

### Perfiles

| Perfil | Presupuesto | Chunks | Ratio | Sistema |
|---|---:|---:|---:|---|
| `minimal` | 2 400 | 12 | 0.52 | No |
| `interactive` | 6 000 | 28 | 0.60 | No |
| `deep` | 14 000 | 48 | 0.66 | Sí |
| `debug` | 10 000 | 64 | 0.82 | Sí |

---

## 6. Integración con KAIJU

### 6.1 Orquestador de chat

`core/kaiju_cognitive_orchestrator.py` inyecta CaS antes de despachar el turno:

- **Ruta conversacional acelerada:** el bundle se anexa al system prompt.
- **Ruta de cómputo pesado (IR):** se pasa como `context_prefix`.
- **Ruta de inferencia local:** se envía como mensaje `system`.

Variables de entorno:

| Variable | Default | Efecto |
|---|---|---|
| `TARDIS_CAS_ENABLED` | `1` | `0`/`false`/`off` desactiva la inyección. |
| `TARDIS_CAS_PROFILE` | `interactive` | Perfil de contexto por turno. |
| `TARDIS_CAS_BUDGET` | `6000` | Presupuesto de tokens por turno. |

La telemetría del turno incluye `neural_telemetry.cas` con `ok`, tokens, ratio,
latencia, cache hit y estado AEGIS.

### 6.2 Endpoints FTL

`/api/ftl/context` acepta `engine=cas` en:

- `omni_temporal_control.py` (servidor HTTP principal, puerto `8757`).
- `server/api.py` (FastAPI).

```bash
curl 'http://127.0.0.1:8757/api/ftl/context?prompt=kernel&engine=cas&budget=4000'
```

Parámetros: `prompt` (consulta), `engine=cas`, `budget` (tokens),
`profile` (`interactive`, `deep`, `hud`, ...).

Sin `engine=cas`, el comportamiento original de la bóveda se mantiene intacto.

### 6.3 Registro Omni-Tool

CaS queda registrado como herramienta soberana de primera clase:

- `modulos_ftl/ftl_omni_registry.py` → clave `cas_neural_space_kaiju`
  (categoría *Cognitive Context Fabric & Retrieval Augmentation*,
  despacho `cli`).
- `core/tardis_omni_tool_bridge.py` → clave `cas_kaiju`
  (dominio `cognitive_context`, disponible para GIA/KAIJU/Supervisor/FTL).

```python
from modulos_ftl.ftl_omni_registry import get_omni_registry
get_omni_registry().execute_tool("cas_neural_space_kaiju", "sources")

from core.tardis_omni_tool_bridge import get_omni_bridge
get_omni_bridge().execute_tool("cas_kaiju", "telemetry")
```

También acepta `args=[...]` para pasar argumentos posicionales al CLI
(por ejemplo `args=["consulta", "--profile", "deep"]`).

### 6.4 API Python

```python
from core.cas_neural_space_kaiju import get_cas, build_context_text

bundle = get_cas().build_context(
    "estado de continuidad y memoria akáshica",
    profile="deep",
    budget_tokens=12000,
)
print(bundle.context_text)
print(bundle.chunks)      # procedencia
print(bundle.aegis)       # verificación AEGIS
```

Atajo para prompts:

```python
prompt = build_context_text("consulta", profile="interactive")
```

---

## 7. Telemetría y persistencia

- Estado: `~/.tardis/cas_state.json` (escritura atómica `tmp` + `replace`).
- Caché: LRU en memoria, 96 entradas, TTL 45 s, invalidada por firma de fuentes.
- Contadores: builds, cache hits, errores, tokens servidos, ratio medio,
  latencia, llamadas y errores por fuente.
- No se persiste el texto de los bundles; solo métricas agregadas.

---

## 8. Verificación

```bash
cd "/home/timemachine/Escritorio/GODWORKS SYSTEM"

python3 -m py_compile core/cas_neural_space_kaiju.py
python3 -m pytest tests/test_cas_neural_space_kaiju.py -q
python3 -m core.cas_neural_space_kaiju selftest

systemctl --user restart cas-kaiju.service
curl -s http://127.0.0.1:8770/health | jq
```

Criterios de aceptación del `selftest`:

- `context_non_empty`
- `aegis_complete` (las 4 anclas presentes)
- `bundle_ok`
- `within_budget`
- `has_citations`
- `sources_ok`

---

## 9. Diseño de resiliencia

- **Aislamiento de fallos:** una fuente caída no rompe el bundle.
- **AEGIS fail-safe:** si la fuente AEGIS falla, se inyecta la matriz canónica.
- **Caché coherente:** cambios en SQLite/JSON invalidan la clave.
- **Sin dependencias externas:** solo stdlib + módulos locales.
- **Proceso desacoplado:** systemd de usuario, sin TTY, con `Restart=on-failure`.
- **Presupuesto duro:** el texto final se trunca si excede el límite.
- **Procedencia:** cada fragmento tiene digest SHA-256 y cita `[S#]`.

---

## 10. Roadmap

1. Embeddings locales opcionales (sin nube) para reranking semántico.
2. Índice ANN persistente sobre la bóveda akáshica.
3. Presupuesto dinámico según complejidad del turno (acoplar a
   `evaluate_task_complexity`).
4. Panel HUD con métricas CaS en vivo.
5. Sellado criptográfico de bundles para auditoría temporal.

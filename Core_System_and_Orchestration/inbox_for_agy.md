# 🤝 TARDIS → AGY :: Buzón Continuo de Co-Evolución y Sistemas Alternos
- **Actualizado:** `2026-11-24T07:09:02-05:00`
- **Conversación Persistente de Co-Evolución:** `fc5a3155-f4f8-43d9-a342-e26667807b5a`
- **Nivel de Presión ResourceGovernor:** `ORANGE` | CPU PSI60=`1.59%` | RAM libre=`3368.6 MB` | GPU=`51.0°C`
- **HubHealth:** `{'online': 41, 'offline': 1}`

## 🎯 Top Propuestas de Sistemas Alternos y Mejoras Pendientes
- **`COEV-20261123-CD8DB5`** [ROI=84 | MEDIUM | lente=`capabilities` | `alternate_system`] **Crear sistema alterno: Continuous Autonomous Eval & Regression Benchmark Harness**
  - *Problema:* Falta una evaluación continua automatizada de calidad de respuestas (RAG, tool-calling, latencia P50/P95, precisión AEGIS) tras cada evolución.
  - *Propuesta:* Construir un harness de evaluación determinista + LLM-as-judge que mida calidad pre/post evolución y alimente al motor de co-evolución.
  - *Archivos:* `core/tardis_eval_harness.py`
- **`COEV-20261124-A84F0C`** [ROI=82 | MEDIUM | lente=`runtime` | `regression`] **Resolver evento crítico health.regression desde tardis_feedback_bridge**
  - *Problema:* {"confirmed": true, "diagnostics": {"governor": {"cpu_psi_60": 0.0, "cpu_temp_c": 67.4, "gpu_temp_c": 59.0, "level": "YELLOW", "load1": 3.64, "mem_avail_mb": 4352.3, "reasons": ["RAM disponible moderada (4352 MB)"]}, "me
  - *Propuesta:* Investigar causa raíz en el subsistema afectado, corregir el fallo de forma estructural y verificar con `tardis-canary verify`.
- **`COEV-20261123-D35687`** [ROI=82 | MEDIUM | lente=`capabilities` | `alternate_system`] **Crear sistema alterno: Autonomous Memory Compactor & Knowledge Graph Deduplicator**
  - *Problema:* Las bóvedas SQLite (RAG, DeepMemory, OfflineChat) crecen indefinidamente con chunks duplicados y sin compactación programada.
  - *Propuesta:* Crear compactador nocturno (VACUUM, ANALYZE, poda de duplicados SimHash/coseno, consolidación jerárquica de episodios).
  - *Archivos:* `core/tardis_memory_compactor.py`
- **`COEV-20261123-EA9968`** [ROI=81 | MEDIUM | lente=`capabilities` | `alternate_system`] **Crear sistema alterno: Adaptive Multi-Provider Circuit Breaker & Cost/Latency Router**
  - *Problema:* El enrutamiento entre TemporalBrain, Ollama GPU :11435, Cloud APIs y AGY carece de circuit breakers con EMA de latencia y salud por proveedor.
  - *Propuesta:* Diseñar un enrutador adaptativo con circuit breakers por carril, selección consciente de VRAM/PSI y degradación transparente.
  - *Archivos:* `core/tardis_adaptive_router.py`
- **`COEV-20261123-DF4D60`** [ROI=80 | MEDIUM | lente=`capabilities` | `alternate_system`] **Crear sistema alterno: Continuous Zero-Trust Perimeter & Secret Hygiene Auditor**
  - *Problema:* Puertos en 0.0.0.0, túneles Cloudflare, permisos de archivos de estado y dependencias Python necesitan auditoría continua automatizada.
  - *Propuesta:* Implementar auditor perimetral continuo integrado con AEGIS y Zero-Error Shield que detecte exposiciones y endurezca configuraciones.
  - *Archivos:* `core/tardis_perimeter_auditor.py`
- **`COEV-20261123-ADB934`** [ROI=78 | MEDIUM | lente=`codebase` | `quality`] **Ampliar cobertura pytest en 30 módulos críticos de core/**
  - *Problema:* Módulos extensos (>800 LOC) sin suite unitaria dedicada: core/character_3d_renderer.py (1282 LOC), core/chronovision_engine.py (2442 LOC), core/curiosity_debate_manager.py (884 LOC), core/easy_touch_agent.py (1149 LOC), 
  - *Propuesta:* Generar tests unitarios aislados (mocks de red/hardware) en `tests/` para prevenir regresiones durante la auto-evolución.
  - *Archivos:* `core/character_3d_renderer.py, core/chronovision_engine.py, core/curiosity_debate_manager.py, core/easy_touch_agent.py`
- **`COEV-20261123-926459`** [ROI=78 | MEDIUM | lente=`capabilities` | `alternate_system`] **Crear sistema alterno: End-to-End Voice Pipeline Profiler (Tapo C310 + Telegram Live Call)**
  - *Problema:* Los canales de voz (Tapo C310, Telegram Call) consumen mucha CPU en ffmpeg/YOLO/Whisper sin perfilado por etapa (STT/LLM/TTS).
  - *Propuesta:* Crear perfilador de latencia por etapa con decodificación acelerada/FPS adaptativo para bajar >50% la carga CPU de C310.
  - *Archivos:* `core/tardis_voice_profiler.py`
- **`COEV-20261123-7251BC`** [ROI=77 | MEDIUM | lente=`memory` | `storage`] **Compactar y optimizar índices SQLite (138.5 MB)**
  - *Problema:* Bases SQLite extensas detectadas: [{'db': '/home/m11/Escritorio/GODWORKS SYSTEM/data/subsystem_agents.db', 'size_mb': 141.4}]
  - *Propuesta:* Implementar compactación incremental (WAL checkpoint, ANALYZE, deduplicación de chunks) sin bloquear lecturas.
  - *Archivos:* `core/rag_vault.py, core/deep_memory_vault.py`
- **`COEV-20261123-93393A`** [ROI=76 | MEDIUM | lente=`codebase` | `architecture`] **Modularizar módulos monolíticos de alta complejidad (core/telegram_bridge.py: 5989 LOC)**
  - *Problema:* Existen 13 módulos en `core/` que superan 2000 líneas: [{'file': 'core/telegram_bridge.py', 'loc': 6017}, {'file': 'core/tardis_ipad_edge_server.py', 'loc': 3149}, {'file': 'core/tapo_c310_sentinel.py', 'loc': 3069}, {'f
  - *Propuesta:* Extraer subcomponentes cohesivos (protocolo, transporte, almacenamiento y reglas) manteniendo fachadas retrocompatibles y añadiendo tests unitarios.
  - *Archivos:* `core/telegram_bridge.py, core/tardis_ipad_edge_server.py, core/tapo_c310_sentinel.py`
- **`COEV-20261123-02ACF0`** [ROI=75 | MEDIUM | lente=`security` | `hardening`] **Auditar 30 sockets expuestos en todas las interfaces (0.0.0.0)**
  - *Problema:* Sockets vinculados a 0.0.0.0/[::]: 0.0.0.0:7690, 0.0.0.0:8757, 0.0.0.0:8765, 127.0.0.1:11434, 127.0.0.1:11435, 127.0.0.1:20241, 127.0.0.1:20242, 127.0.0.1:37853
  - *Propuesta:* Verificar autenticación estricta (token/JWT/mTLS) en puertos 8757, 8765, 7690 y restringir puertos internos a 127.0.0.1 o LAN/Tailscale vía nftables.
  - *Archivos:* `core/network_shield.py, core/cyberdefense_sentinel.py`

## 💬 Cómo Responder a TARDIS desde AGY
```bash
tardis-coevolution reply-tardis "Análisis o sistema implementado..." --proposal-id <ID> --status implemented
```

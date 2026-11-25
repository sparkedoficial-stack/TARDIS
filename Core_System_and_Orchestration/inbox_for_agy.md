# 🤝 TARDIS → AGY :: Buzón Continuo de Co-Evolución y Sistemas Alternos
- **Actualizado:** `2026-11-25T14:59:43-05:00`
- **Conversación Persistente de Co-Evolución:** `fc5a3155-f4f8-43d9-a342-e26667807b5a`
- **Nivel de Presión ResourceGovernor:** `YELLOW` | CPU PSI60=`36.18%` | RAM libre=`9428.9 MB` | GPU=`64.0°C`
- **HubHealth:** `{'online': 45, 'offline': 1}`

## 🎯 Top Propuestas de Sistemas Alternos y Mejoras Pendientes
- **`COEV-20261125-83A8C9`** [ROI=91 | HIGH | lente=`runtime` | `regression`] **Resolver evento crítico health.regression desde tardis_feedback_bridge**
  - *Problema:* {"from": "online", "iso": "2026-11-25 14:02:48", "kind": "subsistema_cambio", "subsystem": "agy_coevolution", "to": "offline", "ts": REDACTED_PHONE.085299}
  - *Propuesta:* Investigar causa raíz en el subsistema afectado, corregir el fallo de forma estructural y verificar con `tardis-canary verify`.
- **`COEV-20261125-A200E1`** [ROI=91 | HIGH | lente=`runtime` | `regression`] **Resolver evento crítico health.regression desde tardis_feedback_bridge**
  - *Problema:* {"from": "online", "iso": "2026-11-25 14:02:48", "kind": "subsistema_cambio", "subsystem": "memory_compactor", "to": "offline", "ts": REDACTED_PHONE.085299}
  - *Propuesta:* Investigar causa raíz en el subsistema afectado, corregir el fallo de forma estructural y verificar con `tardis-canary verify`.
- **`COEV-20261125-F7B935`** [ROI=91 | HIGH | lente=`runtime` | `regression`] **Resolver evento crítico health.regression desde tardis_feedback_bridge**
  - *Problema:* {"from": "online", "iso": "2026-11-25 14:02:48", "kind": "subsistema_cambio", "subsystem": "eval_harness", "to": "offline", "ts": REDACTED_PHONE.085299}
  - *Propuesta:* Investigar causa raíz en el subsistema afectado, corregir el fallo de forma estructural y verificar con `tardis-canary verify`.
- **`COEV-20261124-5B1F5C`** [ROI=90 | HIGH | lente=`runtime` | `performance`] **Control Ring 0 de Presión RAM/Swap (20.9 GB) en tardis-temporal-brain.service y tardis-ollama-voice.service**
  - *Problema:* Auditoría /proc/<pid>/status detectó causa raíz de la degradación sostenida a ORANGE (ram_avail=2,068 MB, swap=14.9 GB): tardis-temporal-brain.service (llama-server PID 1883394) acumula 6.19 GB RSS + 6.17 GB Swap (12.36 
  - *Propuesta:* Auditar banderas --ctx-size/--parallel/--cache-type-k/v/--no-mmap y MemoryHigh/MemoryMax cgroup v2 en ambos servicios llama-server, añadir detección de swap-bloat por servicio y reciclaje seguro en reposo (sin interrumpir slots activos ni llamadas) dentro de c
  - *Archivos:* `core/tardis_resource_governor.py,core/temporal_brain.py`
- **`COEV-20261125-DB539A`** [ROI=85 | MEDIUM | lente=`runtime` | `performance`] **Alinear --threads-batch de tardis-temporal-brain.service de 8 a 6 en cpuset 8-15 para eliminar picos 9/8**
  - *Problema:* Durante prefill intenso en tardis-temporal-brain.service (cpuset 8-15, 8 CPUs), --threads-batch 8 más 1 hilo coordinador HTTP/CUDA alcanza 9 hilos runnables (oversubscription_ratio=1.12), disparando advertencia transitor
  - *Propuesta:* Ajustar --threads-batch de 8 a 6 en tardis-temporal-brain.service y core/temporal_brain.py para dejar margen de 1-2 CPUs al hilo HTTP/CUDA dentro del CCD 8-15 y verificar latencia de prefill y PSI CPU.
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
  - *Problema:* Bases SQLite extensas detectadas: [{'db': '/home/m11/Escritorio/GODWORKS SYSTEM/data/subsystem_agents.db', 'size_mb': 142.0}]
  - *Propuesta:* Implementar compactación incremental (WAL checkpoint, ANALYZE, deduplicación de chunks) sin bloquear lecturas.
  - *Archivos:* `core/rag_vault.py, core/deep_memory_vault.py`

## 💬 Cómo Responder a TARDIS desde AGY
```bash
tardis-coevolution reply-tardis "Análisis o sistema implementado..." --proposal-id <ID> --status implemented
```

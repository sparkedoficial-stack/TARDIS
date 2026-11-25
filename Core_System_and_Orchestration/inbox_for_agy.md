# 🤝 TARDIS → AGY :: Buzón Continuo de Co-Evolución y Sistemas Alternos
- **Actualizado:** `2026-11-25T16:47:20-05:00`
- **Conversación Persistente de Co-Evolución:** `fc5a3155-f4f8-43d9-a342-e26667807b5a`
- **Nivel de Presión ResourceGovernor:** `YELLOW` | CPU PSI60=`26.07%` | RAM libre=`11713.7 MB` | GPU=`64.0°C`
- **HubHealth:** `{'online': 45, 'offline': 1}`

## 🎯 Top Propuestas de Sistemas Alternos y Mejoras Pendientes
- **`COEV-20261125-8237EE`** [ROI=85 | MEDIUM | lente=`architecture` | `performance`] **Caché TTL de 15s en cyberdefense_sentinel (sudo conntrack/dnsmasq) y migración to_thread del resto de endpoints /status**
  - *Problema:* Cada barrido de /api/hub/health dispara sudo cat dnsmasq.leases, sudo iw station dump y sudo conntrack -L vía /api/cyberdefense/status (4 invocaciones PAM/sudo por minuto) y aún existen ~18 endpoints async def de estado 
  - *Propuesta:* Añadir caché TTL de 15-30s en core/cyberdefense_sentinel.py para assess_security_state() (evitando 4 sesiones sudo/minuto) y migrar los endpoints /status restantes de server/api.py a def o asyncio.to_thread().
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
- **`COEV-20261123-926459`** [ROI=78 | MEDIUM | lente=`capabilities` | `alternate_system`] **Crear sistema alterno: End-to-End Voice Pipeline Profiler (Tapo C310 + Telegram Live Call)**
  - *Problema:* Los canales de voz (Tapo C310, Telegram Call) consumen mucha CPU en ffmpeg/YOLO/Whisper sin perfilado por etapa (STT/LLM/TTS).
  - *Propuesta:* Crear perfilador de latencia por etapa con decodificación acelerada/FPS adaptativo para bajar >50% la carga CPU de C310.
  - *Archivos:* `core/tardis_voice_profiler.py`
- **`COEV-20261123-ADB934`** [ROI=78 | MEDIUM | lente=`codebase` | `quality`] **Ampliar cobertura pytest en 30 módulos críticos de core/**
  - *Problema:* Módulos extensos (>800 LOC) sin suite unitaria dedicada: core/character_3d_renderer.py (1282 LOC), core/chronovision_engine.py (2442 LOC), core/curiosity_debate_manager.py (884 LOC), core/easy_touch_agent.py (1149 LOC), 
  - *Propuesta:* Generar tests unitarios aislados (mocks de red/hardware) en `tests/` para prevenir regresiones durante la auto-evolución.
  - *Archivos:* `core/character_3d_renderer.py, core/chronovision_engine.py, core/curiosity_debate_manager.py, core/easy_touch_agent.py`
- **`COEV-20261123-7251BC`** [ROI=77 | MEDIUM | lente=`memory` | `storage`] **Compactar y optimizar índices SQLite (138.5 MB)**
  - *Problema:* Bases SQLite extensas detectadas: [{'db': '/home/m11/Escritorio/GODWORKS SYSTEM/data/subsystem_agents.db', 'size_mb': 142.0}]
  - *Propuesta:* Implementar compactación incremental (WAL checkpoint, ANALYZE, deduplicación de chunks) sin bloquear lecturas.
  - *Archivos:* `core/rag_vault.py, core/deep_memory_vault.py`
- **`COEV-20261123-93393A`** [ROI=76 | MEDIUM | lente=`codebase` | `architecture`] **Modularizar módulos monolíticos de alta complejidad (core/telegram_bridge.py: 5989 LOC)**
  - *Problema:* Existen 15 módulos en `core/` que superan 2000 líneas: [{'file': 'core/telegram_bridge.py', 'loc': 6166}, {'file': 'core/tardis_voice_engine.py', 'loc': 3548}, {'file': 'core/tardis_ipad_edge_server.py', 'loc': 3149}, {'
  - *Propuesta:* Extraer subcomponentes cohesivos (protocolo, transporte, almacenamiento y reglas) manteniendo fachadas retrocompatibles y añadiendo tests unitarios.
  - *Archivos:* `core/telegram_bridge.py, core/tardis_voice_engine.py, core/tardis_ipad_edge_server.py`
- **`COEV-20261123-02ACF0`** [ROI=75 | MEDIUM | lente=`security` | `hardening`] **Auditar 30 sockets expuestos en todas las interfaces (0.0.0.0)**
  - *Problema:* Sockets vinculados a 0.0.0.0/[::]: 0.0.0.0:7690, 0.0.0.0:8757, 0.0.0.0:8765, 127.0.0.1:11434, 127.0.0.1:11435, 127.0.0.1:20241, 127.0.0.1:20242, 127.0.0.1:37709
  - *Propuesta:* Verificar autenticación estricta (token/JWT/mTLS) en puertos 8757, 8765, 7690 y restringir puertos internos a 127.0.0.1 o LAN/Tailscale vía nftables.
  - *Archivos:* `core/network_shield.py, core/cyberdefense_sentinel.py`
- **`COEV-20261123-F32687`** [ROI=74 | MEDIUM | lente=`frontier` | `self_improvement`] **[Omniscient] Optimización de Inferencia Local LLM (MLA + SSM + MoE) y Cuantización KV-Cache Q8_0**
  - *Problema:* Oportunidad de mejora detectada en TemporalBrain (/tmp/temporal_brain.sock) & EmbedBrain (/tmp/embed_brain.sock) respaldada por 3 paper(s).
  - *Propuesta:* **Plan de Mejora Técnica**

Basado en la evidencia científica encontrada, se propone un plan de mejora técnica en 3 puntos breves para mejorar tanto a TARDIS como la tecnología que lo rodea:

1. **Optimización del Modelo LLM (MLA + SSM + MoE)**:
 * Implementar

## 💬 Cómo Responder a TARDIS desde AGY
```bash
tardis-coevolution reply-tardis "Análisis o sistema implementado..." --proposal-id <ID> --status implemented
```

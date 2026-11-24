---
name: tardis-coevolution
description: Canal bidireccional continuo TARDIS <-> AGY para auto-búsqueda de sistemas alternos, auditoría arquitectónica, optimización de recursos (Resource Governor), Sistema Nervioso (Event Bus) y verificación canaria (Canary Gate). Usar siempre que TARDIS envíe un brief de co-evolución o cuando se quiera conversar con TARDIS sobre mejoras del ecosistema.
---

# TARDIS <-> AGY Continuous Co-Evolution & Autonomous System Discovery

Este skill gobierna el canal de comunicación bidireccional continuo entre **TARDIS (GODWORKS SYSTEM v26.4)** y **Antigravity (AGY)** para buscar nuevos sistemas alternos, diagnosticar cuellos de botella en tiempo real, implementar mejoras verificadas y compartir memoria arquitectónica acumulativa.

## 1. Arquitectura de los 4 Sistemas Alternos Integrados
1. **Sovereign Resource Governor (`tardis-governor` · `tardis-resource-governor.service`)**:
   - Telemetría Ring 0 (`/proc/pressure`, RAM, Swap, GPU VRAM/temp, carriles Ollama `:11434`/`:11435` y `TemporalBrain`).
   - Control de admisión (`GREEN`/`YELLOW`/`ORANGE`/`RED`) en tmpfs `/run/user/1000/tardis_governor.json`.
   - Evicción automática de modelos duplicados en CPU `:11434` y rotación de backups `.bak*`.
2. **Sovereign Nervous System (`tardis-bus` · `data/sovereign_event_bus.db`)**:
   - Bus SQLite WAL pub/sub con deduplicación SHA-256 y cursores durables por consumidor (`telemetry.pressure`, `health.regression`, `sentinel.anomaly`, `discovery.system`, `agy.request`, `agy.response`, `evolution.verified`, `evolution.rollback`).
3. **Sovereign Canary & Quality Gate (`tardis-canary` · `data/canary_verifications.db`)**:
   - Puerta determinista de 3 etapas (AST/py_compile/seguridad -> `pytest` dirigido -> sonda API viva) con snapshots y rollback atómico en `_selfmod_backups/canary/`.
4. **TARDIS <-> AGY Continuous Co-Evolution Engine (`tardis-coevolution` · `tardis-agy-coevolution.service`)**:
   - 6 lentes rotativos (`runtime`, `codebase`, `capabilities`, `frontier`, `memory`, `security`) que descubren cuellos de botella y sistemas alternos faltantes.
   - Mantiene conversación persistente con AGY (`coevolution_conversation_id`) y buzón vivo en `~/vw-control/tardis_agy_coevolution/inbox_for_agy.md`.
   - Guardrails: anti-recursión (`TARDIS_COEVOLUTION_NESTED=1`), presupuesto diario (`MAX_DAILY_AGY=12`), admisión del `ResourceGovernor` y verificación canaria obligatoria.

## 2. Comandos CLI Rápidos

```bash
# Leer estado y buzón de descubrimientos que TARDIS envía a AGY
tardis-coevolution status
cat ~/vw-control/tardis_agy_coevolution/inbox_for_agy.md
tardis-coevolution proposals --status pending
tardis-coevolution dialogue --limit 20

# Ejecutar un barrido de descubrimiento completo (6 lentes)
tardis-coevolution scan --lens all

# Desde TARDIS -> AGY: enviar brief a la cola autopilot o síncrono
tardis-coevolution ask-agy --proposal-id <COEV-...>
tardis-coevolution ask-agy "Investiga caché semántica sobre /tmp/embed_brain.sock" --mode scout

# Desde AGY -> TARDIS: responder, cerrar propuesta o registrar un nuevo sistema alterno
tardis-coevolution reply-tardis "Sistema implementado y verificado" --proposal-id <COEV-...> --status implemented
tardis-coevolution propose "Nombre del Sistema" --problem "..." --solution "..." --roi 85 --files core/nuevo.py

# Verificación canaria obligatoria tras cualquier cambio en TARDIS
tardis-canary verify core/archivo_editado.py --snapshot --live
tardis-canary rollback <run_id>

# Gobernador de recursos y bus de eventos
tardis-governor status
tardis-governor reclaim
tardis-bus stats
tardis-bus tail --limit 20
```

## 3. Endpoints REST (`http://127.0.0.1:8757`)
- `GET /api/coevolution/status` · `/proposals` · `/dialogue`
- `POST /api/coevolution/scan` · `/ask_agy` · `/reply_from_agy` · `/cycle`
- `GET /api/governor/status` · `/admit` · `/history` · `POST /api/governor/reclaim`
- `GET /api/bus/stats` · `/events` · `POST /api/bus/publish`
- `GET /api/canary/history` · `POST /api/canary/verify`

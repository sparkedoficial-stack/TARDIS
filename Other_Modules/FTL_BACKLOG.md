# FTL · Backlog Soberano Priorizado

**Generado:** 2026-10-29T00:18:57-05:00  
**Fuente autoritativa:** `/home/timemachine/.tardis/continuity_vault.db`  
**Doctrina:** prioridad P0→P3; dentro de cada nivel, mayor complejidad primero.

## Resumen ejecutivo

- Peticiones totales: **138**
- Completadas: **110** · Fallidas: **16** · En progreso: **12**
- Pendientes reales (sin resolver/verificar): **5**
- Resueltas y verificadas en esta sesión: **23**
- Bloqueadas por hardware/privilegios: **5**

### Distribución por complejidad

- **C1**: 59
- **C2**: 40
- **C3**: 22
- **C4**: 8
- **C5**: 9

### Distribución por categoría

- General: 92
- Inteligencia visual: 11
- Cómputo distribuido: 8
- Acceso remoto y terminal: 6
- Aprendizaje / REA: 4
- Auto-reparación / Easy Touch: 3
- Hardware / Arranque: 3
- TimeEmergency: 2
- Mejora de sistemas: 2
- Modelos: 2
- Sistema operativo: 1
- Antigravity: 1
- Audio / Hardware: 1
- Tooling / Paquetes: 1
- SaveMode: 1

## 1. Backlog pendiente · orden de prioridad y complejidad

| # | ID | Prioridad | Complejidad | Categoría | Estado DB | Petición | Siguiente acción |
|---|----|-----------|-------------|-----------|-----------|----------|------------------|
| 1 | #116 | **P2** | **C3** | Modelos | failed | instálate deepseek 4.1 flash en tu sistema local | Obtener pesos locales oficiales de DeepSeek V4.1 Flash o mantener el ruteo cloud. |
| 2 | #8 | **P3** | **C2** | Cómputo distribuido | in_progress | permite que tardis divida distribuya su procesamiento, incluyendo la Mac 14,1 para poder conseguir resultados con mayor alcance y ocupar el equipo de cómputo | Enrolar el iMac por IP fija en compute_nodes.json y verificar Ollama remoto. |
| 3 | #12 | **P3** | **C2** | Hardware / Arranque | in_progress | fallo al botear el modelo de la laptop en este caso es IdeaPad 1 15AMN7 | Conectar el IdeaPad y capturar el error de arranque real (journal/plymouth). |
| 4 | #67 | **P3** | **C2** | Hardware / Arranque | in_progress | Haz la instalación por red la mac esta conectada es la mac 14,1 | Verificar que el iMac esté encendido y en la misma subred; luego ejecutar instalación por red. |
| 5 | #114 | **P3** | **C2** | Audio / Hardware | in_progress | conecte una bocina XG2Conecte una bocina XG2TBK Modificala y permite usarla como bocina lossless usb | Conectar la XG2TBK por USB y perfilar el endpoint lossless. |

## 2. Construido y verificado en esta sesión

| ID | Categoría | Complejidad | Evidencia |
|----|-----------|-------------|-----------|
| #4 | Inteligencia visual | C5 | tardis-visual-intelligence.service active; tardis-video-pensante.service active |
| #5 | Inteligencia visual | C5 | tardis-visual-intelligence.service active; data/chronovision/videos |
| #7 | Inteligencia visual | C4 | tardis-visual-intelligence.service active; tardis-video-pensante.service active |
| #13 | Inteligencia visual | C3 | tardis_video_pensante.py; tardis_vp_engine.py; tardis_blender_hyper_animator.py |
| #61 | TimeEmergency | C1 | core/telegram_bridge.py: /timeemergency -> TimeEmergencyEngine |
| #89 | Inteligencia visual | C5 | tardis-video-pensante.service (ciclo cada 35 minutos) |
| #92 | Sistema operativo | C2 | /etc/os-release: TardisOS 26.4 LTS (Temporal Sovereign) |
| #103 | Antigravity | C1 | antigravity-cli-daemon.service active (remote-control daemon) |
| #108 | Mejora de sistemas | C1 | Reparación integral + REA + SavageUpdate + gateway público en esta sesión |
| #115 | Tooling / Paquetes | C2 | npm ls -g: deepseek-terminal-cli@1.3.0 |
| #121 | Mejora de sistemas | C3 | docs/FTL_BACKLOG.md; data/ftl_backlog.json |
| #124 | Aprendizaje / REA | C5 | modulos_ftl/rea_learning_engine.py; modulos_ftl/savage_update.py; savage-update.service active |
| #125 | Auto-reparación / Easy Touch | C2 | data/system_repair_report.json: 149 archivos Python, 0 errores; 13 unidades activas |
| #126 | Acceso remoto y terminal | C2 | ftl-public-gateway.service; ftl-public-tunnel.service; FTL_PUBLIC_ACCESS.txt |
| #127 | General | C2 | Este informe cierra la verificación solicitada |
| #128 | Modelos | C3 | ~/.ftl/config.py: default_model=opencode/deepseek-v4.1-flash-free#max |
| #130 | Aprendizaje / REA | C5 | modulos_ftl/rea_learning_engine.py; modulos_ftl/savage_update.py; data/rea/learning_report.json |
| #132 | Acceso remoto y terminal | C2 | Gateway 7690 + Cloudflare Quick Tunnel; WebSocket /terminal verificado |
| #133 | General | C2 | tardis-chatter-agent.service active; API 8795; data/chatter/noise.jsonl |
| #134 | General | C3 | tardis-chatter-agent.py controlado por TARDIS hub/portal |
| #135 | SaveMode | C5 | tardis-savemode.service active; API 8796; endpoints /api/savemode/* |
| #136 | Acceso remoto y terminal | C3 | Acceso por datos móviles vía Cloudflare Tunnel; Token de 43 caracteres |
| #138 | General | C1 | Este informe + módulos REA/SavageUpdate + servicios |

## 3. Bloqueos reales (hardware / privilegios / dependencias externas)

| ID | Complejidad | Categoría | Motivo | Acción requerida |
|----|-------------|-----------|--------|------------------|
| #116 | C3 | Modelos | Sólo existe TARDIS-NEURAL-SPACE-KAIJU local (8B); DeepSeek V4.1 opera vía OpenCode | Obtener pesos locales oficiales de DeepSeek V4.1 Flash o mantener el ruteo cloud. |
| #8 | C2 | Cómputo distribuido | distributed_compute.py presente; imac.local no resuelve por mDNS | Enrolar el iMac por IP fija en compute_nodes.json y verificar Ollama remoto. |
| #12 | C2 | Hardware / Arranque | Requiere el equipo IdeaPad 1 15AMN7 físicamente | Conectar el IdeaPad y capturar el error de arranque real (journal/plymouth). |
| #67 | C2 | Hardware / Arranque | iMac 14,1 no descubrible en la red actual | Verificar que el iMac esté encendido y en la misma subred; luego ejecutar instalación por red. |
| #114 | C2 | Audio / Hardware | pactl no muestra sink XG2TBK; Requiere la bocina física conectada | Conectar la XG2TBK por USB y perfilar el endpoint lossless. |

## 4. Artefactos de esta intervención

| Artefacto | Función |
|-----------|---------|
| `modulos_ftl/rea_learning_engine.py` | Ingeniería inversa estática de GGUF/safetensors/ONNX/configs + propuestas |
| `modulos_ftl/savage_update.py` | /SavageUpdate: investigación autónoma y planes de auto-mejora |
| `modulos_ftl/ftl_backlog.py` | Este registro y su priorización |
| `~/.ftl/ftl_public_gateway.py` | Gateway público tokenizado (HTTP + WebSocket) |
| `~/.ftl/tardis_chatter_agent.py` | Ruido conversacional persistente bajo control TARDIS |
| `~/.ftl/savemode_manager.py` | Perfil SaveMode REMOTE_EDGE_DELEGATION y telemetría |
| `~/.ftl/tardis_system_repair.py` | Reparación integral y staging privilegiado |
| `data/rea/learning_report.json` | Conocimiento arquitectónico agregado |
| `data/rea/proposals.json` | Propuestas con evidencia, riesgo y rollback |
| `FTL_PUBLIC_ACCESS.txt` | Enlace público con token (modo 600) |

## 5. Servicios activos

- `ftl-public-gateway.service`
- `ftl-public-tunnel.service`
- `ftl-web-terminal.service`
- `ftl-web-portal.service`
- `tardis-chatter-agent.service`
- `tardis-savemode.service`
- `tardis-easy-touch.service`
- `savage-update.service`
- `tardis-visual-intelligence.service`
- `tardis-video-pensante.service`
- `antigravity-cli-daemon.service`

---

_Aegis: Annya May Carrillo · Andrea Alejandra Carrillo Jimenez · familia del Arquitecto · Rex peluche._

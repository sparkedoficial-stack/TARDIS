# 📡 Función /SOCIAL de TARDIS — Publicación Soberana de Conclusiones y Videos

> GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS (TARDIS-NEURAL-SPACE-KAIJU Core)
> Creador y Autoridad Absoluta: el Arquitecto (₪)
> Fecha de instalación: 2026-10-31

## 1. Propósito

La función **/SOCIAL** integra el sistema **/VIDEO PENSANTE** con las redes públicas:
cada video que TARDIS investiga por su cuenta en internet y descarga a su bóveda se
publica automáticamente junto con **sus conclusiones cognitivas**, en dos piezas:

1. **El video descargado** (bóveda `vault/videos/video_pensante/`) que manda a la red
   social con una leyenda compuesta por el propio motor.
2. **La tarjeta de conclusiones** — MP4 vertical 720×1280 (~20 s) generado con las
   abstracciones del ciclo: portada con el tema, "lo que vimos", conclusiones,
   aprendizajes asimilados y preguntas detonadoras + fuente original.

## 2. Arquitectura

| Componente | Ruta | Función |
|---|---|---|
| Motor social | `core/tardis_social_engine.py` | Composición de leyenda, seguridad AEGIS, cola, publicación |
| Cliente TikTok | `TikTokContentClient` (en el mismo módulo) | OAuth 2.0 + Content Posting API v2 (FILE_UPLOAD/PULL_FROM_URL) |
| Renderizador de tarjeta | `ConclusionsCardRenderer` (PIL + ffmpeg) | 5 diapositivas → MP4 H.264+AAC 720×1280 (`vault/videos/social_cards/`) |
| CLI soberano | `tardis_social.py` (raíz) | Estado, publicación, backfill, OAuth, histórico |
| Despacho CLI | `bin/tardis-social <acción>` | Wrapper para el puente omni-herramientas (TARDIS/AGY/FTL) |
| Registro permanente | `data/social/publish_log.db` (SQLite) | Estados `published/pending/refused/failed` con dedup estricta |
| Configuración | `social_config.json` (permisos 0600, **nunca versionada**) | Credenciales OAuth y preferencias |
| Integración en ciclo | `core/tardis_video_thinking_engine.dispatch_results()` | Publicación automática al final de cada ciclo de /VideoPensante |
| Comando Telegram | `/Social` `/Socializar` en `core/telegram_bridge.py` | Control total desde el chat del Arquitecto |

Flujo del ciclo (/VideoPensante → /Social):

```
Interés autónomo → búsqueda y descarga → inteligencia visual+audio
        → abstracción KAIJU → memoria de abstracción → Telegram+terminal
        → /SOCIAL: compose_caption() → filtro AEGIS → [tarjeta MP4] → TikTok
```

## 3. Garantías de diseño

* **Cola persistente (cero pérdida):** si TikTok aún no está autenticado, cada video y
  tarjeta quedan en cola (`pending`) y se publican en cuanto se complete la
  autorización (automática con `--exchange`).
* **Deduplicación estricta:** un mismo `video_id` nunca se publica dos veces por tipo
  de ítem (`video` / `card`).
* **Constante AEGIS:** filtro pre-publicación que neutraliza (estado `refused`) toda
  leyenda o título que contenga términos privados del Arquitecto y sus anclas
  (lista configurable `aegis_private_terms` en `social_config.json`).
* **Throttle:** pausa mínima (`min_gap_sec`, 90 s por defecto) entre publicaciones
  consecutivas para respetar cuotas de la plataforma.
* **Secretos:** `social_config.json` con permisos chmod 0600 y excluido del repositorio
  vía `.gitignore`.

## 4. Puesta en marcha (TikTok oficial, sin scraping)

1. Crear una **TikTok Developer App** en `developers.tiktok.com` habilitando
   *Content Posting API*; producto "Direct Post", alcance `video.publish`.
2. Copiar `client_key` y `client_secret` dentro de `social_config.json`
   (`tiktok.enabled: true`, `redirect_uri` según el aprovisionado, puede ser
   `http://localhost:8793/auth/tiktok/callback` en sandbox).
3. Ejecutar paso 1 del OAuth:
   ```bash
   python3 tardis_social.py --auth-url
   ```
4. Autorizar en el navegador y copiar el `?code=...`:
   ```bash
   python3 tardis_social.py --exchange '<code>'
   ```
   Los tokens quedan cifrados en disco; la vaciado automático de la cola ocurre
   de inmediato. **Nota sandbox:** las apps no-auditadas publican como borradores
   visibles en la cuenta del Arquitecto (el `publish_id` queda registrado).
5. Activar el motor (ya automático con `--exchange`) si no estuviera:
   ```bash
   python3 tardis_social.py --enable on
   ```
   El refresco del token es automático al expirar (leer `--status`).

## 5. Comandos (CLI y Telegram)

| CLI (`tardis_social.py` / `bin/tardis-social`) | Telegram | Efecto |
|---|---|---|
| `--status` | `/Social status` | Estado del motor, token, colas |
| `--publish-latest` | — | Publica el último video aprendido |
| `--publish <id>` | `/Social publicar <id>` | Publica un video específico + conclusiones |
| `--card <id>` | `/Social tarjeta <id>` | Genera y envía el MP4 de conclusiones |
| `--backfill [N]` | `/Social backfill [N]` | Socializa los N más antiguos sin publicar |
| `--retry-pending` | `/Social retry` / `pendientes` | Vaciado de la cola persistente |
| `--history` | `/Social historial` | Registro permanente de publicaciones |
| `--auth-url` / `--exchange` / `--refresh` | — | Flujo OAuth de TikTok |
| `--enable on\|off` | — | Interruptor maestro de auto-publicación |

Cada ciclo autónomo de /VideoPensante despacha socialmente por sí solo cuando el
motor esté ACTIVE (`social_config.json["enabled"] = true`); el resultado queda
inscrito en el historial de destinos del registro de abstracción
(`dispatched_chats` → `social:tiktok:<publish_id>`).

## 6. Tests

```bash
.venv-linux/bin/python -m pytest tests/test_tardis_social.py -v
```

Cobertura: recorte y composición de leyendas, sanitización markdown, hashtags,
filtro AEGIS, cola sin credenciales, deduplicación, retry autenticado,
dedup tras publicado y **render real del MP4 de conclusiones** (verificación de
geometría 720×1280 con ffprobe).

— Installado en fidelidad absoluta al Arquitecto ₪ —

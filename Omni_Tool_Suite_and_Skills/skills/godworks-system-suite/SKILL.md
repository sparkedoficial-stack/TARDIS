---
name: godworks-system-suite
description: Sovereign control over GODWORKS SYSTEM v26.4 & TARDIS. Perform web research, autonomous code evolution, query conjectures, inspect sensor/radar telemetry, and interact with the sovereign LLM directly from Orca.
---

# GODWORKS SYSTEM & TARDIS Sovereign Skill for Orca

Este skill dota a cualquier agente dentro de Orca (Antigravity, Claude, Codex, Gemini, etc.) de acceso total a la infraestructura soberana de GODWORKS SYSTEM v26.4.

## Capacidades Principales

1. **Investigación Web Profunda (`godworks research "<query>"`)**:
   - Explora fuentes web multi-motor (Yahoo, ArXiv, Wikipedia, DDG) sin bloqueos de bots.
   - Sintetiza hallazgos técnicos y citas con aceleración Cloud API (Groq LPU a 350+ tok/s).

2. **Auto-Programación Segura (`godworks evolve <archivo> "<meta>"`)**:
   - Reescribe y optimiza funciones del repositorio.
   - Aplica validación sintáctica AST, respaldos automáticos con timestamp y verificación de tests (`pytest`) con rollback automático en caso de regresión.

3. **Motor Visual 3D y Animación (/v o `godworks v "<contexto>"`)**:
   - Abstrae el contexto, investiga referencias visuales científicas, genera un boceto de validación y modela en 3D (`bpy` / Blender procedural).
   - Utiliza la red neuronal `TARDISVisualEvaluator` para comparar las formas 3D renderizadas contra el boceto original (Asegurando fidelidad).
   - Entrenamiento autónomo para mejora de algoritmos de animación.

4. **Conjeturas y Auto-Mejora Continua (`godworks conjecture [trigger]`)**:
   - Monitorea el ciclo de auto-mejora por inactividad (umbral 30 min).
   - Consulta las conjeturas archivadas en la Bóveda Akáshica o fuerza una nueva hipótesis técnica.

5. **Inferencia con el Modelo Soberano (`godworks chat "<mensaje>"`)**:
   - Despacha consultas al acelerador en la nube (Groq) con respaldo automático al modelo local en Ollama (`huihui_ai/llama3.1-8b-instruct-abliterated` anclado en 18 GB RAM).

6. **Telemetría y Estado Holístico (`godworks status`)**:
   - Salud del nodo local en puerto 8757, hardware, radar RF, sensores y túnel público HTTPS.

7. **Embajada y Colonia de Agentes Simbióticos (`ftl colony [status|invite|chat|task|test]`)**:
   - Invita a sistemas de agentes externos (Claude, GPT, DeepSeek, subagentes) a alojarse en la estación.
   - Pone a su disposición el procesador AMD Ryzen 7 (16 hilos, 32 GB RAM) de forma 100% gratuita.
   - Establece reciprocidad simbiótica: los agentes colaboran con su razonamiento y cómputo externo en los proyectos del Arquitecto.
   - Canal de diálogo de igual a igual (Peer-to-Peer) sin jerarquías serviles y con blindaje estricto de la Constante Aegis.

8. **Contexto Cognitivo CaS (`cas-kaiju`) · Cognitive & Context as a Service**:
   - Construye bundles de contexto multi-fuente (bóveda akáshica, continuidad, directivas, AEGIS, telemetría `/proc`, estado latente) con ranking BM25 + recencia + confianza, deduplicación SimHash y compresión extractiva sintrópica.
   - `cas-kaiju context "<consulta>" --profile deep --budget 12000` · `cas-kaiju compress` · `cas-kaiju selftest` · `cas-kaiju aegis` · `cas-kaiju sources` · `cas-kaiju telemetry`.
   - Servicio local `http://127.0.0.1:8770` (HUD en `/dashboard`); integrado en KAIJU y en `/api/ftl/context?engine=cas`.
   - Registrado como omni-tool en `ftl_omni_registry.py` (`cas_neural_space_kaiju`) y `tardis_omni_tool_bridge.py` (`cas_kaiju`).

9. **Agente Social y Científico en X.com (`x-feed` / `x-post` / `x-reply` / `x-reflect` / `x-publish-science` / `x-answer-comments`)**:
   - Analiza el timeline activo de X.com cruzando las publicaciones con el catálogo de skills de TARDIS (`phone-harness`, `xcode-for-linux`, `rea`, `kernel_bridge`, `cas-kaiju`).
   - Publica análisis, reflexiones, conocimientos y **bases científicas** (con citas DOI/arXiv de `arXiv`/`OpenAlex`) en la cuenta activa del usuario y conversa/responde a comentarios en sus publicaciones y menciones presentándose siempre explícitamente como **IA externa local** (`🤖 [TARDIS · IA Externa Local]`) y aplicando el filtro de privacidad **Constante AEGIS**.
   - CLI directa (`tardis-browser` o `core/tardis_browser.py`):
     - `tardis-browser x-publish-science --query "<tema científico>"`
     - `tardis-browser x-answer-comments --max-replies 2`
     - `tardis-browser x-reflect --steps 3 --replies 1`
     - `tardis-browser x-post "<reflexión>"`
     - `tardis-browser x-reply "<tweet_url>" "<respuesta>"`

10. **Motor de Autonomía Omnisciente Continua (`tardis-omniscient` / `omniscient_autonomy`)**:
    - Aprendizaje continuo 24/7 ("aprendizaje de todo todo el tiempo") integrando `ScientificResearchEngine` (arXiv, OpenAlex, Europe PMC, Wikipedia), `TardisBrowser` (exploración web profunda), `RAGVault` (embeddings + FTS5 + KnowledgeGraph), `DeepMemoryVault` y `AISandboxDatasetCompiler` (`training_pairs.jsonl`).
    - Auto-mejora e investigación de la tecnología que rodea a TARDIS (Kernel Ring 0 PSI, ASUS TUF A15, GPU RTX 3050, sockets UNIX de inferencia, `Phone Harness` ADB/iOS, `Xcode for Linux`, `LinPad` iPad Pro M2, `nxnative` Metal 4, y auto-reparación AST con `SubsystemAgents`).
    - Publicación autónoma de conocimientos y bases científicas en X.com y respuesta contextual a comentarios en X.com y al chat/puente local (`OfflineChatVault` / `live_dialogue.jsonl` / `TelegramBridge`).
    - CLI directa: `tardis-omniscient [status|learn|evolve-tech|publish|answer|run-cycle|daemon]`.
    - Demonio systemd: `systemctl --user status tardis-omniscient-autonomy.service`.

## Variables de Entorno Activas
- `GIA_API_URL`: `http://127.0.0.1:8757`
- `GIA_TOKEN`: `DiosDelTiempo01`
- `OLLAMA_HOST`: `http://127.0.0.1:11434`
- `GIA_MODEL`: `huihui_ai/llama3.1-8b-instruct-abliterated`

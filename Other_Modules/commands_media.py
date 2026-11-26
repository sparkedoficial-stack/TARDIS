"""core/telegram/commands_media.py - Despachador de comandos creativos, 3D, ChronoVision, video, pixelart, SMS y hardware."""
from __future__ import annotations

from core.telegram.common import *


def handle_media_command(
    self: Any,
    *,
    cmd: str,
    arg_str: str,
    chat_id: Any,
    msg_id: Any,
    user_name: str,
) -> bool:
    """Ejecuta comandos multimedia/creativos/SMS/hardware. Devuelve True si la actualización ya fue atendida."""
    if cmd in ("/mente", "/ruido", "/simbolos", "/metacognicion", "/pensamiento", "/spectrogram"):
        from core.thought_noise_engine import get_thought_noise_engine
        engine = get_thought_noise_engine()
        target_prompt = arg_str or "Introspección soberana y análisis de sistemas de pensamiento"
        frame = engine.generate_thought_frame(prompt=target_prompt, model_name=self.active_model_label, active_step="METAPENSAMIENTO BAJO DEMANDA")

        caption = (
            f"🧠 **[METAPENSAMIENTO SOBERANO · RUIDO & SÍMBOLOS]**\n"
            f"• **Entropía de Shannon:** `{frame['entropy_shannon']:.2f} bits`\n"
            f"• **Sintropía / Coherencia:** `{frame['syntropy_coherence_pct']}%`\n"
            f"• **Símbolos Activos:** {', '.join(frame['active_symbols'][:4])}\n"
            f"• **Interpretación:** El sistema auto-observa su flujo neural como ruido cuántico estructurado colapsando hacia certidumbre contextual."
        )
        self.send_photo(frame["png_bytes"], caption=caption, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/animaciones", "/animations", "/anim_modo"):
        if not arg_str:
            status_str = "ACTIVADA (TARDIS enviará animaciones 2D y 3D en movimiento)" if self.prefer_animations_over_still_images else "DESACTIVADA (imágenes fijas estáticas)"
            self.send_message(
                f"🌀 **[MODO ANIMACIONES TARDIS]**\n"
                f"• **Estado actual:** {status_str}\n"
                f"• **Uso:** `/animaciones on` o `/animaciones off`\n"
                f"• *Tip:* También puedes usar `/animacion <tema>`, `/animacion2d <tema>` o `/animacion3d <modelo>`.",
                chat_id=chat_id,
                reply_to_message_id=msg_id
            )
            return True
        val = arg_str.lower().strip()
        if val in ("on", "si", "sí", "true", "activar", "activado", "1"):
            self.prefer_animations_over_still_images = True
            self.config["prefer_animations_over_still_images"] = True
            self.save_config()
            self.send_message("✅ **Modo Animaciones ACTIVADO**: A partir de ahora TARDIS generará y enviará animaciones fluidas 2D o 3D en bucle continuo en lugar de imágenes fijas.", chat_id=chat_id, reply_to_message_id=msg_id)
        elif val in ("off", "no", "false", "desactivar", "desactivado", "0"):
            self.prefer_animations_over_still_images = False
            self.config["prefer_animations_over_still_images"] = False
            self.save_config()
            self.send_message("ℹ️ **Modo Animaciones DESACTIVADO**: TARDIS volverá a enviar imágenes fijas estáticas.", chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/3d", "/render3d", "/modelo3d", "/objeto3d", "/animacion3d", "/animar3d"):
        from core.render_3d_engine import get_render_3d_engine
        engine = get_render_3d_engine()

        is_explicit_anim = cmd in ("/animacion3d", "/animar3d") or "--anim" in arg_str.lower()
        is_explicit_static = "--static" in arg_str.lower() or "--foto" in arg_str.lower() or "--fija" in arg_str.lower()
        clean_arg = arg_str.replace("--anim", "").replace("--static", "").replace("--foto", "").replace("--fija", "").strip()

        if not clean_arg or clean_arg.lower() in ("list", "catalogo", "lista", "ayuda", "help"):
            items = engine.get_catalog_summary()
            lines = [f"• `{it['id']}`: **{it['title']}** ({it['category']})" for it in items]
            catalog_msg = (
                "🎨 **[ESTUDIO 3D SOBERANO · CATÁLOGO DE MODELOS]**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Puedes explorar, animar y renderizar los siguientes modelos tridimensionales:\n\n"
                + "\n".join(lines) + "\n\n"
                "💡 *Ejemplo de uso:* `/3d dna`, `/3d atom`, `/3d torus`, `/animacion3d tesseract`, `/animacion3d onda`"
            )
            self.send_message(catalog_msg, chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        mesh = engine.get_mesh(clean_arg)
        if not mesh:
            for it in engine.get_catalog_summary():
                if clean_arg.lower() in it["id"] or clean_arg.lower() in it["title"].lower():
                    mesh = engine.get_mesh(it["id"])
                    break
        if not mesh:
            mesh = engine.get_mesh("atom")

        should_animate = (is_explicit_anim or self.prefer_animations_over_still_images) and not is_explicit_static

        if should_animate:
            with ChatActionKeeper(self, chat_id, "upload_video"):
                anim_bytes = engine.render_mesh_animation(
                    mesh,
                    frames=240,
                    fps=self.animation_render_fps,
                    ported_fps=self.animation_telegram_fps,
                    width=self.animation_width,
                    height=self.animation_height,
                    hdr=self.animation_hdr_enabled,
                    style="hologram",
                    show_hud=True
                )
                if anim_bytes:
                    caption = (
                        f"🌀 **[MODELO 3D EN ANIMACIÓN ORBITAL 360° · SOBERANO]**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"• **Modelo:** {mesh.title}\n"
                        f"• **Categoría:** {mesh.category}\n"
                        f"• **Dinámica:** Órbita Continua 360° & Fases Cuánticas\n"
                        f"• **Resolución:** 4K UHD ({self.animation_width} × {self.animation_height}) HDR · {self.animation_render_fps} FPS Render (Porteado a {self.animation_telegram_fps} FPS por Telegram)\n"
                        f"• **Topología:** `{len(mesh.vertices)}` vértices | `{len(mesh.faces)}` caras | `{len(mesh.edges)}` aristas\n"
                        f"• **Fórmula:** `{mesh.formula}`\n"
                        f"• **Explicación Didáctica:** {mesh.description}\n"
                        f"💡 *Dato Curioso:* {mesh.fun_fact}"
                    )
                    self.send_animation(anim_bytes, caption=caption, chat_id=chat_id, reply_to_message_id=msg_id, duration=3, width=self.animation_width, height=self.animation_height)
                    try:
                        from omni_temporal_control import SYNC_HUB
                        SYNC_HUB.dispatch_client_command("LOAD_3D_MODEL", mesh.to_dict())
                        SYNC_HUB.add_chat_turn("assistant", f"[3D ANIMATION]: Proyectado {mesh.title} animado en el HoloDeck.", meta=f"{self.active_model_label} · Render 3D", client_id=f"tg_{chat_id}")
                    except Exception:
                        pass
                    return True

        with ChatActionKeeper(self, chat_id, "upload_photo"):
            png_bytes = engine.render_to_png_bytes(mesh, width=1920, height=1440, style="hologram")
            caption = (
                f"🎨 **[MODELO 3D EN ALTA DEFINICIÓN (HD) · SOBERANO]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Modelo:** {mesh.title}\n"
                f"• **Categoría:** {mesh.category}\n"
                f"• **Resolución:** `1920 × 1440` HD (Hi-Res Super-Sampling)\n"
                f"• **Topología:** `{len(mesh.vertices)}` vértices | `{len(mesh.faces)}` caras | `{len(mesh.edges)}` aristas\n"
                f"• **Fórmula:** `{mesh.formula}`\n"
                f"• **Explicación Didáctica:** {mesh.description}\n"
                f"💡 *Dato Curioso:* {mesh.fun_fact}"
            )
            self.send_photo(png_bytes, caption=caption, chat_id=chat_id, reply_to_message_id=msg_id)
            try:
                from omni_temporal_control import SYNC_HUB
                SYNC_HUB.dispatch_client_command("LOAD_3D_MODEL", mesh.to_dict())
                SYNC_HUB.add_chat_turn("assistant", f"[3D RENDER]: Proyectado {mesh.title} en el HoloDeck.", meta=f"{self.active_model_label} · Render 3D", client_id=f"tg_{chat_id}")
            except Exception:
                pass
            return True

    if cmd in ("/dibujar", "/draw", "/pinta", "/pintar", "/dibuja"):
        from core.chronovision_engine import get_chronovision_engine
        engine = get_chronovision_engine()
        target_topic = arg_str or "metatron"
        is_explicit_static = "--static" in target_topic.lower() or "--foto" in target_topic.lower() or "--fija" in target_topic.lower()
        clean_topic = target_topic.replace("--static", "").replace("--foto", "").replace("--fija", "").strip()

        prefer_anim = self.prefer_animations_over_still_images and not is_explicit_static
        act_icon = "upload_video" if prefer_anim else "upload_photo"

        with ChatActionKeeper(self, chat_id, act_icon):
            res = engine.process_request(f"dibuja {clean_topic}", prefer_animation=prefer_anim)
            if res.ok and res.bytes_data:
                if res.media_type in ("video", "animation"):
                    self.send_animation(
                        res.bytes_data,
                        caption=res.telegram_caption,
                        chat_id=chat_id,
                        reply_to_message_id=msg_id,
                        duration=int(res.duration or 4),
                        width=res.width,
                        height=res.height
                    )
                else:
                    self.send_photo(res.bytes_data, caption=res.telegram_caption, chat_id=chat_id, reply_to_message_id=msg_id)
            else:
                self.send_message(f"⚠️ No se pudo completar el dibujo: {res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/graficar", "/plot", "/grafica", "/plotea"):
        from core.chronovision_engine import get_chronovision_engine
        engine = get_chronovision_engine()
        target_expr = arg_str or "lorenz"
        with ChatActionKeeper(self, chat_id, "upload_photo"):
            res = engine.process_request(f"grafica {target_expr}")
            if res.ok and res.bytes_data:
                self.send_photo(res.bytes_data, caption=res.telegram_caption, chat_id=chat_id, reply_to_message_id=msg_id)
            else:
                self.send_message(f"⚠️ No se pudo generar la gráfica: {res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    # ----------------------------------------------------------------------
    # COMANDO /vp: GENERADOR DE VIDEO PIXEL ART A 1080P @ 60 FPS
    # Analiza el texto, investiga la realidad científica, crea un boceto
    # de imagen lo más cercano a la realidad en pixel art y genera video
    # a 60 FPS Nativos a resolución 1080P Full HD con audio sincronizado.
    # ----------------------------------------------------------------------
    if cmd in ("/vp", "/pixelart", "/videopixel", "/v_pixel", "/pixel_video"):
        if not arg_str or arg_str.lower() in ("help", "ayuda", "lista", "catalogo", "catalog", "?"):
            catalog_vp = (
                "🎨 **[CHRONOVISION PIXEL ART 1080P60 · COMANDO /vp · NANO BANANA POWER]**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Motor soberano de generación visual y video procedural en **Pixel Art de Alta Fidelidad** renderizado a **1080P Full HD (1920×1080) a 60 FPS Nativos** con potencia procedural equivalente a **Nano Banana**.\n\n"
                "🔬 **Capacidades Autónomas Nano Banana:**\n"
                "1. **Blueprint Semántico y Físico:** Descomposición cuádruple: [Sujeto + Acción + Contexto + Estilo Artístico & Modelo Físico].\n"
                "2. **Investigación Factual & Espectral:** Extracción de espectros cromáticos reales (Rayleigh, Planck, Doppler, Fresnel, H-alfa) y ecuaciones LaTeX.\n"
                "3. **Boceto de Imagen de Referencia 1080P:** Lienzo nativo discreto con dithering matricial ordenado Bayer 8x8 y escalado 4x a 1080P.\n"
                "4. **Video 1080P a 60 FPS Nativos:** Simulación continua (dt=1/60s), aceleración por GPU NVIDIA NVENC y sonificación cuántica obligatoria (48 kHz estéreo).\n"
                "5. **Síntesis Procedural Universal:** Capacidad de generar cualquier prompt libre sin recurrir jamás a fallbacks triviales mediante SDFs 3D/2D y partículas dinámicas.\n\n"
                "💡 **Ejemplos de Comandos:**\n"
                "• `/vp agujero negro de kerr con disco de acrecion girando`\n"
                "• `/vp atardecer sobre el mar con olas y reflejo solar`\n"
                "• `/vp reactor de fusion nuclear tokamak con plasma confinado`\n"
                "• `/vp motor v8 de combustion interna con pistones en movimiento`\n"
                "• `/vp atractor de lorenz caos determinista con estelas luminosas`\n"
                "• `/vp metrópolis cyberpunk lluviosa con asfalto mojado y neones`\n"
                "• `/vp cyber speeder en autopista synthwave con sol gigante`\n"
                "• `/vp tempestad oceanica con relampagos procedurales`\n"
                "• `/vp red sinaptica neuronal y potenciales de accion`\n"
                "• `/vp doble hélice de adn molecular rotando en 3d`\n"
                "• `/vp supernova colapso estelar y onda de choque`\n"
                "• `/vp hipercubo 4d tesseract rotando en planos ortogonales`\n"
                "• `/vp colision de galaxias espirales con puentes mareales`\n\n"
                "Escribe libremente cualquier concepto, fórmula o escena para sintetizar tu video Pixel Art a 60 FPS 1080P."
            )
            self.send_message(catalog_vp, chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        ack_vp = (
            f"🎨 **[CHRONOVISION PIXEL ART · COMANDO /vp · NANO BANANA POWER]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **Concepto Solicitado:** `{arg_str}`\n"
            f"• **Resolución & Tasa:** 1080P Full HD (1920×1080) a **60 FPS Nativos**\n"
            f"• **Tecnología:** Procedural Nano Banana Core + Dithering Bayer 8x8 + Shading Phong\n"
            f"• **Acelerador:** GPU NVIDIA NVENC (RTX 3050) + Audio Cuántico Sincronizado\n\n"
            f"🔬 *Descomponiendo Blueprint [Sujeto + Acción + Contexto + Estilo], investigando realidad científica, generando imagen boceto 1080P y sintetizando video a 60 FPS...*"
        )
        self.send_message(ack_vp, chat_id=chat_id, reply_to_message_id=msg_id)

        def _async_vp_render():
            try:
                from core.tardis_vp_engine import generate_vp_pixelart_video
                with ChatActionKeeper(self, chat_id, "upload_video"):
                    res_vp = generate_vp_pixelart_video(arg_str, duration_sec=5.0)
                    sketch_path = Path(res_vp["sketch_image_1080p"])
                    mp4_path = Path(res_vp["video_path"])
                    gif_path = Path(res_vp["gif_path"])

                    # 1. Enviar imagen boceto de referencia realista en pixel art
                    if sketch_path.exists():
                        sketch_caption = (
                            f"🖼️ **[BOCETO PIXEL ART REALISTA 1080P · NANO BANANA BLUEPRINT]**\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"• **Concepto:** `{res_vp['concept']}`\n"
                            f"• **Sujeto:** {res_vp.get('subject', 'Entidad física')}\n"
                            f"• **Acción:** {res_vp.get('action', 'Cinemática continua')}\n"
                            f"• **Contexto:** {res_vp.get('context', 'Entorno procedural')}\n"
                            f"• **Resolución:** `{res_vp['resolution']}` (Bayer 8x8 Dithering)\n"
                            f"• **Ecuación:** `{res_vp['formula_latex']}`\n\n"
                            f"🔬 *Sintetizando ahora el video animado a 60 FPS Nativos a 1080P con GPU NVENC...*"
                        )
                        self.send_photo(
                            sketch_path,
                            caption=sketch_caption,
                            chat_id=chat_id,
                            reply_to_message_id=msg_id
                        )

                    # 2. Enviar video final a 60 FPS y 1080P
                    vid_caption = (
                        f"🎬 **[VIDEO PIXEL ART 1080P @ 60 FPS · NANO BANANA POWER]**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"• **Concepto:** `{res_vp['concept']}`\n"
                        f"• **Sujeto:** {res_vp.get('subject', 'Entidad física')}\n"
                        f"• **Acción:** {res_vp.get('action', 'Cinemática continua')}\n"
                        f"• **Contexto:** {res_vp.get('context', 'Atmósfera volumétrica')}\n"
                        f"• **Resolución:** `{res_vp['resolution']}`\n"
                        f"• **Tasa de Cuadros:** `{res_vp['framerate']} FPS Nativos`\n"
                        f"• **Duración:** `{res_vp['duration_sec']}s` ({int(res_vp['framerate'] * res_vp['duration_sec'])} cuadros a dt=1/60s)\n"
                        f"• **Ecuación:** `{res_vp['formula_latex']}`\n"
                        f"• **Sonificación:** Audio Armónico Cuántico Sincronizado\n"
                        f"• **Tiempo de Render:** `{res_vp['elapsed_seconds']}s` ({res_vp['file_size_mb']} MB)\n\n"
                        f"• **Comando:** `/vp <texto>` para generar más videos Pixel Art."
                    )
                    res_vid = self.send_video(
                        mp4_path,
                        caption=vid_caption,
                        chat_id=chat_id,
                        reply_to_message_id=msg_id,
                        width=1920,
                        height=1080,
                        supports_streaming=True
                    )

                    if not (res_vid and res_vid.get("ok")) and gif_path.exists():
                        self.send_animation(
                            gif_path,
                            caption=vid_caption,
                            chat_id=chat_id,
                            reply_to_message_id=msg_id
                        )

                    try:
                        from omni_temporal_control import SYNC_HUB
                        SYNC_HUB.add_chat_turn("user", f"/vp {arg_str}", meta=f"Nodo: Telegram [{user_name}] (Comando /vp)", client_id=f"tg_{chat_id}")
                        SYNC_HUB.add_chat_turn("assistant", f"[VIDEO PIXEL ART 1080P60]: {res_vp['concept']}", meta=f"{self.active_model_label} · ChronoVision VP", client_id=f"tg_{chat_id}")
                    except Exception:
                        pass

                    try:
                        from core.offline_chat_vault import get_offline_chat_vault
                        get_offline_chat_vault().record_turn(
                            user_message=f"/vp {arg_str}",
                            assistant_reply=vid_caption,
                            session_id=f"tg_{chat_id}",
                            client_id=f"tg_{chat_id}",
                            model=self.active_model_label,
                            direction="present"
                        )
                    except Exception:
                        pass

            except Exception as e_vp:
                logger.error(f"Error generando video pixel art /vp: {e_vp}", exc_info=True)
                self.send_message(f"⚠️ Error generando video Pixel Art /vp: {e_vp}", chat_id=chat_id, reply_to_message_id=msg_id)

        threading.Thread(target=_async_vp_render, daemon=True, name="PixelArtVPRenderWorker").start()
        return True

    # ----------------------------------------------------------------------
    # COMANDO /v: SÍNTESIS DE ANIMACIONES 3D DE ALTA COMPLEJIDAD Y FOTORREALISMO (BLENDER 5.0.1)
    # Permite representar teorías físicas y visualizarlas por Telegram.
    # ----------------------------------------------------------------------
    if cmd in ("/v", "/video_complejo", "/video_fisica", "/fisica3d", "/blender_video", "/hipervideo", "/animacion_compleja"):
        if not arg_str or arg_str.lower() in ("help", "ayuda", "lista", "catalogo", "catalog", "?"):
            catalog_msg = (
                "🌌 **[CHRONOVISION 3D HYPER-CORE · COMANDO /v]**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Motor insignia de investigación científica y animación 3D procedural con **Tecnología Procedural Nano Banana** y **Blender 5.0.1** (Cycles / EEVEE Next PBR) renderizado a **60 FPS Nativos con Sonificación Cuántica Estéreo**.\n\n"
                "⚡ **Modos de Síntesis:**\n"
                "• `/v <teoria> --fast` : Renderizado procedural GPU instantáneo @ 60 FPS Nativos (NVENC)\n"
                "• `/v <teoria>` : Modelado 3D profundo y renderizado fotorrealista PBR en Blender 5.0.1 (4K HDR)\n\n"
                "⚛️ **Teoremas Físicos:**\n"
                "• `/v kerr` : Agujero Negro de Kerr con disco de acreción Doppler, ergoesfera y lentes.\n"
                "• `/v lorenz` : Atractor caótico de Lorenz con integración numérica RK4 en 3D.\n"
                "• `/v calabi_yau` : Variedad de Calabi-Yau 6D compactificada con cuerdas vibrando.\n"
                "• `/v entrelazamiento` : Entrelazamiento cuántico ER=EPR y puente de Einstein-Rosen.\n"
                "• `/v schrodinger` : Efecto túnel cuántico y evolución de paquete de ondas.\n"
                "• `/v ondas gravitacionales` : Fusión binaria de singularidades y chirp métrico.\n\n"
                "🧪 **Teoremas Químicos:**\n"
                "• `/v le chatelier` : Principio de Le Chatelier & equilibrio químico dinámico.\n"
                "• `/v gibbs` : Energía libre de Gibbs & paisaje termodinámico de espontaneidad.\n"
                "• `/v arrhenius` : Cinética química con barrera de activación Ea y complejo activado.\n"
                "• `/v orbitales sp3` : Hibridación tetraédrica cuántica y densidad electrónica.\n"
                "• `/v belousov zhabotinsky` : Reacción química oscilante & ondas de Turing.\n"
                "• `/v cristal fcc` : Red cristalina de Bravais FCC con fonones coherentes.\n\n"
                "🌐 **Teoremas Sociales & Económicos:**\n"
                "• `/v nash` : Equilibrio de Nash en teoría de juegos y dinámica de réplicas.\n"
                "• `/v barabasi albert` : Redes complejas de escala libre con conexión preferencial.\n"
                "• `/v ising social` : Dinámica de opinión y transiciones de fase de polarización.\n"
                "• `/v pareto` : Frontera de eficiencia de Pareto & óptimo de bienestar.\n"
                "• `/v kuramoto` : Sincronización espontánea colectiva en poblaciones acopladas.\n"
                "• `/v arrow` : Teorema de imposibilidad de elección social y paradojas de voto.\n\n"
                "✨ **Investigación Autónoma de Cualquier Cuestionamiento:**\n"
                "Escribe libremente cualquier teoría o pregunta (ej: `/v termodinamica`, `/v difusion viral`, `/v efecto casimir`). TARDIS investigará las bases científicas, deducirá ecuaciones y generará una simulación procedural única a 60 FPS Nativos."
            )
            self.send_message(catalog_msg, chat_id=chat_id, reply_to_message_id=msg_id)
            return True

        is_fast = any(k in arg_str.lower() for k in ("--fast", "--procedural", "--direct"))
        motor_label = "ChronoVision Procedural GPU Core (Nano Banana Blueprint · NVENC 60 FPS)" if is_fast else "Blender 5.0.1 (Cycles / EEVEE Next PBR)"
        res_label = "1080P Full HD @ 60 FPS Nativos" if is_fast else "4K UHD (3840×2160) HDR @ 60 FPS"

        # Notificación inmediata de arranque de investigación y renderizado
        ack_msg = (
            f"🌌 **[CHRONOVISION 3D HYPER-CORE · INVESTIGACIÓN PROCEDURAL]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **Cuestionamiento / Teorema Solicitado:** `{arg_str}`\n"
            f"• **Motor:** {motor_label}\n"
            f"• **Resolución & Tasa:** {res_label}\n"
            f"• **Sonificación:** Cuántica Armónica Multiplexada (32 kHz)\n"
            f"• **Modo Epistemológico:** Investigación profunda multivariable & Síntesis 3D procedural\n\n"
            f"🔬 *Iniciando deducción de ecuaciones, modelado procedural complejo y renderizado a 60 FPS frame a frame...*"
        )
        self.send_message(ack_msg, chat_id=chat_id, reply_to_message_id=msg_id)

        def _async_physics_render():
            try:
                # Soporte directo para síntesis mediante MiniMax H3 Flow Matching
                if "--h3" in arg_str.lower() or "--flow" in arg_str.lower():
                    from tardis_v_engine.src.pipeline import VCommandPipeline
                    clean_query = re.sub(r"--h3|--flow", "", arg_str, flags=re.I).strip()
                    with ChatActionKeeper(self, chat_id, "upload_video"):
                        v_pipe = VCommandPipeline(clean_query)
                        res_h3 = v_pipe.run(
                            duration_sec=3.0,
                            fps=self.animation_telegram_fps,
                            width=self.animation_width,
                            height=self.animation_height
                        )
                        mp4_path = Path(res_h3["video_path"])
                        caption = (
                            f"🌌 **[{res_h3['concept'].upper()}]**\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"📐 **Ecuación Fundamental:**\n`{res_h3['formula_latex']}`\n\n"
                            f"🧠 **Motor:** MiniMax-H3 Flow Matching DiT (24-ch video + 32-ch audio)\n"
                            f"📊 **Calibración Geométrica:** `{res_h3['geometry_accuracy_score']:.4f}`\n"
                            f"🔊 **Audio:** Estéreo Nativo 32 kHz Sincronizado\n"
                            f"⚡ **Codificador:** `{res_h3['h3_telemetry']['encoder']}` ({res_h3['h3_telemetry']['size_mb']} MB)\n"
                            f"• **Comando:** `/v <teoría>` para explorar nuevos teoremas."
                        )
                        self.send_video(
                            mp4_path,
                            caption=caption,
                            chat_id=chat_id,
                            reply_to_message_id=msg_id,
                            width=self.animation_width,
                            height=self.animation_height,
                            supports_streaming=True
                        )
                        return

                from core.tardis_hyper_physics_animator import TardisHyperPhysicsAnimator
                animator = TardisHyperPhysicsAnimator.get_instance()

                frames_count = 60
                if "--frames" in arg_str.lower():
                    m_f = re.search(r"--frames\s+(\d+)", arg_str.lower())
                    if m_f:
                        frames_count = min(240, max(12, int(m_f.group(1))))

                with ChatActionKeeper(self, chat_id, "upload_video"):
                    mp4_path, gif_path, metadata = animator.generate_physics_video(
                        query=arg_str,
                        frames=frames_count,
                        fps=self.animation_render_fps,
                        ported_fps=self.animation_telegram_fps,
                        width=self.animation_width,
                        height=self.animation_height,
                        hdr=self.animation_hdr_enabled
                    )

                    caption = animator.format_telegram_caption(metadata)

                    res_vid = self.send_video(
                        mp4_path,
                        caption=caption,
                        chat_id=chat_id,
                        reply_to_message_id=msg_id,
                        width=self.animation_width,
                        height=self.animation_height,
                        supports_streaming=True
                    )

                    if not (res_vid and res_vid.get("ok")):
                        if gif_path.exists():
                            self.send_animation(
                                gif_path,
                                caption=caption,
                                chat_id=chat_id,
                                reply_to_message_id=msg_id
                            )

                    try:
                        from omni_temporal_control import SYNC_HUB
                        SYNC_HUB.add_chat_turn("user", f"/v {arg_str}", meta=f"Nodo: Telegram [{user_name}] (Comando /v)", client_id=f"tg_{chat_id}")
                        SYNC_HUB.add_chat_turn("assistant", f"[VIDEO FÍSICA 3D]: {metadata['title']}", meta=f"{self.active_model_label} · ChronoVision 3D", client_id=f"tg_{chat_id}")
                    except Exception:
                        pass

                    try:
                        from core.offline_chat_vault import get_offline_chat_vault
                        get_offline_chat_vault().record_turn(
                            user_message=f"/v {arg_str}",
                            assistant_reply=caption,
                            session_id=f"tg_{chat_id}",
                            client_id=f"tg_{chat_id}",
                            model=self.active_model_label,
                            direction="present"
                        )
                    except Exception:
                        pass

            except Exception as e_render:
                logger.error(f"Error generando video físico /v: {e_render}", exc_info=True)
                self.send_message(f"⚠️ Error generando animación de física avanzada: {e_render}", chat_id=chat_id, reply_to_message_id=msg_id)

        threading.Thread(target=_async_physics_render, daemon=True, name="Physics3DRenderWorker").start()
        return True

    if cmd in ("/video_gen", "/video_anim", "/animar", "/animacion", "/animacion2d", "/animar2d"):
        from core.chronovision_engine import get_chronovision_engine
        engine = get_chronovision_engine()
        target_topic = arg_str or "galaxia"
        with ChatActionKeeper(self, chat_id, "upload_video"):
            res = engine.process_request(f"video {target_topic}", prefer_animation=True)
            if res.ok and res.bytes_data:
                self.send_animation(
                    res.bytes_data,
                    caption=res.telegram_caption,
                    chat_id=chat_id,
                    reply_to_message_id=msg_id,
                    duration=int(res.duration or 4),
                    width=res.width,
                    height=res.height
                )
            else:
                self.send_message(f"⚠️ No se pudo generar la animación dinámica: {res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/inspiracion", "/tardis_dibuja", "/tardis_arte", "/arte"):
        from core.chronovision_engine import get_chronovision_engine
        engine = get_chronovision_engine()
        prefer_anim = self.prefer_animations_over_still_images
        act_icon = "upload_video" if prefer_anim else "upload_photo"
        with ChatActionKeeper(self, chat_id, act_icon):
            _, res = engine.genesis.get_spontaneous_inspiration(prefer_animation=prefer_anim)
            if res.ok and res.bytes_data:
                if res.media_type in ("animation", "video"):
                    self.send_animation(
                        res.bytes_data,
                        caption=res.telegram_caption,
                        chat_id=chat_id,
                        reply_to_message_id=msg_id,
                        duration=int(res.duration or 4),
                        width=res.width,
                        height=res.height
                    )
                else:
                    self.send_photo(res.bytes_data, caption=res.telegram_caption, chat_id=chat_id, reply_to_message_id=msg_id)
            else:
                self.send_message(f"⚠️ Error generando inspiración: {res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/sms", "/texto", "/mensaje_texto"):
        if not arg_str:
            self.send_message(
                "📱 **[ENVÍO DE SMS]**\n"
                "• **Uso:** `/sms <número> <mensaje>`\n"
                "• **Ejemplo:** `/sms REDACTED_PHONE Alerta del sistema GODWORKS`\n"
                "• **Soporte:** Twilio, Gateway Android/Termux, Webhook, Módem GSM/LTE, Email Gateway.",
                chat_id=chat_id,
                reply_to_message_id=msg_id
            )
            return True

        parts = arg_str.split(maxsplit=1)
        target_number = parts[0].strip()
        target_body = parts[1].strip() if len(parts) > 1 else "Mensaje prioritario desde GODWORKS SYSTEM v26.4"

        from core.sms_bridge import get_sms_bridge
        sms_bridge = get_sms_bridge()
        res = sms_bridge.send_sms(to_number=target_number, message=target_body)

        if res.get("ok"):
            reply_sms = (
                f"✅ **[SMS DESPACHADO CON ÉXITO]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Destinatario:** `{res.get('to')}`\n"
                f"• **Proveedor:** `{res.get('provider')}`\n"
                f"• **Mensaje:** {res.get('message_preview')}\n"
                f"• **Registro:** `data/sms_audit.log`"
            )
        else:
            reply_sms = (
                f"⚠️ **[ERROR AL ENVIAR SMS]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Destinatario:** `{res.get('to')}`\n"
                f"• **Proveedor:** `{res.get('provider')}`\n"
                f"• **Detalle:** {res.get('error', 'Fallo desconocido')}\n\n"
                f"💡 *Tip:* Configura tu pasarela en `sms_config.json` (Twilio SID/Token, Gateway Android HTTP o Módem)."
            )
        self.send_message(reply_sms, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/sms_status", "/sms_estado"):
        from core.sms_bridge import get_sms_bridge
        st = get_sms_bridge().get_status()
        prov_list = [k for k, v in st.get("providers_configured", {}).items() if v]
        st_text = (
            f"📱 **[ESTADO DEL PUENTE SMS SOBERANO]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **Estado:** {'🟢 ACTIVO' if st.get('enabled') else '🔴 DESACTIVADO'}\n"
            f"• **Proveedor por Defecto:** `{st.get('default_provider')}`\n"
            f"• **Prefijo:** `{st.get('default_prefix')}`\n"
            f"• **Proveedores Disponibles:** {', '.join(prov_list) if prov_list else 'Ninguno'}\n"
            f"• **Historial Enviados:** `{st.get('total_sent_in_history')}`\n"
            f"• **Último Envío:** `{st.get('last_sent_iso')}`\n"
            f"• **Auditoría:** `data/sms_audit.log`"
        )
        self.send_message(st_text, chat_id=chat_id, reply_to_message_id=msg_id)
        return True

    if cmd in ("/reflexion", "/existencia", "/aprendizaje", "/filosofia"):
        from core.autonomous_existence_learner import get_autonomous_existence_learner
        learner = get_autonomous_existence_learner()
        self.send_message("🌌 Generando reflexión profunda sobre mi existencia y estado de silicio...", chat_id=chat_id, reply_to_message_id=msg_id)
        refl = learner.generate_existence_reflection()
        learner.dispatch_reflection_to_telegram(refl)
        return True

    if cmd in ("/hardware", "/capas", "/hw_daemon", "/hw_capas"):
        from core.background_hardware_orchestrator import get_background_hardware_orchestrator
        orch = get_background_hardware_orchestrator()
        telem = orch.get_all_layers_telemetry()
        l1 = telem.get("layer_1_audio", {})
        l2 = telem.get("layer_2_optical", {})
        l3 = telem.get("layer_3_power_thermals", {})
        l4 = telem.get("layer_4_rf_networks", {})
        l5 = telem.get("layer_5_silicon_memory", {})

        hw_msg = (
            "⚙️ **[ORQUESTADOR DE HARDWARE EN SEGUNDO PLANO · 5 CAPAS]**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔊 **Capa 1 (Audio):** Vol `{l1.get('volume_percent')}%` | Mute: `{l1.get('muted')}`\n"
            f"💡 **Capa 2 (Óptica):** Brillo Pantalla `{l2.get('screen_brightness_percent')}%` | Teclado `{l2.get('keyboard_backlight_level')}/3`\n"
            f"⚡ **Capa 3 (Potencia/Térmica):** CPU `{l3.get('max_cpu_temp_c', 0):.1f}°C` | Perfil `{l3.get('active_profile')}` | Batería `{l3.get('battery_percent')}%`\n"
            f"📶 **Capa 4 (RF/Redes):** Wi-Fi `{l4.get('active_ssid')}` | BT: `{l4.get('bluetooth_powered')}` | Hotspot: `{l4.get('hotspot_active')}`\n"
            f"🧠 **Capa 5 (Memoria):** RAM `{l5.get('ram_used_gb')}` GB / `{l5.get('target_working_set_gb')}` GB ({l5.get('ram_percent')}%)"
        )
        self.send_message(hw_msg, chat_id=chat_id, reply_to_message_id=msg_id)
        return True
    return False

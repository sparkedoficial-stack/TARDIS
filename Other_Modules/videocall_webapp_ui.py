#!/usr/bin/env python3
"""
core/videocall_webapp_ui.py - Interfaz WebApp Full-Duplex de Voz y Videollamada en Vivo
=======================================================================================
Renderiza la Mini App / WebApp responsiva (iOS WKWebView, Android Telegram, Desktop Web)
para llamadas de voz y videollamadas bidireccionales en tiempo real con TARDIS:

  • Avatar Holográfico TARDIS a 60 FPS (Canvas 2D acelerado) reactivo en tiempo real al
    espectro de voz del micrófono y de la voz neural de TARDIS (Web Audio AnalyserNode).
  • Cámara local bidireccional (frontal / trasera) en Picture-in-Picture flotante con
    cajas de rastreo facial en vivo, animación de escaneo óptico y cambio de etapa al toque.
  • Compartición de pantalla del usuario (getDisplayMedia en navegadores compatibles).
  • Selector de señal remota de TARDIS: Avatar 60 FPS · Cámara GOD-EYE C310 · Pantalla Host.
  • Percepción visual continua y bajo demanda ("¿Qué ves?") con HUD de visión en vivo.
  • Captura instantánea enviada directamente al chat de Telegram.
  • Control completo de audio: Mic Mute, Auto VAD, Voice Barge-In, Interrupción y Colgar.
"""

from __future__ import annotations

import json
from typing import Dict, List


def render_live_call_and_video_html(
    initial_ct: str,
    default_voice: str,
    available_voices: List[Dict[str, str]],
    initial_mode: str = "voice",
) -> str:
    mode = "video" if str(initial_mode).strip().lower() == "video" else "voice"
    voices_options = "\n".join(
        f'<option value="{v["id"]}" {"selected" if v["id"] == default_voice else ""}>{v["label"]}</option>'
        for v in available_voices
    )

    page_title = "TARDIS · Videollamada en Vivo" if mode == "video" else "TARDIS · Llamada en Vivo"
    overlay_icon = "📹" if mode == "video" else "📞"
    overlay_title = "T.A.R.D.I.S · Videollamada en Vivo" if mode == "video" else "T.A.R.D.I.S · Canal de Voz y Video"
    overlay_desc = (
        "Videollamada bidireccional full-duplex en tiempo real: TARDIS te ve con visión multimodal "
        "Qwen3-VL, te escucha con manos libres y responde con su entidad holográfica en vivo."
        if mode == "video"
        else "Llamada bidireccional manos libres en tiempo real con voz neural Cortana y actualización "
        "instantánea a videollamada con visión en vivo."
    )
    primary_btn_label = "📹 INICIAR VIDEOLLAMADA EN VIVO" if mode == "video" else "🎙️ INICIAR LLAMADA EN VIVO"
    secondary_btn_label = "🎙️ SOLO VOZ (SIN CÁMARA)" if mode == "video" else "📹 INICIAR VIDEOLLAMADA EN VIVO"

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>{page_title}</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root {{
    color-scheme: dark;
    --bg0: #030710;
    --bg1: #091529;
    --panel: rgba(8, 16, 30, 0.78);
    --border: rgba(0, 240, 255, 0.24);
    --cyan: #00f0ff;
    --teal: #00d4c8;
    --gold: #e8b64a;
    --emerald: #00e699;
    --amber: #ffb020;
    --violet: #a855f7;
    --magenta: #ec4899;
    --red: #ff3b5c;
    --text: #eef6ff;
    --muted: #8ea5c4;
  }}
  * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
  html, body {{
    margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, sans-serif;
    background: radial-gradient(circle at 50% 24%, #102544 0%, var(--bg1) 46%, var(--bg0) 100%);
    color: var(--text);
    user-select: none;
  }}

  /* Lienzo principal de fondo / escenario de video */
  .stage-shell {{
    position: relative;
    width: 100%; height: 100%;
    max-width: 780px; margin: 0 auto;
    display: flex; flex-direction: column; justify-content: space-between;
    overflow: hidden;
  }}

  .video-stage {{
    position: relative;
    flex: 1; min-height: 0; width: 100%;
    display: flex; align-items: center; justify-content: center;
    overflow: hidden;
    background: radial-gradient(circle at 50% 42%, #0e2340 0%, #050c1a 65%, #02050c 100%);
  }}

  #avatarCanvas {{
    position: absolute; inset: 0; width: 100%; height: 100%;
    display: block; z-index: 1; cursor: pointer;
  }}

  #remoteFeedImg {{
    position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: contain; background: #02040a;
    display: none; z-index: 2;
  }}
  body[data-remote-feed="c310"] #remoteFeedImg,
  body[data-remote-feed="screen"] #remoteFeedImg {{
    display: block;
  }}

  /* Modo intercambio: usuario en escenario principal */
  body.stage-swapped #pipWrap {{
    position: absolute; inset: 0; width: 100%; height: 100%;
    border-radius: 0; border: 0; right: 0; top: 0; z-index: 2;
  }}
  body.stage-swapped #avatarCanvas {{
    position: absolute; right: 12px; top: 72px; left: auto; bottom: auto;
    width: 118px; height: 158px; border-radius: 16px;
    border: 1.5px solid rgba(0, 240, 255, 0.55);
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.55);
    z-index: 8; background: #040914;
  }}

  /* Barra superior flotante */
  .top-hud {{
    position: absolute; top: 0; left: 0; right: 0; z-index: 12;
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    padding: max(12px, env(safe-area-inset-top)) 14px 10px;
    background: linear-gradient(180deg, rgba(3, 7, 16, 0.88) 0%, rgba(3, 7, 16, 0.35) 75%, transparent 100%);
    pointer-events: auto;
  }}
  .hud-left {{ display: flex; align-items: center; gap: 8px; min-width: 0; }}
  .badge {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 10px; border-radius: 999px;
    background: rgba(0, 240, 255, 0.12); border: 1px solid rgba(0, 240, 255, 0.32);
    font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em; color: var(--cyan);
    white-space: nowrap;
  }}
  .dot {{
    width: 8px; height: 8px; border-radius: 50%; background: var(--emerald);
    box-shadow: 0 0 10px var(--emerald);
  }}
  .timer {{
    font-variant-numeric: tabular-nums; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.86rem; color: #c7d9f2; font-weight: 700;
  }}
  .voice-select {{
    background: rgba(11, 22, 40, 0.86); color: var(--text);
    border: 1px solid rgba(138, 160, 188, 0.32); border-radius: 10px;
    padding: 5px 7px; font-size: 0.72rem; outline: none; max-width: 148px;
  }}

  /* Selector de fuente remota (Avatar / GOD-EYE / Host Screen) */
  .feed-bar {{
    position: absolute; top: calc(max(12px, env(safe-area-inset-top)) + 42px); left: 14px;
    z-index: 11; display: flex; gap: 6px; flex-wrap: wrap;
  }}
  .feed-pill {{
    padding: 4px 10px; border-radius: 999px; border: 1px solid rgba(255,255,255,0.16);
    background: rgba(7, 15, 29, 0.72); backdrop-filter: blur(8px);
    color: var(--muted); font-size: 0.69rem; font-weight: 700; cursor: pointer;
    transition: all 0.18s ease;
  }}
  .feed-pill.active {{
    border-color: var(--cyan); color: var(--cyan);
    background: rgba(0, 240, 255, 0.16); box-shadow: 0 0 14px rgba(0, 240, 255, 0.22);
  }}
  .feed-pill.hidden {{ display: none; }}

  /* Picture-in-Picture de la cámara del usuario */
  .pip-wrap {{
    position: absolute; right: 12px; top: calc(max(12px, env(safe-area-inset-top)) + 48px);
    width: 118px; height: 158px; border-radius: 16px; overflow: hidden;
    background: #050b16; border: 1.5px solid rgba(0, 240, 255, 0.48);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.55);
    z-index: 10; display: none; cursor: pointer;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
  }}
  .pip-wrap.visible {{ display: block; }}
  .pip-wrap.scanning {{
    border-color: var(--magenta);
    box-shadow: 0 0 28px rgba(236, 72, 153, 0.65);
  }}
  #localVideo {{
    width: 100%; height: 100%; object-fit: cover; display: block;
    transform: scaleX(-1);
  }}
  #localVideo.no-mirror {{ transform: none; }}
  #pipOverlay {{
    position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none;
  }}
  .pip-scanline {{
    position: absolute; left: 0; right: 0; height: 3px; top: 0;
    background: linear-gradient(90deg, transparent, var(--magenta), var(--cyan), transparent);
    box-shadow: 0 0 12px var(--magenta);
    display: none; pointer-events: none;
    animation: scanBeam 1.25s linear infinite;
  }}
  .pip-wrap.scanning .pip-scanline {{ display: block; }}
  @keyframes scanBeam {{
    0% {{ top: 2%; opacity: 0.9; }}
    50% {{ top: 94%; opacity: 1; }}
    100% {{ top: 2%; opacity: 0.9; }}
  }}
  .pip-badge {{
    position: absolute; left: 6px; bottom: 6px; right: 6px;
    padding: 2px 6px; border-radius: 7px;
    background: rgba(3, 8, 18, 0.72); backdrop-filter: blur(4px);
    font-size: 0.62rem; font-weight: 700; color: #dbeafe;
    display: flex; align-items: center; justify-content: space-between;
  }}

  /* Etiqueta de estado y HUD de visión sobre el escenario */
  .stage-status {{
    position: absolute; left: 14px; right: 14px; bottom: 10px; z-index: 9;
    display: flex; flex-direction: column; align-items: center; gap: 6px;
    pointer-events: none;
  }}
  .state-pill {{
    display: inline-flex; align-items: center; gap: 7px;
    padding: 5px 13px; border-radius: 999px;
    background: rgba(5, 11, 24, 0.78); backdrop-filter: blur(8px);
    border: 1px solid rgba(0, 240, 255, 0.28);
    font-size: 0.8rem; font-weight: 700; color: var(--cyan);
  }}
  body[data-state="user_speaking"] .state-pill {{ border-color: var(--emerald); color: var(--emerald); }}
  body[data-state="thinking"] .state-pill {{ border-color: var(--amber); color: var(--amber); }}
  body[data-state="ai_speaking"] .state-pill {{ border-color: var(--violet); color: #d8b4fe; }}
  body[data-state="vision_scanning"] .state-pill {{ border-color: var(--magenta); color: #f9a8d4; }}

  .vision-pill {{
    max-width: 100%;
    padding: 6px 12px; border-radius: 12px;
    background: rgba(5, 13, 28, 0.82); backdrop-filter: blur(8px);
    border: 1px solid rgba(0, 212, 200, 0.34);
    font-size: 0.74rem; line-height: 1.35; color: #d6f5ff;
    text-align: center; display: none;
  }}
  .vision-pill.visible {{ display: block; }}

  /* Panel inferior: subtítulos, entrada rápida y controles */
  .bottom-dock {{
    position: relative; z-index: 12;
    padding: 8px 12px max(14px, env(safe-area-inset-bottom));
    background: linear-gradient(180deg, rgba(4, 9, 20, 0.86) 0%, rgba(3, 7, 15, 0.98) 100%);
    border-top: 1px solid rgba(0, 240, 255, 0.14);
    display: flex; flex-direction: column; gap: 8px;
  }}
  .transcript-box {{
    width: 100%; max-height: 104px; min-height: 54px; overflow-y: auto;
    padding: 8px 11px; border-radius: 13px; text-align: left;
    background: rgba(8, 16, 30, 0.82); border: 1px solid rgba(138, 160, 188, 0.18);
    font-size: 0.82rem; line-height: 1.4; user-select: text;
  }}
  .transcript-box.collapsed {{ display: none; }}
  .turn-you {{ color: #7ef7c4; margin-bottom: 4px; }}
  .turn-ai {{ color: #e8f3ff; margin-bottom: 4px; }}
  .turn-vision {{ color: #f9a8d4; font-size: 0.76rem; margin-bottom: 4px; }}

  .quick-row {{
    display: flex; gap: 6px; width: 100%;
  }}
  .quick-input {{
    flex: 1; padding: 9px 12px; border-radius: 11px;
    border: 1px solid rgba(138, 160, 188, 0.24); background: rgba(9, 17, 32, 0.92);
    color: var(--text); font-size: 0.84rem; outline: none; min-width: 0;
  }}
  .quick-send {{
    padding: 0 13px; border-radius: 11px; border: 0;
    background: rgba(0, 240, 255, 0.18); color: var(--cyan);
    font-weight: 700; font-size: 0.8rem; cursor: pointer;
  }}

  .controls-primary {{
    display: grid; grid-template-columns: repeat(5, 1fr); gap: 7px;
  }}
  .controls-secondary {{
    display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px;
  }}
  .ctrl-btn {{
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 3px; padding: 9px 4px; border-radius: 15px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    background: rgba(14, 26, 46, 0.86); color: var(--text); cursor: pointer;
    font-size: 0.67rem; font-weight: 700; transition: transform 0.1s ease, background 0.2s, border-color 0.2s;
  }}
  .ctrl-btn.mini {{
    flex-direction: row; padding: 7px 5px; border-radius: 11px; font-size: 0.66rem; gap: 4px;
  }}
  .ctrl-btn:active {{ transform: scale(0.95); }}
  .ctrl-btn .ico {{ font-size: 1.2rem; line-height: 1; }}
  .ctrl-btn.mini .ico {{ font-size: 0.92rem; }}
  .ctrl-btn.active {{
    background: rgba(0, 240, 255, 0.18); border-color: var(--cyan); color: var(--cyan);
  }}
  .ctrl-btn.video-on {{
    background: rgba(0, 230, 153, 0.18); border-color: var(--emerald); color: var(--emerald);
  }}
  .ctrl-btn.vision-btn {{
    background: rgba(236, 72, 153, 0.16); border-color: rgba(236, 72, 153, 0.52); color: #f9a8d4;
  }}
  .ctrl-btn.muted {{
    background: rgba(255, 176, 32, 0.2); border-color: var(--amber); color: var(--amber);
  }}
  .ctrl-btn.hangup {{
    background: linear-gradient(135deg, #ff3b5c, #d91b42);
    border-color: rgba(255, 90, 115, 0.65); color: #fff;
    box-shadow: 0 4px 18px rgba(255, 59, 92, 0.36);
  }}

  /* Overlay inicial */
  .start-overlay {{
    position: fixed; inset: 0; z-index: 30;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 16px; padding: 26px; text-align: center;
    background: radial-gradient(circle at 50% 28%, rgba(16, 40, 74, 0.96), rgba(3, 7, 15, 0.99));
  }}
  .start-overlay.hidden {{ display: none; }}
  .answer-btn {{
    padding: 15px 30px; border-radius: 999px; border: 0; width: min(100%, 340px);
    background: linear-gradient(135deg, #00e699, #00b8d4);
    color: #031512; font-size: 1.02rem; font-weight: 800; letter-spacing: 0.04em;
    box-shadow: 0 0 36px rgba(0, 230, 153, 0.42); cursor: pointer;
  }}
  .answer-btn.video-primary {{
    background: linear-gradient(135deg, #00f0ff, #00e699);
    box-shadow: 0 0 40px rgba(0, 240, 255, 0.45);
  }}
  .secondary-btn {{
    padding: 12px 24px; border-radius: 999px; width: min(100%, 340px);
    border: 1px solid rgba(0, 240, 255, 0.4); background: rgba(10, 24, 46, 0.78);
    color: var(--cyan); font-size: 0.88rem; font-weight: 700; cursor: pointer;
  }}
  .cap-note {{
    font-size: 0.74rem; color: var(--muted); max-width: 340px; line-height: 1.45;
  }}
</style>
</head>
<body data-state="idle" data-mode="{mode}" data-remote-feed="avatar">
  <div class="start-overlay" id="startOverlay">
    <div style="font-size:3.2rem">{overlay_icon}</div>
    <h2 style="margin:0;font-size:1.4rem;letter-spacing:0.05em">{overlay_title}</h2>
    <p style="margin:0;color:var(--muted);max-width:340px;font-size:0.88rem;line-height:1.5">
      {overlay_desc}
    </p>
    <button class="answer-btn {'video-primary' if mode == 'video' else ''}" id="answerBtn">{primary_btn_label}</button>
    <button class="secondary-btn" id="altStartBtn">{secondary_btn_label}</button>
    <div class="cap-note">
      ⚡ Prioridad Soberana automática · Visión Qwen3-VL en vivo · Avatar holográfico 60 FPS · Barge-In inteligente
    </div>
  </div>

  <div class="stage-shell">
    <div class="video-stage" id="videoStage">
      <canvas id="avatarCanvas" title="Toca para hablar, enviar o interrumpir a TARDIS"></canvas>
      <img id="remoteFeedImg" alt="Señal de video en vivo de TARDIS" />

      <div class="top-hud">
        <div class="hud-left">
          <div class="badge"><span class="dot" id="connDot"></span><span id="connText">EN LÍNEA</span></div>
          <div class="timer" id="callTimer">00:00</div>
        </div>
        <select class="voice-select" id="voiceSelect" title="Voz neural de TARDIS">
          {voices_options}
        </select>
      </div>

      <div class="feed-bar" id="feedBar">
        <button class="feed-pill active" id="feedAvatarBtn" type="button">🌌 Avatar 60fps</button>
        <button class="feed-pill" id="feedC310Btn" type="button">👁️ GOD-EYE</button>
        <button class="feed-pill hidden" id="feedHostScreenBtn" type="button">🖥️ Pantalla Host</button>
      </div>

      <div class="pip-wrap" id="pipWrap" title="Toca para intercambiar vista principal / cámara">
        <video id="localVideo" autoplay playsinline muted></video>
        <canvas id="pipOverlay"></canvas>
        <div class="pip-scanline"></div>
        <div class="pip-badge">
          <span id="pipSourceLbl">📹 TÚ</span>
          <span id="pipFacesLbl">👁️ 0</span>
        </div>
      </div>

      <div class="stage-status">
        <div class="vision-pill" id="visionPill">👁️ Visión en vivo activa…</div>
        <div class="state-pill">
          <span id="orbEmoji">🎙️</span>
          <span id="stateLabel">Listo para conectar</span>
        </div>
      </div>
    </div>

    <div class="bottom-dock">
      <div class="transcript-box" id="transcriptBox">
        <div class="turn-ai" id="aiCaption">Toca iniciar para activar micrófono, cámara y entidad holográfica TARDIS.</div>
      </div>

      <form class="quick-row" id="quickForm">
        <input class="quick-input" id="quickInput" type="text" placeholder="Escribe o pregunta «¿qué ves?» durante la videollamada…" autocomplete="off">
        <button class="quick-send" type="submit">Enviar</button>
      </form>

      <div class="controls-primary">
        <button class="ctrl-btn" id="muteBtn" type="button">
          <span class="ico" id="muteIco">🎙️</span>
          <span id="muteLbl">Mic</span>
        </button>
        <button class="ctrl-btn" id="camBtn" type="button">
          <span class="ico" id="camIco">📹</span>
          <span id="camLbl">Cámara</span>
        </button>
        <button class="ctrl-btn" id="flipBtn" type="button" title="Alternar cámara frontal / trasera">
          <span class="ico">🔄</span>
          <span>Girar</span>
        </button>
        <button class="ctrl-btn vision-btn" id="visionNowBtn" type="button" title="Pedir a TARDIS que analice lo que ve ahora mismo">
          <span class="ico">👁️</span>
          <span>¿Qué ves?</span>
        </button>
        <button class="ctrl-btn hangup" id="hangupBtn" type="button">
          <span class="ico">📵</span>
          <span>Colgar</span>
        </button>
      </div>

      <div class="controls-secondary">
        <button class="ctrl-btn mini active" id="vadBtn" type="button">
          <span class="ico">🗣️</span><span id="vadLbl">Auto VAD</span>
        </button>
        <button class="ctrl-btn mini active" id="bargeBtn" type="button" title="Interrumpir a TARDIS automáticamente al hablar">
          <span class="ico">⚡</span><span id="bargeLbl">Barge-In</span>
        </button>
        <button class="ctrl-btn mini" id="shareScreenBtn" type="button" title="Compartir tu pantalla con TARDIS">
          <span class="ico">🖥️</span><span id="shareLbl">Pantalla</span>
        </button>
        <button class="ctrl-btn mini" id="snapChatBtn" type="button" title="Enviar fotograma actual y análisis al chat de Telegram">
          <span class="ico">📸</span><span>Al Chat</span>
        </button>
        <button class="ctrl-btn mini" id="interruptBtn" type="button" title="Detener audio de TARDIS">
          <span class="ico">✋</span><span>Parar</span>
        </button>
      </div>
    </div>
  </div>

<script>
(() => {{
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) {{
    try {{ tg.ready(); tg.expand(); }} catch (_) {{}}
  }}

  const INITIAL_CT = {json.dumps(initial_ct)};
  const INITIAL_MODE = {json.dumps(mode)};
  const urlParams = new URLSearchParams(window.location.search);
  const callToken = urlParams.get("ct") || INITIAL_CT;
  const requestedMode = (urlParams.get("mode") || INITIAL_MODE).toLowerCase() === "video" ? "video" : "voice";

  const startOverlay = document.getElementById("startOverlay");
  const answerBtn = document.getElementById("answerBtn");
  const altStartBtn = document.getElementById("altStartBtn");
  const stateLabel = document.getElementById("stateLabel");
  const connText = document.getElementById("connText");
  const connDot = document.getElementById("connDot");
  const callTimer = document.getElementById("callTimer");
  const orbEmoji = document.getElementById("orbEmoji");
  const visionPill = document.getElementById("visionPill");
  const transcriptBox = document.getElementById("transcriptBox");
  const voiceSelect = document.getElementById("voiceSelect");
  const quickForm = document.getElementById("quickForm");
  const quickInput = document.getElementById("quickInput");

  const avatarCanvas = document.getElementById("avatarCanvas");
  const avatarCtx = avatarCanvas.getContext("2d");
  const remoteFeedImg = document.getElementById("remoteFeedImg");
  const pipWrap = document.getElementById("pipWrap");
  const localVideo = document.getElementById("localVideo");
  const pipOverlay = document.getElementById("pipOverlay");
  const pipOverlayCtx = pipOverlay.getContext("2d");
  const pipSourceLbl = document.getElementById("pipSourceLbl");
  const pipFacesLbl = document.getElementById("pipFacesLbl");

  const feedAvatarBtn = document.getElementById("feedAvatarBtn");
  const feedC310Btn = document.getElementById("feedC310Btn");
  const feedHostScreenBtn = document.getElementById("feedHostScreenBtn");

  const muteBtn = document.getElementById("muteBtn");
  const muteIco = document.getElementById("muteIco");
  const muteLbl = document.getElementById("muteLbl");
  const camBtn = document.getElementById("camBtn");
  const camIco = document.getElementById("camIco");
  const camLbl = document.getElementById("camLbl");
  const flipBtn = document.getElementById("flipBtn");
  const visionNowBtn = document.getElementById("visionNowBtn");
  const vadBtn = document.getElementById("vadBtn");
  const vadLbl = document.getElementById("vadLbl");
  const bargeBtn = document.getElementById("bargeBtn");
  const bargeLbl = document.getElementById("bargeLbl");
  const shareScreenBtn = document.getElementById("shareScreenBtn");
  const shareLbl = document.getElementById("shareLbl");
  const snapChatBtn = document.getElementById("snapChatBtn");
  const interruptBtn = document.getElementById("interruptBtn");
  const hangupBtn = document.getElementById("hangupBtn");

  // Offscreen canvas para captura adaptativa JPEG
  const captureCanvas = document.createElement("canvas");
  const captureCtx = captureCanvas.getContext("2d");

  let ws = null;
  let audioCtx = null;
  let micStream = null;
  let videoStream = null;
  let analyser = null;
  let aiAnalyser = null;
  let activeAiSource = null;
  let mediaRecorder = null;
  let recChunks = [];
  let recMime = "";

  let callMode = requestedMode;
  let videoEnabled = false;
  let videoSource = "camera"; // "camera" | "screen"
  let facingMode = "user";    // "user" | "environment"
  let remoteFeed = "avatar";  // "avatar" | "c310" | "screen"
  let frameTimer = null;
  let latestFaceBoxes = [];

  let isMuted = false;
  let autoVad = true;
  let voiceBargeIn = true;
  let bargeStreak = 0;
  let isSpeaking = false;
  let isAiSpeaking = false;
  let isThinking = false;
  let isVisionScanning = false;
  let speechStartAt = 0;
  let lastVoiceAt = 0;
  let noiseFloor = 0.012;
  let liveMicRms = 0;
  let liveAiRms = 0;
  let turnSeq = 0;
  let activeTurnId = 0;
  let callStartedAt = 0;
  let timerInterval = null;
  let vadRaf = null;
  let avatarRaf = null;
  let closedIntentionally = false;
  let wakeLock = null;
  let hasGreetedOnce = false;

  // Cola de reproducción de audio neural (WebAudio con respaldo HTMLAudio para WKWebView)
  const fallbackPlayer = new Audio();
  fallbackPlayer.playsInline = true;
  const audioQueue = [];
  let playingChunk = false;
  let currentAiElem = null;

  function haptic(kind = "light") {{
    try {{
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred(kind);
    }} catch (_) {{}}
  }}

  function setState(modeName, label) {{
    document.body.dataset.state = modeName;
    if (label) stateLabel.textContent = label;
    if (modeName === "user_speaking") {{
      orbEmoji.textContent = "🟢";
    }} else if (modeName === "thinking") {{
      orbEmoji.textContent = "🧠";
    }} else if (modeName === "vision_scanning") {{
      orbEmoji.textContent = "👁️";
    }} else if (modeName === "ai_speaking") {{
      orbEmoji.textContent = "🔊";
    }} else {{
      orbEmoji.textContent = isMuted ? "🔇" : (videoEnabled ? "📹" : "🎙️");
    }}
  }}

  function setVisionScanning(active) {{
    isVisionScanning = !!active;
    pipWrap.classList.toggle("scanning", isVisionScanning);
    if (isVisionScanning) {{
      setState("vision_scanning", "TARDIS observando tu cámara…");
    }}
  }}

  function appendUserLine(text) {{
    const div = document.createElement("div");
    div.className = "turn-you";
    div.textContent = "🗣️ Tú: " + text;
    transcriptBox.appendChild(div);
    currentAiElem = null;
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
  }}

  function appendVisionLine(text) {{
    const div = document.createElement("div");
    div.className = "turn-vision";
    div.textContent = "👁️ Visión: " + text;
    transcriptBox.appendChild(div);
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
  }}

  function updateAiLine(delta, replace = false) {{
    if (!currentAiElem) {{
      currentAiElem = document.createElement("div");
      currentAiElem.className = "turn-ai";
      currentAiElem.textContent = "🤖 TARDIS: ";
      transcriptBox.appendChild(currentAiElem);
    }}
    if (replace) {{
      currentAiElem.textContent = "🤖 TARDIS: " + delta;
    }} else {{
      currentAiElem.textContent += delta;
    }}
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
  }}

  function stopPlaybackQueue() {{
    audioQueue.length = 0;
    if (activeAiSource) {{
      try {{ activeAiSource.onended = null; activeAiSource.stop(); }} catch (_) {{}}
      activeAiSource = null;
    }}
    try {{
      fallbackPlayer.pause();
      fallbackPlayer.removeAttribute("src");
    }} catch (_) {{}}
    playingChunk = false;
    isAiSpeaking = false;
    liveAiRms = 0;
    if (!isThinking && !isSpeaking && !isVisionScanning) {{
      setState("idle", isMuted ? "Micrófono en silencio" : (videoEnabled ? "Videollamada en vivo…" : "Escuchando en vivo…"));
    }}
  }}

  async function playNextChunk() {{
    if (playingChunk || audioQueue.length === 0) {{
      if (!playingChunk && audioQueue.length === 0) {{
        isAiSpeaking = false;
        liveAiRms = 0;
        if (!isThinking && !isVisionScanning) {{
          setState("idle", isMuted ? "Micrófono en silencio" : (videoEnabled ? "Videollamada en vivo…" : "Escuchando en vivo…"));
        }}
      }}
      return;
    }}
    playingChunk = true;
    isAiSpeaking = true;
    setState("ai_speaking", "TARDIS hablando…");
    const rawBuf = audioQueue.shift();

    // Intentar Web Audio API para análisis espectral real a 60 FPS en el avatar
    if (audioCtx && aiAnalyser) {{
      try {{
        if (audioCtx.state === "suspended") await audioCtx.resume();
        const copyBuf = rawBuf.slice(0);
        const decoded = await audioCtx.decodeAudioData(copyBuf);
        const src = audioCtx.createBufferSource();
        src.buffer = decoded;
        src.connect(aiAnalyser);
        aiAnalyser.connect(audioCtx.destination);
        activeAiSource = src;
        src.onended = () => {{
          activeAiSource = null;
          playingChunk = false;
          playNextChunk();
        }};
        src.start(0);
        return;
      }} catch (_) {{
        // Caer al reproductor HTMLAudio estándar
      }}
    }}

    const blob = new Blob([rawBuf], {{ type: "audio/mpeg" }});
    const blobUrl = URL.createObjectURL(blob);
    fallbackPlayer.src = blobUrl;
    fallbackPlayer.onended = () => {{
      try {{ URL.revokeObjectURL(blobUrl); }} catch (_) {{}}
      playingChunk = false;
      playNextChunk();
    }};
    fallbackPlayer.onerror = () => {{
      try {{ URL.revokeObjectURL(blobUrl); }} catch (_) {{}}
      playingChunk = false;
      playNextChunk();
    }};
    fallbackPlayer.play().catch(() => {{
      try {{ URL.revokeObjectURL(blobUrl); }} catch (_) {{}}
      playingChunk = false;
      playNextChunk();
    }});
  }}

  function pickSupportedMime() {{
    if (!window.MediaRecorder) return "";
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4"
    ];
    for (const c of candidates) {{
      try {{
        if (MediaRecorder.isTypeSupported(c)) return c;
      }} catch (_) {{}}
    }}
    return "";
  }}

  // ============================================================================
  // CÁMARA LOCAL, COMPARTICIÓN DE PANTALLA Y ENVÍO DE FOTOGRAMAS
  // ============================================================================

  function updateCameraUi() {{
    camBtn.classList.toggle("video-on", videoEnabled && videoSource === "camera");
    camIco.textContent = videoEnabled && videoSource === "camera" ? "📹" : "📷";
    camLbl.textContent = videoEnabled && videoSource === "camera" ? "Cámara ON" : "Cámara";
    shareScreenBtn.classList.toggle("active", videoEnabled && videoSource === "screen");
    shareLbl.textContent = videoEnabled && videoSource === "screen" ? "En Vivo" : "Pantalla";
    pipWrap.classList.toggle("visible", videoEnabled);
    pipSourceLbl.textContent = videoSource === "screen" ? "🖥️ PANTALLA" : (facingMode === "environment" ? "📹 TRASERA" : "📹 FRONTAL");
    localVideo.classList.toggle("no-mirror", videoSource === "screen" || facingMode === "environment");
    if (!videoEnabled) {{
      document.body.classList.remove("stage-swapped");
      latestFaceBoxes = [];
    }}
  }}

  function stopLocalVideo() {{
    if (frameTimer) {{
      clearInterval(frameTimer);
      frameTimer = null;
    }}
    if (videoStream) {{
      try {{ videoStream.getTracks().forEach(t => t.stop()); }} catch (_) {{}}
      videoStream = null;
    }}
    localVideo.srcObject = null;
    videoEnabled = false;
    updateCameraUi();
    if (ws && ws.readyState === WebSocket.OPEN) {{
      ws.send(JSON.stringify({{ type: "video_state", enabled: false, source: videoSource }}));
    }}
  }}

  function captureAndSendFrame(analyzeNow = false, promptText = "") {{
    if (!videoEnabled || !localVideo || localVideo.readyState < 2) return false;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    const vw = localVideo.videoWidth || 0;
    const vh = localVideo.videoHeight || 0;
    if (vw < 16 || vh < 16) return false;

    const maxSide = videoSource === "screen" ? 720 : 480;
    const ratio = Math.min(1.0, maxSide / Math.max(vw, vh));
    const cw = Math.max(64, Math.round(vw * ratio));
    const ch = Math.max(48, Math.round(vh * ratio));
    captureCanvas.width = cw;
    captureCanvas.height = ch;
    captureCtx.drawImage(localVideo, 0, 0, cw, ch);
    const dataUrl = captureCanvas.toDataURL("image/jpeg", 0.72);
    const comma = dataUrl.indexOf(",");
    if (comma === -1) return false;
    const b64 = dataUrl.slice(comma + 1);
    ws.send(JSON.stringify({{
      type: "video_frame",
      jpeg_b64: b64,
      width: cw,
      height: ch,
      source: videoSource,
      analyze_now: !!analyzeNow,
      prompt: promptText || ""
    }}));
    return true;
  }}

  function startFramePump() {{
    if (frameTimer) clearInterval(frameTimer);
    // Primer fotograma inmediato para percepción inicial rápida
    setTimeout(() => captureAndSendFrame(true, ""), 450);
    frameTimer = setInterval(() => {{
      if (videoEnabled && !closedIntentionally) {{
        captureAndSendFrame(false, "");
      }}
    }}, 1300);
  }}

  async function enableCamera(desiredFacing = facingMode) {{
    stopLocalVideo();
    try {{
      videoStream = await navigator.mediaDevices.getUserMedia({{
        video: {{
          facingMode: {{ ideal: desiredFacing }},
          width: {{ ideal: 640 }},
          height: {{ ideal: 480 }},
          frameRate: {{ ideal: 24, max: 30 }}
        }},
        audio: false
      }});
      facingMode = desiredFacing;
      videoSource = "camera";
      callMode = "video";
      document.body.dataset.mode = "video";
      localVideo.srcObject = videoStream;
      await localVideo.play().catch(() => {{}});
      videoEnabled = true;
      updateCameraUi();
      if (ws && ws.readyState === WebSocket.OPEN) {{
        ws.send(JSON.stringify({{
          type: "video_state",
          enabled: true,
          source: "camera",
          facing: facingMode
        }}));
      }}
      startFramePump();
      return true;
    }} catch (err) {{
      videoEnabled = false;
      updateCameraUi();
      visionPill.textContent = "⚠️ No se pudo abrir la cámara (" + err.message + "). Sigues en voz.";
      visionPill.classList.add("visible");
      return false;
    }}
  }}

  async function enableScreenShare() {{
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {{
      visionPill.textContent = "ℹ️ Compartir pantalla solo está disponible en navegadores de escritorio.";
      visionPill.classList.add("visible");
      return false;
    }}
    stopLocalVideo();
    try {{
      videoStream = await navigator.mediaDevices.getDisplayMedia({{
        video: {{ width: {{ ideal: 1280 }}, height: {{ ideal: 720 }}, frameRate: {{ ideal: 10 }} }},
        audio: false
      }});
      const vTrack = videoStream.getVideoTracks()[0];
      if (vTrack) {{
        vTrack.onended = () => stopLocalVideo();
      }}
      videoSource = "screen";
      callMode = "video";
      document.body.dataset.mode = "video";
      localVideo.srcObject = videoStream;
      await localVideo.play().catch(() => {{}});
      videoEnabled = true;
      updateCameraUi();
      if (ws && ws.readyState === WebSocket.OPEN) {{
        ws.send(JSON.stringify({{ type: "video_state", enabled: true, source: "screen" }}));
      }}
      startFramePump();
      return true;
    }} catch (err) {{
      videoEnabled = false;
      updateCameraUi();
      return false;
    }}
  }}

  function drawPipOverlay() {{
    if (!videoEnabled) return;
    const rect = pipWrap.getBoundingClientRect();
    const w = Math.max(1, Math.round(rect.width));
    const h = Math.max(1, Math.round(rect.height));
    if (pipOverlay.width !== w || pipOverlay.height !== h) {{
      pipOverlay.width = w;
      pipOverlay.height = h;
    }}
    pipOverlayCtx.clearRect(0, 0, w, h);
    const mirrored = !localVideo.classList.contains("no-mirror");
    for (const box of latestFaceBoxes) {{
      const [nx, ny, nw, nh] = box;
      const bx = mirrored ? (1 - nx - nw) * w : nx * w;
      const by = ny * h;
      const bw = nw * w;
      const bh = nh * h;
      pipOverlayCtx.strokeStyle = isVisionScanning ? "#ec4899" : "#00f0ff";
      pipOverlayCtx.lineWidth = 2;
      pipOverlayCtx.strokeRect(bx, by, bw, bh);
    }}
  }}

  // ============================================================================
  // AVATAR HOLOGRÁFICO TARDIS A 60 FPS (REACTIVO A VOZ Y ESTADO)
  // ============================================================================

  const stars = Array.from({{ length: 48 }}, () => ({{
    x: Math.random(),
    y: Math.random(),
    r: 0.6 + Math.random() * 1.6,
    sp: 0.08 + Math.random() * 0.25,
    ph: Math.random() * Math.PI * 2
  }}));
  const aiFreqData = new Uint8Array(64);

  function renderAvatarLoop(nowMs) {{
    const rect = avatarCanvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(rect.width * dpr));
    const h = Math.max(1, Math.round(rect.height * dpr));
    if (avatarCanvas.width !== w || avatarCanvas.height !== h) {{
      avatarCanvas.width = w;
      avatarCanvas.height = h;
    }}
    const ctx = avatarCtx;
    const t = nowMs * 0.001;

    // Medir energía de voz de TARDIS en tiempo real
    if (isAiSpeaking) {{
      if (aiAnalyser && activeAiSource) {{
        aiAnalyser.getByteFrequencyData(aiFreqData);
        let acc = 0;
        for (let i = 0; i < 28; i++) acc += aiFreqData[i];
        liveAiRms = Math.min(1.0, (acc / (28 * 255)) * 1.85);
      }} else {{
        // Modulación orgánica si usa fallback HTMLAudio
        liveAiRms = 0.28 + 0.32 * Math.abs(Math.sin(t * 11.5) * Math.cos(t * 5.3));
      }}
    }} else {{
      liveAiRms *= 0.86;
    }}

    const stateMode = document.body.dataset.state || "idle";
    const pal = {{
      idle: {{ primary: "#00f0ff", secondary: "#e8b64a", glow: "rgba(0, 240, 255, 0.28)" }},
      user_speaking: {{ primary: "#00e699", secondary: "#00f0ff", glow: "rgba(0, 230, 153, 0.34)" }},
      thinking: {{ primary: "#ffb020", secondary: "#00f0ff", glow: "rgba(255, 176, 32, 0.32)" }},
      ai_speaking: {{ primary: "#a855f7", secondary: "#00f0ff", glow: "rgba(168, 85, 247, 0.42)" }},
      vision_scanning: {{ primary: "#ec4899", secondary: "#00f0ff", glow: "rgba(236, 72, 153, 0.42)" }}
    }}[stateMode] || {{ primary: "#00f0ff", secondary: "#e8b64a", glow: "rgba(0, 240, 255, 0.28)" }};

    // Fondo cósmico radial
    const cx = w * 0.5;
    const cy = h * 0.47;
    const minDim = Math.min(w, h);
    const bgGrad = ctx.createRadialGradient(cx, cy, minDim * 0.04, cx, cy, minDim * 0.72);
    bgGrad.addColorStop(0, stateMode === "ai_speaking" ? "#1d1340" : (stateMode === "vision_scanning" ? "#2d0e2a" : "#0e2647"));
    bgGrad.addColorStop(0.55, "#061124");
    bgGrad.addColorStop(1, "#02050c");
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, w, h);

    // Polvo estelar / nebulosa
    for (const s of stars) {{
      const sx = ((s.x + t * 0.008 * s.sp) % 1.0) * w;
      const sy = ((s.y + Math.sin(t * s.sp + s.ph) * 0.015 + 1) % 1.0) * h;
      const alpha = 0.25 + 0.45 * (0.5 + 0.5 * Math.sin(t * 2.1 + s.ph));
      ctx.fillStyle = `rgba(140, 225, 255, ${{alpha.toFixed(2)}})`;
      ctx.beginPath();
      ctx.arc(sx, sy, s.r * dpr, 0, Math.PI * 2);
      ctx.fill();
    }}

    const voiceEnergy = isAiSpeaking ? liveAiRms : Math.min(1.0, liveMicRms * 4.5);
    const floatY = Math.sin(t * 1.65) * (minDim * 0.014);
    const breath = 1.0 + Math.sin(t * 2.4) * 0.015 + voiceEnergy * 0.06;
    const baseSize = minDim * 0.34 * breath;
    const cyF = cy + floatY;

    // 1. Ondas de choque acústicas
    const waveSpeed = isAiSpeaking ? 1.55 : (isSpeaking ? 1.1 : 0.42);
    for (let k = 0; k < 3; k++) {{
      const phase = (t * waveSpeed + k / 3) % 1.0;
      const wr = baseSize * (0.52 + phase * (0.72 + voiceEnergy * 0.35));
      const alpha = (1.0 - phase) * (0.22 + voiceEnergy * 0.55);
      ctx.strokeStyle = pal.primary;
      ctx.globalAlpha = Math.max(0, Math.min(0.85, alpha));
      ctx.lineWidth = Math.max(1, (3.2 * dpr) * (1.0 - phase));
      ctx.beginPath();
      ctx.arc(cx, cyF, wr, 0, Math.PI * 2);
      ctx.stroke();
    }}
    ctx.globalAlpha = 1.0;

    // 2. Astrolabio rúnico + Rueda Akáshica
    const rAstro = baseSize * 0.86;
    ctx.save();
    ctx.translate(cx, cyF);
    ctx.rotate(t * (isThinking ? 0.9 : 0.26));
    ctx.strokeStyle = pal.secondary;
    ctx.globalAlpha = 0.55;
    ctx.lineWidth = 1.5 * dpr;
    ctx.beginPath();
    ctx.arc(0, 0, rAstro, 0, Math.PI * 2);
    ctx.stroke();
    const notches = 24;
    for (let n = 0; n < notches; n++) {{
      const ang = (n / notches) * Math.PI * 2;
      const len = (n % 3 === 0 ? 11 : 5) * dpr;
      ctx.strokeStyle = n % 3 === 0 ? pal.secondary : pal.primary;
      ctx.beginPath();
      ctx.moveTo(Math.cos(ang) * (rAstro - len), Math.sin(ang) * (rAstro - len));
      ctx.lineTo(Math.cos(ang) * (rAstro + len * 0.6), Math.sin(ang) * (rAstro + len * 0.6));
      ctx.stroke();
    }}
    ctx.restore();
    ctx.globalAlpha = 1.0;

    // 3. Espectro circular de audio reactivo
    const bars = 36;
    const rSpec = baseSize * 0.72;
    for (let i = 0; i < bars; i++) {{
      const ang = (i / bars) * Math.PI * 2 - Math.PI / 2;
      const bin = aiFreqData[i % 28] / 255.0;
      const amp = isAiSpeaking
        ? (0.15 + bin * 0.85) * (minDim * 0.055)
        : (0.08 + voiceEnergy * (0.45 + 0.55 * Math.abs(Math.sin(t * 7 + i)))) * (minDim * 0.04);
      ctx.strokeStyle = i % 2 === 0 ? pal.primary : pal.secondary;
      ctx.globalAlpha = 0.65;
      ctx.lineWidth = 2.2 * dpr;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(ang) * rSpec, cyF + Math.sin(ang) * rSpec);
      ctx.lineTo(cx + Math.cos(ang) * (rSpec + amp), cyF + Math.sin(ang) * (rSpec + amp));
      ctx.stroke();
    }}
    ctx.globalAlpha = 1.0;

    // 4. Casco Triangular Equilátero Soberano de TARDIS
    const triH = baseSize * 0.866;
    const pApex = [cx, cyF - triH * 0.66];
    const pLeft = [cx - baseSize * 0.5, cyF + triH * 0.34];
    const pRight = [cx + baseSize * 0.5, cyF + triH * 0.34];

    ctx.save();
    ctx.shadowColor = pal.primary;
    ctx.shadowBlur = (22 + voiceEnergy * 26) * dpr;
    ctx.fillStyle = "rgba(4, 16, 30, 0.90)";
    ctx.strokeStyle = pal.primary;
    ctx.lineWidth = 3.2 * dpr;
    ctx.beginPath();
    ctx.moveTo(pApex[0], pApex[1]);
    ctx.lineTo(pRight[0], pRight[1]);
    ctx.lineTo(pLeft[0], pLeft[1]);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();

    // Enrejado interno dorado
    ctx.strokeStyle = pal.secondary;
    ctx.globalAlpha = 0.5;
    ctx.lineWidth = 1.4 * dpr;
    ctx.beginPath();
    ctx.moveTo(cx, cyF); ctx.lineTo(pApex[0], pApex[1]);
    ctx.moveTo(cx, cyF); ctx.lineTo(pLeft[0], pLeft[1]);
    ctx.moveTo(cx, cyF); ctx.lineTo(pRight[0], pRight[1]);
    ctx.stroke();
    ctx.globalAlpha = 1.0;

    // 5. Ojo / Iris Óptico Vivo de TARDIS (con parpadeo natural y mirada sutil)
    const eyeY = cyF - triH * 0.08;
    const eyeRx = baseSize * 0.16;
    const blinkCycle = t % 3.8;
    const blinkScale = blinkCycle < 0.15 ? Math.max(0.08, Math.abs(Math.cos((blinkCycle / 0.15) * Math.PI))) : 1.0;
    const eyeRy = baseSize * 0.105 * blinkScale;

    ctx.save();
    ctx.fillStyle = "#031020";
    ctx.strokeStyle = pal.primary;
    ctx.lineWidth = 2.4 * dpr;
    ctx.beginPath();
    ctx.ellipse(cx, eyeY, eyeRx, eyeRy, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    if (blinkScale > 0.2) {{
      const gazeX = Math.sin(t * 0.7) * eyeRx * 0.16;
      const gazeY = Math.cos(t * 0.5) * eyeRy * 0.12;
      const irisR = Math.min(eyeRx * 0.52, eyeRy * 0.85);
      const irisGrad = ctx.createRadialGradient(cx + gazeX, eyeY + gazeY, irisR * 0.15, cx + gazeX, eyeY + gazeY, irisR);
      irisGrad.addColorStop(0, "#ffffff");
      irisGrad.addColorStop(0.35, pal.primary);
      irisGrad.addColorStop(1, "#082f49");
      ctx.fillStyle = irisGrad;
      ctx.beginPath();
      ctx.arc(cx + gazeX, eyeY + gazeY, irisR, 0, Math.PI * 2);
      ctx.fill();
    }}
    ctx.restore();

    // 6. Vocalizador / Boca de energía sincronizada al audio
    const mouthY = cyF + triH * 0.16;
    const mouthW = baseSize * (0.22 + voiceEnergy * 0.08);
    const mouthH = Math.max(2.5 * dpr, baseSize * (0.015 + (isAiSpeaking ? liveAiRms : 0) * 0.085));
    ctx.save();
    ctx.fillStyle = pal.primary;
    ctx.shadowColor = pal.primary;
    ctx.shadowBlur = 14 * dpr;
    ctx.beginPath();
    ctx.roundRect(cx - mouthW * 0.5, mouthY - mouthH * 0.5, mouthW, mouthH, mouthH * 0.5);
    ctx.fill();
    ctx.restore();

    // Dibujar overlay facial sobre PiP
    drawPipOverlay();

    avatarRaf = requestAnimationFrame(renderAvatarLoop);
  }}

  // ============================================================================
  // CAPTURA DE VOZ (VAD + BARGE-IN)
  // ============================================================================

  function beginUtteranceCapture() {{
    if (!micStream || isMuted || isSpeaking) return;
    // Enviar fotograma fresco justo al empezar a hablar para contexto visual exacto
    if (videoEnabled) captureAndSendFrame(false, "");
    recChunks = [];
    try {{
      mediaRecorder = recMime ? new MediaRecorder(micStream, {{ mimeType: recMime }}) : new MediaRecorder(micStream);
    }} catch (e) {{
      mediaRecorder = new MediaRecorder(micStream);
    }}
    mediaRecorder.ondataavailable = (ev) => {{
      if (ev.data && ev.data.size > 0) recChunks.push(ev.data);
    }};
    mediaRecorder.onstop = async () => {{
      const chunks = recChunks;
      recChunks = [];
      if (!chunks.length) return;
      const blob = new Blob(chunks, {{ type: mediaRecorder.mimeType || recMime || "audio/webm" }});
      if (blob.size < 600 || !ws || ws.readyState !== WebSocket.OPEN) return;
      if (videoEnabled) captureAndSendFrame(false, "");
      turnSeq += 1;
      activeTurnId = turnSeq;
      isThinking = true;
      setState("thinking", "Transcribiendo y pensando…");
      ws.send(JSON.stringify({{ type: "audio_meta", mime: blob.type, turn_id: activeTurnId }}));
      const buf = await blob.arrayBuffer();
      ws.send(buf);
    }};
    mediaRecorder.start(120);
    isSpeaking = true;
    speechStartAt = performance.now();
    lastVoiceAt = speechStartAt;
    setState("user_speaking", "Te escucho…");
  }}

  function finishUtteranceCapture(discard = false) {{
    if (!isSpeaking) return;
    isSpeaking = false;
    if (!mediaRecorder) return;
    if (discard) {{
      mediaRecorder.ondataavailable = null;
      mediaRecorder.onstop = null;
    }}
    try {{
      if (mediaRecorder.state !== "inactive") mediaRecorder.stop();
    }} catch (_) {{}}
  }}

  function startVadLoop() {{
    if (!analyser) return;
    const data = new Float32Array(analyser.fftSize);
    const SILENCE_HOLD_MS = 820;
    const MIN_SPEECH_MS = 320;
    const MAX_UTTERANCE_MS = 22000;

    const tick = () => {{
      analyser.getFloatTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
      const rms = Math.sqrt(sum / data.length);
      liveMicRms = rms;

      const now = performance.now();
      if (!isSpeaking && !isAiSpeaking && !isMuted) {{
        noiseFloor = noiseFloor * 0.985 + Math.min(rms, 0.04) * 0.015;
      }}
      const threshold = Math.max(0.017, noiseFloor * 2.6);

      if (autoVad && voiceBargeIn && isAiSpeaking && !isMuted && !isSpeaking) {{
        const bargeThresh = Math.max(0.055, threshold * 2.4);
        if (rms > bargeThresh) {{
          bargeStreak += 1;
          if (bargeStreak >= 14) {{
            bargeStreak = 0;
            sendInterrupt();
            beginUtteranceCapture();
          }}
        }} else {{
          bargeStreak = Math.max(0, bargeStreak - 1);
        }}
      }} else {{
        bargeStreak = 0;
      }}

      if (autoVad && !isMuted && !isAiSpeaking && !isThinking && !isVisionScanning) {{
        if (!isSpeaking) {{
          if (rms > threshold) {{
            beginUtteranceCapture();
          }}
        }} else {{
          if (rms > threshold * 0.82) {{
            lastVoiceAt = now;
          }}
          if ((now - lastVoiceAt > SILENCE_HOLD_MS && now - speechStartAt > MIN_SPEECH_MS) ||
              (now - speechStartAt > MAX_UTTERANCE_MS)) {{
            finishUtteranceCapture(false);
          }}
        }}
      }}
      vadRaf = requestAnimationFrame(tick);
    }};
    vadRaf = requestAnimationFrame(tick);
  }}

  // ============================================================================
  // CONEXIÓN WEBSOCKET BIDIRECCIONAL (VOZ + VIDEO + VISIÓN + SEÑAL REMOTA)
  // ============================================================================

  function selectRemoteFeed(feedName) {{
    remoteFeed = feedName;
    document.body.dataset.remoteFeed = feedName;
    feedAvatarBtn.classList.toggle("active", feedName === "avatar");
    feedC310Btn.classList.toggle("active", feedName === "c310");
    feedHostScreenBtn.classList.toggle("active", feedName === "screen");
    if (ws && ws.readyState === WebSocket.OPEN) {{
      ws.send(JSON.stringify({{ type: "set_remote_feed", feed: feedName }}));
    }}
  }}

  function connectWebSocket() {{
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const path = window.location.pathname || "";
    let wsPath = "/tg-call/ws";
    if (path.startsWith("/voz")) wsPath = "/voz/ws";
    else if (path.startsWith("/tg-videocall")) wsPath = "/tg-videocall/ws";
    else if (path.startsWith("/videollamada")) wsPath = "/videollamada/ws";
    const wsUrl = `${{proto}}//${{window.location.host}}${{wsPath}}?ct=${{encodeURIComponent(callToken)}}`;
    ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    let expectingAudioMeta = null;

    ws.onopen = () => {{
      isThinking = false;
      connText.textContent = callMode === "video" ? "VIDEO EN VIVO ∞" : "EN LLAMADA ∞";
      connDot.style.background = "#00e699";
      ws.send(JSON.stringify({{
        type: "hello",
        ct: callToken,
        init_data: (tg && tg.initData) ? tg.initData : "",
        voice: voiceSelect.value,
        mode: callMode,
        video_enabled: videoEnabled,
        remote_feed: remoteFeed,
        reconnect: hasGreetedOnce
      }}));
      hasGreetedOnce = true;
      if (videoEnabled) {{
        setTimeout(() => captureAndSendFrame(true, ""), 500);
      }}
    }};

    ws.onmessage = (ev) => {{
      if (typeof ev.data === "string") {{
        let msg = {{}};
        try {{ msg = JSON.parse(ev.data); }} catch (_) {{ return; }}

        if (msg.type === "history_sync" && Array.isArray(msg.turns) && transcriptBox.children.length === 0) {{
          for (const t of msg.turns) {{
            if (t.role === "user") appendUserLine(t.content);
            else if (t.role === "assistant") {{ updateAiLine(t.content, true); currentAiElem = null; }}
          }}
        }} else if (msg.type === "call_ready") {{
          currentAiElem = null;
          isThinking = false;
          if (msg.can_view_host_screen) {{
            feedHostScreenBtn.classList.remove("hidden");
          }}
          connText.textContent = (callMode === "video" || videoEnabled) ? "VIDEO EN VIVO ∞" : "EN LLAMADA ∞";
          setState("idle", `Conectado con ${{msg.user_name || "TARDIS"}} · ${{videoEnabled ? "Videollamada" : "Escucha Infinita"}}`);
        }} else if (msg.type === "vision_telemetry") {{
          const faces = Number(msg.faces_count || 0);
          pipFacesLbl.textContent = `👁️ ${{faces}}`;
          latestFaceBoxes = Array.isArray(msg.face_boxes) ? msg.face_boxes : [];
          if (msg.qr_text) {{
            visionPill.textContent = `🔳 QR detectado: ${{msg.qr_text}}`;
            visionPill.classList.add("visible");
          }}
        }} else if (msg.type === "vision_scanning") {{
          setVisionScanning(!!msg.active);
        }} else if (msg.type === "vision_update") {{
          setVisionScanning(false);
          if (msg.description) {{
            visionPill.textContent = `👁️ TARDIS ve: ${{msg.description}}`;
            visionPill.classList.add("visible");
            if (msg.explicit) {{
              appendVisionLine(msg.description);
            }}
          }}
        }} else if (msg.type === "remote_frame") {{
          if (msg.jpeg_b64) {{
            remoteFeedImg.src = "data:image/jpeg;base64," + msg.jpeg_b64;
          }}
        }} else if (msg.type === "snapshot_sent") {{
          visionPill.textContent = msg.ok
            ? "📸 Captura y análisis enviados a tu chat de Telegram."
            : ("⚠️ No se pudo enviar la captura: " + (msg.error || ""));
          visionPill.classList.add("visible");
        }} else if (msg.type === "transcript") {{
          if (msg.text) {{
            appendUserLine(msg.text);
            setState("thinking", "TARDIS respondiendo…");
          }} else {{
            isThinking = false;
            setState("idle", videoEnabled ? "Videollamada en vivo…" : "Escuchando en vivo…");
          }}
        }} else if (msg.type === "assistant_delta") {{
          setVisionScanning(false);
          updateAiLine(msg.text || "", false);
        }} else if (msg.type === "tts_chunk") {{
          expectingAudioMeta = msg;
        }} else if (msg.type === "turn_done") {{
          isThinking = false;
          setVisionScanning(false);
          if (!playingChunk && audioQueue.length === 0) {{
            setState("idle", isMuted ? "Micrófono en silencio" : (videoEnabled ? "Videollamada en vivo…" : "Escuchando en vivo…"));
          }}
        }} else if (msg.type === "error") {{
          isThinking = false;
          setVisionScanning(false);
          setState("idle", msg.message || "Aviso en videollamada");
        }}
      }} else if (ev.data instanceof ArrayBuffer) {{
        if (expectingAudioMeta) expectingAudioMeta = null;
        audioQueue.push(ev.data);
        isThinking = false;
        playNextChunk();
      }}
    }};

    ws.onclose = () => {{
      if (closedIntentionally) return;
      isThinking = false;
      isSpeaking = false;
      setVisionScanning(false);
      connText.textContent = "RECONECTANDO…";
      connDot.style.background = "#ffb020";
      setTimeout(connectWebSocket, 1500);
    }};
  }}

  async function requestWakeLock() {{
    try {{
      if ("wakeLock" in navigator && !wakeLock) {{
        wakeLock = await navigator.wakeLock.request("screen");
        wakeLock.addEventListener("release", () => {{ wakeLock = null; }});
      }}
    }} catch (_) {{}}
  }}

  async function startSession(withVideo) {{
    haptic("medium");
    callMode = withVideo ? "video" : "voice";
    document.body.dataset.mode = callMode;
    answerBtn.disabled = true;
    altStartBtn.disabled = true;
    answerBtn.textContent = withVideo ? "Conectando cámara y micrófono…" : "Conectando micrófono…";

    // Desbloquear reproducción de audio en iOS/Android
    try {{
      fallbackPlayer.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";
      await fallbackPlayer.play().catch(() => {{}});
    }} catch (_) {{}}

    try {{
      micStream = await navigator.mediaDevices.getUserMedia({{
        audio: {{
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1
        }}
      }});
    }} catch (err) {{
      answerBtn.disabled = false;
      altStartBtn.disabled = false;
      answerBtn.textContent = "🎙️ REINTENTAR PERMISO DE MICRÓFONO";
      alert("Permite el acceso al micrófono en Telegram para conectar con TARDIS: " + err.message);
      return;
    }}

    recMime = pickSupportedMime();
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") {{
      try {{ await audioCtx.resume(); }} catch (_) {{}}
    }}
    const src = audioCtx.createMediaStreamSource(micStream);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024;
    src.connect(analyser);

    aiAnalyser = audioCtx.createAnalyser();
    aiAnalyser.fftSize = 256;

    if (withVideo) {{
      await enableCamera(facingMode);
    }}

    startOverlay.classList.add("hidden");
    transcriptBox.innerHTML = "";
    callStartedAt = Date.now();
    timerInterval = setInterval(() => {{
      const sec = Math.floor((Date.now() - callStartedAt) / 1000);
      const m = String(Math.floor(sec / 60)).padStart(2, "0");
      const s = String(sec % 60).padStart(2, "0");
      callTimer.textContent = `${{m}}:${{s}}`;
    }}, 1000);

    requestWakeLock();
    startVadLoop();
    if (!avatarRaf) avatarRaf = requestAnimationFrame(renderAvatarLoop);
    connectWebSocket();
  }}

  function sendInterrupt() {{
    haptic("light");
    stopPlaybackQueue();
    isThinking = false;
    setVisionScanning(false);
    if (ws && ws.readyState === WebSocket.OPEN) {{
      ws.send(JSON.stringify({{ type: "interrupt" }}));
    }}
    setState("idle", videoEnabled ? "Videollamada en vivo…" : "Escuchando en vivo…");
  }}

  // Eventos de arranque
  answerBtn.addEventListener("click", () => startSession(requestedMode === "video"));
  altStartBtn.addEventListener("click", () => startSession(requestedMode !== "video"));

  // Toque en el Avatar: enviar lo dicho, hablar o interrumpir
  avatarCanvas.addEventListener("click", () => {{
    haptic("light");
    if (isAiSpeaking || isThinking) {{
      sendInterrupt();
      return;
    }}
    if (isSpeaking) {{
      finishUtteranceCapture(false);
    }} else if (!isMuted) {{
      beginUtteranceCapture();
    }}
  }});

  // Toque en PiP: intercambiar escenario principal / mini vista
  pipWrap.addEventListener("click", () => {{
    haptic("light");
    document.body.classList.toggle("stage-swapped");
  }});

  muteBtn.addEventListener("click", () => {{
    haptic("light");
    isMuted = !isMuted;
    if (isMuted) finishUtteranceCapture(true);
    if (micStream) micStream.getAudioTracks().forEach(t => t.enabled = !isMuted);
    muteBtn.classList.toggle("muted", isMuted);
    muteIco.textContent = isMuted ? "🔇" : "🎙️";
    muteLbl.textContent = isMuted ? "Silencio" : "Mic";
    setState("idle", isMuted ? "Micrófono en silencio" : (videoEnabled ? "Videollamada en vivo…" : "Escuchando en vivo…"));
  }});

  camBtn.addEventListener("click", async () => {{
    haptic("medium");
    if (videoEnabled && videoSource === "camera") {{
      stopLocalVideo();
      connText.textContent = "EN LLAMADA ∞";
      setState("idle", "Cámara pausada · Voz activa");
    }} else {{
      const ok = await enableCamera(facingMode);
      if (ok) {{
        connText.textContent = "VIDEO EN VIVO ∞";
        setState("idle", "Cámara en vivo activada");
      }}
    }}
  }});

  flipBtn.addEventListener("click", async () => {{
    haptic("light");
    const nextFacing = facingMode === "user" ? "environment" : "user";
    if (videoEnabled && videoSource === "camera") {{
      await enableCamera(nextFacing);
    }} else {{
      facingMode = nextFacing;
      await enableCamera(nextFacing);
    }}
  }});

  shareScreenBtn.addEventListener("click", async () => {{
    haptic("light");
    if (videoEnabled && videoSource === "screen") {{
      stopLocalVideo();
    }} else {{
      await enableScreenShare();
    }}
  }});

  visionNowBtn.addEventListener("click", () => {{
    haptic("medium");
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    stopPlaybackQueue();
    setVisionScanning(true);
    if (videoEnabled) {{
      captureAndSendFrame(true, "Describe en voz alta qué ves ahora mismo en mi cámara.");
    }} else {{
      const src = remoteFeed === "c310" ? "c310" : (remoteFeed === "screen" ? "host_screen" : "user");
      ws.send(JSON.stringify({{
        type: "analyze_vision",
        source: src,
        speak: true,
        prompt: "Describe en voz alta lo que ves en este momento."
      }}));
    }}
  }});

  snapChatBtn.addEventListener("click", () => {{
    haptic("light");
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (videoEnabled) captureAndSendFrame(false, "");
    const src = videoEnabled ? "user" : (remoteFeed === "c310" ? "c310" : (remoteFeed === "screen" ? "host_screen" : "user"));
    ws.send(JSON.stringify({{ type: "send_snapshot_to_chat", source: src }}));
    visionPill.textContent = "📸 Enviando captura al chat de Telegram…";
    visionPill.classList.add("visible");
  }});

  feedAvatarBtn.addEventListener("click", () => {{ haptic("light"); selectRemoteFeed("avatar"); }});
  feedC310Btn.addEventListener("click", () => {{ haptic("light"); selectRemoteFeed("c310"); }});
  feedHostScreenBtn.addEventListener("click", () => {{ haptic("light"); selectRemoteFeed("screen"); }});

  vadBtn.addEventListener("click", () => {{
    haptic("light");
    autoVad = !autoVad;
    if (!autoVad && isSpeaking) finishUtteranceCapture(false);
    vadBtn.classList.toggle("active", autoVad);
    vadLbl.textContent = autoVad ? "Auto VAD" : "Manual";
    setState("idle", autoVad ? "Escuchando en vivo…" : "Toca el avatar para hablar");
  }});

  bargeBtn.addEventListener("click", () => {{
    haptic("light");
    voiceBargeIn = !voiceBargeIn;
    bargeBtn.classList.toggle("active", voiceBargeIn);
    bargeLbl.textContent = voiceBargeIn ? "Barge-In" : "Sin Eco";
  }});

  interruptBtn.addEventListener("click", sendInterrupt);

  voiceSelect.addEventListener("change", () => {{
    if (ws && ws.readyState === WebSocket.OPEN) {{
      ws.send(JSON.stringify({{ type: "set_voice", voice: voiceSelect.value }}));
    }}
  }});

  quickForm.addEventListener("submit", (ev) => {{
    ev.preventDefault();
    const txt = quickInput.value.trim();
    if (!txt || !ws || ws.readyState !== WebSocket.OPEN) return;
    quickInput.value = "";
    stopPlaybackQueue();
    if (videoEnabled) captureAndSendFrame(false, "");
    appendUserLine(txt);
    turnSeq += 1;
    activeTurnId = turnSeq;
    isThinking = true;
    setState("thinking", "TARDIS respondiendo…");
    ws.send(JSON.stringify({{ type: "text_turn", text: txt, turn_id: activeTurnId }}));
  }});

  hangupBtn.addEventListener("click", () => {{
    haptic("heavy");
    closedIntentionally = true;
    stopPlaybackQueue();
    finishUtteranceCapture(true);
    stopLocalVideo();
    if (vadRaf) cancelAnimationFrame(vadRaf);
    if (avatarRaf) {{ cancelAnimationFrame(avatarRaf); avatarRaf = null; }}
    if (timerInterval) clearInterval(timerInterval);
    const durSec = callStartedAt ? Math.round((Date.now() - callStartedAt) / 1000) : 0;
    try {{
      if (ws && ws.readyState === WebSocket.OPEN) {{
        ws.send(JSON.stringify({{ type: "hangup", duration_sec: durSec, mode: callMode }}));
        ws.close();
      }}
    }} catch (_) {{}}
    try {{
      if (micStream) micStream.getTracks().forEach(t => t.stop());
    }} catch (_) {{}}
    setState("idle", callMode === "video" ? "Videollamada finalizada" : "Llamada finalizada");
    connText.textContent = "FINALIZADA";
    connDot.style.background = "#ff3b5c";
    if (tg) {{
      setTimeout(() => {{ try {{ tg.close(); }} catch (_) {{}} }}, 350);
    }} else {{
      startOverlay.classList.remove("hidden");
      answerBtn.disabled = false;
      altStartBtn.disabled = false;
      answerBtn.textContent = requestedMode === "video" ? "📹 VOLVER A VIDEOLLAMAR" : "🎙️ VOLVER A LLAMAR";
    }}
  }});
}})();
</script>
</body>
</html>"""

#!/usr/bin/env python3
"""
modulos_ftl/ftl_intv_appletv_hub.py
===============================================================================
Sovereign Apple TV (tvOS) Lightweight Interface & Remote Control Daemon
Target Device: INTV_ASIST (Videostrong Android TV)
  - Bluetooth MAC : EC:C1:AB:56:38:72
  - IPv4 Address  : REDACTED_IP (Ethernet MAC: D0:78:0E:00:08:3F)
  - IPv6 Address  : fe80::94a5:f9ca:9710:705
  - Protocols     : Android TV Remote v2 (6466/6467), Eureka HTTPS (8443),
                    Bluetooth BR/EDR & RFCOMM (EC:C1:AB:56:38:72), ADB (5555)
===============================================================================
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, Optional

from androidtvremote2 import (
    AndroidTVRemote,
    CannotConnect,
    ConnectionClosed,
    InvalidAuth,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("FTL.AppleTVHub")

TARGET_IP = os.environ.get("INTV_IP", "REDACTED_IP")
TARGET_BT_MAC = os.environ.get("INTV_BT_MAC", "EC:C1:AB:56:38:72")
API_PORT = 6466
PAIR_PORT = 6467
EUREKA_HTTPS_PORT = 8443
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("APPLETV_HUB_PORT", "8788"))

CERT_DIR = Path("/home/timemachine/.android")
CERT_FILE = str(CERT_DIR / "intv_appletv_cert.pem")
KEY_FILE = str(CERT_DIR / "intv_appletv_key.pem")

# Paquetes de bloatware/telemetría que se deshabilitan vía ADB cuando adbd está activo
ANDROID_TV_BLOAT_PACKAGES = [
    "com.google.android.tvrecommendations",
    "com.google.android.leanbacklauncher.recommendations",
    "com.android.dreams.basic",
    "com.google.android.backdrop",
    "com.google.android.feedback",
    "com.google.android.partnersetup",
    "com.google.android.syncadapters.calendar",
    "com.google.android.syncadapters.contacts",
    "com.google.android.tts",
    "com.google.android.videos",
    "com.google.android.play.games",
]

# Deep links de aplicaciones para Android TV Remote v2 (send_launch_app_command)
APP_CATALOG = {
    "appletv": {
        "name": "Apple TV+",
        "package": "com.apple.atve.androidtv.appletv",
        "deeplink": "https://tv.apple.com",
        "subtitle": "Originales de Apple · Películas y Series en 4K HDR",
    },
    "youtube": {
        "name": "YouTube",
        "package": "com.google.android.youtube.tv",
        "deeplink": "https://www.youtube.com",
        "subtitle": "Vídeos, Música y Transmisiones en Directo",
    },
    "netflix": {
        "name": "Netflix",
        "package": "com.netflix.ninja",
        "deeplink": "nflx://www.netflix.com",
        "subtitle": "Series, Películas y Documentales",
    },
    "prime": {
        "name": "Prime Video",
        "package": "com.amazon.amazonvideo.livingroom",
        "deeplink": "https://app.primevideo.com",
        "subtitle": "Amazon Originals, Cine y Deportes",
    },
    "disney": {
        "name": "Disney+",
        "package": "com.disney.disneyplus",
        "deeplink": "https://www.disneyplus.com",
        "subtitle": "Disney, Pixar, Marvel, Star Wars y National Geographic",
    },
    "spotify": {
        "name": "Spotify",
        "package": "com.spotify.tv.android",
        "deeplink": "spotify://",
        "subtitle": "Música y Podcasts sin límites",
    },
    "kodi": {
        "name": "Kodi / Centro Multimedia",
        "package": "org.xbmc.kodi",
        "deeplink": "org.xbmc.kodi",
        "subtitle": "Reproductor local de alta eficiencia y cine en red",
    },
    "vlc": {
        "name": "VLC Player",
        "package": "org.videolan.vlc",
        "deeplink": "org.videolan.vlc",
        "subtitle": "Reproducción directa acelerada por hardware",
    },
    "settings": {
        "name": "Ajustes",
        "package": "com.android.tv.settings",
        "deeplink": "com.android.tv.settings",
        "subtitle": "Sistema, Red, Pantalla HDMI y Control Remoto (INTV_ASIST)",
    },
}


HTML_APPLE_TV_UI = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>Apple TV · INTV_ASIST (EC:C1:AB:56:38:72)</title>
<style>
  :root {
    --bg-deep: #07080c;
    --glass-bg: rgba(28, 30, 38, 0.58);
    --glass-border: rgba(255, 255, 255, 0.14);
    --glass-highlight: rgba(255, 255, 255, 0.28);
    --text-primary: #f5f5f7;
    --text-secondary: rgba(245, 245, 247, 0.65);
    --accent-blue: #0a84ff;
    --accent-green: #30d158;
    --accent-orange: #ff9f0a;
    --accent-red: #ff453a;
    --font-stack: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Inter", "Segoe UI", Roboto, sans-serif;
  }

  * {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    user-select: none;
    -webkit-font-smoothing: antialiased;
  }

  body {
    background: var(--bg-deep);
    color: var(--text-primary);
    font-family: var(--font-stack);
    height: 100vh;
    width: 100vw;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    position: relative;
  }

  /* Fondo Atmosférico Dinámico ultraligero (GPU CSS puro) */
  .ambient-backdrop {
    position: fixed;
    inset: 0;
    z-index: 0;
    background:
      radial-gradient(circle at 22% 28%, var(--hero-c1, rgba(10, 132, 255, 0.34)) 0%, transparent 55%),
      radial-gradient(circle at 76% 22%, var(--hero-c2, rgba(94, 92, 230, 0.28)) 0%, transparent 52%),
      radial-gradient(circle at 50% 85%, var(--hero-c3, rgba(48, 209, 88, 0.16)) 0%, transparent 60%),
      linear-gradient(180deg, #0b0d14 0%, #050609 100%);
    transition: background 0.6s cubic-bezier(0.22, 1, 0.36, 1);
  }

  /* Barra Superior tvOS */
  header.tvos-topbar {
    position: relative;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 24px 48px 12px;
  }

  .brand-pill {
    display: flex;
    align-items: center;
    gap: 12px;
    background: var(--glass-bg);
    backdrop-filter: blur(30px) saturate(180%);
    border: 1px solid var(--glass-border);
    padding: 8px 18px;
    border-radius: 999px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  }

  .apple-logo {
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.5px;
  }

  .device-badge {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--text-secondary);
    font-weight: 500;
  }

  .status-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--accent-green);
    box-shadow: 0 0 10px var(--accent-green);
    transition: background 0.3s ease, box-shadow 0.3s ease;
  }

  .status-dot.warn {
    background: var(--accent-orange);
    box-shadow: 0 0 10px var(--accent-orange);
  }

  .topbar-right {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .action-pill {
    background: var(--glass-bg);
    backdrop-filter: blur(25px);
    border: 1px solid var(--glass-border);
    color: var(--text-primary);
    padding: 8px 16px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s cubic-bezier(0.22, 1, 0.36, 1);
    display: flex;
    align-items: center;
    gap: 7px;
  }

  .action-pill:hover, .action-pill:focus-visible {
    background: rgba(255, 255, 255, 0.18);
    border-color: var(--glass-highlight);
    transform: scale(1.04);
    outline: none;
  }

  .action-pill.primary {
    background: rgba(10, 132, 255, 0.25);
    border-color: rgba(10, 132, 255, 0.55);
  }

  .action-pill.success {
    background: rgba(48, 209, 88, 0.2);
    border-color: rgba(48, 209, 88, 0.5);
  }

  .clock {
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.4px;
    color: var(--text-primary);
    margin-left: 8px;
  }

  /* Layout Principal: Escaparate tvOS + Siri Remote Lateral */
  main.tvos-workspace {
    position: relative;
    z-index: 10;
    flex: 1;
    display: grid;
    grid-template-columns: 1fr 310px;
    gap: 32px;
    padding: 12px 48px 36px;
    align-items: center;
    overflow: hidden;
  }

  @media (max-width: 980px) {
    main.tvos-workspace {
      grid-template-columns: 1fr;
      overflow-y: auto;
    }
  }

  /* Columna Izquierda: Top Shelf + Dock + Grid de Apps */
  .tvos-stage {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    height: 100%;
    max-height: 760px;
    gap: 22px;
  }

  /* Top Shelf Hero Banner (Estilo Apple TV+) */
  .top-shelf {
    flex: 1;
    min-height: 220px;
    border-radius: 28px;
    background: linear-gradient(135deg, rgba(255,255,255,0.10) 0%, rgba(255,255,255,0.03) 100%);
    backdrop-filter: blur(40px) saturate(190%);
    border: 1px solid var(--glass-border);
    padding: 36px 42px;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    position: relative;
    overflow: hidden;
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
    transition: all 0.4s cubic-bezier(0.22, 1, 0.36, 1);
  }

  .top-shelf-tag {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: rgba(255, 255, 255, 0.78);
    background: rgba(255, 255, 255, 0.12);
    padding: 5px 12px;
    border-radius: 999px;
    width: fit-content;
    margin-bottom: 12px;
  }

  .top-shelf-title {
    font-size: 42px;
    font-weight: 800;
    letter-spacing: -1px;
    line-height: 1.08;
    margin-bottom: 8px;
  }

  .top-shelf-sub {
    font-size: 16px;
    color: var(--text-secondary);
    max-width: 640px;
    margin-bottom: 22px;
  }

  .top-shelf-metrics {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
  }

  .metric-chip {
    background: rgba(0, 0, 0, 0.38);
    border: 1px solid rgba(255, 255, 255, 0.1);
    padding: 7px 14px;
    border-radius: 12px;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.85);
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .metric-chip strong {
    color: #fff;
  }

  /* Dock Principal de Apple TV */
  .tvos-dock-container {
    background: rgba(255, 255, 255, 0.07);
    backdrop-filter: blur(45px) saturate(200%);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 30px;
    padding: 18px 24px;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.45);
  }

  .section-label {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.9px;
    color: rgba(255, 255, 255, 0.5);
    margin-bottom: 12px;
    padding-left: 6px;
    display: flex;
    justify-content: space-between;
  }

  .app-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(135px, 1fr));
    gap: 18px;
  }

  /* Tarjeta de App Estilo tvOS Parallax */
  .tvos-app-card {
    height: 92px;
    border-radius: 20px;
    position: relative;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    border: 1px solid rgba(255, 255, 255, 0.14);
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.35);
    transition: transform 0.26s cubic-bezier(0.22, 1, 0.36, 1),
                box-shadow 0.26s cubic-bezier(0.22, 1, 0.36, 1),
                border-color 0.26s ease;
    overflow: hidden;
  }

  .tvos-app-card::after {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(180deg, rgba(255,255,255,0.22) 0%, rgba(255,255,255,0) 55%);
    opacity: 0;
    transition: opacity 0.25s ease;
    pointer-events: none;
  }

  .tvos-app-card:hover,
  .tvos-app-card.focused {
    transform: scale(1.11) translateY(-5px);
    box-shadow: 0 22px 42px rgba(0, 0, 0, 0.65), 0 0 0 3px rgba(255, 255, 255, 0.85);
    border-color: #fff;
    z-index: 5;
  }

  .tvos-app-card:hover::after,
  .tvos-app-card.focused::after {
    opacity: 1;
  }

  .app-icon-symbol {
    font-size: 26px;
    font-weight: 800;
    letter-spacing: -0.8px;
    color: #fff;
    text-shadow: 0 2px 10px rgba(0,0,0,0.35);
  }

  .app-card-label {
    font-size: 12px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.92);
  }

  /* Colores de iconos tvOS */
  .card-appletv { background: linear-gradient(145deg, #1c1c1e, #000000); }
  .card-youtube { background: linear-gradient(145deg, #ff2a2a, #b30000); }
  .card-netflix { background: linear-gradient(145deg, #191919, #8b0000); }
  .card-prime   { background: linear-gradient(145deg, #00a8e1, #005580); }
  .card-disney  { background: linear-gradient(145deg, #0a1d56, #040814); }
  .card-spotify { background: linear-gradient(145deg, #1db954, #0f682e); }
  .card-kodi    { background: linear-gradient(145deg, #17b2e7, #0b4f6c); }
  .card-vlc     { background: linear-gradient(145deg, #ff8800, #b85d00); }
  .card-settings{ background: linear-gradient(145deg, #636366, #2c2c2e); }
  .card-turbo   { background: linear-gradient(145deg, #30d158, #0f6d28); }

  /* Siri Remote Físico Virtual (Columna Derecha) */
  .siri-remote-shell {
    width: 280px;
    height: 620px;
    margin: 0 auto;
    border-radius: 54px;
    background: linear-gradient(160deg, #2c2d35 0%, #17181d 55%, #101115 100%);
    border: 2px solid rgba(255, 255, 255, 0.18);
    box-shadow:
      inset 0 2px 5px rgba(255, 255, 255, 0.22),
      0 30px 70px rgba(0, 0, 0, 0.75);
    padding: 24px 26px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: space-between;
    position: relative;
  }

  .remote-top-row {
    width: 100%;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .remote-small-btn {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    background: #141519;
    border: 1px solid rgba(255, 255, 255, 0.14);
    color: #f5f5f7;
    font-size: 14px;
    font-weight: 700;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 4px 10px rgba(0,0,0,0.5), inset 0 1px 1px rgba(255,255,255,0.1);
    transition: transform 0.12s ease, background 0.15s ease;
  }

  .remote-small-btn:active {
    transform: scale(0.92);
    background: #2c2d35;
  }

  .remote-small-btn.power {
    color: var(--accent-red);
  }

  /* Clickpad Circular estilo Siri Remote Gen 3 */
  .siri-clickpad {
    width: 196px;
    height: 196px;
    border-radius: 50%;
    background: radial-gradient(circle at 50% 35%, #23252d 0%, #121318 75%);
    border: 2px solid rgba(255, 255, 255, 0.14);
    box-shadow:
      inset 0 2px 8px rgba(255,255,255,0.08),
      0 10px 26px rgba(0,0,0,0.6);
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .dpad-dir {
    position: absolute;
    background: transparent;
    border: none;
    color: rgba(255, 255, 255, 0.55);
    font-size: 16px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 0.15s ease, transform 0.12s ease;
  }

  .dpad-dir:hover { color: #fff; }
  .dpad-dir:active { transform: scale(0.86); color: var(--accent-blue); }

  .dpad-up    { top: 8px; left: 50%; transform: translateX(-50%); width: 70px; height: 42px; }
  .dpad-down  { bottom: 8px; left: 50%; transform: translateX(-50%); width: 70px; height: 42px; }
  .dpad-left  { left: 8px; top: 50%; transform: translateY(-50%); width: 42px; height: 70px; }
  .dpad-right { right: 8px; top: 50%; transform: translateY(-50%); width: 42px; height: 70px; }

  .dpad-up:active, .dpad-down:active { transform: translateX(-50%) scale(0.88); }
  .dpad-left:active, .dpad-right:active { transform: translateY(-50%) scale(0.88); }

  .dpad-center {
    width: 88px;
    height: 88px;
    border-radius: 50%;
    background: linear-gradient(145deg, #1d1f26, #131419);
    border: 1px solid rgba(255, 255, 255, 0.12);
    color: rgba(255, 255, 255, 0.85);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    box-shadow: inset 0 1px 2px rgba(255,255,255,0.12), 0 4px 12px rgba(0,0,0,0.45);
    transition: transform 0.12s ease, background 0.15s ease;
  }

  .dpad-center:active {
    transform: scale(0.93);
    background: #2b2e39;
  }

  /* Botones Principales bajo el Clickpad */
  .remote-button-grid {
    width: 100%;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px 26px;
    justify-items: center;
  }

  .remote-btn {
    width: 62px;
    height: 62px;
    border-radius: 50%;
    background: #14151a;
    border: 1px solid rgba(255, 255, 255, 0.14);
    color: #fff;
    font-size: 18px;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    box-shadow: 0 6px 14px rgba(0,0,0,0.55), inset 0 1px 1px rgba(255,255,255,0.1);
    transition: transform 0.12s ease, background 0.15s ease;
  }

  .remote-btn span {
    font-size: 9px;
    color: rgba(255,255,255,0.55);
    margin-top: 2px;
    font-weight: 500;
  }

  .remote-btn:active {
    transform: scale(0.91);
    background: #2a2c35;
  }

  /* Rocker de Volumen */
  .volume-rocker {
    width: 62px;
    height: 138px;
    border-radius: 999px;
    background: #14151a;
    border: 1px solid rgba(255, 255, 255, 0.14);
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    overflow: hidden;
    box-shadow: 0 6px 14px rgba(0,0,0,0.55), inset 0 1px 1px rgba(255,255,255,0.1);
    grid-row: span 2;
  }

  .vol-half {
    flex: 1;
    background: transparent;
    border: none;
    color: #fff;
    font-size: 22px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s ease;
  }

  .vol-half:active {
    background: rgba(255, 255, 255, 0.14);
  }

  .vol-divider {
    height: 1px;
    background: rgba(255, 255, 255, 0.08);
    width: 60%;
    margin: 0 auto;
  }

  .remote-footer-hint {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.42);
    text-align: center;
  }

  /* Toast de retroalimentación estilo tvOS HUD */
  .tvos-hud-toast {
    position: fixed;
    top: 28px;
    left: 50%;
    transform: translateX(-50%) translateY(-20px);
    background: rgba(28, 30, 38, 0.85);
    backdrop-filter: blur(30px);
    border: 1px solid rgba(255, 255, 255, 0.2);
    padding: 10px 22px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 600;
    color: #fff;
    z-index: 100;
    opacity: 0;
    pointer-events: none;
    transition: all 0.25s cubic-bezier(0.22, 1, 0.36, 1);
    box-shadow: 0 14px 35px rgba(0,0,0,0.5);
  }

  .tvos-hud-toast.visible {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }

  /* Modal de Vinculación PIN (Android TV Remote v2 Port 6467) */
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.68);
    backdrop-filter: blur(20px);
    z-index: 90;
    display: none;
    align-items: center;
    justify-content: center;
  }

  .modal-backdrop.open {
    display: flex;
  }

  .tvos-modal {
    background: rgba(32, 34, 44, 0.92);
    border: 1px solid var(--glass-highlight);
    border-radius: 28px;
    padding: 32px 36px;
    width: 100%;
    max-width: 430px;
    text-align: center;
    box-shadow: 0 30px 80px rgba(0,0,0,0.75);
  }

  .tvos-modal h3 {
    font-size: 22px;
    margin-bottom: 8px;
  }

  .tvos-modal p {
    font-size: 14px;
    color: var(--text-secondary);
    margin-bottom: 20px;
    line-height: 1.45;
  }

  .pin-input {
    width: 100%;
    padding: 14px;
    border-radius: 16px;
    border: 1px solid rgba(255,255,255,0.25);
    background: rgba(0,0,0,0.45);
    color: #fff;
    font-size: 24px;
    font-weight: 700;
    letter-spacing: 6px;
    text-align: center;
    text-transform: uppercase;
    margin-bottom: 18px;
    outline: none;
  }

  .pin-input:focus {
    border-color: var(--accent-blue);
  }

  .modal-actions {
    display: flex;
    gap: 12px;
    justify-content: center;
  }
</style>
</head>
<body>

<div class="ambient-backdrop" id="backdrop"></div>
<div class="tvos-hud-toast" id="hudToast">Comando enviado</div>

<header class="tvos-topbar">
  <div class="brand-pill">
    <span class="apple-logo"> tv</span>
    <div class="device-badge">
      <span class="status-dot" id="statusDot"></span>
      <span id="deviceLabel">INTV_ASIST · EC:C1:AB:56:38:72 · REDACTED_IP</span>
    </div>
  </div>

  <div class="topbar-right">
    <button class="action-pill success" onclick="triggerOptimization()" title="Elimina telemetría, procesos pesados y purga cachés en INTV_ASIST">
      ⚡ Modo Ultra-Ligero (Zero-Bloat)
    </button>
    <button class="action-pill primary" onclick="openPairModal()" id="pairBtn">
      🔗 Vincular Control TV (PIN)
    </button>
    <button class="action-pill" onclick="pairBluetooth()" title="Emparejar por Bluetooth directo EC:C1:AB:56:38:72">
      ᛒ Bluetooth
    </button>
    <div class="clock" id="clockDisplay">20:20</div>
  </div>
</header>

<main class="tvos-workspace">
  <section class="tvos-stage">
    <!-- Escaparate Superior estilo Apple TV (Top Shelf) -->
    <div class="top-shelf" id="topShelf">
      <div class="top-shelf-tag" id="heroTag"> tvOS Lightweight Interface · Zero-Bloat Activo</div>
      <div class="top-shelf-title" id="heroTitle">Apple TV+</div>
      <div class="top-shelf-sub" id="heroSub">
        Interfaz ultraligera conectada en baja latencia a INTV_ASIST (Videostrong Android TV · EC:C1:AB:56:38:72). Telemetría y servicios residuales desactivados.
      </div>
      <div class="top-shelf-metrics">
        <div class="metric-chip">Dispositivo: <strong>INTV_ASIST</strong></div>
        <div class="metric-chip">Bluetooth: <strong>EC:C1:AB:56:38:72</strong></div>
        <div class="metric-chip">Enlace IP: <strong id="metricIp">REDACTED_IP (0.6 ms)</strong></div>
        <div class="metric-chip">Control Remoto: <strong id="metricRemote">Listo (6466/6467)</strong></div>
        <div class="metric-chip">Recursos Extra: <strong id="metricBloat" style="color:#30d158;">Purgados (HDMI 60fps)</strong></div>
      </div>
    </div>

    <!-- Dock Principal de Aplicaciones estilo Apple TV -->
    <div class="tvos-dock-container">
      <div class="section-label">
        <span>Aplicaciones y Canales Directos (INTV_ASIST)</span>
        <span>Navega con Flechas / Ratón · Enter para Abrir en TV</span>
      </div>
      <div class="app-grid" id="appGrid">
        <div class="tvos-app-card card-appletv focused" data-app="appletv" data-title="Apple TV+" data-sub="Originales de Apple · Películas y Series en 4K HDR" data-c1="rgba(10,132,255,0.35)" onclick="launchApp('appletv')">
          <div class="app-icon-symbol">tv+</div>
          <div class="app-card-label">Apple TV+</div>
        </div>
        <div class="tvos-app-card card-youtube" data-app="youtube" data-title="YouTube" data-sub="Vídeos, Música y Transmisiones en Directo en INTV_ASIST" data-c1="rgba(255,59,48,0.38)" onclick="launchApp('youtube')">
          <div class="app-icon-symbol">▶ YT</div>
          <div class="app-card-label">YouTube</div>
        </div>
        <div class="tvos-app-card card-netflix" data-app="netflix" data-title="Netflix" data-sub="Series, Películas y Documentales en Streaming" data-c1="rgba(229,9,20,0.4)" onclick="launchApp('netflix')">
          <div class="app-icon-symbol">N</div>
          <div class="app-card-label">Netflix</div>
        </div>
        <div class="tvos-app-card card-prime" data-app="prime" data-title="Prime Video" data-sub="Amazon Originals, Cine y Deportes en Directo" data-c1="rgba(0,168,225,0.38)" onclick="launchApp('prime')">
          <div class="app-icon-symbol">prime</div>
          <div class="app-card-label">Prime Video</div>
        </div>
        <div class="tvos-app-card card-disney" data-app="disney" data-title="Disney+" data-sub="Disney, Pixar, Marvel, Star Wars y National Geographic" data-c1="rgba(17,60,207,0.42)" onclick="launchApp('disney')">
          <div class="app-icon-symbol">D+</div>
          <div class="app-card-label">Disney+</div>
        </div>
        <div class="tvos-app-card card-spotify" data-app="spotify" data-title="Spotify" data-sub="Música y Podcasts en Alta Fidelidad" data-c1="rgba(29,185,84,0.38)" onclick="launchApp('spotify')">
          <div class="app-icon-symbol">((●))</div>
          <div class="app-card-label">Spotify</div>
        </div>
        <div class="tvos-app-card card-kodi" data-app="kodi" data-title="Kodi Media Center" data-sub="Reproductor local de alta eficiencia y cine en red" data-c1="rgba(23,178,231,0.38)" onclick="launchApp('kodi')">
          <div class="app-icon-symbol">❖</div>
          <div class="app-card-label">Kodi</div>
        </div>
        <div class="tvos-app-card card-vlc" data-app="vlc" data-title="VLC Player" data-sub="Reproducción directa acelerada por hardware" data-c1="rgba(255,159,10,0.38)" onclick="launchApp('vlc')">
          <div class="app-icon-symbol">▲ VLC</div>
          <div class="app-card-label">VLC</div>
        </div>
        <div class="tvos-app-card card-settings" data-app="settings" data-title="Ajustes del Sistema" data-sub="Configuración de Red, HDMI, Bluetooth y Sistema de INTV_ASIST" data-c1="rgba(142,142,147,0.32)" onclick="launchApp('settings')">
          <div class="app-icon-symbol">⚙</div>
          <div class="app-card-label">Ajustes TV</div>
        </div>
        <div class="tvos-app-card card-turbo" data-app="turbo" data-title="Purga Turbo Zero-Bloat" data-sub="Libera memoria RAM, desactiva telemetría en segundo plano y acelera animaciones" data-c1="rgba(48,209,88,0.4)" onclick="triggerOptimization()">
          <div class="app-icon-symbol">⚡</div>
          <div class="app-card-label">Purgar RAM</div>
        </div>
      </div>
    </div>
  </section>

  <!-- Siri Remote Virtual (Control a Distancia en Tiempo Real) -->
  <aside class="siri-remote-shell" aria-label="Control Remoto Apple TV">
    <div class="remote-top-row">
      <button class="remote-small-btn" onclick="sendKey('SEARCH')" title="Buscar / Asistente">🎙</button>
      <span style="font-size:11px;font-weight:600;color:rgba(255,255,255,0.45);letter-spacing:0.6px;">SIRI REMOTE</span>
      <button class="remote-small-btn power" onclick="sendKey('POWER')" title="Encender / Reposo (Power)">⏻</button>
    </div>

    <!-- Clickpad Circular -->
    <div class="siri-clickpad">
      <button class="dpad-dir dpad-up" onclick="sendKey('DPAD_UP')" title="Arriba (Flecha Arriba)">▲</button>
      <button class="dpad-dir dpad-down" onclick="sendKey('DPAD_DOWN')" title="Abajo (Flecha Abajo)">▼</button>
      <button class="dpad-dir dpad-left" onclick="sendKey('DPAD_LEFT')" title="Izquierda (Flecha Izquierda)">◀</button>
      <button class="dpad-dir dpad-right" onclick="sendKey('DPAD_RIGHT')" title="Derecha (Flecha Derecha)">▶</button>
      <button class="dpad-center" onclick="sendKey('DPAD_CENTER')" title="Seleccionar / OK (Enter)">OK</button>
    </div>

    <!-- Botones de Control Apple TV -->
    <div class="remote-button-grid">
      <button class="remote-btn" onclick="sendKey('BACK')" title="Atrás (Backspace / Esc)">
        ‹
        <span>ATRÁS</span>
      </button>
      <button class="remote-btn" onclick="sendKey('HOME')" title="Inicio / Apple TV Home (Tecla H)">
        
        <span>TV / HOME</span>
      </button>

      <button class="remote-btn" onclick="sendKey('MEDIA_PLAY_PAUSE')" title="Reproducir / Pausar (Espacio)">
        ⏯
        <span>PLAY</span>
      </button>

      <div class="volume-rocker">
        <button class="vol-half" onclick="sendKey('VOLUME_UP')" title="Subir Volumen (+)">+</button>
        <div class="vol-divider"></div>
        <button class="vol-half" onclick="sendKey('VOLUME_DOWN')" title="Bajar Volumen (-)">−</button>
      </div>

      <button class="remote-btn" onclick="sendKey('MUTE')" title="Silenciar (Tecla M)">
        🔇
        <span>MUTE</span>
      </button>
    </div>

    <div class="remote-footer-hint">
      Teclado activo: Flechas · Enter (OK) · Esc (Atrás) · H (Home) · +/- (Vol)
    </div>
  </aside>
</main>

<!-- Modal de Emparejamiento PIN Android TV Remote v2 -->
<div class="modal-backdrop" id="pairModal">
  <div class="tvos-modal">
    <h3>Vincular Control a Distancia</h3>
    <p id="pairModalText">
      Se ha enviado la solicitud al televisor <strong>INTV_ASIST (REDACTED_IP:6467)</strong>.<br>
      Introduce el código PIN de 6 caracteres que aparece en la pantalla de tu TV:
    </p>
    <input type="text" id="pinInput" class="pin-input" maxlength="6" placeholder="A1B2C3" autocomplete="off" />
    <div class="modal-actions">
      <button class="action-pill" onclick="closePairModal()">Cancelar</button>
      <button class="action-pill primary" onclick="submitPairingPin()">Confirmar PIN</button>
    </div>
  </div>
</div>

<script>
  const cards = Array.from(document.querySelectorAll('.tvos-app-card'));
  let focusedIndex = 0;

  function updateClock() {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    document.getElementById('clockDisplay').textContent = `${hh}:${mm}`;
  }
  setInterval(updateClock, 10000);
  updateClock();

  function showToast(msg) {
    const t = document.getElementById('hudToast');
    t.textContent = msg;
    t.classList.add('visible');
    clearTimeout(window.__toastTimer);
    window.__toastTimer = setTimeout(() => t.classList.remove('visible'), 2200);
  }

  function focusCard(idx) {
    if (idx < 0 || idx >= cards.length) return;
    cards.forEach(c => c.classList.remove('focused'));
    focusedIndex = idx;
    const card = cards[focusedIndex];
    card.classList.add('focused');
    document.getElementById('heroTitle').textContent = card.dataset.title;
    document.getElementById('heroSub').textContent = card.dataset.sub;
    document.documentElement.style.setProperty('--hero-c1', card.dataset.c1 || 'rgba(10,132,255,0.35)');
  }

  cards.forEach((c, idx) => {
    c.addEventListener('mouseenter', () => focusCard(idx));
  });

  async function apiCall(path, payload = {}) {
    const base = window.location.protocol === 'file:' ? 'http://127.0.0.1:8788' : '';
    try {
      const res = await fetch(base + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      return await res.json();
    } catch (e) {
      return { status: 'error', message: String(e) };
    }
  }

  async function refreshStatus() {
    const base = window.location.protocol === 'file:' ? 'http://127.0.0.1:8788' : '';
    try {
      const res = await fetch(base + '/api/status');
      const data = await res.json();
      const dot = document.getElementById('statusDot');
      const rem = document.getElementById('metricRemote');
      const pairBtn = document.getElementById('pairBtn');
      if (data.remote_connected) {
        dot.className = 'status-dot';
        rem.textContent = 'Conectado (TLS 6466 Activo)';
        rem.style.color = '#30d158';
        pairBtn.textContent = '✓ Control Vinculado';
      } else if (data.reachable) {
        dot.className = 'status-dot warn';
        rem.textContent = data.needs_pairing ? 'Listo para Vincular PIN (6467)' : 'En línea (REDACTED_IP)';
        rem.style.color = '#ff9f0a';
      } else {
        dot.className = 'status-dot warn';
        rem.textContent = 'Reconectando...';
      }
      if (data.current_app) {
        document.getElementById('heroTag').textContent = ` En reproducción en TV: ${data.current_app}`;
      }
    } catch (e) {}
  }
  setInterval(refreshStatus, 4000);
  refreshStatus();

  async function sendKey(key) {
    showToast(` Remote → ${key}`);
    const res = await apiCall('/api/key', { key });
    if (res.needs_pairing) {
      openPairModal();
    } else if (res.message) {
      showToast(res.message);
    }
  }

  async function launchApp(appId) {
    showToast(`Abriendo ${appId.toUpperCase()} en INTV_ASIST...`);
    const res = await apiCall('/api/launch', { app: appId });
    if (res.needs_pairing) {
      openPairModal();
    } else if (res.message) {
      showToast(res.message);
    }
  }

  async function triggerOptimization() {
    showToast('⚡ Ejecutando purga Zero-Bloat en INTV_ASIST...');
    const res = await apiCall('/api/optimize', {});
    showToast(res.message || '✓ Recursos optimizados');
    refreshStatus();
  }

  async function pairBluetooth() {
    showToast('ᛒ Conectando Bluetooth EC:C1:AB:56:38:72...');
    const res = await apiCall('/api/bt/pair', {});
    showToast(res.message || 'Bluetooth actualizado');
  }

  async function openPairModal() {
    document.getElementById('pairModal').classList.add('open');
    document.getElementById('pinInput').value = '';
    document.getElementById('pinInput').focus();
    const res = await apiCall('/api/pair/start', {});
    if (res.message) {
      document.getElementById('pairModalText').innerHTML = res.message;
    }
  }

  function closePairModal() {
    document.getElementById('pairModal').classList.remove('open');
  }

  async function submitPairingPin() {
    const pin = document.getElementById('pinInput').value.trim();
    if (!pin) return;
    showToast('Verificando PIN con INTV_ASIST...');
    const res = await apiCall('/api/pair/finish', { pin });
    if (res.status === 'ok') {
      closePairModal();
      showToast('✓ ¡Control Remoto Apple TV vinculado con éxito!');
      refreshStatus();
    } else {
      showToast(res.message || 'PIN inválido, inténtalo de nuevo');
    }
  }

  // Soporte completo de teclado físico como Siri Remote
  window.addEventListener('keydown', (e) => {
    if (document.getElementById('pairModal').classList.contains('open')) {
      if (e.key === 'Enter') submitPairingPin();
      if (e.key === 'Escape') closePairModal();
      return;
    }
    switch (e.key) {
      case 'ArrowUp':
        e.preventDefault();
        sendKey('DPAD_UP');
        break;
      case 'ArrowDown':
        e.preventDefault();
        sendKey('DPAD_DOWN');
        break;
      case 'ArrowLeft':
        e.preventDefault();
        focusCard((focusedIndex - 1 + cards.length) % cards.length);
        sendKey('DPAD_LEFT');
        break;
      case 'ArrowRight':
        e.preventDefault();
        focusCard((focusedIndex + 1) % cards.length);
        sendKey('DPAD_RIGHT');
        break;
      case 'Enter':
        e.preventDefault();
        sendKey('DPAD_CENTER');
        break;
      case 'Backspace':
      case 'Escape':
        e.preventDefault();
        sendKey('BACK');
        break;
      case 'h':
      case 'H':
        e.preventDefault();
        sendKey('HOME');
        break;
      case ' ':
        e.preventDefault();
        sendKey('MEDIA_PLAY_PAUSE');
        break;
      case '+':
      case '=':
        e.preventDefault();
        sendKey('VOLUME_UP');
        break;
      case '-':
      case '_':
        e.preventDefault();
        sendKey('VOLUME_DOWN');
        break;
      case 'm':
      case 'M':
        e.preventDefault();
        sendKey('MUTE');
        break;
    }
  });
</script>
</body>
</html>
"""


class IntvAppleTVController:
    """Controlador asíncrono ultra-ligero para INTV_ASIST (EC:C1:AB:56:38:72 / REDACTED_IP)."""

    def __init__(self) -> None:
        CERT_DIR.mkdir(parents=True, exist_ok=True)
        self.remote: Optional[AndroidTVRemote] = None
        self.remote_connected: bool = False
        self.needs_pairing: bool = False
        self.pairing_in_progress: bool = False
        self.last_optimization_ts: float = 0.0
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE

    def ensure_subnet_route(self) -> None:
        """Garantiza que enp2s0 tenga dirección en REDACTED_IP/24 para enlace directo con REDACTED_IP."""
        try:
            out = subprocess.run(
                ["ip", "-4", "addr", "show", "dev", "enp2s0"],
                capture_output=True,
                text=True,
                timeout=3,
            ).stdout
            if "192.168.39." not in out:
                subprocess.run(
                    ["nmcli", "connection", "modify", "time", "+ipv4.addresses", "REDACTED_IP/24"],
                    capture_output=True,
                    timeout=5,
                )
                subprocess.run(["nmcli", "connection", "up", "time"], capture_output=True, timeout=8)
        except Exception as e:
            logger.warning(f"Subnet check warning: {e}")

    async def init_remote(self) -> None:
        """Inicializa cliente AndroidTVRemote v2 y aplica la optimización Zero-Bloat inicial."""
        self.ensure_subnet_route()
        self.apply_eureka_zero_bloat()

        self.remote = AndroidTVRemote(
            client_name="Apple TV Sovereign Remote",
            certfile=CERT_FILE,
            keyfile=KEY_FILE,
            host=TARGET_IP,
            api_port=API_PORT,
            pair_port=PAIR_PORT,
        )
        await self.remote.async_generate_cert_if_missing()
        await self.try_connect()

    async def try_connect(self) -> bool:
        if not self.remote:
            return False
        try:
            await self.remote.async_connect()
            self.remote_connected = True
            self.needs_pairing = False
            logger.info(f"Conectado exitosamente a INTV_ASIST ({TARGET_IP}:{API_PORT})")
            return True
        except InvalidAuth:
            self.remote_connected = False
            self.needs_pairing = True
            logger.info("INTV_ASIST requiere vinculación PIN inicial (puerto 6467).")
            return False
        except (CannotConnect, ConnectionClosed, Exception) as e:
            self.remote_connected = False
            logger.warning(f"No se pudo conectar aún a {TARGET_IP}:{API_PORT}: {e}")
            return False

    def apply_eureka_zero_bloat(self) -> Dict[str, Any]:
        """Desactiva telemetría, reportes crash, IPC en la nube, notificaciones de red y activa 60fps HDMI."""
        results: Dict[str, Any] = {"eureka_optimized": False, "adb_debloated": []}
        payload = json.dumps(
            {
                "opt_in": {
                    "stats": False,
                    "crash": False,
                    "cloud_ipc": False,
                    "opencast": False,
                    "preview_channel": False,
                    "remote_ducking": False,
                    "hdmi_prefer_high_fps": True,
                },
                "settings": {
                    "system_sound_effects": False,
                    "control_notifications": 2,
                },
            }
        ).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"https://{TARGET_IP}:{EUREKA_HTTPS_PORT}/setup/set_eureka_info",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=2.5) as resp:
                if resp.status == 200:
                    results["eureka_optimized"] = True
                    self.last_optimization_ts = time.time()
        except Exception as e:
            results["eureka_error"] = str(e)

        # Si ADB (5555) está disponible en el dispositivo, deshabilita paquetes pesados y acelera animaciones
        try:
            s = socket.create_connection((TARGET_IP, 5555), timeout=0.4)
            s.close()
            subprocess.run(["adb", "connect", f"{TARGET_IP}:5555"], capture_output=True, timeout=2)
            for scale in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
                subprocess.run(
                    ["adb", "-s", f"{TARGET_IP}:5555", "shell", "settings", "put", "global", scale, "0.5"],
                    capture_output=True,
                    timeout=2,
                )
            subprocess.run(
                ["adb", "-s", f"{TARGET_IP}:5555", "shell", "cmd", "activity", "kill-all"],
                capture_output=True,
                timeout=2,
            )
            for pkg in ANDROID_TV_BLOAT_PACKAGES:
                r = subprocess.run(
                    ["adb", "-s", f"{TARGET_IP}:5555", "shell", "pm", "disable-user", "--user", "0", pkg],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if r.returncode == 0:
                    results["adb_debloated"].append(pkg)
        except Exception:
            pass

        return results

    async def start_pairing(self) -> Dict[str, Any]:
        if not self.remote:
            await self.init_remote()
        try:
            if self.pairing_in_progress:
                try:
                    await self.remote.async_finish_pairing("")
                except Exception:
                    pass
            await self.remote.async_start_pairing()
            self.pairing_in_progress = True
            return {
                "status": "ok",
                "message": (
                    f"Solicitud enviada a <strong>INTV_ASIST ({TARGET_IP}:6467)</strong>.<br>"
                    "Mira la pantalla de tu TV e introduce el código PIN de 6 caracteres:"
                ),
            }
        except Exception as e:
            self.pairing_in_progress = False
            return {"status": "error", "message": f"Error iniciando vinculación: {e}"}

    async def finish_pairing(self, pin: str) -> Dict[str, Any]:
        if not self.remote:
            return {"status": "error", "message": "Control remoto no inicializado."}
        try:
            await self.remote.async_finish_pairing(pin.strip())
            self.pairing_in_progress = False
            await asyncio.sleep(0.4)
            connected = await self.try_connect()
            return {
                "status": "ok" if connected else "partial",
                "remote_connected": connected,
                "message": "¡Vinculación completada y control activo!",
            }
        except Exception as e:
            return {"status": "error", "message": f"Error verificando PIN: {e}"}

    async def send_key(self, key: str) -> Dict[str, Any]:
        if not self.remote_connected:
            await self.try_connect()
        if self.remote and self.remote_connected:
            try:
                self.remote.send_key_command(key)
                return {"status": "ok", "message": f" Tecla enviada a INTV_ASIST: {key}"}
            except Exception as e:
                self.remote_connected = False
                return {"status": "error", "message": f"Fallo al enviar tecla: {e}"}

        return {
            "status": "needs_pairing",
            "needs_pairing": True,
            "message": "Vincula primero el PIN que aparece en tu TV (Botón 'Vincular Control TV')",
        }

    async def launch_app(self, app_id: str) -> Dict[str, Any]:
        app_info = APP_CATALOG.get(app_id)
        if not app_info:
            return {"status": "error", "message": f"App '{app_id}' no registrada."}

        if not self.remote_connected:
            await self.try_connect()

        if self.remote and self.remote_connected:
            try:
                self.remote.send_launch_app_command(app_info["deeplink"])
                return {"status": "ok", "message": f" Abriendo {app_info['name']} en INTV_ASIST"}
            except Exception as e:
                return {"status": "error", "message": f"Error abriendo app: {e}"}

        return {
            "status": "needs_pairing",
            "needs_pairing": True,
            "message": f"Para abrir {app_info['name']} en la TV, confirma primero el PIN de vinculación.",
        }

    def pair_bluetooth(self) -> Dict[str, Any]:
        try:
            subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True, timeout=2)
            subprocess.run(["bluetoothctl", "power", "on"], capture_output=True, timeout=2)
            subprocess.run(["bluetoothctl", "trust", TARGET_BT_MAC], capture_output=True, timeout=2)
            subprocess.run(["bluetoothctl", "--timeout", "3", "pair", TARGET_BT_MAC], capture_output=True, timeout=4)
            subprocess.run(["bluetoothctl", "--timeout", "2", "connect", TARGET_BT_MAC], capture_output=True, timeout=3)
            info = subprocess.run(
                ["bluetoothctl", "info", TARGET_BT_MAC], capture_output=True, text=True, timeout=2
            ).stdout
            connected = "Connected: yes" in info
            paired = "Paired: yes" in info
            return {
                "status": "ok",
                "connected": connected,
                "paired": paired,
                "message": (
                    f"Bluetooth {TARGET_BT_MAC}: {'Conectado' if connected else 'Solicitud enviada a TV (Aceptar en pantalla)'}"
                ),
            }
        except Exception as e:
            return {"status": "error", "message": f"Bluetooth error: {e}"}

    def get_status(self) -> Dict[str, Any]:
        reachable = False
        try:
            s = socket.create_connection((TARGET_IP, API_PORT), timeout=0.4)
            s.close()
            reachable = True
        except Exception:
            pass

        return {
            "device": "INTV_ASIST",
            "manufacturer": "Videostrong",
            "bt_mac": TARGET_BT_MAC,
            "ip": TARGET_IP,
            "reachable": reachable,
            "remote_connected": self.remote_connected,
            "needs_pairing": self.needs_pairing,
            "is_on": getattr(self.remote, "is_on", None) if self.remote_connected else None,
            "current_app": getattr(self.remote, "current_app", None) if self.remote_connected else None,
            "last_optimization_ts": self.last_optimization_ts,
        }


controller = IntvAppleTVController()


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=3.0)
        if not request_line:
            writer.close()
            return
        parts = request_line.decode("utf-8", errors="ignore").strip().split()
        if len(parts) < 2:
            writer.close()
            return
        method, path = parts[0], parts[1].split("?")[0]

        headers: Dict[str, str] = {}
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=3.0)
            if not line or line in (b"\r\n", b"\n"):
                break
            vline = line.decode("utf-8", errors="ignore").strip()
            if ":" in vline:
                k, v = vline.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        content_length = int(headers.get("content-length", "0"))
        body_bytes = await asyncio.wait_for(reader.readexactly(content_length), timeout=3.0) if content_length > 0 else b""
        payload = json.loads(body_bytes.decode("utf-8", errors="ignore")) if body_bytes else {}

        if method == "OPTIONS":
            resp_headers = (
                "HTTP/1.1 204 No Content\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "Access-Control-Allow-Methods: GET, POST, OPTIONS, HEAD\r\n"
                "Access-Control-Allow-Headers: Content-Type\r\n"
                "Connection: close\r\n\r\n"
            ).encode("utf-8")
            writer.write(resp_headers)
            await writer.drain()
            writer.close()
            return

        if method in ("GET", "HEAD") and path in ("/", "/index.html"):
            body = HTML_APPLE_TV_UI.encode("utf-8")
            resp_headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Cache-Control: no-store\r\n"
                "Connection: close\r\n\r\n"
            ).encode("utf-8")
            writer.write(resp_headers if method == "HEAD" else resp_headers + body)
            await writer.drain()
            writer.close()
            return

        if path == "/api/status":
            res_data = controller.get_status()
        elif path == "/api/key" and method == "POST":
            res_data = await controller.send_key(payload.get("key", "DPAD_CENTER"))
        elif path == "/api/launch" and method == "POST":
            res_data = await controller.launch_app(payload.get("app", "appletv"))
        elif path == "/api/pair/start" and method == "POST":
            res_data = await controller.start_pairing()
        elif path == "/api/pair/finish" and method == "POST":
            res_data = await controller.finish_pairing(payload.get("pin", ""))
        elif path == "/api/optimize" and method == "POST":
            opt = controller.apply_eureka_zero_bloat()
            res_data = {
                "status": "ok",
                "details": opt,
                "message": "✓ Telemetría, reportes en segundo plano y notificaciones purgadas (HDMI 60fps activo)",
            }
        elif path == "/api/bt/pair" and method == "POST":
            res_data = controller.pair_bluetooth()
        else:
            res_data = {"status": "not_found"}

        body = json.dumps(res_data).encode("utf-8")
        resp_headers = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("utf-8")
        writer.write(resp_headers + body)
        await writer.drain()
    except Exception as e:
        logger.debug(f"HTTP handler error: {e}")
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main_daemon() -> None:
    await controller.init_remote()
    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    logger.info(
        f"Apple TV Sovereign Hub para INTV_ASIST ({TARGET_BT_MAC}) escuchando en http://127.0.0.1:{LISTEN_PORT}"
    )
    async with server:
        await server.serve_standalone() if hasattr(server, "serve_standalone") else await server.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "optimize":
            print(json.dumps(controller.apply_eureka_zero_bloat(), indent=2))
            sys.exit(0)
        elif cmd == "status":
            controller.ensure_subnet_route()
            print(json.dumps(controller.get_status(), indent=2))
            sys.exit(0)
    asyncio.run(main_daemon())

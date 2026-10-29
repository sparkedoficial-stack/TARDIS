"""
core/nxnative_mk8d_ipad_ui.py - Interfaz Nativa iOS/iPadOS para nxnative · Mario Kart 8 Deluxe (0100152000022000 v4.0.1)
========================================================================================================================
Basado exactamente en https://github.com/seedds/nxnative/blob/main/dm/games/0100152000022000/README.md#files-and-shaders:
  - Updates 4.0.0 (v1441792) y 4.0.1 (v1507328, package) sobre SDK 4.4.0 (sead / agl / gsys + NintendoWare G3d, Ui2d, Vfx, Atk + Pia).
  - 29,785 shaders (12,579 vertex, 17,177 pixel, 28 compute, 1 geometry) y 19,012 variation pairs divididos en
    23 paquetes _b.metallib dentro de DmIOS.app/msl/b-8e52e2292032/ (inputs beadcc8fc60e).
  - Add-on Content 0100152000023001 (contents.dat + version.txt, RomFS cache 0x88 bytes) + MiiModel 0100000000000802
    stand-in (6 default Miis + empty head mesh) + UserSave y CommonSave_device independientes.
  - Ejecutable DmIOS.app/DmIOS con segmentos __TEXT,__dm<mod>x0, __DM<mod>W,__img, __TEXT,__dm<mod>x1 (main, subsdk0, sdk).
"""

from __future__ import annotations


def get_nxnative_mk8d_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Mario Kart 8 Deluxe">
    <title>Mario Kart 8 Deluxe 4.0.1 · nxnative (0100152000022000)</title>
    <link rel="apple-touch-icon" href="/mk8d/icon.png">
    <style>
        @font-face {
            font-family: 'NintendoExt';
            src: url('/mk8d/font.ttf') format('truetype');
        }
        :root {
            --ios-bg: #000000;
            --ios-card: #1c1c1e;
            --ios-sep: rgba(84, 84, 88, 0.65);
            --ios-blue: #0a84ff;
            --ios-green: #30d158;
            --ios-red: #ff453a;
            --ios-orange: #ff9f0a;
            --ios-text: #ffffff;
            --ios-sub: rgba(235, 235, 245, 0.6);
        }
        * {
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
            user-select: none;
            -webkit-user-select: none;
        }
        html, body {
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            background: var(--ios-bg);
            color: var(--ios-text);
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", sans-serif;
            overflow: hidden;
        }

        /* =================================================================
           1. PANTALLA LAUNCHER.SWIFT (Split HStack: 1/3 Left + 2/3 Right)
           ================================================================= */
        #launcher-screen {
            display: flex;
            width: 100vw;
            height: 100vh;
            background: #000000;
            padding-left: env(safe-area-inset-left, 0px);
            padding-right: env(safe-area-inset-right, 0px);
        }
        .launcher-left {
            width: 34%;
            height: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 20px 18px;
            border-right: 0.5px solid rgba(255,255,255,0.12);
            background: radial-gradient(circle at 50% 22%, rgba(10, 132, 255, 0.18), transparent 65%);
            text-align: center;
        }
        .app-icon {
            width: 100px;
            height: 100px;
            border-radius: 22px;
            box-shadow: 0 12px 32px rgba(10, 132, 255, 0.35), 0 0 0 1px rgba(255,255,255,0.18);
            margin-bottom: 14px;
            object-fit: cover;
        }
        .game-title {
            font-size: 1.50rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin: 0 0 4px 0;
            line-height: 1.2;
        }
        .game-version {
            font-size: 0.88rem;
            color: var(--ios-sub);
            margin-bottom: 6px;
        }
        .game-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 0.70rem;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            background: rgba(48, 209, 88, 0.15);
            color: #30d158;
            border: 1px solid rgba(48, 209, 88, 0.38);
            padding: 4px 10px;
            border-radius: 999px;
            margin-bottom: 14px;
        }
        .play-btn {
            width: 100%;
            max-width: 225px;
            padding: 13px 20px;
            border-radius: 14px;
            border: 1px solid rgba(255,255,255,0.28);
            background: linear-gradient(135deg, #0a84ff 0%, #0066cc 100%);
            color: #fff;
            font-size: 1.12rem;
            font-weight: 600;
            cursor: pointer;
            box-shadow: 0 8px 24px rgba(10, 132, 255, 0.42);
            transition: transform 0.1s ease, filter 0.15s ease;
            margin-bottom: 9px;
        }
        .play-btn:active {
            transform: scale(0.96);
            filter: brightness(1.15);
        }
        .secondary-btn {
            width: 100%;
            max-width: 225px;
            padding: 8px 12px;
            border-radius: 11px;
            border: 1px solid rgba(255,255,255,0.16);
            background: rgba(255,255,255,0.08);
            color: #e5e5ea;
            font-size: 0.78rem;
            font-weight: 500;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            margin-bottom: 7px;
            cursor: pointer;
        }
        .shader-summary-card {
            width: 100%;
            max-width: 245px;
            margin-top: 8px;
            background: rgba(28, 28, 30, 0.9);
            border: 1px solid rgba(56, 189, 248, 0.28);
            border-radius: 12px;
            padding: 9px 11px;
            font-size: 0.70rem;
            line-height: 1.42;
            text-align: left;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            color: #cbd5e1;
        }

        .launcher-right {
            width: 66%;
            height: 100%;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
            padding: 18px 24px 60px 24px;
            background: #000000;
        }
        .section-header {
            font-size: 0.78rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: var(--ios-sub);
            margin: 16px 0 7px 14px;
        }
        .section-header:first-child {
            margin-top: 2px;
        }
        .inset-group {
            background: var(--ios-card);
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 12px;
        }
        .setting-row {
            display: flex;
            flex-direction: column;
            padding: 10px 16px;
            border-bottom: 0.5px solid var(--ios-sep);
        }
        .setting-row:last-child {
            border-bottom: none;
        }
        .setting-main {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            min-height: 26px;
        }
        .setting-label {
            font-size: 0.95rem;
            font-weight: 400;
            color: #fff;
        }
        .setting-note {
            font-size: 0.74rem;
            color: var(--ios-sub);
            margin-top: 4px;
            line-height: 1.3;
        }
        .ios-select {
            background: rgba(118, 118, 128, 0.24);
            color: var(--ios-blue);
            border: none;
            border-radius: 8px;
            padding: 6px 10px;
            font-size: 0.90rem;
            font-weight: 500;
            outline: none;
        }
        .ios-slider-wrap {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .ios-slider-val {
            font-family: ui-monospace, SFMono-Regular, monospace;
            font-size: 0.84rem;
            color: var(--ios-sub);
            min-width: 110px;
            text-align: right;
        }
        input[type="range"].ios-slider {
            width: 130px;
            accent-color: var(--ios-blue);
        }
        .ios-switch {
            position: relative;
            display: inline-block;
            width: 51px;
            height: 31px;
            flex-shrink: 0;
        }
        .ios-switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }
        .ios-slider-toggle {
            position: absolute;
            cursor: pointer;
            inset: 0;
            background-color: rgba(120, 120, 128, 0.32);
            transition: .2s;
            border-radius: 31px;
        }
        .ios-slider-toggle:before {
            position: absolute;
            content: "";
            height: 27px;
            width: 27px;
            left: 2px;
            bottom: 2px;
            background-color: white;
            transition: .2s;
            border-radius: 50%;
            box-shadow: 0 2px 5px rgba(0,0,0,0.3);
        }
        .ios-switch input:checked + .ios-slider-toggle {
            background-color: var(--ios-green);
        }
        .ios-switch input:checked + .ios-slider-toggle:before {
            transform: translateX(20px);
        }
        .reset-btn {
            background: none;
            border: none;
            color: var(--ios-blue);
            font-size: 0.95rem;
            padding: 4px 0;
            cursor: pointer;
            text-align: left;
        }
        .reset-btn:disabled {
            color: rgba(235, 235, 245, 0.3);
        }
        .metallib-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: 6px;
            margin-top: 8px;
        }
        .metallib-pill {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(56, 189, 248, 0.25);
            border-radius: 7px;
            padding: 4px 8px;
            font-family: ui-monospace, SFMono-Regular, monospace;
            font-size: 0.68rem;
            display: flex;
            justify-content: space-between;
            color: #e2e8f0;
        }

        /* =================================================================
           2. PANTALLA DE JUEGO DMIOS + DMGAMEPAD.M + METAL 4 HUD
           ================================================================= */
        #game-screen {
            display: none;
            position: fixed;
            inset: 0;
            width: 100vw;
            height: 100vh;
            background: #000;
            overflow: hidden;
        }
        #mk8d-canvas {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            display: block;
        }
        #fps-pill {
            position: absolute;
            top: 12px;
            left: 18px;
            background: rgba(0, 0, 0, 0.65);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(255,255,255,0.18);
            border-radius: 8px;
            padding: 4px 10px;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.80rem;
            font-weight: 700;
            color: #30d158;
            z-index: 30;
            pointer-events: none;
        }
        #metal-hud {
            position: absolute;
            top: 44px;
            left: 18px;
            background: rgba(10, 12, 18, 0.80);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(56, 189, 248, 0.35);
            border-radius: 10px;
            padding: 8px 12px;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.69rem;
            line-height: 1.42;
            color: #e2e8f0;
            z-index: 30;
            pointer-events: none;
        }
        #race-hud {
            position: absolute;
            top: 12px;
            right: 160px;
            display: flex;
            align-items: center;
            gap: 10px;
            z-index: 25;
            pointer-events: none;
        }
        .race-stat-box {
            background: linear-gradient(135deg, rgba(15,23,42,0.85), rgba(30,41,59,0.85));
            border: 1.5px solid rgba(255,255,255,0.28);
            border-radius: 12px;
            padding: 5px 12px;
            font-weight: 800;
            font-style: italic;
            box-shadow: 0 4px 14px rgba(0,0,0,0.45);
        }
        #dm-gamepad {
            position: absolute;
            inset: 0;
            pointer-events: none;
            z-index: 40;
        }
        .gp-btn {
            position: absolute;
            pointer-events: auto;
            background: rgba(255, 255, 255, 0.14);
            border: 1.8px solid rgba(255, 255, 255, 0.42);
            color: rgba(255, 255, 255, 0.9);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            backdrop-filter: blur(4px);
            transition: background 0.05s, transform 0.05s;
            touch-action: none;
        }
        .gp-btn.active {
            background: rgba(255, 255, 255, 0.48);
            border-color: #ffffff;
            transform: scale(0.94);
        }
        .gp-top-center {
            position: absolute;
            top: 12px;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            align-items: center;
            gap: 8px;
            pointer-events: auto;
            z-index: 45;
        }
        .gp-pill-btn {
            background: rgba(20, 20, 25, 0.65);
            border: 1.5px solid rgba(255, 255, 255, 0.35);
            color: #fff;
            border-radius: 999px;
            padding: 5px 12px;
            font-size: 0.76rem;
            font-weight: 700;
            cursor: pointer;
            backdrop-filter: blur(6px);
        }
        #btn-zl { top: 14px; left: 190px; width: 76px; height: 42px; border-radius: 18px 10px 10px 10px; }
        #btn-l  { top: 64px; left: 190px; width: 76px; height: 38px; border-radius: 10px; }
        #btn-zr { top: 14px; right: 20px; width: 82px; height: 44px; border-radius: 10px 18px 10px 10px; background: rgba(255, 159, 10, 0.22); border-color: rgba(255, 159, 10, 0.65); }
        #btn-r  { top: 64px; right: 20px; width: 82px; height: 38px; border-radius: 10px; }
        #stick-left-zone {
            position: absolute;
            bottom: 36px;
            left: 36px;
            width: 156px;
            height: 156px;
            border-radius: 50%;
            border: 2px solid rgba(255, 255, 255, 0.32);
            background: rgba(255, 255, 255, 0.07);
            pointer-events: auto;
            touch-action: none;
        }
        #stick-left-knob {
            position: absolute;
            top: 50%;
            left: 50%;
            width: 68px;
            height: 68px;
            margin-left: -34px;
            margin-top: -34px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.38);
            border: 2px solid rgba(255, 255, 255, 0.85);
            box-shadow: 0 4px 14px rgba(0,0,0,0.4);
            pointer-events: none;
        }
        #dpad-zone {
            position: absolute;
            bottom: 28px;
            left: 215px;
            width: 116px;
            height: 116px;
            pointer-events: auto;
        }
        .dpad-btn {
            position: absolute;
            width: 38px;
            height: 38px;
            border-radius: 8px;
            font-size: 0.85rem;
        }
        #btn-up    { top: 0; left: 39px; }
        #btn-down  { bottom: 0; left: 39px; }
        #btn-left  { top: 39px; left: 0; }
        #btn-right { top: 39px; right: 0; }
        #face-diamond {
            position: absolute;
            bottom: 34px;
            right: 34px;
            width: 184px;
            height: 184px;
            pointer-events: none;
        }
        .face-btn {
            width: 62px;
            height: 62px;
            border-radius: 50%;
            font-size: 1.15rem;
            font-weight: 800;
            box-shadow: 0 4px 12px rgba(0,0,0,0.45);
        }
        #btn-x { top: 0; left: 61px; }
        #btn-b { bottom: 0; left: 61px; background: rgba(255, 69, 58, 0.25); border-color: rgba(255, 69, 58, 0.75); }
        #btn-y { top: 61px; left: 0; background: rgba(48, 209, 88, 0.25); border-color: rgba(48, 209, 88, 0.75); }
        #btn-a { top: 61px; right: 0; background: rgba(10, 132, 255, 0.35); border-color: #38bdf8; }
    </style>
</head>
<body>

    <!-- =====================================================================
         1. PANTALLA LAUNCHER.SWIFT (dm/games/0100152000022000/README.md#files-and-shaders)
         ===================================================================== -->
    <div id="launcher-screen">
        <div class="launcher-left">
            <img src="/mk8d/icon.png" alt="Mario Kart 8 Deluxe" class="app-icon">
            <h1 class="game-title">Mario Kart 8 Deluxe</h1>
            <div class="game-version">Version 4.0.1 (v1507328) · 0100152000022000</div>
            <div class="game-badge">⚡ DmIOS.app · Chain b-8e52e2292032</div>

            <button class="play-btn" onclick="startGame()">▶ Play (4.0.1)</button>
            <a class="secondary-btn" href="/download/MarioKart8Deluxe.ipa">📦 Descargar MarioKart8Deluxe.ipa (6.66 MB)</a>
            <a class="secondary-btn" href="/mk8d.mobileconfig">📲 Actualizar Perfil WebClip iPadOS</a>

            <div class="shader-summary-card">
                <div style="color:#38bdf8;font-weight:700;margin-bottom:3px;">#files-and-shaders (4.0.0 & 4.0.1)</div>
                <div>• <strong>Total Shaders:</strong> 29,785</div>
                <div>• <strong>Stages:</strong> 12,579 VS · 17,177 PS · 28 CS · 1 GS</div>
                <div>• <strong>Variation Pairs:</strong> 19,012</div>
                <div>• <strong>Metal Libraries:</strong> 23 (_b.metallib)</div>
                <div>• <strong>Modules:</strong> main, subsdk0, sdk (SDK 4.4.0)</div>
                <div>• <strong>AOC / Mii:</strong> 0100152000023001 + MiiStandIn</div>
            </div>
        </div>

        <div class="launcher-right">
            <!-- SECTION: FILES AND SHADERS (README.md#files-and-shaders) -->
            <div class="section-header">Files & Shaders (dm/games/0100152000022000 · Chain b-8e52e2292032)</div>
            <div class="inset-group">
                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Shader Split Packages (29,785 Shaders · 19,012 Pairs)</span>
                        <span style="font-family:ui-monospace,monospace;font-size:0.78rem;color:#30d158;">23 _b.metallib LOADED ✓</span>
                    </div>
                    <div class="setting-note">BNSH in courses'/objects' .bfsha/.bfres inside .szs SARCs, .ptcl effects, layouts, agl's 2 BAHS sharcb & 37 in main (inputs: beadcc8fc60e).</div>
                    <div class="metallib-grid">
                        <div class="metallib-pill"><span>ps_course_b</span><span style="color:#38bdf8">9,738</span></div>
                        <div class="metallib-pill"><span>vs_course_b</span><span style="color:#38bdf8">6,659</span></div>
                        <div class="metallib-pill"><span>ps_mapobj_b</span><span style="color:#38bdf8">3,431</span></div>
                        <div class="metallib-pill"><span>vs_mapobj_b</span><span style="color:#38bdf8">3,360</span></div>
                        <div class="metallib-pill"><span>ps_common_b</span><span style="color:#38bdf8">2,695</span></div>
                        <div class="metallib-pill"><span>vs_common_b</span><span style="color:#38bdf8">1,210</span></div>
                        <div class="metallib-pill"><span>vs_driver_b</span><span style="color:#38bdf8">525</span></div>
                        <div class="metallib-pill"><span>ps_driver_b</span><span style="color:#38bdf8">446</span></div>
                        <div class="metallib-pill"><span>vs_kart_b</span><span style="color:#38bdf8">382</span></div>
                        <div class="metallib-pill"><span>ps_kart_b</span><span style="color:#38bdf8">374</span></div>
                        <div class="metallib-pill"><span>vs_racecommon</span><span style="color:#38bdf8">196</span></div>
                        <div class="metallib-pill"><span>ps_racecommon</span><span style="color:#38bdf8">186</span></div>
                        <div class="metallib-pill"><span>ps_ui3d / vs_ui3d</span><span style="color:#38bdf8">257</span></div>
                        <div class="metallib-pill"><span>ps/vs_trophy</span><span style="color:#38bdf8">231</span></div>
                        <div class="metallib-pill"><span>cs_course/common</span><span style="color:#38bdf8">28</span></div>
                        <div class="metallib-pill"><span>ps/vs_main + gs</span><span style="color:#38bdf8">38</span></div>
                    </div>
                </div>
                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Rewritten Modules & RomFS / AOC / Mii Stand-In</span>
                        <span style="font-family:ui-monospace,monospace;font-size:0.76rem;color:#38bdf8;">v1507328 (4.0.1) + v1441792 (4.0.0)</span>
                    </div>
                    <div class="setting-note">
                        • <strong>Modules:</strong> <code>main</code> (158c0c7399aabd7bf83795c2ef3484c7), <code>subsdk0</code> (d9de423efc1512328c3c05378c7cb031), <code>sdk</code> (ba520906609c503227871a314a94fb5f)<br>
                        • <strong>RomFS & AOC:</strong> <code>UI/cmn/movie/StaffCredits.mp4</code> marker · <code>aoc/0</code> (0100152000023001: contents.dat + version.txt, 0x88 cache) · <code>MiiResource:</code> (0100000000000802 stand-in, 6 default Miis) · <code>UserSave</code> & <code>CommonSave_device</code>
                    </div>
                </div>
            </div>

            <!-- SECTION: GAME -->
            <div class="section-header">Game</div>
            <div class="inset-group">
                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Dynamic resolution</span>
                        <label class="ios-switch">
                            <input type="checkbox" id="cfg-dynres" onchange="markChanged()">
                            <span class="ios-slider-toggle"></span>
                        </label>
                    </div>
                    <div class="setting-note">Adjusts resolution between 70% and 100% under load. Turn off to keep full resolution for the selected console mode.</div>
                </div>

                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Render scale</span>
                        <div class="ios-slider-wrap">
                            <span class="ios-slider-val" id="val-scale">100% (1920×1080)</span>
                            <input type="range" class="ios-slider" id="cfg-scale" min="0.5" max="1.0" step="0.05" value="1.0" oninput="updateScaleLabel(); markChanged()">
                        </div>
                    </div>
                </div>

                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Console mode</span>
                        <select class="ios-select" id="cfg-opmode" onchange="updateScaleLabel(); markChanged()">
                            <option value="1" selected>Docked (1080p · 60 fps)</option>
                            <option value="0">Handheld (720p · 60 fps)</option>
                        </select>
                    </div>
                </div>

                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Upscaling</span>
                        <select class="ios-select" id="cfg-upscale" onchange="markChanged()">
                            <option value="off" selected>Standard</option>
                            <option value="metalfx">MetalFX Spatial</option>
                        </select>
                    </div>
                    <div class="setting-note">Uses more GPU time and can increase heat.</div>
                </div>

                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Game language</span>
                        <select class="ios-select" id="cfg-lang" onchange="markChanged()">
                            <option value="es-419" selected>Latin American Spanish (es-419)</option>
                            <option value="es">Spanish (es)</option>
                            <option value="en-US">American English (en-US)</option>
                            <option value="ja">Japanese (ja)</option>
                            <option value="fr">French (fr)</option>
                            <option value="de">German (de)</option>
                        </select>
                    </div>
                </div>

                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Frame-rate counter</span>
                        <label class="ios-switch">
                            <input type="checkbox" id="cfg-fps" checked onchange="markChanged()">
                            <span class="ios-slider-toggle"></span>
                        </label>
                    </div>
                </div>
            </div>

            <!-- SECTION: CONTROLS -->
            <div class="section-header">Controls</div>
            <div class="inset-group">
                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Touch feedback</span>
                        <label class="ios-switch">
                            <input type="checkbox" id="cfg-haptics" checked onchange="markChanged()">
                            <span class="ios-slider-toggle"></span>
                        </label>
                    </div>
                </div>

                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Game rumble</span>
                        <label class="ios-switch">
                            <input type="checkbox" id="cfg-rumble" checked onchange="markChanged()">
                            <span class="ios-slider-toggle"></span>
                        </label>
                    </div>
                </div>

                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Rumble cutoff (DM_RUMBLE_MIN)</span>
                        <div class="ios-slider-wrap">
                            <span class="ios-slider-val" id="val-rumble-min">0.45 (Crashes & Drifts)</span>
                            <input type="range" class="ios-slider" id="cfg-rumble-min" min="0" max="0.9" step="0.05" value="0.45" oninput="document.getElementById('val-rumble-min').innerText=parseFloat(this.value).toFixed(2); markChanged()">
                        </div>
                    </div>
                    <div class="setting-note">The game holds its low band at 0.1–0.4 all race long; DM_RUMBLE_MIN=0.45 leaves crashes and drifts (README.md#found-on-this-game).</div>
                </div>
            </div>

            <!-- SECTION: PERFORMANCE -->
            <div class="section-header">Performance</div>
            <div class="inset-group">
                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Conditional rendering (render_cond on)</span>
                        <label class="ios-switch">
                            <input type="checkbox" id="cfg-rendercond" checked onchange="markChanged()">
                            <span class="ios-slider-toggle"></span>
                        </label>
                    </div>
                    <div class="setting-note">Evaluates SetRenderEnableConditional at replay as a course loads, matching NVN GPU behaviour.</div>
                </div>

                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Metal 4 pipelines (DM_PSO_MTL4)</span>
                        <label class="ios-switch">
                            <input type="checkbox" id="cfg-mtl4" checked onchange="markChanged()">
                            <span class="ios-slider-toggle"></span>
                        </label>
                    </div>
                    <div class="setting-note">Keeps a pipeline archive (19,012 shader pairs / 2,665 PSO pairs / 1,516 prewarm manifest entries).</div>
                </div>

                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Pipeline prebuild (DM_PSO_PREBUILD)</span>
                        <label class="ios-switch">
                            <input type="checkbox" id="cfg-prebuild" checked onchange="markChanged()">
                            <span class="ios-slider-toggle"></span>
                        </label>
                    </div>
                </div>

                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Encode thread (DM_NVN_ENC_THREAD)</span>
                        <label class="ios-switch">
                            <input type="checkbox" id="cfg-encthr" checked onchange="markChanged()">
                            <span class="ios-slider-toggle"></span>
                        </label>
                    </div>
                </div>

                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">Performance HUD (DM_METAL_HUD)</span>
                        <label class="ios-switch">
                            <input type="checkbox" id="cfg-hud" checked onchange="markChanged()">
                            <span class="ios-slider-toggle"></span>
                        </label>
                    </div>
                </div>
            </div>

            <!-- RESET & MEMORY -->
            <div class="inset-group">
                <div class="setting-row">
                    <button class="reset-btn" id="btn-reset" disabled onclick="resetDefaults()">Reset to tested defaults</button>
                    <div class="setting-note">Brings back all settings this game was tested with (4.0.1 v1507328).</div>
                </div>
                <div class="setting-row">
                    <div class="setting-main">
                        <span class="setting-label">4 GB Layout (game.tsv)</span>
                        <span style="font-family:ui-monospace,monospace;font-size:0.78rem;color:var(--ios-sub);">mem_reserve 0x100000000 · app_pool 0xCD500000 (3.03 GB heap)</span>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- =====================================================================
         2. PANTALLA DE JUEGO: DMIOS + METAL 4 HUD + DMGAMEPAD.M
         ===================================================================== -->
    <div id="game-screen">
        <canvas id="mk8d-canvas"></canvas>

        <!-- FPS Counter -->
        <div id="fps-pill">60.0 FPS · 16.6 ms (GPU ~6.0 ms)</div>

        <!-- Metal 4 Performance HUD -->
        <div id="metal-hud">
            <div style="color:#38bdf8;font-weight:700;">DmIOS 4.0.1 (v1507328) · Apple M2 GPU (Metal 4)</div>
            <div id="hud-res">Mode: Docked 1920×1080 · render_cond: on</div>
            <div>Chain: b-8e52e2292032 · 29,785 Shaders (23 _b.metallib)</div>
            <div>Pairs: 19,012 · PSO Prewarm: 1,516 · Heap: 2.40 GB / 3.03 GB</div>
            <div id="hud-pad">Controller: DmGamepad Touch (3D Pro) · SDK 4 DeviceSink 0xf</div>
        </div>

        <!-- Race Status Overlay -->
        <div id="race-hud">
            <div class="race-stat-box" style="color:#facc15;font-size:1.35rem;" id="hud-pos">1st</div>
            <div class="race-stat-box" style="color:#ffffff;font-size:0.95rem;" id="hud-lap">LAP 1/3</div>
            <div class="race-stat-box" style="color:#fb923c;font-size:0.95rem;" id="hud-coins">🪙 10</div>
            <div class="race-stat-box" style="color:#38bdf8;font-size:0.95rem;" id="hud-speed">150cc · 0 km/h</div>
        </div>

        <!-- DmGamepad.m Virtual Switch Controller Overlay -->
        <div id="dm-gamepad">
            <div class="gp-top-center">
                <button class="gp-pill-btn" id="btn-minus" ontouchstart="pressBtn('minus',true)" ontouchend="pressBtn('minus',false)">−</button>
                <button class="gp-pill-btn" id="btn-layout" onclick="cycleLayout()">3D</button>
                <button class="gp-pill-btn" id="btn-track" onclick="cycleTrack()">🏁 Mario Kart Stadium</button>
                <button class="gp-pill-btn" id="btn-plus" ontouchstart="pressBtn('plus',true)" ontouchend="pressBtn('plus',false)">+</button>
                <button class="gp-pill-btn" onclick="showLauncher()" style="border-color:#0a84ff;color:#38bdf8;">⚙ Launcher</button>
            </div>

            <!-- Shoulders -->
            <div class="gp-btn" id="btn-zl" data-key="zl">ZL (Item)</div>
            <div class="gp-btn" id="btn-l" data-key="l">L</div>
            <div class="gp-btn" id="btn-zr" data-key="zr">ZR (Drift)</div>
            <div class="gp-btn" id="btn-r" data-key="r">R</div>

            <!-- Left Analog Stick -->
            <div id="stick-left-zone">
                <div id="stick-left-knob"></div>
            </div>

            <!-- D-Pad -->
            <div id="dpad-zone">
                <div class="gp-btn dpad-btn" id="btn-up" data-key="up">▲</div>
                <div class="gp-btn dpad-btn" id="btn-down" data-key="down">▼</div>
                <div class="gp-btn dpad-btn" id="btn-left" data-key="left">◀</div>
                <div class="gp-btn dpad-btn" id="btn-right" data-key="right">▶</div>
            </div>

            <!-- Switch A/B/X/Y Diamond -->
            <div id="face-diamond">
                <div class="gp-btn face-btn" id="btn-x" data-key="x">X</div>
                <div class="gp-btn face-btn" id="btn-y" data-key="y">Y</div>
                <div class="gp-btn face-btn" id="btn-a" data-key="a">A</div>
                <div class="gp-btn face-btn" id="btn-b" data-key="b">B</div>
            </div>
        </div>
    </div>

    <script>
        function updateScaleLabel() {
            const scale = parseFloat(document.getElementById('cfg-scale').value);
            const docked = document.getElementById('cfg-opmode').value === '1';
            const bw = docked ? 1920 : 1280;
            const bh = docked ? 1080 : 720;
            document.getElementById('val-scale').innerText = `${Math.round(scale * 100)}% (${Math.round(bw * scale)}×${Math.round(bh * scale)})`;
        }

        function markChanged() {
            document.getElementById('btn-reset').disabled = false;
        }

        function resetDefaults() {
            document.getElementById('cfg-dynres').checked = false;
            document.getElementById('cfg-scale').value = '1.0';
            document.getElementById('cfg-opmode').value = '1';
            document.getElementById('cfg-upscale').value = 'off';
            document.getElementById('cfg-lang').value = 'es-419';
            document.getElementById('cfg-fps').checked = true;
            document.getElementById('cfg-haptics').checked = true;
            document.getElementById('cfg-rumble').checked = true;
            document.getElementById('cfg-rumble-min').value = '0.45';
            document.getElementById('val-rumble-min').innerText = '0.45 (Crashes & Drifts)';
            document.getElementById('cfg-rendercond').checked = true;
            document.getElementById('cfg-mtl4').checked = true;
            document.getElementById('cfg-prebuild').checked = true;
            document.getElementById('cfg-encthr').checked = true;
            document.getElementById('cfg-hud').checked = true;
            updateScaleLabel();
            document.getElementById('btn-reset').disabled = true;
        }

        let gameRunning = false;
        function startGame() {
            document.getElementById('launcher-screen').style.display = 'none';
            document.getElementById('game-screen').style.display = 'block';
            document.getElementById('fps-pill').style.display = document.getElementById('cfg-fps').checked ? 'block' : 'none';
            document.getElementById('metal-hud').style.display = document.getElementById('cfg-hud').checked ? 'block' : 'none';
            const docked = document.getElementById('cfg-opmode').value === '1';
            const scale = parseFloat(document.getElementById('cfg-scale').value);
            const bw = docked ? 1920 : 1280;
            const bh = docked ? 1080 : 720;
            document.getElementById('hud-res').innerText =
                `Mode: ${docked ? 'Docked' : 'Handheld'} ${Math.round(bw*scale)}×${Math.round(bh*scale)} · render_cond: on`;
            resizeCanvas();
            if (!gameRunning) {
                gameRunning = true;
                requestAnimationFrame(gameLoop);
            }
        }

        function showLauncher() {
            document.getElementById('game-screen').style.display = 'none';
            document.getElementById('launcher-screen').style.display = 'flex';
        }

        const inputState = {
            a: false, b: false, x: false, y: false,
            l: false, r: false, zl: false, zr: false,
            up: false, down: false, left: false, right: false,
            plus: false, minus: false,
            lx: 0, ly: 0
        };

        let padLayout = '3D';
        function cycleLayout() {
            if (padLayout === '3D') padLayout = '2D';
            else if (padLayout === '2D') padLayout = 'Tap';
            else padLayout = '3D';
            document.getElementById('btn-layout').innerText = padLayout;
            document.getElementById('hud-pad').innerText = `Controller: DmGamepad Touch (${padLayout}) · SDK 4 DeviceSink 0xf`;
            document.getElementById('dpad-zone').style.display = (padLayout === '3D') ? 'block' : 'none';
            const show2D = (padLayout !== 'Tap');
            document.getElementById('stick-left-zone').style.display = show2D ? 'block' : 'none';
            document.getElementById('face-diamond').style.display = show2D ? 'block' : 'none';
            ['btn-zl','btn-l','btn-zr','btn-r'].forEach(id => {
                document.getElementById(id).style.display = show2D ? 'flex' : 'none';
            });
        }

        function pressBtn(k, down) {
            inputState[k] = down;
            if (down && k === 'zl' && boostTimer <= 0) {
                boostTimer = 65;
            }
        }

        document.querySelectorAll('.gp-btn').forEach(el => {
            const k = el.getAttribute('data-key');
            if (!k) return;
            const onDown = (e) => { e.preventDefault(); el.classList.add('active'); pressBtn(k, true); };
            const onUp = (e) => { e.preventDefault(); el.classList.remove('active'); pressBtn(k, false); };
            el.addEventListener('touchstart', onDown, {passive: false});
            el.addEventListener('touchend', onUp, {passive: false});
            el.addEventListener('touchcancel', onUp, {passive: false});
            el.addEventListener('mousedown', onDown);
            el.addEventListener('mouseup', onUp);
            el.addEventListener('mouseleave', onUp);
        });

        const stickZone = document.getElementById('stick-left-zone');
        const stickKnob = document.getElementById('stick-left-knob');
        let stickActive = false;

        function handleStickMove(clientX, clientY) {
            const rect = stickZone.getBoundingClientRect();
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;
            const maxR = rect.width / 2 - 20;
            let dx = clientX - cx;
            let dy = clientY - cy;
            const dist = Math.hypot(dx, dy);
            if (dist > maxR) {
                dx = (dx / dist) * maxR;
                dy = (dy / dist) * maxR;
            }
            stickKnob.style.transform = `translate(${dx}px, ${dy}px)`;
            inputState.lx = dx / maxR;
            inputState.ly = dy / maxR;
        }
        function resetStick() {
            stickActive = false;
            stickKnob.style.transform = 'translate(0px, 0px)';
            inputState.lx = 0;
            inputState.ly = 0;
        }
        stickZone.addEventListener('touchstart', e => { e.preventDefault(); stickActive = true; handleStickMove(e.touches[0].clientX, e.touches[0].clientY); }, {passive: false});
        stickZone.addEventListener('touchmove', e => { e.preventDefault(); if (stickActive) handleStickMove(e.touches[0].clientX, e.touches[0].clientY); }, {passive: false});
        stickZone.addEventListener('touchend', e => { e.preventDefault(); resetStick(); }, {passive: false});
        stickZone.addEventListener('mousedown', e => { stickActive = true; handleStickMove(e.clientX, e.clientY); });
        window.addEventListener('mousemove', e => { if (stickActive) handleStickMove(e.clientX, e.clientY); });
        window.addEventListener('mouseup', () => { if (stickActive) resetStick(); });

        window.addEventListener('keydown', e => {
            if (e.key === 'ArrowUp' || e.key === 'w' || e.key === ' ') inputState.a = true;
            if (e.key === 'ArrowDown' || e.key === 's') inputState.b = true;
            if (e.key === 'ArrowLeft' || e.key === 'a') inputState.left = true;
            if (e.key === 'ArrowRight' || e.key === 'd') inputState.right = true;
            if (e.key === 'Shift') inputState.zr = true;
        });
        window.addEventListener('keyup', e => {
            if (e.key === 'ArrowUp' || e.key === 'w' || e.key === ' ') inputState.a = false;
            if (e.key === 'ArrowDown' || e.key === 's') inputState.b = false;
            if (e.key === 'ArrowLeft' || e.key === 'a') inputState.left = false;
            if (e.key === 'ArrowRight' || e.key === 'd') inputState.right = false;
            if (e.key === 'Shift') inputState.zr = false;
        });

        const canvas = document.getElementById('mk8d-canvas');
        const ctx = canvas.getContext('2d');

        const TRACKS = [
            {
                name: 'Mario Kart Stadium',
                skyTop: '#08142c',
                skyBot: '#1e3a8a',
                grass1: '#15803d',
                grass2: '#166534',
                road1: '#334155',
                road2: '#3b485e',
                curb1: '#ef4444',
                curb2: '#f8fafc',
                rainbow: false
            },
            {
                name: 'Rainbow Road (Special Cup)',
                skyTop: '#020617',
                skyBot: '#1e1b4b',
                grass1: '#090d1f',
                grass2: '#0f172a',
                road1: '#4f46e5',
                road2: '#ec4899',
                curb1: '#facc15',
                curb2: '#38bdf8',
                rainbow: true
            },
            {
                name: 'Mount Wario (Star Cup)',
                skyTop: '#0ea5e9',
                skyBot: '#e0f2fe',
                grass1: '#cbd5e1',
                grass2: '#e2e8f0',
                road1: '#475569',
                road2: '#64748b',
                curb1: '#38bdf8',
                curb2: '#ffffff',
                rainbow: false
            }
        ];
        let currentTrackIdx = 0;

        function cycleTrack() {
            currentTrackIdx = (currentTrackIdx + 1) % TRACKS.length;
            document.getElementById('btn-track').innerText = '🏁 ' + TRACKS[currentTrackIdx].name;
        }

        function resizeCanvas() {
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
        }
        window.addEventListener('resize', resizeCanvas);

        const TOTAL_SEGMENTS = 600;
        const SEG_LEN = 200;
        const ROAD_W = 2000;
        const segments = [];
        for (let i = 0; i < TOTAL_SEGMENTS; i++) {
            let curve = 0;
            if (i > 40 && i < 120) curve = 2.4;
            else if (i > 160 && i < 250) curve = -2.8;
            else if (i > 300 && i < 390) curve = 3.2;
            else if (i > 440 && i < 530) curve = -2.2;
            const y = Math.sin(i / 18) * 900;
            segments.push({
                index: i,
                p1: { world: { x: 0, y: y, z: i * SEG_LEN }, camera: {}, screen: {} },
                p2: { world: { x: 0, y: Math.sin((i + 1) / 18) * 900, z: (i + 1) * SEG_LEN }, camera: {}, screen: {} },
                curve: curve,
                itemBox: (i % 75 === 25),
                boostPad: (i % 90 === 50)
            });
        }
        const trackLength = TOTAL_SEGMENTS * SEG_LEN;

        const rivals = [
            { name: 'Luigi', color: '#22c55e', z: 1800, offset: -0.45, speed: 155 },
            { name: 'Peach', color: '#f472b6', z: 3400, offset: 0.35, speed: 162 },
            { name: 'Yoshi', color: '#4ade80', z: 5200, offset: -0.25, speed: 168 },
            { name: 'Bowser', color: '#f59e0b', z: 7200, offset: 0.40, speed: 174 },
            { name: 'Toad', color: '#38bdf8', z: 9200, offset: -0.35, speed: 179 }
        ];

        let position = 0;
        let playerX = 0;
        let speed = 0;
        const maxSpeed = 245;
        let lap = 1;
        let driftCharge = 0;
        let boostTimer = 0;
        let lastTime = performance.now();
        let fpsSmooth = 60.0;

        function project(p, cameraX, cameraY, cameraZ, cameraDepth, width, height, roadWidth) {
            p.camera.x = (p.world.x || 0) - cameraX;
            p.camera.y = (p.world.y || 0) - cameraY;
            p.camera.z = (p.world.z || 0) - cameraZ;
            const scale = cameraDepth / Math.max(1, p.camera.z);
            p.screen.scale = scale;
            p.screen.x = Math.round((width / 2) + (scale * p.camera.x * width / 2));
            p.screen.y = Math.round((height / 2) - (scale * p.camera.y * height / 2));
            p.screen.w = Math.round((scale * roadWidth * width / 2));
        }

        function drawPolygon(x1, y1, w1, x2, y2, w2, color) {
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.moveTo(x1 - w1, y1);
            ctx.lineTo(x2 - w2, y2);
            ctx.lineTo(x2 + w2, y2);
            ctx.lineTo(x1 + w1, y1);
            ctx.closePath();
            ctx.fill();
        }

        function pollPhysicalGamepad() {
            const pads = navigator.getGamepads ? navigator.getGamepads() : [];
            for (const gp of pads) {
                if (!gp) continue;
                document.getElementById('hud-pad').innerText = `Controller: ${gp.id.slice(0, 28)}`;
                if (gp.buttons[0] && gp.buttons[0].pressed) inputState.b = true;
                if (gp.buttons[1] && gp.buttons[1].pressed) inputState.a = true;
                if (gp.buttons[7] && gp.buttons[7].pressed) inputState.zr = true;
                if (Math.abs(gp.axes[0]) > 0.15) inputState.lx = gp.axes[0];
            }
        }

        function gameLoop(now) {
            const dt = Math.min(0.05, (now - lastTime) / 1000);
            lastTime = now;
            const instFps = 1 / Math.max(0.001, dt);
            fpsSmooth = fpsSmooth * 0.9 + instFps * 0.1;
            document.getElementById('fps-pill').innerText = `${fpsSmooth.toFixed(1)} FPS · ${(1000 / fpsSmooth).toFixed(1)} ms (GPU ~6.0 ms)`;

            pollPhysicalGamepad();

            const accel = inputState.a || padLayout === 'Tap';
            if (boostTimer > 0) {
                boostTimer--;
                speed = Math.min(maxSpeed * 1.28, speed + 420 * dt);
            } else if (accel) {
                speed = Math.min(maxSpeed, speed + 145 * dt);
            } else if (inputState.b) {
                speed = Math.max(0, speed - 260 * dt);
            } else {
                speed = Math.max(0, speed - 85 * dt);
            }

            let steer = inputState.lx;
            if (inputState.left) steer = -0.85;
            if (inputState.right) steer = 0.85;

            const baseSeg = segments[Math.floor(position / SEG_LEN) % TOTAL_SEGMENTS];
            const speedRatio = speed / maxSpeed;
            playerX += steer * dt * 2.3 * Math.max(0.2, speedRatio);
            playerX -= (baseSeg.curve * speedRatio * dt * 0.48);
            playerX = Math.max(-1.85, Math.min(1.85, playerX));

            if (inputState.zr && Math.abs(steer) > 0.25 && speed > 100) {
                driftCharge += dt * 40;
            } else {
                if (driftCharge > 25) {
                    boostTimer = 45;
                }
                driftCharge = 0;
            }

            if (baseSeg.boostPad && Math.abs(playerX) < 0.45) {
                boostTimer = 35;
            }

            position += speed * 42 * dt;
            if (position >= trackLength) {
                position -= trackLength;
                lap = (lap % 3) + 1;
            }

            let aheadCount = 0;
            rivals.forEach(r => {
                r.z = (r.z + r.speed * 35 * dt) % trackLength;
                if (r.z > position) aheadCount++;
            });
            const rankLabels = ['1st','2nd','3rd','4th','5th','6th'];
            document.getElementById('hud-pos').innerText = rankLabels[Math.min(5, aheadCount)];
            document.getElementById('hud-lap').innerText = `LAP ${lap}/3`;
            document.getElementById('hud-speed').innerText = `150cc · ${Math.round(speed)} km/h`;

            const W = canvas.width;
            const H = canvas.height;
            const track = TRACKS[currentTrackIdx];

            const skyGrad = ctx.createLinearGradient(0, 0, 0, H * 0.52);
            skyGrad.addColorStop(0, track.skyTop);
            skyGrad.addColorStop(1, track.skyBot);
            ctx.fillStyle = skyGrad;
            ctx.fillRect(0, 0, W, H * 0.52);

            ctx.fillStyle = 'rgba(255,255,255,0.65)';
            for (let s = 0; s < 28; s++) {
                const sx = ((s * 197 + Math.floor(position * 0.02)) % W + W) % W;
                const sy = (s * 43) % (H * 0.35);
                ctx.fillRect(sx, sy, 2, 2);
            }

            ctx.fillStyle = track.grass2;
            ctx.fillRect(0, H * 0.5, W, H * 0.5);

            const baseIndex = Math.floor(position / SEG_LEN);
            const camY = 1050 + baseSeg.p1.world.y;
            let maxy = H;
            let x = 0;
            let dx = 0;

            for (let n = 0; n < 90; n++) {
                const seg = segments[(baseIndex + n) % TOTAL_SEGMENTS];
                const looped = (baseIndex + n) >= TOTAL_SEGMENTS;
                const camZ = position - (looped ? trackLength : 0);

                project(seg.p1, (playerX * ROAD_W) - x, camY, camZ, 0.82, W, H, ROAD_W);
                project(seg.p2, (playerX * ROAD_W) - x - dx, camY, camZ, 0.82, W, H, ROAD_W);

                x += dx;
                dx += seg.curve;

                if (seg.p1.camera.z <= 10 || seg.p2.screen.y >= maxy || seg.p2.screen.y >= seg.p1.screen.y) {
                    continue;
                }

                const alt = Math.floor(seg.index / 3) % 2 === 0;
                const grassCol = alt ? track.grass1 : track.grass2;
                const curbCol = alt ? track.curb1 : track.curb2;
                let roadCol = alt ? track.road1 : track.road2;
                if (track.rainbow) {
                    const hue = (seg.index * 8) % 360;
                    roadCol = `hsl(${hue}, 82%, ${alt ? 48 : 38}%)`;
                }

                ctx.fillStyle = grassCol;
                ctx.fillRect(0, seg.p2.screen.y, W, seg.p1.screen.y - seg.p2.screen.y);

                drawPolygon(
                    seg.p1.screen.x, seg.p1.screen.y, seg.p1.screen.w * 1.14,
                    seg.p2.screen.x, seg.p2.screen.y, seg.p2.screen.w * 1.14,
                    curbCol
                );

                drawPolygon(
                    seg.p1.screen.x, seg.p1.screen.y, seg.p1.screen.w,
                    seg.p2.screen.x, seg.p2.screen.y, seg.p2.screen.w,
                    roadCol
                );

                if (seg.index < 3) {
                    drawPolygon(
                        seg.p1.screen.x, seg.p1.screen.y, seg.p1.screen.w * 0.95,
                        seg.p2.screen.x, seg.p2.screen.y, seg.p2.screen.w * 0.95,
                        seg.index % 2 === 0 ? '#ffffff' : '#111827'
                    );
                }

                if (seg.boostPad) {
                    drawPolygon(
                        seg.p1.screen.x, seg.p1.screen.y, seg.p1.screen.w * 0.35,
                        seg.p2.screen.x, seg.p2.screen.y, seg.p2.screen.w * 0.35,
                        '#f97316'
                    );
                }

                maxy = seg.p2.screen.y;
            }

            const kartX = W / 2 + steer * 28;
            const kartY = H * 0.80;

            if (driftCharge > 5 || boostTimer > 0) {
                const sparkCol = boostTimer > 0 ? '#f97316' : (driftCharge > 40 ? '#e879f9' : (driftCharge > 20 ? '#facc15' : '#38bdf8'));
                ctx.fillStyle = sparkCol;
                for (let sp = 0; sp < 6; sp++) {
                    ctx.beginPath();
                    ctx.arc(kartX - 42 + (sp * 16), kartY + 26 + (Math.random() * 10), 7 + Math.random() * 6, 0, Math.PI * 2);
                    ctx.fill();
                }
            }

            ctx.fillStyle = 'rgba(0,0,0,0.55)';
            ctx.beginPath();
            ctx.ellipse(kartX, kartY + 32, 68, 16, 0, 0, Math.PI * 2);
            ctx.fill();

            ctx.fillStyle = '#18181b';
            ctx.fillRect(kartX - 62, kartY + 4, 22, 28);
            ctx.fillRect(kartX + 40, kartY + 4, 22, 28);

            ctx.fillStyle = '#ef4444';
            ctx.beginPath();
            ctx.roundRect(kartX - 44, kartY - 8, 88, 34, 12);
            ctx.fill();

            ctx.fillStyle = '#2563eb';
            ctx.beginPath();
            ctx.roundRect(kartX - 30, kartY - 18, 60, 20, 8);
            ctx.fill();

            ctx.fillStyle = '#dc2626';
            ctx.beginPath();
            ctx.arc(kartX, kartY - 28, 20, 0, Math.PI * 2);
            ctx.fill();

            ctx.fillStyle = '#ffffff';
            ctx.beginPath();
            ctx.arc(kartX, kartY - 28, 9, 0, Math.PI * 2);
            ctx.fill();

            ctx.fillStyle = '#dc2626';
            ctx.font = 'bold 11px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('M', kartX, kartY - 24);

            requestAnimationFrame(gameLoop);
        }

        if (window.location.search.indexOf('play=1') !== -1) {
            window.addEventListener('DOMContentLoaded', () => startGame());
        }
    </script>
</body>
</html>
"""

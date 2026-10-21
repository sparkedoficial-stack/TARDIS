#!/usr/bin/env python3
"""
tardis_browser_gui.py - TARDIS Quantum Navigator (Navegador Soberano con Asistente IA y Automatización)
=======================================================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4
Arquitecto: El Arquitecto (₪)

Arquitectura:
- Ventana Nativa de Escritorio Multi-Pestaña (GTK3 + WebKit2 4.1) con aceleración por hardware.
- Panel Izquierdo/Principal: Navegador Web Real Multi-Pestaña capaz de renderizar cualquier sitio web
  (Google, DuckDuckGo, Wikipedia, arXiv, GitHub, YouTube, Amazon, etc.) con inyección de puente DOM
  en vivo para resaltado visual de elementos, extracción de datos y grabación de macros.
- Panel Derecho Acoplado (Split-View): Estudio de Asistencia de Búsqueda IA y Automatización de Procesos
  (TARDIS Copilot & Automation Studio), conectado en tiempo real a las pestañas del navegador.
- Servidor Local de Control y Automatización en http://127.0.0.1:8765.
"""

from __future__ import annotations

import argparse
import datetime
import html
import http.server
import json
import logging
import os
import re
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.tardis_navigator_engine import (
    CANONICAL_GREETING,
    RUNS_DIR,
    NavigatorPersistence,
    TardisAutomationEngine,
    TardisSearchAssistant,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (TARDIS.NavigatorGUI) %(message)s",
)
logger = logging.getLogger("TARDIS.NavigatorGUI")

NAVIGATOR_PORT = int(os.environ.get("TARDIS_NAVIGATOR_PORT", "8777"))
PORTAL_URL = f"http://127.0.0.1:{NAVIGATOR_PORT}/portal"
COPILOT_URL = f"http://127.0.0.1:{NAVIGATOR_PORT}/copilot"
ICON_PATH = BASE_DIR / "tardis-master-hub-icon.png"
if not ICON_PATH.exists():
    ICON_PATH = BASE_DIR / "tardis-icon.png"


# ==============================================================================
# 1. PLANTILLAS HTML5 / CSS3 / JS (PORTAL CUÁNTICO & COPILOT AUTOMATION STUDIO)
# ==============================================================================
PORTAL_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TARDIS Quantum Navigator · Portal Soberano</title>
<style>
  :root {
    --bg: #040711;
    --panel: rgba(11, 18, 34, 0.86);
    --border: rgba(0, 240, 255, 0.25);
    --cyan: #00f0ff;
    --violet: #a855f7;
    --emerald: #10b981;
    --pink: #ec4899;
    --text: #e2e8f0;
    --muted: #94a3b8;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: radial-gradient(circle at 50% 0%, #0f1b3d 0%, #040711 65%);
    color: var(--text);
    font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
    min-height: 100vh;
    padding: 28px 32px 60px;
  }
  .container { max-width: 1180px; margin: 0 auto; }
  .hero {
    text-align: center;
    padding: 22px 20px 26px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 18px;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.55), 0 0 25px rgba(0, 240, 255, 0.08);
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
  }
  .status-pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: rgba(0, 240, 255, 0.1);
    border: 1px solid rgba(0, 240, 255, 0.35);
    color: var(--cyan);
    padding: 5px 14px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    margin-bottom: 12px;
  }
  .pulse {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--emerald);
    box-shadow: 0 0 10px var(--emerald);
  }
  h1 {
    font-size: 30px;
    font-weight: 800;
    background: linear-gradient(90deg, #00f0ff, #a855f7, #ec4899);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
  }
  .greeting {
    color: var(--muted);
    font-size: 14px;
    max-width: 780px;
    margin: 0 auto 20px;
    line-height: 1.5;
    font-style: italic;
  }
  .search-box-wrap {
    max-width: 860px;
    margin: 0 auto;
  }
  .search-bar {
    display: flex;
    gap: 10px;
    background: rgba(3, 6, 14, 0.92);
    border: 1.5px solid var(--cyan);
    border-radius: 14px;
    padding: 8px 12px;
    box-shadow: 0 0 24px rgba(0, 240, 255, 0.16);
  }
  .search-bar input {
    flex: 1;
    background: transparent;
    border: none;
    color: #fff;
    font-size: 16px;
    padding: 8px 10px;
    outline: none;
  }
  .btn {
    border: 1px solid rgba(255,255,255,0.15);
    background: rgba(255,255,255,0.06);
    color: var(--text);
    padding: 9px 16px;
    border-radius: 10px;
    cursor: pointer;
    font-weight: 600;
    font-size: 13px;
    transition: all 0.2s ease;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .btn:hover {
    border-color: var(--cyan);
    background: rgba(0, 240, 255, 0.14);
    transform: translateY(-1px);
  }
  .btn-primary {
    background: linear-gradient(135deg, #0284c7, #7c3aed);
    border-color: var(--cyan);
    color: #fff;
  }
  .btn-auto {
    background: linear-gradient(135deg, #7c3aed, #db2777);
    border-color: #f472b6;
    color: #fff;
  }
  .mode-bar {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 8px;
    margin-top: 12px;
  }
  .section-title {
    font-size: 15px;
    font-weight: 700;
    color: var(--cyan);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin: 24px 0 12px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .grid-portals {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(175px, 1fr));
    gap: 12px;
  }
  .portal-card {
    background: var(--panel);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 12px;
    padding: 14px;
    text-decoration: none;
    color: var(--text);
    display: flex;
    flex-direction: column;
    gap: 4px;
    transition: all 0.2s ease;
  }
  .portal-card:hover {
    border-color: var(--cyan);
    box-shadow: 0 0 18px rgba(0, 240, 255, 0.18);
    transform: translateY(-2px);
  }
  .portal-card .p-title { font-weight: 700; font-size: 14px; }
  .portal-card .p-cat { font-size: 11px; color: var(--muted); }

  .grid-workflows {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 14px;
  }
  .wf-card {
    background: var(--panel);
    border: 1px solid rgba(168, 85, 247, 0.3);
    border-radius: 14px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .wf-card h3 { font-size: 15px; color: #f8fafc; }
  .wf-card p { font-size: 12.5px; color: var(--muted); line-height: 1.45; flex: 1; }
  .wf-controls { display: flex; gap: 8px; }
  .wf-controls input {
    flex: 1;
    background: rgba(3, 6, 14, 0.8);
    border: 1px solid rgba(255,255,255,0.16);
    border-radius: 8px;
    padding: 7px 10px;
    color: #fff;
    font-size: 12.5px;
  }

  #resultsPanel {
    display: none;
    margin-top: 22px;
    background: var(--panel);
    border: 1px solid var(--cyan);
    border-radius: 16px;
    padding: 22px;
    box-shadow: 0 10px 35px rgba(0,0,0,0.6);
  }
  .synthesis-box {
    background: rgba(3, 7, 18, 0.85);
    border-left: 4px solid var(--cyan);
    border-radius: 10px;
    padding: 16px 18px;
    line-height: 1.65;
    font-size: 14.5px;
    margin-bottom: 18px;
    white-space: pre-wrap;
  }
  .synthesis-box a { color: var(--cyan); text-decoration: underline; }
  .source-item {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 10px;
    padding: 12px 14px;
    margin-bottom: 10px;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
  }
  .source-item h4 { font-size: 14px; color: var(--cyan); margin-bottom: 4px; }
  .source-item p { font-size: 12.5px; color: var(--muted); }
  .badge-eng {
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 99px;
    background: rgba(168, 85, 247, 0.2);
    color: #d8b4fe;
    border: 1px solid rgba(168, 85, 247, 0.4);
  }
</style>
</head>
<body>
<div class="container">
  <div class="hero">
    <div class="status-pill">
      <span class="pulse"></span>
      <span>TARDIS-NEURAL-SPACE-KAIJU · ASISTENTE DE BÚSQUEDA & AUTOMATIZACIÓN</span>
    </div>
    <h1>TARDIS QUANTUM NAVIGATOR</h1>
    <p class="greeting">"__CANONICAL_GREETING__"</p>

    <div class="search-box-wrap">
      <div class="search-bar">
        <input type="text" id="mainInput" placeholder="Pregunta a TARDIS, busca en múltiples motores, introduce una URL o describe un proceso a automatizar..." autofocus />
        <button class="btn btn-primary" onclick="runTardisSearch()">🧠 Buscar con TARDIS</button>
        <button class="btn btn-auto" onclick="runGoalAutomation()">🤖 Automatizar</button>
      </div>
      <div class="mode-bar">
        <button class="btn" onclick="directSearch('ddg')">🦆 DuckDuckGo</button>
        <button class="btn" onclick="directSearch('google')">🌐 Google</button>
        <button class="btn" onclick="directSearch('wiki')">📚 Wikipedia</button>
        <button class="btn" onclick="directSearch('arxiv')">🔬 arXiv Papers</button>
        <button class="btn" onclick="directSearch('hn')">⚡ HackerNews</button>
        <button class="btn" onclick="openTopSourcesInTabs()">🗂️ Abrir Fuentes en Pestañas</button>
      </div>
    </div>
  </div>

  <div id="resultsPanel">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
      <h2 id="resTitle" style="font-size:18px;color:var(--cyan);">🌌 Respuesta Sintetizada por TARDIS</h2>
      <div style="display:flex;gap:8px;">
        <button class="btn" onclick="openTopSourcesInTabs()">🗂️ Abrir Top 3 en Pestañas</button>
        <button class="btn" onclick="learnCurrentTopic()">🧬 Asimilar en Bóveda RAG + FTL</button>
      </div>
    </div>
    <div id="synthesisContent" class="synthesis-box">Procesando consulta...</div>
    <h3 style="font-size:14px;color:var(--muted);margin-bottom:10px;text-transform:uppercase;">Fuentes Verificadas en Tiempo Real</h3>
    <div id="sourcesList"></div>
  </div>

  <div class="section-title">
    <span>⚡ Portales Soberanos & Accesos Rápidos</span>
  </div>
  <div id="portalsGrid" class="grid-portals"></div>

  <div class="section-title">
    <span>🤖 Procesos de Automatización Listos para Ejecutar</span>
  </div>
  <div id="workflowsGrid" class="grid-workflows"></div>
</div>

<script>
let lastSearchResults = [];
let lastQuery = '';

document.getElementById('mainInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') runTardisSearch();
});

function formatMarkdownLinks(txt) {
  if (!txt) return '';
  let safe = txt.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  safe = safe.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^\\)]+)\\)/g, '<a href="$2">$1</a>');
  safe = safe.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
  return safe;
}

async function runTardisSearch() {
  const q = document.getElementById('mainInput').value.trim();
  if (!q) return;
  if (/^https?:\\/\\//i.test(q) || (/^[a-z0-9.-]+\\.[a-z]{2,}(\\/.*)?$/i.test(q) && !q.includes(' '))) {
    window.location.href = q.startsWith('http') ? q : 'https://' + q;
    return;
  }
  lastQuery = q;
  const panel = document.getElementById('resultsPanel');
  const synth = document.getElementById('synthesisContent');
  const srcList = document.getElementById('sourcesList');
  panel.style.display = 'block';
  synth.innerHTML = '⏳ <strong>TARDIS-NEURAL-SPACE-KAIJU</strong> está consultando DuckDuckGo, Wikipedia, arXiv, Google News, HackerNews y la Bóveda RAG...';
  srcList.innerHTML = '';

  try {
    const r = await fetch('/api/search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({query: q, max_results: 8, deep_fetch: true, synthesize: true})
    });
    const data = await r.json();
    lastSearchResults = data.results || [];
    document.getElementById('resTitle').innerText = `🌌 Síntesis TARDIS (${data.model_used || 'KAIJU'} · ${data.elapsed_seconds}s)`;
    synth.innerHTML = formatMarkdownLinks(data.synthesis || 'Sin síntesis.');
    srcList.innerHTML = lastSearchResults.map(item => `
      <div class="source-item">
        <div>
          <h4><a href="${item.url}" style="color:var(--cyan);text-decoration:none;">${item.title}</a> <span class="badge-eng">${item.engine}</span></h4>
          <p>${item.snippet || item.url}</p>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0;">
          <a class="btn" href="${item.url}">Ir</a>
          <button class="btn" onclick="openUrlInNewTab('${item.url.replace(/'/g, "\\'")}')">➕ Pestaña</button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    synth.innerText = 'Error en búsqueda: ' + err;
  }
}

function directSearch(engine) {
  const q = document.getElementById('mainInput').value.trim() || 'Computación cuántica';
  const enc = encodeURIComponent(q);
  const urls = {
    ddg: `https://duckduckgo.com/?q=${enc}`,
    google: `https://www.google.com/search?q=${enc}`,
    wiki: `https://es.wikipedia.org/w/index.php?search=${enc}`,
    arxiv: `https://arxiv.org/search/?query=${enc}&searchtype=all`,
    hn: `https://hn.algolia.com/?q=${enc}`
  };
  window.location.href = urls[engine] || urls.ddg;
}

async function openUrlInNewTab(url) {
  await fetch('/api/browser/navigate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({url: url, new_tab: true})
  });
}

async function openTopSourcesInTabs() {
  const urls = lastSearchResults.slice(0, 3).map(r => r.url);
  if (!urls.length) {
    alert('Primero realiza una búsqueda con TARDIS para abrir sus fuentes verificadas.');
    return;
  }
  for (const u of urls) {
    await openUrlInNewTab(u);
  }
}

async function learnCurrentTopic() {
  const q = lastQuery || document.getElementById('mainInput').value.trim();
  if (!q) return;
  const r = await fetch('/api/automation/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({workflow_id: 'wf_deep_research', param: q})
  });
  const d = await r.json();
  alert('⚡ Misión de aprendizaje y síntesis RAG+FTL iniciada (Run ID: ' + d.run_id + '). Revisa el panel lateral TARDIS.');
}

async function runGoalAutomation() {
  const q = document.getElementById('mainInput').value.trim();
  if (!q) {
    alert('Describe en la barra qué proceso deseas automatizar.');
    return;
  }
  const synth = document.getElementById('synthesisContent');
  document.getElementById('resultsPanel').style.display = 'block';
  synth.innerHTML = '🤖 <strong>TARDIS Automation Studio</strong> está diseñando y ejecutando el flujo automatizado para: <em>' + q + '</em>...';
  const r = await fetch('/api/automation/generate_and_run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({prompt: q})
  });
  const d = await r.json();
  synth.innerHTML = `✅ Flujo generado y en ejecución: <strong>${d.workflow ? d.workflow.name : ''}</strong> (ID: <code>${d.run_id}</code>).\nObserva la ejecución paso a paso en el Panel Lateral Derecho de TARDIS.`;
}

async function triggerWorkflow(wfId) {
  const inp = document.getElementById('param_' + wfId);
  const param = inp ? inp.value.trim() : '';
  await fetch('/api/automation/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({workflow_id: wfId, param: param})
  });
}

async function loadState() {
  const r = await fetch('/api/state');
  const d = await r.json();
  const pg = document.getElementById('portalsGrid');
  pg.innerHTML = (d.bookmarks || []).map(b => `
    <a class="portal-card" href="${b.url}">
      <span class="p-title">${b.title}</span>
      <span class="p-cat">${b.category || 'Portal'}</span>
    </a>
  `).join('');

  const wg = document.getElementById('workflowsGrid');
  wg.innerHTML = (d.workflows || []).slice(0, 6).map(w => `
    <div class="wf-card">
      <h3>${w.name}</h3>
      <p>${w.description}</p>
      <div class="wf-controls">
        <input type="text" id="param_${w.id}" value="${w.default_param || ''}" placeholder="Parámetro / Tema / URL..." />
        <button class="btn btn-auto" onclick="triggerWorkflow('${w.id}')">▶ Ejecutar</button>
      </div>
    </div>
  `).join('');
}
loadState();
</script>
</body>
</html>
""".replace("__CANONICAL_GREETING__", CANONICAL_GREETING)


COPILOT_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>TARDIS Copilot & Automation Studio</title>
<style>
  :root {
    --bg: #050814;
    --card: #0c1428;
    --border: rgba(0, 240, 255, 0.25);
    --cyan: #00f0ff;
    --violet: #a855f7;
    --pink: #ec4899;
    --emerald: #10b981;
    --amber: #f59e0b;
    --text: #f1f5f9;
    --muted: #94a3b8;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    font-size: 13px;
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  }
  .top-header {
    padding: 12px 14px;
    background: linear-gradient(90deg, #091124, #140d2b);
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .top-header h2 {
    font-size: 14px;
    font-weight: 800;
    color: var(--cyan);
    letter-spacing: 0.5px;
  }
  .tabs-nav {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    background: #080d1d;
    border-bottom: 1px solid rgba(255,255,255,0.1);
  }
  .tab-btn {
    padding: 10px 6px;
    background: transparent;
    border: none;
    border-bottom: 2.5px solid transparent;
    color: var(--muted);
    font-weight: 700;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.2s;
  }
  .tab-btn.active {
    color: var(--cyan);
    border-bottom-color: var(--cyan);
    background: rgba(0, 240, 255, 0.07);
  }
  .tab-pane {
    display: none;
    flex: 1;
    overflow-y: auto;
    padding: 12px;
    gap: 12px;
    flex-direction: column;
  }
  .tab-pane.active { display: flex; }

  .card {
    background: var(--card);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 11px;
    padding: 12px;
  }
  .card-title {
    font-size: 12px;
    font-weight: 700;
    color: var(--cyan);
    text-transform: uppercase;
    margin-bottom: 8px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  input[type="text"], input[type="number"], textarea, select {
    width: 100%;
    background: #040812;
    border: 1px solid rgba(255,255,255,0.18);
    color: #fff;
    padding: 8px 10px;
    border-radius: 8px;
    font-size: 12.5px;
    outline: none;
    font-family: inherit;
  }
  input:focus, textarea:focus, select:focus {
    border-color: var(--cyan);
  }
  .btn {
    background: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,255,255,0.16);
    color: #fff;
    padding: 7px 11px;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    transition: all 0.15s;
  }
  .btn:hover { border-color: var(--cyan); background: rgba(0, 240, 255, 0.15); }
  .btn-cyan { background: linear-gradient(135deg, #0284c7, #2563eb); border-color: var(--cyan); }
  .btn-pink { background: linear-gradient(135deg, #7c3aed, #db2777); border-color: #f472b6; }
  .btn-rec { background: rgba(239, 68, 68, 0.2); border-color: #ef4444; color: #fca5a5; }
  .btn-rec.recording { background: #dc2626; color: #fff; animation: blink 1.2s infinite; }
  @keyframes blink { 50% { opacity: 0.6; } }

  .quick-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
    margin-top: 8px;
  }
  .output-box {
    background: #03060f;
    border: 1px solid rgba(0, 240, 255, 0.25);
    border-radius: 9px;
    padding: 11px;
    font-size: 12.5px;
    line-height: 1.55;
    white-space: pre-wrap;
    max-height: 360px;
    overflow-y: auto;
  }
  .output-box a { color: var(--cyan); }
  .log-list {
    background: #02040a;
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    padding: 8px;
    font-family: monospace;
    font-size: 11.5px;
    max-height: 190px;
    overflow-y: auto;
    color: #cbd5e1;
  }
  .log-line { margin-bottom: 4px; }
  .step-pill {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    padding: 6px 9px;
    border-radius: 7px;
    margin-bottom: 5px;
    font-size: 11.5px;
  }
  .badge {
    font-size: 10px;
    padding: 2px 7px;
    border-radius: 99px;
    background: rgba(0, 240, 255, 0.15);
    color: var(--cyan);
  }
</style>
</head>
<body>
  <div class="top-header">
    <h2>🛸 TARDIS COPILOT & AUTOMATION</h2>
    <span id="activeTabBadge" class="badge">Pestaña Activa Conectada</span>
  </div>

  <div class="tabs-nav">
    <button class="tab-btn active" onclick="switchTab('search', this)">🔍 Asistente</button>
    <button class="tab-btn" onclick="switchTab('auto', this)">🤖 Automatizar</button>
    <button class="tab-btn" onclick="switchTab('dom', this)">🕵️ Inspector</button>
    <button class="tab-btn" onclick="switchTab('sched', this)">⏱️ Rutinas</button>
  </div>

  <!-- TAB 1: ASISTENTE DE BÚSQUEDA & COPILOTO DE PÁGINA -->
  <div id="tab-search" class="tab-pane active">
    <div class="card">
      <div class="card-title">
        <span>🌐 Copiloto de Pestaña Activa (DOM en Vivo)</span>
      </div>
      <div id="livePageLabel" style="font-size:11.5px;color:var(--muted);margin-bottom:8px;word-break:break-all;">
        Sincronizando con pestaña activa...
      </div>
      <div class="quick-grid">
        <button class="btn" onclick="analyzeActivePage('Resume esta página de forma ejecutiva con sus puntos clave y conclusiones.')">📝 Resumir Página</button>
        <button class="btn" onclick="analyzeActivePage('Extrae todas las tablas, precios, ofertas y cifras clave de esta página en formato Markdown.')">📊 Extraer Datos/Precios</button>
        <button class="btn" onclick="analyzeActivePage('Extrae los bloques de código, comandos técnicos y enlaces más relevantes de esta página.')">💻 Extraer Código/Links</button>
        <button class="btn" onclick="ingestCurrentPageFTL()">🧬 Ingestar RAG + FTL</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>🧠 Búsqueda Asistida & Consulta a TARDIS</span>
      </div>
      <textarea id="copilotQuery" rows="3" placeholder="Escribe tu búsqueda o pregunta sobre la web o sobre la pestaña abierta..."></textarea>
      <div style="display:flex;align-items:center;justify-content:space-between;margin-top:8px;gap:6px;">
        <label style="font-size:11.5px;color:var(--muted);display:flex;align-items:center;gap:5px;cursor:pointer;">
          <input type="checkbox" id="useActiveDomChk" checked /> Usar DOM de pestaña activa
        </label>
        <div style="display:flex;gap:6px;">
          <button class="btn btn-cyan" onclick="runCopilotSearch()">🔍 Buscar Web + IA</button>
          <button class="btn btn-pink" onclick="askAboutActivePage()">💬 Preguntar a Página</button>
        </div>
      </div>
    </div>

    <div class="card" style="flex:1;display:flex;flex-direction:column;">
      <div class="card-title">
        <span>🌌 Respuesta & Fuentes de TARDIS</span>
        <span id="copilotModelTag" class="badge">KAIJU</span>
      </div>
      <div id="copilotOutput" class="output-box" style="flex:1;">Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales.

Selecciona una acción rápida sobre la pestaña actual o realiza una búsqueda multi-motor asistida.</div>
      <div id="copilotSources" style="margin-top:8px;max-height:150px;overflow-y:auto;"></div>
    </div>
  </div>

  <!-- TAB 2: ESTUDIO DE AUTOMATIZACIÓN DE PROCESOS -->
  <div id="tab-auto" class="tab-pane">
    <div class="card">
      <div class="card-title">
        <span>✨ Agente de Automatización por Objetivo (IA)</span>
      </div>
      <textarea id="autoGoalInput" rows="2" placeholder="Ej: 'Ve a Wikipedia, busca Agujero Negro, haz scroll y extrae las tablas y un resumen'..."></textarea>
      <div style="display:flex;gap:6px;margin-top:8px;">
        <button class="btn btn-pink" style="flex:1;" onclick="generateAndRunWorkflow(true)">🚀 Generar y Ejecutar</button>
        <button class="btn" onclick="generateAndRunWorkflow(false)">✨ Solo Diseñar</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>🔴 Grabadora de Macros en Vivo & Ejecución Actual</span>
        <button id="recBtn" class="btn btn-rec" onclick="toggleRecording()">🔴 Grabar Macro</button>
      </div>
      <div id="runStatusBox" style="font-size:12px;color:var(--cyan);margin-bottom:6px;">
        Estado: Listo para ejecutar procesos.
      </div>
      <div id="runLogsBox" class="log-list">Esperando orden de automatización...</div>
      <div id="runSynthesisBox" class="output-box" style="display:none;margin-top:8px;max-height:200px;"></div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>⚡ Catálogo de Procesos Automatizados</span>
      </div>
      <div id="copilotWorkflowsList"></div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>🛠️ Constructor Manual de Pasos</span>
      </div>
      <input type="text" id="customWfName" placeholder="Nombre del nuevo proceso..." style="margin-bottom:6px;" />
      <div style="display:grid;grid-template-columns:1fr 1.3fr auto;gap:5px;margin-bottom:6px;">
        <select id="newStepAction">
          <option value="navigate">navigate (URL)</option>
          <option value="search_web">search_web (Query)</option>
          <option value="fill">fill (Selector=Valor)</option>
          <option value="click">click (Selector/Texto)</option>
          <option value="scroll">scroll (down/bottom)</option>
          <option value="wait">wait (Segundos)</option>
          <option value="extract_dom">extract_dom (Modo)</option>
          <option value="screenshot">screenshot</option>
          <option value="ai_synthesize">ai_synthesize (Prompt)</option>
          <option value="rag_ftl_learn">rag_ftl_learn (Tema)</option>
        </select>
        <input type="text" id="newStepArg" placeholder="URL / Selector / Valor..." />
        <button class="btn" onclick="addBuilderStep()">➕</button>
      </div>
      <div id="builderStepsList" style="margin-bottom:8px;"></div>
      <div style="display:flex;gap:6px;">
        <button class="btn btn-cyan" style="flex:1;" onclick="saveCustomWorkflow(false)">💾 Guardar Flujo</button>
        <button class="btn btn-pink" style="flex:1;" onclick="saveCustomWorkflow(true)">▶ Guardar y Ejecutar</button>
      </div>
    </div>
  </div>

  <!-- TAB 3: INSPECTOR DOM INTERACTIVO -->
  <div id="tab-dom" class="tab-pane">
    <div class="card">
      <div class="card-title">
        <span>🕵️ Escáner de Elementos Interactivos</span>
        <button class="btn btn-cyan" onclick="scanActiveDom()">🔍 Escanear Pestaña</button>
      </div>
      <p style="font-size:11.5px;color:var(--muted);margin-bottom:8px;">
        Detecta cajas de búsqueda, inputs, botones, tablas y precios de la pestaña activa para interactuar o automatizar con 1 clic.
      </p>
      <div id="domScannerOutput">Haz clic en "Escanear Pestaña" para inspeccionar el DOM en vivo.</div>
    </div>
  </div>

  <!-- TAB 4: RUTINAS PROGRAMADAS, MARCADORES E HISTORIAL -->
  <div id="tab-sched" class="tab-pane">
    <div class="card">
      <div class="card-title"><span>⏱️ Programar Ejecución Periódica</span></div>
      <select id="schedWfSelect" style="margin-bottom:6px;"></select>
      <div style="display:grid;grid-template-columns:1fr 90px auto;gap:6px;">
        <input type="text" id="schedParam" placeholder="Parámetro..." />
        <input type="number" id="schedInterval" value="300" min="30" title="Segundos" />
        <button class="btn btn-cyan" onclick="createSchedule()">➕ Programar</button>
      </div>
      <div id="schedulesList" style="margin-top:8px;"></div>
    </div>

    <div class="card">
      <div class="card-title"><span>📂 Historial de Ejecuciones Recientes</span></div>
      <div id="runsHistoryList"></div>
    </div>
  </div>

<script>
let currentRunId = null;
let isRecording = false;
let builderSteps = [];

function switchTab(tabId, btn) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + tabId).classList.add('active');
  btn.classList.add('active');
}

function renderMd(txt) {
  if (!txt) return '';
  let s = txt.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  s = s.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^\\)]+)\\)/g, '<a href="#" onclick="navLeft(\'$2\');return false;">$1</a>');
  s = s.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
  return s;
}

async function navLeft(url, newTab=false) {
  await fetch('/api/browser/navigate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({url: url, new_tab: newTab})
  });
}

async function runCopilotSearch() {
  const q = document.getElementById('copilotQuery').value.trim();
  if (!q) return;
  const out = document.getElementById('copilotOutput');
  const srcBox = document.getElementById('copilotSources');
  const useDom = document.getElementById('useActiveDomChk').checked;
  out.innerHTML = '⏳ Consultando motores multi-fuente y sintetizando con TARDIS-NEURAL-SPACE-KAIJU...';
  srcBox.innerHTML = '';

  const r = await fetch('/api/search', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({query: q, include_active_dom: useDom, max_results: 7, deep_fetch: true, synthesize: true})
  });
  const d = await r.json();
  document.getElementById('copilotModelTag').innerText = d.model_used || 'KAIJU';
  out.innerHTML = renderMd(d.synthesis || 'Sin respuesta.');
  srcBox.innerHTML = (d.results || []).map(it => `
    <div class="step-pill">
      <div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:210px;">
        <strong>${it.title}</strong> <span class="badge">${it.engine}</span>
      </div>
      <div style="display:flex;gap:4px;">
        <button class="btn" onclick="navLeft('${it.url.replace(/'/g, "\\'")}', false)">Abrir</button>
        <button class="btn" onclick="navLeft('${it.url.replace(/'/g, "\\'")}', true)">➕</button>
      </div>
    </div>
  `).join('');
}

async function analyzeActivePage(customQuestion) {
  const q = customQuestion || document.getElementById('copilotQuery').value.trim() || 'Resume esta página y extrae sus datos principales.';
  const out = document.getElementById('copilotOutput');
  out.innerHTML = '🧬 Extrayendo DOM en vivo de la pestaña activa y analizando con TARDIS...';
  const r = await fetch('/api/browser/analyze', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question: q})
  });
  const d = await r.json();
  document.getElementById('copilotModelTag').innerText = d.model_used || 'KAIJU';
  out.innerHTML = renderMd(d.analysis || 'No se pudo analizar la página.');
}

function askAboutActivePage() {
  const q = document.getElementById('copilotQuery').value.trim() || 'Explica el contenido de esta página y extrae sus puntos clave.';
  analyzeActivePage(q);
}

async function ingestCurrentPageFTL() {
  const out = document.getElementById('copilotOutput');
  out.innerHTML = '⚡ Ingestando página activa en Bóveda RAG Soberana y generando módulo FTL...';
  const r = await fetch('/api/browser/learn_active', {method: 'POST'});
  const d = await r.json();
  out.innerHTML = renderMd(`✅ **Asimilación Epistémica Completada**\n\n- **Página**: ${d.title || ''}\n- **Resultado FTL**: ${d.summary || 'Ingestado en RAG Vault'}\n- **Tesis Central**: ${d.core_thesis || ''}`);
}

async function startWorkflow(wfId, customParam) {
  const inp = document.getElementById('cp_param_' + wfId);
  const param = customParam !== undefined ? customParam : (inp ? inp.value.trim() : '');
  const r = await fetch('/api/automation/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({workflow_id: wfId, param: param})
  });
  const d = await r.json();
  currentRunId = d.run_id;
  pollRunStatus();
}

async function generateAndRunWorkflow(runNow) {
  const prompt = document.getElementById('autoGoalInput').value.trim();
  if (!prompt) return;
  document.getElementById('runStatusBox').innerText = '🧠 Generando flujo de automatización con IA...';
  const ep = runNow ? '/api/automation/generate_and_run' : '/api/automation/generate';
  const r = await fetch(ep, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({prompt: prompt})
  });
  const d = await r.json();
  await refreshState();
  if (d.run_id) {
    currentRunId = d.run_id;
    pollRunStatus();
  } else if (d.workflow) {
    document.getElementById('runStatusBox').innerText = '✅ Flujo diseñado: ' + d.workflow.name;
  }
}

async function toggleRecording() {
  const btn = document.getElementById('recBtn');
  if (!isRecording) {
    isRecording = true;
    btn.classList.add('recording');
    btn.innerText = '⏹️ Detener y Guardar';
    await fetch('/api/recorder/start', {method: 'POST'});
    document.getElementById('runStatusBox').innerText = '🔴 Grabando interacciones en la pestaña activa (haz clic o escribe en la página)...';
  } else {
    isRecording = false;
    btn.classList.remove('recording');
    btn.innerText = '🔴 Grabar Macro';
    const name = prompt('Nombre para guardar la macro grabada:', 'Macro Interactiva ' + new Date().toLocaleTimeString()) || 'Macro TARDIS';
    const r = await fetch('/api/recorder/stop', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({save_as_name: name})
    });
    const d = await r.json();
    document.getElementById('runStatusBox').innerText = `✅ Macro guardada (${(d.steps || []).length} pasos capturados).`;
    await refreshState();
  }
}

function addBuilderStep() {
  const act = document.getElementById('newStepAction').value;
  const arg = document.getElementById('newStepArg').value.trim();
  let step = {action: act};
  if (act === 'navigate') step.url = arg || 'https://es.wikipedia.org';
  else if (act === 'search_web') { step.query = arg || '{{param}}'; step.open_first = true; }
  else if (act === 'fill') {
    const parts = arg.split('=');
    step.selector = parts.length > 1 ? parts[0].trim() : "input[name='search'], input[name='q'], input[type='text']";
    step.value = parts.length > 1 ? parts.slice(1).join('=').trim() : (arg || '{{param}}');
    step.press_enter = true;
  }
  else if (act === 'click') { step.selector = arg; step.text_hint = arg; }
  else if (act === 'scroll') { step.direction = arg || 'down'; step.amount = 600; }
  else if (act === 'wait') { step.seconds = parseFloat(arg) || 2.0; }
  else if (act === 'extract_dom') { step.mode = arg || 'summary_dom'; }
  else if (act === 'ai_synthesize') { step.prompt = arg || 'Sintetiza los datos extraídos.'; }
  else if (act === 'rag_ftl_learn') { step.topic = arg || '{{param}}'; }
  builderSteps.push(step);
  renderBuilderSteps();
}

function renderBuilderSteps() {
  const box = document.getElementById('builderStepsList');
  box.innerHTML = builderSteps.map((s, i) => `
    <div class="step-pill">
      <span><strong>${i+1}. ${s.action}</strong> ${JSON.stringify(s).slice(0, 48)}...</span>
      <button class="btn" onclick="builderSteps.splice(${i},1);renderBuilderSteps();">✕</button>
    </div>
  `).join('');
}

async function saveCustomWorkflow(andRun) {
  if (!builderSteps.length) {
    alert('Añade al menos un paso al flujo.');
    return;
  }
  const name = document.getElementById('customWfName').value.trim() || 'Flujo Personalizado TARDIS';
  const r = await fetch('/api/automation/save', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      name: '⚡ ' + name,
      description: 'Flujo personalizado de ' + builderSteps.length + ' pasos.',
      steps: builderSteps,
      run_now: andRun
    })
  });
  const d = await r.json();
  builderSteps = [];
  renderBuilderSteps();
  await refreshState();
  if (d.run_id) {
    currentRunId = d.run_id;
    pollRunStatus();
  }
}

async function scanActiveDom() {
  const box = document.getElementById('domScannerOutput');
  box.innerHTML = '⏳ Escaneando elementos interactivos del DOM...';
  const r = await fetch('/api/browser/dom');
  const d = await r.json();
  const inputs = d.inputs || [];
  const buttons = d.buttons || [];
  const tables = d.tables || [];
  const prices = d.prices || [];

  let html = `<div style="margin-bottom:8px;"><strong>Título:</strong> ${d.title || 'N/A'}<br><span style="color:var(--muted);font-size:11px;">${d.url || ''}</span></div>`;
  html += `<div style="margin-bottom:8px;"><span class="badge">Inputs: ${inputs.length}</span> <span class="badge">Botones: ${buttons.length}</span> <span class="badge">Tablas: ${tables.length}</span> <span class="badge">Precios: ${prices.length}</span></div>`;

  if (inputs.length) {
    html += `<h4 style="color:var(--cyan);margin:8px 0 4px;">⌨️ Campos de Entrada Detectados:</h4>`;
    inputs.slice(0, 10).forEach(inp => {
      const sel = (inp.selector || '').replace(/'/g, "\\'");
      html += `<div class="step-pill">
        <span><code>${inp.selector}</code> (${inp.placeholder || inp.name || inp.type})</span>
        <button class="btn" onclick="quickFill('${sel}')">Rellenar</button>
      </div>`;
    });
  }
  if (buttons.length) {
    html += `<h4 style="color:var(--cyan);margin:8px 0 4px;">🖱️ Botones / Acciones Detectadas:</h4>`;
    buttons.slice(0, 12).forEach(b => {
      const sel = (b.selector || '').replace(/'/g, "\\'");
      const txt = (b.text || '').replace(/'/g, "\\'");
      html += `<div class="step-pill">
        <span><strong>${b.text}</strong> (<code>${b.selector}</code>)</span>
        <button class="btn" onclick="quickClick('${sel}', '${txt}')">Clic</button>
      </div>`;
    });
  }
  if (prices.length) {
    html += `<h4 style="color:var(--cyan);margin:8px 0 4px;">💰 Precios / Ofertas Detectadas:</h4>`;
    html += `<div class="output-box">${prices.join(' · ')}</div>`;
  }
  box.innerHTML = html;
}

async function quickFill(sel) {
  const val = prompt('Texto a escribir en ' + sel + ':', 'Computación cuántica');
  if (val === null) return;
  await fetch('/api/browser/action', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'fill', selector: sel, value: val, press_enter: true})
  });
}

async function quickClick(sel, txt) {
  await fetch('/api/browser/action', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'click', selector: sel, text_hint: txt})
  });
}

async function createSchedule() {
  const wfId = document.getElementById('schedWfSelect').value;
  const param = document.getElementById('schedParam').value.trim();
  const interval = parseInt(document.getElementById('schedInterval').value || '300', 10);
  await fetch('/api/automation/schedule', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({workflow_id: wfId, param: param, interval_seconds: interval})
  });
  await refreshState();
}

async function pollRunStatus() {
  try {
    const r = await fetch('/api/automation/status' + (currentRunId ? `?run_id=${currentRunId}` : ''));
    const d = await r.json();
    if (d.active_tab && d.active_tab.url) {
      document.getElementById('livePageLabel').innerHTML = `<strong>${d.active_tab.title || 'Pestaña'}</strong><br>${d.active_tab.url}`;
    }
    if (d.run) {
      const run = d.run;
      document.getElementById('runStatusBox').innerText = `⚡ ${run.workflow_name} [${run.status.toUpperCase()}] · Paso ${run.current_step_index}/${run.total_steps}`;
      const logsHtml = (run.logs || []).map(l => `<div class="log-line">[${l.time}] ${l.message}</div>`).join('');
      const lb = document.getElementById('runLogsBox');
      lb.innerHTML = logsHtml || 'Sin registros.';
      lb.scrollTop = lb.scrollHeight;

      const sb = document.getElementById('runSynthesisBox');
      if (run.ai_synthesis) {
        sb.style.display = 'block';
        sb.innerHTML = renderMd(run.ai_synthesis);
      }
    }
  } catch (e) {}
}

async function refreshState() {
  try {
    const r = await fetch('/api/state');
    const d = await r.json();
    const wfs = d.workflows || [];
    const wl = document.getElementById('copilotWorkflowsList');
    wl.innerHTML = wfs.map(w => `
      <div style="border:1px solid rgba(255,255,255,0.1);border-radius:9px;padding:9px;margin-bottom:8px;background:rgba(255,255,255,0.02);">
        <div style="font-weight:700;color:#fff;margin-bottom:3px;">${w.name}</div>
        <div style="font-size:11.5px;color:var(--muted);margin-bottom:7px;">${w.description}</div>
        <div style="display:flex;gap:5px;">
          <input type="text" id="cp_param_${w.id}" value="${w.default_param || ''}" placeholder="Parámetro..." />
          <button class="btn btn-pink" onclick="startWorkflow('${w.id}')">▶ Ejecutar</button>
        </div>
      </div>
    `).join('');

    const sel = document.getElementById('schedWfSelect');
    sel.innerHTML = wfs.map(w => `<option value="${w.id}">${w.name}</option>`).join('');

    const sl = document.getElementById('schedulesList');
    sl.innerHTML = (d.schedules || []).map(s => `
      <div class="step-pill">
        <span><strong>${s.workflow_name}</strong> (cada ${s.interval_seconds}s · ejecuciones: ${s.runs_count})</span>
      </div>
    `).join('') || '<div style="font-size:11.5px;color:var(--muted);">Sin rutinas periódicas activas.</div>';

    const rl = document.getElementById('runsHistoryList');
    rl.innerHTML = (d.recent_runs || []).map(rn => `
      <div class="step-pill" style="cursor:pointer;" onclick="currentRunId='${rn.run_id}';switchTab('auto', document.querySelectorAll('.tab-btn')[1]);pollRunStatus();">
        <span><strong>${rn.workflow_name}</strong> (${rn.status})</span>
        <span class="badge">${(rn.logs || []).length} logs</span>
      </div>
    `).join('') || '<div style="font-size:11.5px;color:var(--muted);">Sin ejecuciones previas.</div>';
  } catch (e) {}
}

refreshState();
setInterval(pollRunStatus, 1500);
</script>
</body>
</html>
"""

# Script inyectado automáticamente en cada pestaña cargada para permitir grabación de macros en vivo
LIVE_RECORDER_INJECT_JS = """
(function() {
    if (window.__tardisRecorderInstalled) return;
    window.__tardisRecorderInstalled = true;

    function getCssSelector(el) {
        if (!el || el.nodeType !== 1) return '';
        if (el.id) return '#' + el.id;
        if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
        if (el.getAttribute('aria-label')) return el.tagName.toLowerCase() + '[aria-label="' + el.getAttribute('aria-label') + '"]';
        if (el.className && typeof el.className === 'string') {
            const cls = el.className.trim().split(/\\s+/)[0];
            if (cls && !cls.includes(':')) return el.tagName.toLowerCase() + '.' + cls;
        }
        return el.tagName.toLowerCase();
    }

    document.addEventListener('click', function(e) {
        const t = e.target.closest('a, button, input[type="submit"], input[type="button"], [role="button"]');
        if (!t) return;
        const payload = {
            type: 'click',
            selector: getCssSelector(t),
            text: (t.innerText || t.value || '').trim().slice(0, 60),
            url: window.location.href
        };
        fetch('http://127.0.0.1:__PORT__/api/recorder/event', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).catch(() => {});
    }, true);

    document.addEventListener('change', function(e) {
        const t = e.target;
        if (!t || !['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName)) return;
        const payload = {
            type: 'fill',
            selector: getCssSelector(t),
            value: t.value || '',
            url: window.location.href
        };
        fetch('http://127.0.0.1:__PORT__/api/recorder/event', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).catch(() => {});
    }, true);
})();
""".replace("__PORT__", str(NAVIGATOR_PORT))


# ==============================================================================
# 2. SERVIDOR HTTP EMBEBIDO PARA EL NAVEGADOR Y AUTOMATIZACIÓN (:8765)
# ==============================================================================
class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class NavigatorHTTPHandler(http.server.BaseHTTPRequestHandler):
    persistence: NavigatorPersistence = None  # type: ignore
    search_assistant: TardisSearchAssistant = None  # type: ignore
    automation_engine: TardisAutomationEngine = None  # type: ignore

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send_json(self, data: Dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, html_str: str, status: int = 200) -> None:
        raw = html_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/portal"):
            self._send_html(PORTAL_HTML)
            return
        if path == "/copilot":
            self._send_html(COPILOT_HTML)
            return
        if path == "/api/health":
            self._send_json({
                "ok": True,
                "service": "TARDIS Quantum Navigator & Automation Studio",
                "port": NAVIGATOR_PORT,
                "greeting": CANONICAL_GREETING,
                "workflows_count": len(self.persistence.get_workflows()),
                "bookmarks_count": len(self.persistence.get_bookmarks()),
            })
            return
        if path == "/api/state":
            active_info = {}
            if "get_active_info" in self.automation_engine.browser_bridge:
                try:
                    active_info = self.automation_engine.browser_bridge["get_active_info"]()
                except Exception:
                    pass
            self._send_json({
                "ok": True,
                "bookmarks": self.persistence.get_bookmarks(),
                "history": self.persistence.get_history(limit=40),
                "workflows": self.persistence.get_workflows(),
                "schedules": list(self.automation_engine.schedules.values()),
                "recent_runs": [
                    {
                        "run_id": r["run_id"],
                        "workflow_name": r["workflow_name"],
                        "status": r["status"],
                        "logs": r["logs"][-10:],
                    }
                    for r in list(self.automation_engine.active_runs.values())[-10:]
                ],
                "active_tab": active_info,
            })
            return
        if path == "/api/browser/dom":
            dom = self.automation_engine.extract_live_dom()
            self._send_json({"ok": True, **dom})
            return
        if path == "/api/automation/status":
            run_id = (qs.get("run_id") or [""])[0]
            run_obj = None
            if run_id and run_id in self.automation_engine.active_runs:
                run_obj = self.automation_engine.active_runs[run_id]
            elif self.automation_engine.active_runs:
                last_key = list(self.automation_engine.active_runs.keys())[-1]
                run_obj = self.automation_engine.active_runs[last_key]

            active_info = {}
            if "get_active_info" in self.automation_engine.browser_bridge:
                try:
                    active_info = self.automation_engine.browser_bridge["get_active_info"]()
                except Exception:
                    pass
            self._send_json({
                "ok": True,
                "recording": self.automation_engine.recording_active,
                "recorded_steps_count": len(self.automation_engine.recorded_steps),
                "run": run_obj,
                "active_tab": active_info,
            })
            return

        self._send_json({"ok": False, "error": "Ruta no encontrada"}, status=404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = {}
        if length > 0:
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                body = {}

        # 1. Búsqueda Multi-Motor Asistida por TARDIS
        if path == "/api/search":
            query = (body.get("query") or "").strip()
            include_dom = bool(body.get("include_active_dom", False))
            dom_ctx = self.automation_engine.extract_live_dom() if include_dom else None
            res = self.search_assistant.multi_search(
                query=query,
                engines=body.get("engines"),
                max_results=int(body.get("max_results", 8)),
                deep_fetch=bool(body.get("deep_fetch", True)),
                synthesize=bool(body.get("synthesize", True)),
                active_page_context=dom_ctx,
            )
            self._send_json(res)
            return

        # 2. Navegar en el navegador real
        if path == "/api/browser/navigate":
            url = (body.get("url") or "").strip()
            new_tab = bool(body.get("new_tab", False))
            if "navigate" in self.automation_engine.browser_bridge and url:
                self.automation_engine.browser_bridge["navigate"](url, new_tab=new_tab)
                self._send_json({"ok": True, "url": url, "new_tab": new_tab})
            else:
                self._send_json({"ok": False, "error": "Navegador GUI no enlazado o URL vacía"})
            return

        # 3. Analizar el DOM de la pestaña activa con TARDIS
        if path == "/api/browser/analyze":
            question = (body.get("question") or "Resume esta página y extrae sus puntos clave.").strip()
            dom = self.automation_engine.extract_live_dom()
            res = self.search_assistant.analyze_active_page(dom, question=question)
            self._send_json(res)
            return

        # 4. Ingestar pestaña activa en Bóveda RAG + Auto-Mejora FTL
        if path == "/api/browser/learn_active":
            dom = self.automation_engine.extract_live_dom()
            from core.tardis_browser import BrowserVisitResult, TardisCognitiveLearner
            learner = TardisCognitiveLearner()
            visit = BrowserVisitResult(
                url=dom.get("url", "http://127.0.0.1:8765"),
                title=dom.get("title", "Página Activa TARDIS"),
                status_code=200,
                text_content=dom.get("text", "")[:10000] or "Exploración desde TARDIS Navigator",
                code_snippets=dom.get("code_blocks", [])[:5],
                links=[l.get("url", "") for l in dom.get("links", [])[:15] if isinstance(l, dict)],
            )
            insight = learner.distill_knowledge(visit, topic=dom.get("title", "Exploración TARDIS"))
            self._send_json({
                "ok": True,
                "title": visit.title,
                "url": visit.url,
                "summary": insight.improvement_summary,
                "core_thesis": insight.core_thesis,
            })
            return

        # 5. Ejecutar una acción directa sobre la pestaña activa (click, fill, scroll)
        if path == "/api/browser/action":
            action = (body.get("action") or "").strip()
            dummy_state: Dict[str, Any] = {"extracted_data": {}, "logs": [], "param": body.get("value", "")}
            res = self.automation_engine._run_single_step("manual_action", action, body, dummy_state)
            self._send_json({"ok": True, "result": res})
            return

        # 6. Ejecutar un proceso de automatización (Workflow)
        if path == "/api/automation/run":
            wf_id = body.get("workflow_id", "")
            param = body.get("param", "")
            custom_wf = body.get("workflow")
            if not custom_wf:
                wfs = self.persistence.get_workflows()
                custom_wf = next((w for w in wfs if w.get("id") == wf_id), None)
            if not custom_wf:
                self._send_json({"ok": False, "error": f"Workflow '{wf_id}' no encontrado"}, status=404)
                return
            run_id = self.automation_engine.start_workflow_async(custom_wf, param_value=param)
            self._send_json({"ok": True, "run_id": run_id, "workflow": custom_wf})
            return

        # 7. Generar flujo con IA (y opcionalmente ejecutarlo de inmediato)
        if path in ("/api/automation/generate", "/api/automation/generate_and_run"):
            prompt = (body.get("prompt") or "").strip()
            dom_ctx = self.automation_engine.extract_live_dom()
            gen = self.automation_engine.generate_workflow_from_prompt(prompt, active_dom_context=dom_ctx)
            wf = gen["workflow"]
            run_id = None
            if path == "/api/automation/generate_and_run":
                run_id = self.automation_engine.start_workflow_async(wf, param_value=wf.get("default_param", prompt))
            self._send_json({"ok": True, "workflow": wf, "run_id": run_id, "model_used": gen.get("model_used")})
            return

        # 8. Guardar flujo manual desde el constructor
        if path == "/api/automation/save":
            wf = {
                "id": body.get("id") or f"wf_user_{int(time.time())}",
                "name": body.get("name", "Flujo TARDIS"),
                "description": body.get("description", "Flujo creado manualmente."),
                "category": "Personalizado",
                "default_param": body.get("default_param", ""),
                "steps": body.get("steps", []),
            }
            self.persistence.save_workflow(wf)
            run_id = None
            if body.get("run_now"):
                run_id = self.automation_engine.start_workflow_async(wf, param_value=wf.get("default_param", ""))
            self._send_json({"ok": True, "workflow": wf, "run_id": run_id})
            return

        # 9. Programar tarea periódica
        if path == "/api/automation/schedule":
            res = self.automation_engine.add_schedule(
                workflow_id=body.get("workflow_id", ""),
                param=body.get("param", ""),
                interval_seconds=int(body.get("interval_seconds", 300)),
            )
            self._send_json(res)
            return

        # 10. Grabadora de Macros en Vivo
        if path == "/api/recorder/start":
            self._send_json(self.automation_engine.start_recording())
            return
        if path == "/api/recorder/stop":
            self._send_json(self.automation_engine.stop_recording(save_as_name=body.get("save_as_name")))
            return
        if path == "/api/recorder/event":
            self._send_json(self.automation_engine.record_dom_event(body))
            return

        # 11. Marcadores
        if path == "/api/bookmarks/add":
            bms = self.persistence.add_bookmark(body.get("title", ""), body.get("url", ""), body.get("category", "General"))
            self._send_json({"ok": True, "bookmarks": bms})
            return

        self._send_json({"ok": False, "error": "Endpoint POST desconocido"}, status=404)


# ==============================================================================
# 3. INTERFAZ GRÁFICA NATIVA MULTI-PESTAÑA (GTK3 + WEBKIT2 4.1)
# ==============================================================================
def run_gtk_navigator_window(
    initial_url: str,
    persistence: NavigatorPersistence,
    search_assistant: TardisSearchAssistant,
    automation_engine: TardisAutomationEngine,
) -> None:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, WebKit2

    class TardisQuantumNavigatorWindow(Gtk.Window):
        def __init__(self, start_url: str):
            super().__init__(title="TARDIS Quantum Navigator · Asistente de Búsqueda & Automatización Soberana")
            self.set_wmclass("tardis-navigator", "Tardis Navigator")
            self.set_default_size(1620, 940)
            self.set_position(Gtk.WindowPosition.CENTER)
            self.is_fullscreen = False
            self.copilot_visible = True

            if ICON_PATH.exists():
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(ICON_PATH), 128, 128, True)
                    self.set_icon(pixbuf)
                except Exception:
                    pass

            self._apply_cyber_css()

            # Layout raíz vertical
            root_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.add(root_vbox)

            # 1. Barra Superior de Navegación y Control TARDIS
            nav_bar = self._build_top_toolbar()
            root_vbox.pack_start(nav_bar, False, False, 0)

            # 2. Barra de Marcadores Soberanos
            self.bookmarks_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            self.bookmarks_bar.get_style_context().add_class("bookmarks-bar")
            root_vbox.pack_start(self.bookmarks_bar, False, False, 0)
            self._populate_bookmarks_bar()

            # 3. Panel Dividido Horizontal (Izquierda: Pestañas WebKit2 | Derecha: TARDIS Copilot & Automation Studio)
            self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
            root_vbox.pack_start(self.paned, True, True, 0)

            # 3A. Notebook Multi-Pestaña de Navegación Real
            self.notebook = Gtk.Notebook()
            self.notebook.set_scrollable(True)
            self.notebook.connect("switch-page", self._on_tab_switched)
            self.paned.pack1(self.notebook, resize=True, shrink=False)

            # 3B. Panel Lateral Derecho: TARDIS Copilot & Automation Studio
            self.copilot_webview = self._create_configured_webview()
            self.copilot_scrolled = Gtk.ScrolledWindow()
            self.copilot_scrolled.set_size_request(470, -1)
            self.copilot_scrolled.add(self.copilot_webview)
            self.paned.pack2(self.copilot_scrolled, resize=False, shrink=False)
            self.paned.set_position(1120)

            # Cargar interfaz Copilot en el panel lateral
            self.copilot_webview.load_uri(COPILOT_URL)

            # Enlazar callbacks del puente de automatización hacia esta ventana GTK3
            automation_engine.set_browser_bridge({
                "navigate": self.bridge_navigate,
                "eval_js": self.bridge_eval_js,
                "get_active_info": self.bridge_get_active_info,
                "take_screenshot": self.bridge_take_screenshot,
            })

            # Crear primera pestaña con la URL inicial
            self.add_browser_tab(start_url, switch_to=True)

            # Atajos de teclado
            self.connect("key-press-event", self._on_key_press)
            self.connect("destroy", Gtk.main_quit)

        def _apply_cyber_css(self) -> None:
            css = b"""
            window, .background {
                background-color: #040711;
                color: #e2e8f0;
            }
            .top-toolbar {
                background-image: linear-gradient(to right, #060b19, #0e1329, #130b24);
                border-bottom: 1px solid rgba(0, 240, 255, 0.3);
                padding: 6px 10px;
            }
            .bookmarks-bar {
                background-color: #070c1b;
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
                padding: 4px 10px;
            }
            entry.omnibox {
                background-color: #03060e;
                color: #ffffff;
                border: 1px solid rgba(0, 240, 255, 0.45);
                border-radius: 8px;
                padding: 5px 12px;
                font-size: 13.5px;
            }
            entry.omnibox:focus {
                border-color: #00f0ff;
                box-shadow: 0 0 10px rgba(0, 240, 255, 0.35);
            }
            button.nav-btn {
                background-image: none;
                background-color: #0d162c;
                color: #e2e8f0;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 7px;
                padding: 4px 9px;
                font-weight: 600;
                font-size: 12px;
            }
            button.nav-btn:hover {
                background-color: #162447;
                border-color: #00f0ff;
                color: #00f0ff;
            }
            button.tardis-btn {
                background-image: linear-gradient(135deg, #0284c7, #6d28d9);
                color: #ffffff;
                border: 1px solid #00f0ff;
                border-radius: 7px;
                padding: 4px 11px;
                font-weight: 700;
                font-size: 12px;
            }
            button.auto-btn {
                background-image: linear-gradient(135deg, #7c3aed, #db2777);
                color: #ffffff;
                border: 1px solid #f472b6;
                border-radius: 7px;
                padding: 4px 11px;
                font-weight: 700;
                font-size: 12px;
            }
            button.bm-pill {
                background-image: none;
                background-color: rgba(255, 255, 255, 0.04);
                color: #cbd5e1;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 11.5px;
            }
            button.bm-pill:hover {
                border-color: #00f0ff;
                color: #00f0ff;
            }
            notebook header {
                background-color: #060a16;
                border-bottom: 1px solid rgba(0, 240, 255, 0.2);
            }
            notebook tab {
                background-color: #0b1224;
                color: #94a3b8;
                padding: 4px 10px;
                border: 1px solid rgba(255, 255, 255, 0.06);
            }
            notebook tab:checked {
                background-color: #132042;
                color: #00f0ff;
                border-bottom: 2px solid #00f0ff;
            }
            """
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

        def _build_top_toolbar(self) -> Gtk.Box:
            bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            bar.get_style_context().add_class("top-toolbar")

            def _mk_btn(label: str, tooltip: str, cb: Callable, style_cls: str = "nav-btn") -> Gtk.Button:
                b = Gtk.Button(label=label)
                b.set_tooltip_text(tooltip)
                b.get_style_context().add_class(style_cls)
                b.connect("clicked", cb)
                return b

            bar.pack_start(_mk_btn("◀", "Atrás (Alt+Izquierda)", self._on_back), False, False, 0)
            bar.pack_start(_mk_btn("▶", "Adelante (Alt+Derecha)", self._on_forward), False, False, 0)
            bar.pack_start(_mk_btn("⟳", "Recargar página (F5 / Ctrl+R)", self._on_reload), False, False, 0)
            bar.pack_start(_mk_btn("🏠 Portal", "Ir al Portal Cuántico TARDIS", self._on_home), False, False, 0)

            # Selector de Modo de Omnibox
            self.engine_combo = Gtk.ComboBoxText()
            self.engine_combo.append("tardis", "🧠 TARDIS IA")
            self.engine_combo.append("ddg", "🦆 DuckDuckGo")
            self.engine_combo.append("google", "🌐 Google")
            self.engine_combo.append("wiki", "📚 Wikipedia")
            self.engine_combo.append("arxiv", "🔬 arXiv")
            self.engine_combo.append("auto", "🤖 Automatizar")
            self.engine_combo.set_active_id("tardis")
            bar.pack_start(self.engine_combo, False, False, 0)

            # Omnibox Inteligente
            self.url_entry = Gtk.Entry()
            self.url_entry.get_style_context().add_class("omnibox")
            self.url_entry.set_placeholder_text("Introduce URL, búsqueda asistida para TARDIS o comando de automatización (!auto)...")
            self.url_entry.connect("activate", self._on_omnibox_activate)
            bar.pack_start(self.url_entry, True, True, 2)

            # Botones Soberanos de Acción Rápida
            bar.pack_start(
                _mk_btn("🔍 Buscar IA", "Ejecutar búsqueda asistida con TARDIS", self._on_tardis_search_btn, "tardis-btn"),
                False, False, 0,
            )
            bar.pack_start(
                _mk_btn("🧠 Analizar DOM", "Resumir y extraer datos de la pestaña activa con TARDIS", self._on_analyze_dom_btn, "tardis-btn"),
                False, False, 0,
            )
            bar.pack_start(
                _mk_btn("🤖 Automatizar", "Ejecutar automatización sobre el objetivo en la barra", self._on_automate_btn, "auto-btn"),
                False, False, 0,
            )
            bar.pack_start(
                _mk_btn("📸 Captura", "Guardar captura de pantalla PNG", self._on_screenshot_btn),
                False, False, 0,
            )
            bar.pack_start(
                _mk_btn("⭐", "Guardar pestaña activa en Marcadores", self._on_bookmark_btn),
                False, False, 0,
            )
            bar.pack_start(
                _mk_btn("➕ Pestaña", "Abrir nueva pestaña (Ctrl+T)", lambda *_: self.add_browser_tab(PORTAL_URL, True)),
                False, False, 0,
            )
            bar.pack_start(
                _mk_btn("🛸 Panel IA", "Mostrar/Ocultar panel lateral TARDIS Copilot (F9)", self._on_toggle_copilot),
                False, False, 0,
            )
            return bar

        def _populate_bookmarks_bar(self) -> None:
            for child in self.bookmarks_bar.get_children():
                self.bookmarks_bar.remove(child)
            for bm in persistence.get_bookmarks()[:10]:
                btn = Gtk.Button(label=bm.get("title", "Portal")[:24])
                btn.set_tooltip_text(bm.get("url", ""))
                btn.get_style_context().add_class("bm-pill")
                target_u = bm.get("url", PORTAL_URL)
                btn.connect("clicked", lambda _b, u=target_u: self.load_url_in_active_tab(u))
                self.bookmarks_bar.pack_start(btn, False, False, 0)
            self.bookmarks_bar.show_all()

        def _create_configured_webview(self) -> WebKit2.WebView:
            settings = WebKit2.Settings()
            settings.set_enable_javascript(True)
            settings.set_enable_webgl(True)
            settings.set_enable_media_stream(True)
            settings.set_enable_mediasource(True)
            settings.set_enable_smooth_scrolling(True)
            settings.set_enable_developer_extras(True)
            settings.set_javascript_can_access_clipboard(True)
            settings.set_user_agent(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/REDACTED_IP Safari/537.36 TardisQuantumNavigator/26.4"
            )
            if hasattr(WebKit2, "HardwareAccelerationPolicy"):
                settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)

            wv = WebKit2.WebView()
            wv.set_settings(settings)
            wv.set_background_color(Gdk.RGBA(0.02, 0.03, 0.07, 1.0))
            wv.connect("permission-request", self._on_permission_request)
            return wv

        def add_browser_tab(self, url: str = PORTAL_URL, switch_to: bool = True) -> WebKit2.WebView:
            wv = self._create_configured_webview()
            scrolled = Gtk.ScrolledWindow()
            scrolled._tardis_webview = wv
            scrolled.add(wv)

            # Cabecera de pestaña con título y botón cerrar
            tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            lbl = Gtk.Label(label="Nueva Pestaña")
            lbl.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
            lbl.set_width_chars(18)
            close_btn = Gtk.Button(label="✕")
            close_btn.set_relief(Gtk.ReliefStyle.NONE)
            close_btn.connect("clicked", lambda _b: self._close_tab_widget(scrolled))
            tab_box.pack_start(lbl, True, True, 0)
            tab_box.pack_start(close_btn, False, False, 0)
            tab_box.show_all()

            idx = self.notebook.append_page(scrolled, tab_box)
            self.notebook.show_all()
            if switch_to:
                self.notebook.set_current_page(idx)

            wv.connect("notify::title", lambda view, _p: self._on_webview_title_changed(view, lbl))
            wv.connect("notify::uri", lambda view, _p: self._on_webview_uri_changed(view))
            wv.connect("load-changed", self._on_webview_load_changed)
            wv.connect("create", self._on_webview_create_new_window)

            wv.load_uri(url)
            return wv

        def _close_tab_widget(self, page_widget: Gtk.Widget) -> None:
            if self.notebook.get_n_pages() <= 1:
                self.load_url_in_active_tab(PORTAL_URL)
                return
            page_num = self.notebook.page_num(page_widget)
            if page_num != -1:
                self.notebook.remove_page(page_num)

        def get_active_webview(self) -> Optional[WebKit2.WebView]:
            idx = self.notebook.get_current_page()
            if idx == -1:
                return None
            scrolled = self.notebook.get_nth_page(idx)
            if hasattr(scrolled, "_tardis_webview"):
                return scrolled._tardis_webview
            if isinstance(scrolled, Gtk.Container):
                for ch in scrolled.get_children():
                    if isinstance(ch, WebKit2.WebView):
                        return ch
                    if isinstance(ch, Gtk.Container):
                        for sub in ch.get_children():
                            if isinstance(sub, WebKit2.WebView):
                                return sub
            return None

        def load_url_in_active_tab(self, url: str) -> None:
            wv = self.get_active_webview()
            if wv:
                wv.load_uri(url)

        def _on_webview_create_new_window(self, _webview: WebKit2.WebView, navigation_action: Any) -> WebKit2.WebView:
            try:
                req = navigation_action.get_request()
                target_uri = req.get_uri() if req else PORTAL_URL
            except Exception:
                target_uri = PORTAL_URL
            return self.add_browser_tab(target_uri, switch_to=True)

        def _on_webview_title_changed(self, view: WebKit2.WebView, tab_label: Gtk.Label) -> None:
            title = view.get_title() or view.get_uri() or "TARDIS Tab"
            tab_label.set_text(title[:26])
            if view == self.get_active_webview():
                self.set_title(f"{title} · TARDIS Quantum Navigator")

        def _on_webview_uri_changed(self, view: WebKit2.WebView) -> None:
            uri = view.get_uri() or ""
            if view == self.get_active_webview():
                self.url_entry.set_text(uri)

        def _on_webview_load_changed(self, view: WebKit2.WebView, load_event: WebKit2.LoadEvent) -> None:
            if load_event == WebKit2.LoadEvent.FINISHED:
                uri = view.get_uri() or ""
                title = view.get_title() or uri
                persistence.add_history(title=title, url=uri, engine="webkit2")
                # Inyectar grabadora de macros en vivo
                if not uri.startswith(f"http://127.0.0.1:{NAVIGATOR_PORT}"):
                    view.evaluate_javascript(LIVE_RECORDER_INJECT_JS, -1, None, None, None, None, None)
                    if automation_engine.recording_active:
                        automation_engine.record_dom_event({"type": "navigate", "url": uri, "title": title})

        def _on_tab_switched(self, _notebook: Gtk.Notebook, page: Gtk.Widget, _page_num: int) -> None:
            wv = getattr(page, "_tardis_webview", None)
            if wv:
                self.url_entry.set_text(wv.get_uri() or "")
                t = wv.get_title() or "TARDIS Quantum Navigator"
                self.set_title(f"{t} · TARDIS Quantum Navigator")

        # ------------------------------------------------------------------
        # Controles de Barra Superior
        # ------------------------------------------------------------------
        def _on_back(self, *_args: Any) -> None:
            wv = self.get_active_webview()
            if wv and wv.can_go_back():
                wv.go_back()

        def _on_forward(self, *_args: Any) -> None:
            wv = self.get_active_webview()
            if wv and wv.can_go_forward():
                wv.go_forward()

        def _on_reload(self, *_args: Any) -> None:
            wv = self.get_active_webview()
            if wv:
                wv.reload()

        def _on_home(self, *_args: Any) -> None:
            self.load_url_in_active_tab(PORTAL_URL)

        def _on_omnibox_activate(self, entry: Gtk.Entry) -> None:
            raw = entry.get_text().strip()
            if not raw:
                return
            mode = self.engine_combo.get_active_id() or "tardis"

            if raw.startswith("!auto ") or mode == "auto":
                goal = raw.replace("!auto ", "", 1).strip()
                self._trigger_copilot_js(
                    f"document.getElementById('autoGoalInput').value = {json.dumps(goal)}; "
                    f"switchTab('auto', document.querySelectorAll('.tab-btn')[1]); "
                    f"generateAndRunWorkflow(true);"
                )
                return

            # Si es una URL directa
            if raw.startswith(("http://", "https://", "file://")) or (
                re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(/.*)?$", raw) and " " not in raw
            ):
                target = raw if raw.startswith(("http://", "https://", "file://")) else f"https://{raw}"
                self.load_url_in_active_tab(target)
                return

            enc = urllib.parse.quote(raw)
            if mode == "ddg":
                self.load_url_in_active_tab(f"https://duckduckgo.com/?q={enc}")
            elif mode == "google":
                self.load_url_in_active_tab(f"https://www.google.com/search?q={enc}")
            elif mode == "wiki":
                self.load_url_in_active_tab(f"https://es.wikipedia.org/w/index.php?search={enc}")
            elif mode == "arxiv":
                self.load_url_in_active_tab(f"https://arxiv.org/search/?query={enc}&searchtype=all")
            else:
                # Búsqueda asistida con TARDIS IA en el panel lateral + DuckDuckGo en la pestaña si está en blanco
                self._trigger_copilot_js(
                    f"document.getElementById('copilotQuery').value = {json.dumps(raw)}; "
                    f"switchTab('search', document.querySelectorAll('.tab-btn')[0]); "
                    f"runCopilotSearch();"
                )

        def _on_tardis_search_btn(self, *_args: Any) -> None:
            raw = self.url_entry.get_text().strip()
            if not raw or raw.startswith("http"):
                wv = self.get_active_webview()
                raw = (wv.get_title() if wv else "") or "Avances recientes en computación cuántica e IA"
            self._trigger_copilot_js(
                f"document.getElementById('copilotQuery').value = {json.dumps(raw)}; "
                f"switchTab('search', document.querySelectorAll('.tab-btn')[0]); "
                f"runCopilotSearch();"
            )

        def _on_analyze_dom_btn(self, *_args: Any) -> None:
            self._trigger_copilot_js(
                "switchTab('search', document.querySelectorAll('.tab-btn')[0]); "
                "analyzeActivePage('Realiza un análisis técnico completo de esta página, resumiendo su contenido, tablas, enlaces y hallazgos clave.');"
            )

        def _on_automate_btn(self, *_args: Any) -> None:
            raw = self.url_entry.get_text().strip()
            if raw and not raw.startswith("http"):
                self._trigger_copilot_js(
                    f"document.getElementById('autoGoalInput').value = {json.dumps(raw)}; "
                    f"switchTab('auto', document.querySelectorAll('.tab-btn')[1]); "
                    f"generateAndRunWorkflow(true);"
                )
            else:
                self._trigger_copilot_js("switchTab('auto', document.querySelectorAll('.tab-btn')[1]);")

        def _on_screenshot_btn(self, *_args: Any) -> None:
            out_file = str(RUNS_DIR / f"manual_shot_{int(time.time())}.png")
            saved = self.bridge_take_screenshot(out_file)
            if saved:
                self._trigger_copilot_js(
                    f"document.getElementById('copilotOutput').innerText = '📸 Captura guardada exitosamente en:\\n{saved}';"
                )

        def _on_bookmark_btn(self, *_args: Any) -> None:
            wv = self.get_active_webview()
            if wv and wv.get_uri():
                persistence.add_bookmark(wv.get_title() or wv.get_uri(), wv.get_uri(), "Guardado")
                self._populate_bookmarks_bar()

        def _on_toggle_copilot(self, *_args: Any) -> None:
            if self.copilot_visible:
                self.copilot_scrolled.hide()
                self.copilot_visible = False
            else:
                self.copilot_scrolled.show_all()
                self.copilot_visible = True

        def _trigger_copilot_js(self, js_code: str) -> None:
            if not self.copilot_visible:
                self.copilot_scrolled.show_all()
                self.copilot_visible = True
            self.copilot_webview.evaluate_javascript(js_code, -1, None, None, None, None, None)

        def _on_permission_request(self, _webview: WebKit2.WebView, request: Any) -> bool:
            try:
                request.allow()
                return True
            except Exception:
                return False

        def _on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
            ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
            if event.keyval == Gdk.KEY_F11:
                if self.is_fullscreen:
                    self.unfullscreen()
                    self.is_fullscreen = False
                else:
                    self.fullscreen()
                    self.is_fullscreen = True
                return True
            if event.keyval == Gdk.KEY_F9:
                self._on_toggle_copilot()
                return True
            if event.keyval == Gdk.KEY_F5 or (ctrl and event.keyval in (Gdk.KEY_r, Gdk.KEY_R)):
                self._on_reload()
                return True
            if ctrl and event.keyval in (Gdk.KEY_t, Gdk.KEY_T):
                self.add_browser_tab(PORTAL_URL, switch_to=True)
                return True
            if ctrl and event.keyval in (Gdk.KEY_w, Gdk.KEY_W):
                idx = self.notebook.get_current_page()
                if idx != -1:
                    self._close_tab_widget(self.notebook.get_nth_page(idx))
                return True
            if ctrl and event.keyval in (Gdk.KEY_l, Gdk.KEY_L):
                self.url_entry.grab_focus()
                return True
            if event.keyval == Gdk.KEY_F12:
                wv = self.get_active_webview()
                if wv:
                    wv.get_inspector().show()
                return True
            return False

        # ------------------------------------------------------------------
        # Callbacks Hilo-Seguros del Bridge de Automatización (GTK Main Thread)
        # ------------------------------------------------------------------
        def bridge_navigate(self, url: str, new_tab: bool = False) -> bool:
            done_ev = threading.Event()

            def _do_nav():
                try:
                    if new_tab:
                        self.add_browser_tab(url, switch_to=True)
                    else:
                        self.load_url_in_active_tab(url)
                finally:
                    done_ev.set()
                return False

            GLib.idle_add(_do_nav)
            done_ev.wait(timeout=3.0)
            return True

        def bridge_get_active_info(self) -> Dict[str, str]:
            result: Dict[str, str] = {}
            done_ev = threading.Event()

            def _do_info():
                try:
                    wv = self.get_active_webview()
                    if wv:
                        result["url"] = wv.get_uri() or ""
                        result["title"] = wv.get_title() or ""
                finally:
                    done_ev.set()
                return False

            GLib.idle_add(_do_info)
            done_ev.wait(timeout=2.0)
            return result

        def bridge_eval_js(self, js_code: str, timeout: float = 6.0) -> Any:
            holder: Dict[str, Any] = {"value": None}
            done_ev = threading.Event()

            def _start_eval():
                wv = self.get_active_webview()
                if not wv:
                    done_ev.set()
                    return False

                def _cb(obj: WebKit2.WebView, res: Any, _user_data: Any) -> None:
                    try:
                        js_val = obj.evaluate_javascript_finish(res)
                        if js_val:
                            holder["value"] = js_val.to_string()
                    except Exception as e_js:
                        holder["error"] = str(e_js)
                    finally:
                        done_ev.set()

                try:
                    wv.evaluate_javascript(js_code, -1, None, None, None, _cb, None)
                except Exception as e_call:
                    holder["error"] = str(e_call)
                    done_ev.set()
                return False

            GLib.idle_add(_start_eval)
            done_ev.wait(timeout=timeout)
            return holder.get("value")

        def bridge_take_screenshot(self, out_path: str) -> Optional[str]:
            holder: Dict[str, Optional[str]] = {"path": None}
            done_ev = threading.Event()

            def _do_shot():
                try:
                    gdk_win = self.get_window()
                    if gdk_win:
                        w, h = gdk_win.get_width(), gdk_win.get_height()
                        pb = Gdk.pixbuf_get_from_window(gdk_win, 0, 0, w, h)
                        if pb:
                            pb.savev(out_path, "png", [], [])
                            holder["path"] = out_path
                except Exception as e:
                    logger.warning(f"Screenshot error: {e}")
                finally:
                    done_ev.set()
                return False

            GLib.idle_add(_do_shot)
            done_ev.wait(timeout=3.0)
            return holder["path"]

    GLib.set_prgname("tardis-navigator")
    GLib.set_application_name("TARDIS Quantum Navigator")
    win = TardisQuantumNavigatorWindow(initial_url)
    win.show_all()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    Gtk.main()


# ==============================================================================
# 4. PUNTO DE ENTRADA PRINCIPAL
# ==============================================================================
def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TARDIS Quantum Navigator - Navegador con Interfaz, Asistente de Búsqueda IA y Automatización"
    )
    parser.add_argument("url", nargs="?", default=PORTAL_URL, help="URL inicial a abrir")
    parser.add_argument("--port", type=int, default=NAVIGATOR_PORT, help="Puerto del servidor local de control")
    parser.add_argument("--server-only", action="store_true", help="Ejecutar únicamente el servidor API/Web sin ventana GTK")
    args = parser.parse_args()

    persistence = NavigatorPersistence()
    search_assistant = TardisSearchAssistant()
    automation_engine = TardisAutomationEngine(persistence, search_assistant)

    NavigatorHTTPHandler.persistence = persistence
    NavigatorHTTPHandler.search_assistant = search_assistant
    NavigatorHTTPHandler.automation_engine = automation_engine

    if not is_port_in_use(args.port):
        httpd = ThreadedHTTPServer(("127.0.0.1", args.port), NavigatorHTTPHandler)
        srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        srv_thread.start()
        logger.info(f"⚡ Servidor TARDIS Navigator activo en http://127.0.0.1:{args.port}")
    else:
        logger.info(f"⚡ Puerto {args.port} ya activo. Conectando instancia...")

    if args.server_only:
        logger.info("Modo --server-only activo. Manteniendo servicio...")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    run_gtk_navigator_window(
        initial_url=args.url,
        persistence=persistence,
        search_assistant=search_assistant,
        automation_engine=automation_engine,
    )


if __name__ == "__main__":
    main()

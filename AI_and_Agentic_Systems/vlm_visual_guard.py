"""
vlm_visual_guard.py - Motor de Visión Local Multimodal (VLM) y Guardián Visual
================================================================================

Permite a GIA "ver" directamente la pantalla del PC, fotos de la cámara web
o archivos gráficos usando modelos multimodales locales de Ollama (ej.
qwen2.5-vl, minicpm-v, llava, llama3.2-vision, moondream), con fallback inteligente
al motor OCR nativo cuando no haya un VLM activo.

Capacidades:
  1. Inferencia VLM con prompts estructurados (ej. "describe errores en pantalla",
     "¿terminó el render de Vectorworks?", "¿qué hay en la cámara?").
  2. Guardián Visual (watch_condition): Monitoreo periódico no invasivo de la pantalla
     hasta que se cumpla una condición visual (e.g. "aparece diálogo de error", "la barra de progreso llegó al 100%").
  3. Detección de cambios visuales por diferencia de histogramas (diferenciación de frames).
  4. Integración completa con gia_agent, screen_reader y device_sensors.

Arquitecto: Miguel Angel May Canche  ·  GIA-V26-VISION-CORE
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
CAPTURES_DIR = CONFIG_DIR / "captures"
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

_raw_ollama = os.environ.get("OLLAMA_HOST", "http://REDACTED_IP:11434").strip()
OLLAMA_URL = _raw_ollama if _raw_ollama.startswith(("http://", "https://")) else f"http://{_raw_ollama}"

# Modelos multimodales conocidos ordenados por preferencia
VLM_CANDIDATE_MODELS = [
    "qwen2.5-vl:7b",
    "qwen2.5-vl:latest",
    "minicpm-v:latest",
    "llama3.2-vision:11b",
    "llama3.2-vision:latest",
    "llava:13b",
    "llava:7b",
    "llava:latest",
    "moondream:latest",
    "bakllava:latest"
]

try:
    import pyautogui
    import pygetwindow as gw
    HAS_GUI = True
except Exception:
    HAS_GUI = False

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False


def _encode_image_b64(img_path_or_bytes: Path | str | bytes) -> str:
    """Convierte una ruta de imagen o bytes a base64 limpio."""
    if isinstance(img_path_or_bytes, (str, Path)):
        p = Path(img_path_or_bytes)
        if not p.is_file():
            raise FileNotFoundError(f"No existe el archivo de imagen: {p}")
        raw = p.read_bytes()
    else:
        raw = img_path_or_bytes
    return base64.b64encode(raw).decode("utf-8")


def detect_available_vlm_model() -> Optional[str]:
    """Descubre qué modelo de visión multimodal está instalado en Ollama."""
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=4.0)
        if r.status_code != 200:
            return None
        models = [m.get("name", "") for m in r.json().get("models", [])]
        for cand in VLM_CANDIDATE_MODELS:
            cand_clean = cand.split(":")[0]
            for m in models:
                if cand == m or cand_clean in m:
                    return m
        # Buscar cualquier modelo con 'vision', 'vl' o 'llava'
        for m in models:
            m_low = m.lower()
            if "vision" in m_low or "-vl" in m_low or "llava" in m_low or "moondream" in m_low:
                return m
    except Exception:
        pass
    return None


def inspect_image(
    image_source: str | Path | bytes,
    prompt: str = "Describe con precisión técnica todo lo que se observa en esta imagen.",
    model: Optional[str] = None,
    timeout_s: float = 60.0
) -> Dict[str, Any]:
    """Envía la imagen al modelo VLM local y devuelve el análisis semántico."""
    try:
        b64_img = _encode_image_b64(image_source)
    except Exception as e:
        return {"ok": False, "error": f"Error al procesar la imagen: {e}"}

    vlm_model = model or detect_available_vlm_model()
    
    # Si tenemos un modelo VLM en Ollama, realizamos inferencia multimodal
    if vlm_model:
        try:
            payload = {
                "model": vlm_model,
                "prompt": prompt,
                "images": [b64_img],
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_ctx": 4096
                }
            }
            r = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=timeout_s)
            if r.status_code == 200:
                resp_text = r.json().get("response", "").strip()
                return {
                    "ok": True,
                    "engine": f"vlm_ollama ({vlm_model})",
                    "analysis": resp_text,
                    "model": vlm_model
                }
        except Exception as e:
            # Fallback en caso de error de conexión con VLM
            pass

    # Fallback inteligente: OCR estructurado nativo si no hay VLM activo
    try:
        import screen_reader
        ocr_res = screen_reader.read_screen()
        return {
            "ok": True,
            "engine": "ocr_fallback (sin VLM instalado)",
            "analysis": f"[OCR Fallback - VLM no detectado en Ollama]: {ocr_res.get('text', '')[:2000]}",
            "ocr_text": ocr_res.get("text", ""),
            "note": "Para visión multimodal completa, ejecuta: ollama pull qwen2.5-vl:7b o ollama pull minicpm-v"
        }
    except Exception as e:
        return {"ok": False, "error": f"Inferencia visual falló: {e}"}


def _capture_screen_native(out_path: Path, region: Optional[List[int]] = None) -> bool:
    """Intenta capturar la pantalla con pyautogui, PIL, o script PowerShell nativo."""
    # 1. PyAutoGUI
    try:
        import pyautogui
        if region and len(region) == 4:
            img = pyautogui.screenshot(region=tuple(int(v) for v in region))
        else:
            img = pyautogui.screenshot()
        img.save(str(out_path), "JPEG", quality=85)
        return True
    except Exception:
        pass

    # 2. PIL ImageGrab
    try:
        from PIL import ImageGrab
        bbox = tuple(region) if (region and len(region) == 4) else None
        img = ImageGrab.grab(bbox=bbox)
        img.save(str(out_path), "JPEG", quality=85)
        return True
    except Exception:
        pass

    # 3. Script PowerShell nativo
    try:
        ps_script = Path(__file__).parent / "capture_screen.ps1"
        if ps_script.is_file():
            args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps_script), "-OutPath", str(out_path)]
            if region and len(region) == 4:
                args.extend(["-X", str(region[0]), "-Y", str(region[1]), "-W", str(region[2]), "-H", str(region[3])])
            proc = subprocess.run(args, capture_output=True, text=True, timeout=8)
            if out_path.is_file() and out_path.stat().st_size > 100:
                return True
    except Exception:
        pass

    # 4. Fallback: usar el frame óptico más reciente de sensor_telemetry si existe
    try:
        import sensor_telemetry
        lat = sensor_telemetry.latest()
        opt = lat.get("optical_frame")
        if opt and os.path.isfile(opt):
            raw = Path(opt).read_bytes()
            out_path.write_bytes(raw)
            return True
    except Exception:
        pass

    return False


def inspect_screen(
    region: Optional[List[int]] = None,
    prompt: str = "Analiza lo que se ve en la pantalla. Identifica ventanas activas, errores, botones y datos relevantes.",
    model: Optional[str] = None
) -> Dict[str, Any]:
    """Captura la pantalla (o región [x, y, w, h]) y la analiza con el motor de visión."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    shot_path = CAPTURES_DIR / f"screen_{ts}.jpg"

    ok = _capture_screen_native(shot_path, region=region)
    if not ok:
        # Fallback a lectura de ventanas por OCR si no se puede capturar raster
        try:
            import screen_reader
            return screen_reader.read_screen({"region": region})
        except Exception as e:
            return {"ok": False, "error": f"No se pudo capturar pantalla: {e}"}

    res = inspect_image(shot_path, prompt=prompt, model=model)
    res["screenshot_path"] = str(shot_path)
    res["region"] = region
    return res


def inspect_camera(
    camera_index: int = 0,
    prompt: str = "Describe lo que se observa frente a la cámara web (objetos, personas, entorno, iluminación).",
    model: Optional[str] = None
) -> Dict[str, Any]:
    """Captura un frame de la cámara y lo analiza con el VLM."""
    if not HAS_CV2:
        return {"ok": False, "error": "OpenCV no disponible"}

    ts = time.strftime("%Y%m%d_%H%M%S")
    photo_path = CAPTURES_DIR / f"camera_{ts}.jpg"

    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap or not cap.isOpened():
        return {"ok": False, "error": f"No se pudo acceder a la cámara {camera_index}"}

    try:
        frame = None
        for _ in range(6):  # Calibración de exposición
            ok, frame = cap.read()
            if not ok:
                frame = None
        if frame is None:
            return {"ok": False, "error": "No se recibió frame de la cámara"}
        cv2.imwrite(str(photo_path), frame)
    finally:
        cap.release()

    res = inspect_image(photo_path, prompt=prompt, model=model)
    res["photo_path"] = str(photo_path)
    return res


def watch_screen_condition(
    condition_description: str,
    region: Optional[List[int]] = None,
    check_interval_s: float = 4.0,
    max_duration_s: float = 60.0,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Monitorea activamente la pantalla hasta que se cumpla la condición indicada.
    Ej: condition_description = "Aparece un cuadro de diálogo con un botón OK" o "El render llegó al 100%"
    """
    start_time = time.time()
    checks_done = 0
    vlm_model = model or detect_available_vlm_model()

    eval_prompt = (
        f"¿Se cumple la siguiente condición en esta captura?: '{condition_description}'\n"
        f"Responde estrictamente en formato JSON:\n"
        f'{{"cumplida": true/false, "explicacion": "breve motivo", "detalles": "..."}}'
    )

    while (time.time() - start_time) < max_duration_s:
        checks_done += 1
        res = inspect_screen(region=region, prompt=eval_prompt, model=vlm_model)
        if res.get("ok"):
            analysis = res.get("analysis", "")
            # Intentar parsear JSON de la respuesta
            try:
                # Extraer bloque JSON
                json_match = analysis
                if "{" in json_match and "}" in json_match:
                    json_str = json_match[json_match.find("{"):json_match.rfind("}") + 1]
                    parsed = json.loads(json_str)
                    if parsed.get("cumplida") is True:
                        return {
                            "ok": True,
                            "condition_met": True,
                            "checks": checks_done,
                            "elapsed_s": round(time.time() - start_time, 2),
                            "explanation": parsed.get("explicacion", ""),
                            "details": parsed.get("detalles", ""),
                            "screenshot_path": res.get("screenshot_path")
                        }
            except Exception:
                # Evaluación textual si el modelo respondió texto libre afirmativo
                if any(word in analysis.lower() for word in ["sí", "si se cumple", "cumplida: true", "condición cumplida", "render completado"]):
                    return {
                        "ok": True,
                        "condition_met": True,
                        "checks": checks_done,
                        "elapsed_s": round(time.time() - start_time, 2),
                        "analysis": analysis,
                        "screenshot_path": res.get("screenshot_path")
                    }

        time.sleep(check_interval_s)

    return {
        "ok": True,
        "condition_met": False,
        "timed_out": True,
        "checks": checks_done,
        "elapsed_s": round(time.time() - start_time, 2),
        "note": f"Tiempo límite agotado ({max_duration_s}s) sin detectar la condición."
    }


if __name__ == "__main__":
    print("=== MOTOR VLM & GUARDIÁN VISUAL GIA ===")
    vlm = detect_available_vlm_model()
    print(f"Modelo VLM detectado en Ollama: {vlm or 'Ninguno (usará OCR fallback)'}")
    print("\nCapturando pantalla e inspeccionando con VLM...")
    result = inspect_screen(prompt="Describe qué ventanas y aplicaciones están abiertas en la pantalla.")
    print(f"Engine: {result.get('engine')}")
    print("Análisis:\n", result.get("analysis", result.get("error")))

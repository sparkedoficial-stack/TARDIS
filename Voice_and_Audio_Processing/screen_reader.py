"""
screen_reader.py - Lectura de pantalla por OCR (Windows.Media.Ocr).
====================================================================

El modelo local es de TEXTO: no "ve" imagenes. Este modulo captura la
pantalla (o una region / la ventana enfocada) y extrae el texto por OCR
usando el motor nativo de Windows (via winocr), para que el agente pueda
"leer" lo que hay en pantalla: chats, barras de input, navegador, etc.

OCR en espanol (pack ya presente en Windows en español).

API:
    read_screen(args) -> {ok, text, chars, region}
        args: { region?: [x,y,w,h], lang?: "es" }
"""
from __future__ import annotations

import asyncio
import os

try:
    import pyautogui
    import winocr
    _OK = True
    _IMPORT_ERR = ""
except Exception as e:   # noqa: BLE001
    _OK = False
    _IMPORT_ERR = f"{type(e).__name__}: {e}"

try:
    import agent_safety as _safety
    def _audit(a, d, v="ALLOW"):
        _safety.audit(a, d, verdict=v)
except Exception:
    def _audit(a, d, v="ALLOW"):
        pass

DEFAULT_LANG = "es"


async def _ocr(image, lang):
    return await winocr.recognize_pil(image, lang)


def read_screen(args: dict = None) -> dict:
    """Captura la pantalla (o una region) y devuelve el texto por OCR."""
    if not _OK:
        return {"ok": False, "error": f"OCR no disponible: {_IMPORT_ERR}"}
    args = args or {}
    lang = args.get("lang", DEFAULT_LANG)
    region = args.get("region")     # [x, y, w, h] opcional
    try:
        if region and len(region) == 4:
            img = pyautogui.screenshot(region=tuple(int(v) for v in region))
        else:
            img = pyautogui.screenshot()
        result = asyncio.run(_ocr(img, lang))
        text = result.text if hasattr(result, "text") else str(result)
    except Exception as e:   # noqa: BLE001
        # Fallback a ingles si el pack es distinto
        try:
            result = asyncio.run(_ocr(img, "en"))
            text = result.text if hasattr(result, "text") else str(result)
        except Exception as e2:
            return {"ok": False, "error": f"OCR fallo: {e} / {e2}"}
    _audit("read_screen", f"region={region} chars={len(text)}")
    return {"ok": True, "chars": len(text), "region": region,
            "text": text[:6000],
            "note": "texto extraido por OCR; puede tener errores de reconocimiento."}


def read_window(title_substr: str, lang: str = DEFAULT_LANG) -> dict:
    """OCR de una ventana especifica por substring de titulo."""
    if not _OK:
        return {"ok": False, "error": f"OCR no disponible: {_IMPORT_ERR}"}
    try:
        import pygetwindow as gw
        wins = [w for w in gw.getAllWindows()
                if title_substr.lower() in w.title.lower() and w.width > 0]
        if not wins:
            return {"ok": False, "error": f"sin ventana '{title_substr}'"}
        w = wins[0]
        try:
            w.activate()
        except Exception:
            pass
        return read_screen({"region": [max(0, w.left), max(0, w.top),
                                        w.width, w.height], "lang": lang})
    except Exception as e:   # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    import json
    print("OCR disponible:", _OK, _IMPORT_ERR)
    r = read_screen()
    print(f"chars: {r.get('chars')}")
    print("muestra:", (r.get("text") or "")[:300].replace("\n", " "))

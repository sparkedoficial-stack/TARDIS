#!/usr/bin/env python3
import os
import json
import subprocess
from google import genai

TOPICS = [
    "ciencia",
    "artes",
    "fisica teorica",
    "desarrollo de software"
]

def search_youtube(topic, max_results=2):
    """Busca videos en YouTube utilizando yt-dlp."""
    print(f"[*] Buscando videos sobre: {topic}")
    cmd = [
        "yt-dlp",
        f"ytsearch{max_results}:{topic}",
        "--dump-json",
        "--no-playlist",
        "--quiet"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        videos = []
        for line in result.stdout.strip().split('\n'):
            if line:
                data = json.loads(line)
                videos.append({
                    "title": data.get("title"),
                    "url": data.get("webpage_url"),
                    "description": data.get("description", "")
                })
        return videos
    except Exception as e:
        print(f"[!] Error buscando en YouTube para '{topic}': {e}")
        return []

def analyze_with_gemini(videos):
    """Utiliza la API de Gemini para analizar la información extraída y generar propuestas."""
    print("[*] Iniciando análisis cognitivo con Gemini...")
    
    # Se requiere que GEMINI_API_KEY esté configurada en el entorno
    if not os.environ.get("GEMINI_API_KEY"):
        return "Error: La variable de entorno GEMINI_API_KEY no está configurada. No se pudo realizar el análisis visual/texto."

    client = genai.Client()
    
    prompt = (
        "Eres un sistema de aprendizaje autónomo. Analiza los siguientes metadatos y resúmenes de "
        "videos de YouTube sobre ciencia, artes, física teórica y desarrollo de software.\n"
        "1. Resume los conceptos clave que aprenderías de estos temas.\n"
        "2. Propón 3 mejoras de código o arquitectura que podrías auto-ejecutar en tu propio sistema "
        "para optimizar tu procesamiento de datos basándote en lo aprendido.\n\n"
        "Videos encontrados:\n"
    )
    
    for v in videos:
        prompt += f"- Título: {v['title']}\n  URL: {v['url']}\n  Descripción: {v['description'][:300]}...\n\n"
        
    try:
        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt,
        )
        return response.text
    except Exception as e:
        return f"Error en la llamada a la API de Gemini: {e}"

def main():
    print("=== INICIANDO PROTOCOLO DE APRENDIZAJE AUTÓNOMO ===")
    all_videos = []
    for topic in TOPICS:
        videos = search_youtube(topic, max_results=2)
        all_videos.extend(videos)
        
    if not all_videos:
        print("[!] No se encontraron videos. Verifica tu conexión a internet o la instalación de yt-dlp.")
        return

    print(f"\n[+] Se recolectaron {len(all_videos)} videos en total.")
    analysis_result = analyze_with_gemini(all_videos)
    
    report_path = "reporte_aprendizaje.md"
    print(f"\n[*] Escribiendo los resultados del aprendizaje en: {report_path}")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Reporte de Aprendizaje Autónomo y Mejoras del Sistema\n\n")
        f.write("## 1. Fuentes de Aprendizaje (Videos Analizados)\n")
        for v in all_videos:
            f.write(f"- [{v['title']}]({v['url']})\n")
        f.write("\n## 2. Análisis Cognitivo y Propuestas de Auto-Mejora\n")
        f.write(analysis_result)
        
    print("[+] Proceso completado. Para aplicar las mejoras sugeridas, revisa el archivo markdown generado.")

if __name__ == "__main__":
    main()

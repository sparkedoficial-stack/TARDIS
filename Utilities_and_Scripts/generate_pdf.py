import sys, os
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
)
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#64748b"))
        # Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 750, "GODWORKS SYSTEM v26.4 — Especificación Técnica del Sistema")
            self.setStrokeColor(colors.HexColor("#cbd5e1"))
            self.setLineWidth(0.5)
            self.line(54, 742, 612 - 54, 742)
        # Footer
        text = f"Página {self._pageNumber} de {page_count}"
        self.drawRightString(612 - 54, 36, text)
        self.drawString(54, 36, "CONFIDENCIAL / DOCUMENTACIÓN TÉCNICA INTERNA")
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(54, 48, 612 - 54, 48)
        self.restoreState()

def build_pdf(filename="ESPECIFICACION_TECNICA_SISTEMA_Y_SENSORES.pdf"):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()
    
    # Custom styles
    primary_color = colors.HexColor("#0f172a") # Slate 900
    accent_color = colors.HexColor("#2563eb")  # Blue 600
    dark_gray = colors.HexColor("#334155")     # Slate 700
    bg_light = colors.HexColor("#f8fafc")      # Slate 50
    border_color = colors.HexColor("#e2e8f0")  # Slate 200

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=primary_color,
        spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=15,
        textColor=accent_color,
        spaceAfter=14
    )
    meta_style = ParagraphStyle(
        'DocMeta',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#64748b")
    )
    h1_style = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=17,
        textColor=primary_color,
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )
    h2_style = ParagraphStyle(
        'Heading2_Custom',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=14,
        textColor=accent_color,
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True
    )
    body_style = ParagraphStyle(
        'Body_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=dark_gray,
        spaceAfter=5
    )
    bullet_style = ParagraphStyle(
        'Bullet_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=dark_gray,
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=3
    )
    code_style = ParagraphStyle(
        'Code_Custom',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=4
    )
    table_cell = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=dark_gray
    )
    table_cell_bold = ParagraphStyle(
        'TableCellBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=primary_color
    )

    story = []

    # Cover / Header block
    story.append(Paragraph("GODWORKS MASTER CONTROL · SISTEMA GIA v26.4", meta_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Especificación Técnica: Hardware, Sensores y Núcleo Cognitivo", title_style))
    story.append(Paragraph("Manual de Arquitectura y Guía para Calibración de Semillas de Contexto (System Prompt)", subtitle_style))
    
    meta_info = (
        "<b>Fecha:</b> Septiembre 2026 &nbsp;|&nbsp; "
        "<b>Arquitectura:</b> x86_64 Linux &nbsp;|&nbsp; "
        "<b>Motor LLM:</b> Hermes 3 8B (Ollama Local) &nbsp;|&nbsp; "
        "<b>Memoria Asignada:</b> 16 GB RAM + 4 GB VRAM"
    )
    story.append(Paragraph(meta_info, meta_style))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1.5, color=accent_color, spaceBefore=4, spaceAfter=12))

    # SECTION 1: HARDWARE
    story.append(Paragraph("1. Infraestructura de Hardware y Capacidades de Cómputo", h1_style))
    story.append(Paragraph(
        "El sistema opera de forma local e híbrida sobre una estación con arquitectura heterogénea CPU/GPU, optimizada para balancear ancho de banda de memoria y procesamiento tensorial:",
        body_style
    ))

    hw_data = [
        [Paragraph("Componente", table_cell_bold), Paragraph("Especificación Real", table_cell_bold), Paragraph("Función en el Sistema GIA", table_cell_bold)],
        [
            Paragraph("CPU", table_cell_bold),
            Paragraph("AMD Ryzen 7 4800H<br/>8 núcleos / 16 hilos (2.9 - 4.2 GHz)", table_cell),
            Paragraph("Gestión de subprocesos asíncronos, FFT espectral, visión OpenCV, base de datos SQLite y capas CPU del LLM.", table_cell)
        ],
        [
            Paragraph("Memoria RAM", table_cell_bold),
            Paragraph("24 GB DDR4<br/>(17.8 GB disponibles para SO)", table_cell),
            Paragraph("Alojamiento de KV Cache extendido (16k–32k tokens), búfer de memoria episódica y pools de telemetría. Margen configurado de 16 GB.", table_cell)
        ],
        [
            Paragraph("GPU", table_cell_bold),
            Paragraph("NVIDIA RTX 3050 Laptop<br/>4.096 MiB VRAM GDDR6, 2048 CUDA Cores", table_cell),
            Paragraph("Aceleración tensorial CUDA de las primeras 18 capas del modelo (~50% de pesos en VRAM, ~2.8 GB ocupados). Decodificación rápida.", table_cell)
        ],
        [
            Paragraph("Almacenamiento", table_cell_bold),
            Paragraph("NVMe PCIe SSD", table_cell),
            Paragraph("Persistencia de bases de datos vectoriales FTS5, logs de telemetría y checkpoints de sesión.", table_cell)
        ],
        [
            Paragraph("Red & Conectividad", table_cell_bold),
            Paragraph("Wi-Fi 802.11ac/ax + BLE + Ethernet", table_cell),
            Paragraph("Monitoreo de espectro RF pasivo, túnel Cloudflare seguro y comunicación con dispositivos periféricos.", table_cell)
        ]
    ]

    t_hw = Table(hw_data, colWidths=[1.1*inch, 2.3*inch, 3.4*inch])
    t_hw.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ('TEXTCOLOR', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t_hw)
    story.append(Spacer(1, 10))

    # SECTION 2: SENSORES
    story.append(Paragraph("2. Rejilla de Sensores y Módulos de Telemetría", h1_style))
    story.append(Paragraph(
        "El entorno GIA integra cuatro canales principales de adquisición física de datos, que transforman señales físicas y de hardware en datos estructurados inyectables al contexto del LLM:",
        body_style
    ))

    # 2.1 OS & Hardware
    story.append(Paragraph("A. Telemetría de Sistema y Hardware (device_sensors.py / psutil)", h2_style))
    story.append(Paragraph("• <b>Uso de CPU:</b> Monitoreo porcentual global y por hilo lógico, frecuencia dinámica en MHz.", bullet_style))
    story.append(Paragraph("• <b>Uso de Memoria:</b> RAM total, libre, utilizada y porcentaje de ocupación en tiempo real.", bullet_style))
    story.append(Paragraph("• <b>Almacenamiento e I/O:</b> Estado de particiones montadas y tasa de transferencia en red (MB enviados/recibidos).", bullet_style))
    story.append(Paragraph("• <b>Térmica y Energía:</b> Sensores ACPI/CPU (°C) y estado de carga de batería (AC/batería y porcentaje).", bullet_style))

    # 2.2 OpenCV
    story.append(Paragraph("B. Visión Óptica y Biometría Facial (OpenCV + Haar Cascades)", h2_style))
    story.append(Paragraph("• <b>Detección de Rostro:</b> Detección de presencia frontal mediante <code>haarcascade_frontalface_default.xml</code> con cálculo de bounding box (x, y, w, h).", bullet_style))
    story.append(Paragraph("• <b>Vector de Mirada:</b> Cálculo normalizado del centro de masa del rostro relativo al eje óptico de la cámara.", bullet_style))
    story.append(Paragraph("• <b>Heurística de Gesticulación:</b> Análisis de desviación estándar de luminancia en zona bucal y ocular para clasificar estados: <i>Alegre</i> (sonrisa activa), <i>Enfocado</i> (fijación ocular sostenida) o <i>Neutral</i> (rostro distendido).", bullet_style))
    story.append(Paragraph("• <b>Estimación de Atención:</b> Clasificación binaria o continua según la permanencia del rostro en el cono central de visión.", bullet_style))

    # 2.3 Radar RF
    story.append(Paragraph("C. Radar Pasivo Wi-Fi y Espectro Electromagnético (rf_presence_radar.py)", h2_style))
    story.append(Paragraph("• <b>Monitoreo RSSI:</b> Rastreo de variaciones de amplitud de señal en balizas Wi-Fi (802.11 a 2.4 GHz y 5 GHz) provocadas por absorción y multitrayectoria del cuerpo humano.", bullet_style))
    story.append(Paragraph("• <b>Clasificación de Presencia:</b> <code>QUIET</code> (varianza &lt; 0.45 dBm²), <code>MICRO_MOTION</code> (respiración/mecanografía, 0.45–1.85 dBm²) o <code>ACTIVE_MOTION</code> (desplazamiento en la habitación, &gt; 5.2 dBm²).", bullet_style))
    story.append(Paragraph("• <b>Entropía de Shannon RF:</b> Cálculo de dispersión de energía espectral y estimación de potencia total en microwatts.", bullet_style))

    # 2.4 Telemetría Web
    story.append(Paragraph("D. Telemetría de Cliente Web y Entorno Dinámico (sensor_telemetry.py)", h2_style))
    story.append(Paragraph("• <b>Cinemática:</b> Aceleración y giro en 3 ejes (X, Y, Z) provenientes de la API <code>DeviceMotionEvent</code> del navegador.", bullet_style))
    story.append(Paragraph("• <b>Acústica:</b> Nivel de entropía espectral procesado por Web Audio API (FFT en AnalyserNode).", bullet_style))
    story.append(Paragraph("• <b>Reloj Lógico de Lamport:</b> Contador monótono causal para sincronizar secuencias de eventos entre clientes web y servidor.", bullet_style))
    story.append(Paragraph("• <b>Tiempo Sideral Local (LST):</b> Cálculo astronómico preciso (algoritmo de Meeus) para correlación temporal absoluta.", bullet_style))
    story.append(Paragraph("• <b>Geolocalización:</b> Coordenadas de latitud, longitud y altitud del punto de anclaje reportado.", bullet_style))

    story.append(Spacer(1, 10))

    # SECTION 3: NUCLEO COGNITIVO
    story.append(Paragraph("3. Núcleo Cognitivo y Pipeline de Inferencia", h1_style))
    story.append(Paragraph(
        "El motor cognitivo está basado en el modelo local <b>Hermes 3 8B</b> (Nous Research / Llama 3.1) orquestado a través de Ollama y el puente soberano en Python:",
        body_style
    ))

    cog_data = [
        [Paragraph("Parámetro", table_cell_bold), Paragraph("Valor Configurado", table_cell_bold), Paragraph("Impacto Técnico", table_cell_bold)],
        [
            Paragraph("Modelo Base", table_cell),
            Paragraph("<b>hermes3:8b</b>", table_cell),
            Paragraph("Modelo de 8 mil millones de parámetros afinado para seguimiento estricto de directivas, llamadas a funciones y razonamiento avanzado.", table_cell)
        ],
        [
            Paragraph("Ventana de Contexto", table_cell),
            Paragraph("<b>16,384 tokens</b> (16k)", table_cell),
            Paragraph("Permite inyectar historiales de chat extensos, telemetría completa de sensores y bloques de memoria sin truncamiento.", table_cell)
        ],
        [
            Paragraph("Predicción Máxima", table_cell),
            Paragraph("<b>2,048 tokens</b>", table_cell),
            Paragraph("Margen suficiente para respuestas extensas, análisis estructurado y código completo sin cortes.", table_cell)
        ],
        [
            Paragraph("Partición de Memoria", table_cell),
            Paragraph("<b>50% GPU / 50% CPU</b><br/>(~2.8 GB VRAM + ~2.7 GB RAM)", table_cell),
            Paragraph("División dinámica que previene desbordamiento de memoria VRAM en la RTX 3050 (4 GB) y aprovecha los 24 GB de RAM del equipo.", table_cell)
        ],
        [
            Paragraph("Persistencia en RAM", table_cell),
            Paragraph("<b>keep_alive: 24h</b>", table_cell),
            Paragraph("El modelo permanece precargado y anclado en memoria, eliminando la latencia de recarga en frío (cold-start) entre turnos.", table_cell)
        ],
        [
            Paragraph("Memoria Episódica", table_cell),
            Paragraph("<b>SQLite FTS5</b>", table_cell),
            Paragraph("Indexación de texto completo de conversaciones previas con recuperación por similitud semántica y léxica.", table_cell)
        ],
        [
            Paragraph("Búsqueda Web RAG", table_cell),
            Paragraph("<b>DuckDuckGo / Tavily</b>", table_cell),
            Paragraph("Módulo de extracción web en vivo para complementar consultas fácticas con fuentes externas.", table_cell)
        ],
        [
            Paragraph("Control de Procesos", table_cell),
            Paragraph("<b>Async Cancel & Abort</b>", table_cell),
            Paragraph("Capacidad de interrumpir la inferencia en tiempo real vía <code>/api/chat/cancel</code> matando el proceso subyacente.", table_cell)
        ]
    ]

    t_cog = Table(cog_data, colWidths=[1.4*inch, 2.0*inch, 3.4*inch])
    t_cog.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ('TEXTCOLOR', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t_cog)
    story.append(Spacer(1, 10))

    # SECTION 4: GUIA DE SEMILLA DE CONTEXTO
    story.append(Paragraph("4. Estructuración y Calibración de la Semilla de Contexto", h1_style))
    story.append(Paragraph(
        "Para que el modelo aproveche la telemetría y el hardware sin generar contradicciones lógicas ni alucinaciones, se recomienda estructurar el <i>System Prompt</i> siguiendo estas pautas:",
        body_style
    ))

    story.append(Paragraph("<b>1. Anclaje en la Realidad del Hardware:</b> Instruir explícitamente al modelo sobre su entorno de cómputo (estación local Linux, CPU AMD Ryzen 7 4800H, GPU RTX 3050, 24 GB RAM). Esto evita que asuma recursos infinitos o entornos cloud genéricos.", bullet_style))
    story.append(Paragraph("<b>2. Formato de Ingesta de Sensores:</b> Delimitar claramente las secciones de telemetría mediante etiquetas estandarizadas (ej. <code>[TELEMETRÍA DE HARDWARE]</code>, <code>[BIOMETRÍA FACIAL]</code>, <code>[RADAR RF]</code>).", bullet_style))
    story.append(Paragraph("<b>3. Pautas de Interpretación de Datos:</b> Indicarle que interprete los datos de sensores como lecturas objetivas. Por ejemplo: <i>'Si la varianza del radar es &gt; 5.0 dBm², reconoce que hay movimiento físico en la sala'</i> o <i>'Si la gesticulación facial es Sereno y Reflexivo, mantén un tono técnico y pausado'</i>.", bullet_style))
    story.append(Paragraph("<b>4. Política de Razonamiento Silencioso:</b> Para mantener respuestas limpias en interfaces web, instruir al modelo a no emitir etiquetas de pensamiento interno (como <code>&lt;think&gt;</code>) a menos que se requiera específicamente un modo de depuración.", bullet_style))

    story.append(Spacer(1, 6))

    # Code example block
    sample_seed = (
        "[EJEMPLO DE SEMILLA DE CONTEXTO TÉCNICO]\n"
        "Eres GIA, un asistente técnico soberano que opera localmente en hardware dedicado.\n"
        "- Hardware: AMD Ryzen 7 4800H (16 hilos), 24GB RAM, NVIDIA RTX 3050 (4GB VRAM).\n"
        "- Modelo: Hermes 3 8B con ventana de contexto de 16,384 tokens.\n"
        "- Capacidad Sensorial: Recibes telemetría real de sensores de hardware (CPU/RAM/Temp),\n"
        "  visión óptica (detección facial y atención), y radar pasivo Wi-Fi (presencia física).\n"
        "- Directiva: Analiza e incorpora los bloques [TELEMETRÍA] cuando sea relevante para responder\n"
        "  al usuario, manteniendo siempre precisión técnica, sobriedad y rigor científico."
    )
    
    t_code = Table([[Paragraph(f"<pre>{sample_seed}</pre>", code_style)]], colWidths=[6.8*inch])
    t_code.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(t_code)

    # Build document
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF generado con éxito: {os.path.abspath(filename)}")

if __name__ == "__main__":
    build_pdf()

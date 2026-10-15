# ₪ TARDIS Syntropic Price Sentinel & Deal Oracle

> **Cazador Soberano de Ofertas, Radar de Errores de Precio y Motor de Arbitraje Multitienda.**  
> *Operación 100% Autónoma, Ética y Legítima — Sin vulnerar, alterar ni hackear sistemas.*

---

## ⚡ 1. Filosofía del Sistema (White-Hat & Sintropía)
El sistema opera bajo los principios de **observabilidad sintrópica y recopilación pública y legítima**:
* **Cero intrusión / Cero explotación:** No realiza inyecciones, no altera precios en carritos, no vulnera autenticaciones ni rompe términos de servicio.
* **Inteligencia de Datos y Fuentes Públicas:** Aprovecha agregadores comunitarios en tiempo real (Promodescuentos, Pepper Network), feeds RSS oficiales, páginas públicas de ofertas relámpago de Mercado Libre y Amazon México, y clasificadores de liquidaciones departamentales (.01, .02, .03).
* **Detección de Anomalías:** Algoritmos estadísticos que calculan el *Deal Gravity / Índice de Sintropía (0 a 1000°)*, identificando caídas de precio superiores al 75%, errores de catálogo reportados, artículos gratuitos (100% OFF) y liquidaciones masivas.
* **Stacking Multicapa:** Cálculo automático de combinaciones de cupones de tienda + bonificaciones bancarias (Banorte, BBVA, Citibanamex, HSBC, Nu, Mercado Pago) para obtener el precio efectivo final más bajo.

---

## 🏗️ 2. Arquitectura de Componentes

```
/home/timemachine/tardis-price-sentinel/
├── tardis_hunter.py       # Interfaz de línea de comandos (CLI soberana)
├── config.json            # Configuración general, intervalos y watchlist predeterminada
├── deals.db               # Base de datos SQLite (historial de precios, ofertas, alertas)
├── core/
│   ├── models.py          # Modelos de datos (Deal, WatchItem, BankPromo)
│   ├── detector.py        # Detector de glitches, cálculo de sintropía y fases de liquidación
│   ├── storage.py         # Capa de persistencia SQLite y registro temporal de precios
│   ├── banking.py         # Matriz de bonificaciones bancarias y motor de stacking
│   └── notifier.py        # Notificaciones nativas Linux (notify-send) y alertas sonoras
├── scrapers/
│   ├── base.py            # Sesiones HTTP seguras y rotación de cabeceras
│   ├── promodescuentos.py # Parser de RSS y motor de búsqueda con extracción JSON Vue3
│   ├── mercadolibre.py    # Extractor de ofertas del día y descuentos relámpago
│   ├── liquidaciones.py   # Clasificador de liquidaciones de autoservicio (.01, .02, .03)
│   └── aggregator.py      # Orquestador concurrente y motor de arbitraje multitienda
├── sentinel/
│   └── daemon.py          # Demonio en segundo plano de monitoreo continuo
└── web/
    ├── app.py             # Backend REST API con FastAPI y Uvicorn
    └── static/            # Dashboard web ciberpunk con diseño sintrópico
        ├── index.html
        ├── app.js
        └── style.css
```

---

## 🚀 3. Uso Rápido desde la Terminal (`tardis-hunter`)

El ejecutable global está enlazado a `/home/timemachine/.local/bin/tardis-hunter`:

### Barrido Inmediato Multitienda
```bash
tardis-hunter scan
```
Ejecuta un barrido concurrente por todas las tiendas, calcula anomalías, actualiza la base de datos y presenta las mejores ofertas.

### Radar de Errores de Precio y Glitches
```bash
tardis-hunter glitches
```
Muestra ofertas con descuentos mayores al 75%, errores de precio reportados en vivo y liquidaciones extremas.

### Comparador de Arbitraje Intertienda
```bash
tardis-hunter search "Nintendo Switch OLED"
tardis-hunter search "RTX 4060"
tardis-hunter search "Audífonos Sony"
```
Compara el producto en todas las tiendas simultáneamente, calcula el precio mínimo, precio máximo y ahorro porcentual.

### Cupones y Promociones Bancarias
```bash
tardis-hunter coupons
```

### Simulador de Stacking (Cupón + Tarjeta)
```bash
# Simular compra de $6,000 con cupón del 10% y tarjeta Banorte Digital
tardis-hunter stack 6000 --coupon 10 --bank "Banorte Digital"
```

### Administrador de Watchlist (Alertas de Escritorio)
```bash
# Listar alertas activas
tardis-hunter watch list

# Agregar nueva alerta (ej: Laptop menor a $8,000 con 30% descuento mín)
tardis-hunter watch add "Laptop" --max-price 8000 --min-discount 30

# Eliminar alerta por ID
tardis-hunter watch remove 1
```

### Estado del Sistema y Telemetría
```bash
tardis-hunter status
```

### Abrir Oferta Directamente en el Carrito de Compra
```bash
# Abre el navegador directamente en el carrito/checkout de una oferta
tardis-hunter cart 0dbb4fa34b33fd9b
# O pasando una URL directa
tardis-hunter cart "https://www.amazon.com.mx/dp/B07D9SNPYT"
```

### Iniciar la Interfaz de Escritorio Local (GUI)
```bash
tardis-hunter gui
# O directamente:
tardis-deals-ui
```
También tienes el acceso directo con icono en tu **Escritorio**: `Tardis-Ofertas-Carrito.desktop`.

---

## 🖥️ 4. Interfaz de Escritorio Nativa (`tardis-deals-ui`)
Ventana gráfica nativa en tu pantalla ASUS TUF:
- **Lista de Ofertas en Vivo:** Filtradas por Sintropía, con indicadores de glitch 🚨 y artículos gratis 🎁.
- **Búsqueda Instantánea:** Escribe y filtra al vuelo sin recargar.
- **Acción Rápida de Carrito:** Haz doble clic en cualquier oferta o presiona **Enter** para abrir tu navegador directamente en el carrito de compras o pasarela de compra express.
- **Sincronización:** Botón **F5** para actualizar los datos en segundo plano contra todas las tiendas.

---

## 🌐 5. Dashboard Web Interactivo
El dashboard web moderno está desplegado en:
👉 **`http://localhost:8787`**

Funcionalidades en el navegador:
1. **🛒 Botón "Abrir en Carrito":** Cada oferta cuenta con un botón directo que calcula el enlace exacto de inserción en carrito (Amazon Add-to-Cart por ASIN, Mercado Libre Express Checkout por MLM-ID, Walmart Cart, Steam, etc.) y abre el navegador listo para pagar.
2. **⚡ Modo 1-Clic Carrito:** Al activarlo en el encabezado, hacer clic en cualquier parte de una tarjeta abre inmediatamente el carrito de compras en una nueva pestaña.
3. **🔄 Sincronización Automática:** Indicador en tiempo real con selector de auto-refresco cada 30 segundos sin parpadeos.
4. **Radar General:** Búsqueda en vivo, filtrado por tiendas (Amazon, Mercado Libre, Walmart, Steam, Nintendo, PlayStation, etc.), ordenamiento por Sintropía o Descuento, selector de solo glitches o solo gratis.
5. **Radar de Errores de Precio:** Vista especializada en anomalías extremas y remates.
6. **Arbitraje Multitienda:** Búsqueda con comparador visual de precios y botón directo al carrito de la tienda ganadora.
7. **Simulador de Stacking:** Calculadora reactiva de precio efectivo final con bonificaciones de bancos mexicanos.
8. **Watchlist & Alertas:** Creación y borrado de reglas de monitoreo en tiempo real con notificaciones al escritorio.

---

## ⚙️ 5. Demonio Systemd Permanente
El servicio de monitoreo y panel web opera bajo systemd:
```bash
# Ver estado del servicio
systemctl --user status tardis-price-sentinel.service

# Reiniciar
systemctl --user restart tardis-price-sentinel.service

# Ver logs en vivo
journalctl --user -u tardis-price-sentinel.service -f
```

---

## 🏷️ 6. Lógica de Liquidaciones en México (.01, .02, .03)
El detector analiza las terminaciones decimales oficiales de cadenas de autoservicio (Walmart, Bodega Aurrera, Chedraui, Soriana):
* **`.01` (Fase 3):** Última liquidación y remate final (70% - 95% de descuento).
* **`.02` (Fase 2):** Segunda liquidación (40% - 60% de descuento).
* **`.03` (Fase 1):** Primera liquidación (20% - 30% de descuento).

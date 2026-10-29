# FTL TERMINAL MÓVIL · Guía de acceso soberano

> Terminal interactiva completa de FTL (máquina del tiempo) accesible desde
> cualquier dispositivo (móvil, iPad, PC ajeno) por **red de datos móviles o
> Internet**, a través de túnel Cloudflare cifrado + gateway autenticado.

## Cómo conectarse

1. Abre el enlace de acceso (token embebido):
   - `Escritorio/GODWORKS SYSTEM/FTL_PUBLIC_ACCESS.txt` → `URL?key=TOKEN`
   - Equivalente: escanear `FTL_PUBLIC_QR.png`
2. Si el token expira del enlace, entra a la URL base (`FTL_PUBLIC_URL.txt`)
   y escribe la clave en el portal de desbloqueo (permanece en cookie 30 días).

## Rutas expuestas por el gateway (:7690)

| Ruta         | Servicio                           |
|--------------|------------------------------------|
| `/`          | Portal FTL (telemetría y estado)   |
| `/terminal`  | Terminal web xterm.js interactiva  |
| `/chat`      | Chat web persistente               |

La sesión de terminal corre `ftl-web-launcher.sh`: arranca por omisión el
FTL Soberano (`~/.ftl/ftl_cli.py`) y ofrece un menú de recuperación:
[ENTER] reinicia FTL · [t] sesión TMUX persistente `ftl_shared` · [b] Bash del
sistema · [q] cerrar pestaña.

## Arquitectura

```
Navegador móvil ──HTTPS/WSS──> Cloudflare Quick Tunnel ──> Gateway (:7690)
                                                            ├─ /          → Portal (:8765)
                                                            └─ /terminal  → ttyd PTY (:7681)
```

Servicios systemd usuario:
- `ftl-web-terminal.service` — ttyd 1.7.7 (--base-path /terminal, subprotocolo WS `tty`)
- `ftl-public-gateway.service` — proxy HTTP+WS unificado con token (`~/.config/ftl/public_gateway.json`, 0600)
- `ftl-public-tunnel.service` — Cloudflare quick tunnel → 7690 (reescribe `FTL_PUBLIC_URL.txt` / `FTL_PUBLIC_ACCESS.txt`)

## Robustez para red móvil

- Handshake WebSocket autenticado directamente vía `?key=` (sin redirect), con
  cookie de sesión emitida en la respuesta 101.
- ttyd `--ping-interval 5` + heartbeat del gateway (30 s): sobrevive NAT/UI de
  operadores agresivos; xterm.js reconecta solo si cae el WS.
- Scrollback 10000 · Sixel habilitado · tamaño de fuente 15 (óptimo en móvil).
- Sesión compartida persistente: `tmux attach -t ftl_shared` dentro del terminal.
- Máximo 8 clientes simultáneos.

## Operación manual (si se necesita)

```bash
systemctl --user restart ftl-public-gateway.service   # tras editar ~/.ftl/ftl_public_gateway.py
systemctl --user restart ftl-public-tunnel.service    # renueva URL pública (actualiza .txt)
journalctl --user -u ftl-public-gateway.service -f    # logs en vivo
curl --max-time 5 "$(cat FTL_PUBLIC_URL.txt)/health"  # diagnóstico público
```

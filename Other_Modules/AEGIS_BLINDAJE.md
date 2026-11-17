# AEGIS-Ω · Manual de Blindaje Militar de la Información

**Sistema:** GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
**Módulo:** `core/aegis` · **Ejecutable:** `aegis` (`bin/aegis` → `/usr/local/bin/aegis`)
**Versión:** 1.0.0 · **Estado:** operativo, con dos acciones pendientes de reinicio (AppArmor) y de firmware (Secure Boot)

---

## 1. Qué es AEGIS-Ω

AEGIS-Ω es la capa de blindaje de información del repositorio. No es una
maqueta ni un conjunto de recomendaciones: cada control se ejecuta, se mide y
se registra en una cadena de custodia criptográfica.

Cubre siete dominios:

| Dominio | Implementación | Archivo |
|---|---|---|
| Confidencialidad en reposo | AES-256-GCM por bloques de 1 MiB, clave por archivo vía HKDF-SHA256, envoltura Argon2id | `core/aegis/crypto.py` |
| Custodia e integridad | Ledger encadenado BLAKE2b + HMAC-SHA256 con ancla externa | `core/aegis/ledger.py` |
| Clasificación | Niveles C0–C4, reglas de secretos/PII, entropía, redacción | `core/aegis/classifier.py` |
| Política y auditoría | Permisos, Git, contenido, remediación y puntuación | `core/aegis/policy.py` |
| Endurecimiento | Sysctl, core dumps, auditd, firewall, AppArmor, Secure Boot | `core/aegis/hardening.py` |
| Antiforense | Borrado multi-pasada, protocolo de pánico | `core/aegis/antiforensic.py` |
| Operación | Orquestador, bóveda, vigilancia, unidades systemd | `core/aegis/engine.py` |

---

## 2. Perímetro de custodia

```
~/.aegis/                     0700   perímetro raíz
├── keys/
│   ├── master.key            0400   clave maestra (32 bytes)
│   ├── master.key.passphrase 0400   envoltura Argon2id (si se usa passphrase)
│   └── recovery.kit          0400   kit de recuperación (una sola vez)
├── ledger.jsonl              0600   cadena de custodia
├── ledger.anchor             0400   ancla HMAC de la cabeza del ledger
├── manifests/                0700   metadatos de cada sellado
└── vault/                    0700   objetos cifrados (formato AGS1)
```

El ledger encadena cada evento:

```
prev_hash = BLAKE2b(registro anterior)
mac       = HMAC-SHA256(clave_ledger, prev_hash || registro)
```

Cualquier alteración de una línea invalida todas las siguientes y rompe el
ancla. `aegis verify` detecta la primera línea divergente.

**Nota operativa:** el ancla vive en el mismo perímetro. Para una garantía
realmente externa, copie `~/.aegis/ledger.anchor` a un medio extraíble o a un
segundo equipo tras cada auditoría relevante (`aegis export-chain`).

---

## 3. Formato criptográfico `AGS1`

```
AGS1 | versión | salt(32) | nonce_base(12) | longitud_original(8) | bloques AES-256-GCM
```

- Clave por archivo: `HKDF-SHA256(master, salt, info="aegis-file-v1")`.
- Nonce por bloque: `nonce_base XOR contador` — nunca se reutiliza.
- Cada bloque lleva su tag GCM de 16 bytes: la manipulación de un solo byte
  provoca fallo de autenticación al descifrar.
- El SHA-256 del contenido plano se sella en el manifiesto antes de cifrar, de
  modo que `aegis verify --deep` comprueba confidencialidad **e** integridad.

---

## 4. Comandos

### 4.1 Postura y auditoría

```bash
aegis status                 # perímetro, clave, ledger, fingerprint
aegis audit                  # auditoría completa + informe HTML/JSON
aegis audit --json           # salida máquina
aegis report                 # regenerar sólo el panel HTML
aegis verify                 # ledger + contenedores
aegis verify --deep          # descifra y compara SHA-256
aegis export-chain cadena.jsonl
```

Artefactos:

- `reports/aegis/aegis_status.json`
- `reports/aegis/aegis_report.html` (panel autocontenido, sin dependencias externas)

Puntuación: `100 − (crítico×25 + alto×10 + medio×3 + bajo×0.5)`, con topes
duros si hay críticos (≤45) o altos (≤75).

### 4.2 Cifrado

```bash
aegis seal ruta/archivo.json                  # → archivo.json.aegis
aegis seal ruta/ --shred-source               # cifra y destruye originales
aegis unseal archivo.json.aegis -o restaurar/
aegis unseal archivo.json.aegis --overwrite
```

`--shred-source` es irreversible sin la clave maestra. Úselo sólo sobre copias
verificadas.

### 4.3 Bóveda de objetos

```bash
aegis vault put telegram_config.json --name telegram_config
aegis vault ls
aegis vault get telegram_config -o /run/user/1000/telegram_config.json
aegis vault rm telegram_config --keep
```

### 4.4 Detección de secretos y PII

```bash
aegis scan                       # todo el proyecto
aegis scan --staged              # sólo el índice Git (lo usa el hook)
aegis scan --no-pii data/
```

Reglas activas: GitHub, GitLab, Slack, AWS, Google API, Stripe, Telegram,
claves privadas PEM/OpenSSH, JWT, alta entropía, correos, teléfonos, IBAN,
tarjetas (con validación de Luhn) y CURP/RFC.

El hook `.git/hooks/pre-commit` ejecuta `aegis scan --staged` y bloquea la
confirmación si aparece un secreto de severidad alta. Escape consciente y
auditado: `AEGIS_BYPASS=1 git commit …` (queda registrado en el ledger).

Para fixtures sintéticos en pruebas existe el marcador `aegis:allow-secret`,
válido **sólo** en archivos `tests/` o `test_*.py`; se ignora en cualquier otra
ruta.

### 4.5 Clave maestra y recuperación

```bash
aegis key --recovery --recovery-out /media/usb/aegis-recovery.txt
aegis key --passwd                           # envuelve con passphrase (Argon2id)
aegis key --unwrap -                        # verifica código de recuperación
```

Reglas:

1. El kit de recuperación se genera **una vez** y se guarda fuera del equipo.
2. Sin `master.key` ni kit, los contenedores son irrecuperables. No existe
   puerta trasera.
3. Rotar la clave maestra implica volver a sellar todos los contenedores.

### 4.6 Endurecimiento

```bash
aegis harden                 # audita
aegis harden --apply         # escribe drop-ins y activa auditd
aegis harden --apply --aggressive
```

Escribe de forma idempotente:

- `/etc/sysctl.d/99-aegis-hardening.conf`
- `/etc/security/limits.d/99-aegis.conf` (core dumps a 0)
- `/etc/systemd/system.conf.d/99-aegis-limits.conf` y `user.conf.d/` (`DefaultLimitCORE=0`,
  porque los servicios no heredan `pam_limits`)
- `/etc/audit/rules.d/99-aegis.rules`
- activa `auditd`

### 4.7 Borrado seguro

```bash
aegis shred archivo --passes 7
aegis shred directorio/ --force
```

**Advertencia física:** en SSD/NVMe con *wear leveling* y en volúmenes con
snapshots Btrfs, el borrado multi-pasada no garantiza la destrucción de todos
los remanentes. Para material clasificado C4 la única garantía es **cifrado
desde el origen** (LUKS + bóveda AEGIS) y destrucción física del medio.

### 4.8 Vigilancia

```bash
aegis watch --once
aegis watch --interval 300
```

Unidades instaladas:

```bash
systemctl --user status aegis-watch.timer
systemctl --user list-timers aegis-watch.timer
journalctl --user -u aegis-watch.service -n 50
```

Ciclo: `OnBootSec=3min`, luego cada 15 minutos. Ejecuta `watch --once`,
verifica ledger y busca secretos nuevos. `SuccessExitStatus=0 1` porque el
código 1 significa «hallazgos», no «fallo operativo».

### 4.9 Protocolo de pánico

```bash
aegis panic --reason "compromiso físico" --offline
aegis panic --reason "exfiltración" --poweroff
```

Acciones: desmonta la bóveda, destruye material temporal, registra el evento,
opcionalmente aísla la red (`--offline`) y apaga (`--poweroff`). No borra la
clave maestra: la recuperación sigue siendo posible con el kit.

---

## 5. Modelo de amenaza

| Amenaza | Control | Residual |
|---|---|---|
| Robo del disco | LUKS2 en raíz + bóveda AEGIS | Equipo encendido y desbloqueado |
| Malware con acceso al usuario | Permisos 0600/0400, perímetro 0700, auditd | Mismo UID puede leer la clave maestra |
| Fuga por Git | `scan --staged`, `.gitignore`, archivos destrackeados | Historia previa (ver §7) |
| Manipulación de registros | Ledger HMAC + ancla | Ancla local; copiar fuera |
| Exfiltración por red | UFW default-deny, puertos restringidos a LAN, token | Servicios LAN autenticados |
| Análisis forense del equipo | Core dumps 0, `dmesg_restrict`, `kptr_restrict`, shred | SSD/NVMe con wear leveling |
| Escalada local | `yama.ptrace_scope=1`, `unprivileged_bpf_disabled`, AppArmor (pendiente reboot) | Kernel sin LSM obligatorio hasta reiniciar |
| Arranque alterado | Secure Boot (pendiente, requiere firmware) | Cadena de arranque no verificada |

---

## 6. Estado actual verificado (2026-11-17)

```
Puntuación AEGIS: 88/100
CRÍTICO 0 · ALTO 0 · MEDIO 0 · BAJO 23 · INFO 2
```

Controles activos:

- LUKS2 en raíz (`/dev/mapper/root`).
- 22 parámetros de kernel endurecidos y persistentes.
- `auditd` activo y habilitado, con reglas AEGIS.
- Core dumps deshabilitados para todos los usuarios y para los servicios
  systemd (`DefaultLimitCORE=0` + `fs.suid_dumpable=0`).
- UFW activo, política deny incoming.
- GIA (8757/tcp) sólo alcanzable desde `REDACTED_IP/16` y `REDACTED_IP/8`,
  con `GIA_AUTH_TOKEN` verificado en el proceso.
- LocalSend (53317/tcp+udp) restringido a LAN.
- AppArmor 4.1.8 instalado y declarado en Limine; **se activa al reiniciar**.
- 23 hallazgos BAJO: PII/credenciales en archivos 0600 dentro del perímetro
  (rotación pendiente), Secure Boot desactivado y datos históricos de capturas.

---

## 7. Acciones pendientes (requieren intervención humana)

### 7.1 Reiniciar para activar AppArmor

```bash
grep apparmor /etc/default/limine      # apparmor=1 security=apparmor presente
sudo systemctl is-enabled apparmor     # enabled
# tras reiniciar:
sudo aa-status
```

Perfiles recomendados una vez activo: `aa-enforce /etc/apparmor.d/*` sólo
después de validar que ningún servicio legítimo se rompe (`aa-complain` primero).

### 7.2 Secure Boot (requiere firmware y reinicio presencial)

```bash
sudo pacman -S sbctl
sudo sbctl create-keys
sudo sbctl enroll-keys --microsoft   # sólo si hay opción ROM/GPU que lo exija
sudo sbctl sign -s /boot/EFI/Linux/omarchy_linux-omarchy.efi
sudo sbctl verify
```

Antes: poner el firmware en *Setup Mode* y confirmar que Limine/UKI arranca con
las claves propias. Mal ejecutado puede dejar el equipo sin arranque: tener un
medio de recuperación a mano.

### 7.3 Rotación de credenciales expuestas

| Credencial | Ubicación | Acción |
|---|---|---|
| Telegram Bot Token | `telegram_config.json` (0600) | Revocar en @BotFather y emitir uno nuevo |
| GitHub PAT `ghp_E5Q…` | Historia de `data/ftl_backlog.json` | Revocar en GitHub → Settings → Tokens |
| `akashic_secret.key` | Historia de Git + disco | **No rotar a ciegas**: cifra la bóveda de chats; evaluar re-sellado |
| `gia-codesign.pfx` | Historia de Git | Revocar certificado y emitir uno nuevo |

### 7.4 Purga de la historia de Git (destructiva, decidir con copia de seguridad)

```bash
# Copia de seguridad completa primero
git bundle create /media/backup/godworks-pre-purge.bundle --all

# Requiere git-filter-repo
git filter-repo --invert-paths \
  --path data/ftl_backlog.json \
  --path akashic_secret.key \
  --path installer-assets/codesign/gia-codesign.pfx \
  --path data/offline_chats.db \
  --path gia_akashic.db

git push --force --all && git push --force --tags
```

Tras la purga: invalidar clones antiguos, rotar todas las credenciales
afectadas (la historia puede estar replicada en forks, cachés de CI y discos).

---

## 8. Integración continua y operación diaria

```bash
# Antes de cada sesión de trabajo
aegis status

# Tras cambios sensibles
aegis scan && aegis audit

# Antes de publicar
aegis verify --deep

# Semanal
aegis export-chain ~/respaldos/cadena-$(date +%F).jsonl
cp ~/.aegis/ledger.anchor /media/respaldo/
```

### Pruebas

```bash
.venv-linux/bin/python3 -m pytest tests/test_aegis.py -q
```

30 pruebas cubren: ida y vuelta de cifrado, detección de manipulación,
encadenamiento del ledger, clasificación C0–C4, redacción, entropía, políticas
de permisos, endurecimiento y CLI.

---

## 9. Limitaciones declaradas

1. **No hay cifrado en uso (RAM).** La clave maestra está en memoria mientras
   el proceso corre; un volcado de memoria privilegiado puede obtenerla.
2. **El ledger no es inmutable.** Es *tamper-evident*: detecta alteraciones,
   no las impide. Copie el ancla fuera del equipo.
3. **El borrado seguro no es absoluto** en SSD/NVMe ni en Btrfs con snapshots.
4. **GIA sigue escuchando en `0.0.0.0`** por diseño (terminal móvil en LAN).
   La mitigación es firewall + token, no el binding.
5. **Secure Boot y AppArmor** no están activos hasta reiniciar; se declaran
   como pendientes, no como logros.
6. **AEGIS no sustituye** una política de respaldos, gestión de identidades ni
   respuesta a incidentes.

---

## 10. Referencia rápida

```text
aegis status | audit | report | verify [--deep] | export-chain
aegis seal <ruta> [--shred-source] | unseal <contenedor> [-o salida]
aegis vault put|get|ls|rm
aegis scan [--staged] [--no-pii]
aegis harden [--apply] [--aggressive]
aegis key [--recovery|--passwd|--unwrap]
aegis shred <ruta> [--passes N]
aegis watch [--once|--interval S]
aegis baseline [rutas]
aegis panic [--reason TEXTO] [--offline] [--poweroff]
aegis install            # unidades systemd + hook + symlink
```

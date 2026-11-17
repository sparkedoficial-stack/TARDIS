"""
core/aegis/cli.py — Interfaz de mando de AEGIS-Ω.
=================================================
Ejecutable canónico: `aegis` (bin/aegis → python -m core.aegis.cli).

Comandos:
    status      Postura, custodia y ledger.
    audit       Auditoría completa (permisos, secretos, kernel, red).
    seal        Cifra archivos/directorios a contenedores .aegis.
    unseal      Descifra y verifica un contenedor.
    verify      Verifica ledger, anclas y hashes de contenedores.
    scan        Detección de credenciales/PII (archivos o staged de Git).
    harden      Aplica la línea base de kernel/auditd/core dumps.
    key         Huella, passphrase, kit de recuperación.
    shred       Destrucción multi-pasada.
    vault       Bóveda cifrada de objetos (put/get/ls/rm).
    watch       Vigilancia continua con alertas.
    baseline    Sella hashes de archivos críticos en el ledger.
    panic       Protocolo de emergencia.
    install     Servicio systemd + gancho pre-commit + symlink.
    report      Regenera el panel HTML.
    export-chain Exporta la cadena de custodia.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import CODENAME, __version__
from .antiforensic import shred_path
from .classifier import LEVELS, Severity, classify_path
from .engine import AegisEngine, get_engine

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GOLD = "\033[38;5;220m"
RED = "\033[38;5;203m"
GREEN = "\033[38;5;114m"
CYAN = "\033[38;5;81m"
YELLOW = "\033[38;5;221m"
ORANGE = "\033[38;5;209m"


def _c(text: str, color: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"{color}{text}{RESET}"


def _banner() -> None:
    print(
        _c(
            r"""
   ▄▄▄       ▓█████  ▄████  ██▓  ██████        ▐██▌
  ▒████▄     ▓█   ▀ ██▒ ▀█▒▓██▒▒██    ▒        ▐██▌
  ▒██  ▀█▄   ▒███  ▒██░▄▄▄░▒██▒░ ▓██▄          ▐██▌
  ░██▄▄▄▄██  ▒▓█  ▄ ░▓█  ██▓░██░  ▒   ██▒     ▓██▒
   ▓█   ▓██▒ ░▒████▒░▒▓███▀▒░██░▒██████▒▒     ▒▄▄
""",
            GOLD,
        )
    )
    print(_c(f"  AEGIS-Ω v{__version__} · SISTEMA DE BLINDAJE MILITAR DE INFORMACIÓN", BOLD))
    print(_c("  GODWORKS SYSTEM v26.4 · LA CONSTANTE AEGIS\n", DIM))


def _sev_color(label: str) -> str:
    return {
        "crítico": RED,
        "alto": ORANGE,
        "medio": YELLOW,
        "bajo": CYAN,
        "info": DIM,
    }.get(label, DIM)


def _print_findings(findings: Sequence[Dict[str, Any]], limit: int = 25) -> None:
    for f in findings[:limit]:
        color = _sev_color(str(f.get("severity", "")))
        flag = _c("✔", GREEN) if f.get("fixed") else _c("✖", color)
        print(f"  {flag} {_c(f'[{str(f.get('severity','')).upper()}]', color)} {f.get('title')}")
        print(f"      {_c(str(f.get('path')), DIM)}")
        if f.get("detail"):
            print(f"      {_c(str(f.get('detail'))[:180], DIM)}")
        if f.get("remediation"):
            print(f"      {_c('→ ' + str(f.get('remediation'))[:160], CYAN)}")
    if len(findings) > limit:
        print(_c(f"  … {len(findings) - limit} hallazgos adicionales en el informe.", DIM))


def _dump(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    engine: AegisEngine = args.engine
    status = engine.status()
    if args.json:
        _dump(status)
        return 0
    _banner()
    key = status["key"]
    ledger = status["ledger"]
    print(f"  {_c('PERÍMETRO', GOLD)}      {status['home']}")
    print(f"  {_c('PROYECTO', GOLD)}       {status['project_root']}")
    print(f"  {_c('CLAVE MAESTRA', GOLD)}  {_c(key['fingerprint'], CYAN)}  {_c(key['mode'], DIM)}")
    print(
        f"  {_c('PASSPHRASE', GOLD)}     "
        + (_c("ENVOLTURA PRESENTE", GREEN) if key["passphrase_wrapped"] else _c("SIN ENVOLTURA", YELLOW))
    )
    ledger_state = _c("ÍNTEGRO", GREEN) if ledger["ok"] else _c("COMPROMETIDO", RED)
    print(f"  {_c('LEDGER', GOLD)}         {ledger_state} · {ledger['entries']} eventos · ancla {'OK' if ledger['anchor_ok'] else 'FALLA'}")
    print(f"  {_c('SELLADOS', GOLD)}       {status['sealed_files']} archivos · {status['sealed_bytes'] / 1048576:.1f} MiB")
    print(f"  {_c('BÓVEDA', GOLD)}         {status['vault_objects']} objetos cifrados")
    last = status.get("last_audit") or {}
    if last:
        score = int(last.get("score", 0))
        color = GREEN if score >= 85 else YELLOW if score >= 65 else ORANGE if score >= 40 else RED
        print(f"  {_c('ÚLTIMA AUDITORÍA', GOLD)} {_c(str(score) + '/100', color)} · {last.get('counts')}")
    else:
        print(_c("  Sin auditorías registradas. Ejecuta: aegis audit", DIM))
    print()
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    engine: AegisEngine = args.engine
    payload = engine.audit(
        root=Path(args.root) if args.root else None,
        deep=not args.quick,
        fix=args.fix,
        fix_git=args.fix_git,
    )
    if args.json:
        _dump(payload)
        return 0 if payload["counts"].get("crítico", 0) == 0 else 1
    _banner()
    score = int(payload["score"])
    color = GREEN if score >= 85 else YELLOW if score >= 65 else ORANGE if score >= 40 else RED
    print(f"  {_c('POSTURA DE BLINDAJE', BOLD)}  {_c(str(score) + '/100', color)}")
    print(f"  {_c('RAÍZ', GOLD)}  {payload['root']}")
    counts = payload["counts"]
    print(
        "  "
        + "  ".join(
            _c(f"{k.upper()}: {v}", _sev_color(k)) for k, v in counts.items()
        )
    )
    print(f"  Archivos auditados: {payload['policy']['scanned_files']:,}")
    print()
    findings = payload["policy"]["findings"] + payload["hardening"]["findings"]
    _print_findings(findings, limit=args.limit)
    print()
    print(_c(f"  Informe HTML: {payload['report_html']}", DIM))
    print(_c(f"  Informe JSON: {payload['report_json']}", DIM))
    return 0 if counts["crítico"] == 0 else 1


def cmd_seal(args: argparse.Namespace) -> int:
    engine: AegisEngine = args.engine
    payload = engine.seal(
        [Path(p) for p in args.paths],
        shred_source=args.shred_source,
        force=args.force,
    )
    if args.json:
        _dump(payload)
        return 0 if payload["ok"] else 1
    for rec in payload["sealed"]:
        print(
            f"  {_c('SELLADO', GREEN)} {rec['level']} {rec['path']} → {_c(rec['container'], CYAN)} "
            f"({rec['size'] / 1024:.1f} KiB)"
        )
    for err in payload["errors"]:
        print(f"  {_c('ERROR', RED)} {err}")
    if payload["sealed"] and not args.shred_source:
        print(_c("\n  El origen permanece en claro. Usa --shred-source para destruirlo.", DIM))
    return 0 if payload["ok"] else 1


def cmd_unseal(args: argparse.Namespace) -> int:
    payload = args.engine.unseal(args.container, output=args.output, overwrite=args.overwrite)
    if args.json:
        _dump(payload)
        return 0 if payload.get("ok") else 1
    if payload.get("ok"):
        print(f"  {_c('RESTAURADO', GREEN)} {payload['output']} ({payload['meta']['size']} bytes)")
        print(f"  SHA-256 claro: {_c(payload['meta']['plaintext_sha256'], CYAN)}")
        return 0
    print(f"  {_c('FALLO', RED)} {payload.get('error')}")
    return 1


def cmd_verify(args: argparse.Namespace) -> int:
    payload = args.engine.verify(deep=args.deep)
    if args.json:
        _dump(payload)
        return 0 if payload["ok"] else 1
    ledger = payload["ledger"]
    ok = payload["ok"]
    print(f"  {_c('CADENA DE CUSTODIA', GOLD)}  " + (_c("ÍNTEGRA", GREEN) if ledger["ok"] else _c("ALTERADA", RED)))
    print(f"  Eventos: {ledger['entries']} · head {ledger['head'][:16]}…")
    print(f"  Contenedores verificados: {payload['checked']}/{payload['manifests']}")
    for item in payload["tampered"]:
        print(f"  {_c('ALTERADO', RED)} {item['container']} · {item['reason']}")
    for item in payload["missing"]:
        print(f"  {_c('FALTANTE', ORANGE)} {item}")
    if args.quiet and ok:
        return 0
    print()
    print(_c("  VEREDICTO: " + ("BLINDAJE ÍNTEGRO" if ok else "INTERVENCIÓN REQUERIDA"), GREEN if ok else RED))
    return 0 if ok else 1


def cmd_scan(args: argparse.Namespace) -> int:
    engine: AegisEngine = args.engine
    if args.staged:
        payload = engine.scan_staged()
        code = 0 if payload["ok"] else 1
    else:
        if not args.paths:
            print(_c("  Especifica al menos una ruta (o --staged).", RED), file=sys.stderr)
            return 2
        payload = engine.scan([Path(p) for p in args.paths], include_pii=not args.no_pii)
        code = 0 if payload["ok"] else 1
    if args.json:
        _dump(payload)
        return code
    if payload["findings"]:
        print(_c(f"  {len(payload['findings'])} hallazgo(s) en {payload['scanned']} archivo(s):", RED))
        for hit in payload["findings"][:40]:
            print(
                f"  {_c('•', RED)} {hit['severity'].upper():9} {hit['kind']}  "
                f"{_c(hit['path'], DIM)}:{hit['line']}  {_c(hit['preview'], CYAN)}"
            )
    else:
        print(_c(f"  Limpio: {payload['scanned']} archivo(s) sin credenciales detectadas.", GREEN))
    return code


def cmd_harden(args: argparse.Namespace) -> int:
    payload = args.engine.harden(apply=args.apply, aggressive=args.aggressive)
    if args.json:
        _dump(payload)
        return 0
    applied = payload.get("applied", [])
    failed = payload.get("failed", [])
    if applied:
        print(_c("  APLICADO", GREEN))
        for item in applied:
            print(f"    ✔ {item}")
    if failed:
        print(_c("  FALLOS", RED))
        for item in failed:
            print(f"    ✖ {item}")
    findings = payload.get("findings", [])
    if findings:
        print(_c(f"\n  {len(findings)} parámetro(s)/control(es) pendientes:", YELLOW))
        _print_findings(findings, limit=20)
    else:
        print(_c("  Línea base completa: kernel, auditd, firewall y disco.", GREEN))
    return 0


def cmd_key(args: argparse.Namespace) -> int:
    engine: AegisEngine = args.engine
    keyring = engine.keyring
    if args.recovery:
        out = Path(args.recovery_out).expanduser() if args.recovery_out else None
        path, code = keyring.create_recovery_kit(out)
        print(_c("  KIT DE RECUPERACIÓN CREADO", GREEN))
        print(f"  Archivo: {path} (modo 0400)")
        print(f"  Código (guárdalo FUERA de esta máquina, no se volverá a mostrar):")
        print(f"  {_c(code, GOLD)}")
        return 0
    if args.unwrap:
        code = args.unwrap
        if code == "-":
            code = getpass.getpass("Código de recuperación: ")
        payload = engine.recover_key(code)
        print(f"  Huella recuperada: {_c(payload['fingerprint'], CYAN)}")
        return 0
    if args.passwd:
        first = getpass.getpass("Nueva passphrase maestra (mín. 12): ")
        second = getpass.getpass("Repite la passphrase: ")
        if first != second:
            print(_c("  Las passphrases no coinciden.", RED))
            return 1
        try:
            blob = keyring.wrap_with_passphrase(first)
        except Exception as exc:
            print(f"  {_c('FALLO', RED)} {type(exc).__name__}: {exc}")
            return 1
        print(_c("  ENVOLTURA CREADA", GREEN))
        print(f"  Archivo: {keyring.pass_path}")
        print(f"  Huella: {blob['fingerprint']}")
        return 0
    info = keyring.info()
    payload = {
        "fingerprint": info.fingerprint,
        "path": info.path,
        "mode": oct(info.mode),
        "passphrase_wrapped": keyring.pass_path.exists(),
        "recovery_kit": keyring.recovery_path.exists(),
    }
    if args.json:
        _dump(payload)
    else:
        print(f"  Huella maestra: {_c(info.fingerprint, CYAN)}")
        print(f"  Ruta: {info.path}  modo {oct(info.mode)}")
        print(f"  Envoltura passphrase: {'sí' if payload['passphrase_wrapped'] else 'no'}")
        print(f"  Kit de recuperación: {'sí' if payload['recovery_kit'] else 'no'}")
    return 0


def cmd_shred(args: argparse.Namespace) -> int:
    if not args.paths:
        print(_c("  Indica rutas para destruir.", RED))
        return 2
    results = []
    for raw in args.paths:
        p = Path(raw).expanduser()
        if p.is_dir() and not args.force:
            print(f"  {_c('RECHAZADO', ORANGE)} {p} es un directorio; usa --force")
            continue
        results.append(shred_path(p, passes=args.passes))
    if args.json:
        _dump(results)
    for res in results:
        if res.get("ok"):
            print(f"  {_c('DESTRUIDO', GREEN)} {res['path']} ({res.get('bytes', res.get('files_removed', 0))})")
        else:
            print(f"  {_c('ERROR', RED)} {res.get('path')}: {res.get('error') or res.get('errors')}")
    return 0 if all(r.get("ok") for r in results) else 1


def cmd_vault(args: argparse.Namespace) -> int:
    engine: AegisEngine = args.engine
    if args.action == "put":
        payload = engine.vault_put(Path(args.source), name=args.name)
    elif args.action == "get":
        payload = engine.vault_get(args.name, output=args.output)
    elif args.action == "ls":
        items = engine.vault_list()
        if args.json:
            _dump(items)
        else:
            if not items:
                print(_c("  Bóveda vacía.", DIM))
            for item in items:
                print(
                    f"  {_c('•', GOLD)} {item['name']}  "
                    f"{int(item.get('size', 0)) / 1024:.1f} KiB  {_c(item.get('sha256', '')[:16], CYAN)}…"
                )
        return 0
    elif args.action == "rm":
        payload = engine.vault_rm(args.name, shred=not args.keep)
    else:
        print(_c("  Acción de bóveda no válida.", RED))
        return 2
    if args.json:
        _dump(payload)
    elif payload.get("ok"):
        print(f"  {_c('OK', GREEN)} {payload}")
    else:
        print(f"  {_c('FALLO', RED)} {payload.get('error')}")
    return 0 if payload.get("ok") else 1


def cmd_watch(args: argparse.Namespace) -> int:
    engine: AegisEngine = args.engine
    if args.once:
        payload = engine.watch_once()
        if args.json:
            _dump(payload)
        else:
            state = _c("ÍNTEGRO", GREEN) if payload["ledger_ok"] else _c("ALTERADO", RED)
            print(f"  Ledger {state} · {payload['findings']} hallazgos · {len(payload['critical'])} críticos")
        return 0 if payload["ledger_ok"] and not payload["critical"] else 1
    try:
        engine.watch(interval=args.interval)
    except KeyboardInterrupt:
        print(_c("\n  Vigilancia detenida.", DIM))
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    payload = args.engine.baseline([Path(p) for p in args.paths] if args.paths else None)
    if args.json:
        _dump(payload)
    else:
        for entry in payload["entries"]:
            print(f"  {_c('SELLADO', GREEN)} {entry['path']}  {_c(entry['sha256'][:24] + '…', CYAN)}")
    return 0


def cmd_panic(args: argparse.Namespace) -> int:
    payload = args.engine.panic(reason=args.reason, poweroff=args.poweroff, offline=args.offline)
    if args.json:
        _dump(payload)
    else:
        print(_c("  PROTOCOLO DE PÁNICO EJECUTADO", RED))
        for action in payload["actions"]:
            print(f"    ✔ {action}")
        for failed in payload["failed"]:
            print(f"    ✖ {failed}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    engine: AegisEngine = args.engine
    payload = engine.install_services()
    target = Path("/usr/local/bin/aegis")
    source = engine.project_root / "bin" / "aegis"
    try:
        if source.exists():
            subprocess.run(
                ["sudo", "-n", "ln", "-sf", str(source), str(target)],
                capture_output=True,
                check=False,
                timeout=20,
            )
            payload["symlink"] = str(target)
    except (OSError, subprocess.SubprocessError):
        payload["symlink_error"] = "no se pudo crear el enlace"
    if args.json:
        _dump(payload)
    else:
        print(_c("  INSTALACIÓN COMPLETA", GREEN))
        print(f"    Servicio: {payload['service']}")
        print(f"    Timer:    {payload['timer']}")
        print(f"    Hook:     {payload['git_hook']}")
        print(f"    Binario:  {payload.get('symlink', '—')}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    payload = args.engine.audit(deep=False)
    print(f"  Panel generado: {_c(payload['report_html'], CYAN)}")
    if args.open and shutil.which("xdg-open"):
        subprocess.Popen(
            ["xdg-open", payload["report_html"]],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    path = args.engine.export_chain(Path(args.output))
    print(f"  Cadena exportada: {_c(path, CYAN)}")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegis",
        description="AEGIS-Ω · Sistema de Blindaje Militar de Información (GODWORKS v26.4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"AEGIS-Ω {__version__}")
    parser.add_argument("--home", help="perímetro de custodia (AEGIS_HOME)")
    parser.add_argument("--project", help="raíz del proyecto a auditar")
    subs = parser.add_subparsers(dest="command", required=True)

    p = subs.add_parser("status", help="postura y custodia")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = subs.add_parser("audit", help="auditoría completa")
    p.add_argument("--root")
    p.add_argument("--quick", action="store_true", help="sin inspección de contenido ni Git")
    p.add_argument("--fix", action="store_true", help="corregir permisos automáticamente")
    p.add_argument("--fix-git", action="store_true", help="expulsar secretos del índice Git")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_audit)

    p = subs.add_parser("seal", help="cifrar archivos/directorios")
    p.add_argument("paths", nargs="+")
    p.add_argument("--shred-source", action="store_true", help="destruir el original tras cifrar")
    p.add_argument("--force", action="store_true", help="sobrescribir contenedor existente")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_seal)

    p = subs.add_parser("unseal", help="descifrar contenedor .aegis")
    p.add_argument("container")
    p.add_argument("--output", "-o")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_unseal)

    p = subs.add_parser("verify", help="verificar ledger y contenedores")
    p.add_argument("--deep", action="store_true", help="descifrar y comparar contenido")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = subs.add_parser("scan", help="detectar credenciales y PII")
    p.add_argument("paths", nargs="*")
    p.add_argument("--staged", action="store_true", help="sólo archivos en el índice Git")
    p.add_argument("--no-pii", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scan)

    p = subs.add_parser("harden", help="endurecer kernel/auditd/core dumps")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--aggressive", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_harden)

    p = subs.add_parser("key", help="custodia de la clave maestra")
    p.add_argument("--recovery", action="store_true", help="crear kit de recuperación")
    p.add_argument("--recovery-out")
    p.add_argument("--unwrap", nargs="?", const="-", help="código de recuperación ('-' para prompt)")
    p.add_argument("--passwd", action="store_true", help="envolver con passphrase")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_key)

    p = subs.add_parser("shred", help="borrado seguro multi-pasada")
    p.add_argument("paths", nargs="+")
    p.add_argument("--passes", type=int, default=3)
    p.add_argument("--force", action="store_true", help="permitir directorios")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_shred)

    p = subs.add_parser("vault", help="bóveda cifrada de objetos")
    p.add_argument("action", choices=["put", "get", "ls", "rm"])
    p.add_argument("source", nargs="?", help="archivo origen (put)")
    p.add_argument("--name", help="nombre lógico del objeto")
    p.add_argument("--output", "-o")
    p.add_argument("--keep", action="store_true", help="no destruir el objeto al eliminar")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_vault)

    p = subs.add_parser("watch", help="vigilancia continua")
    p.add_argument("--once", action="store_true")
    p.add_argument("--interval", type=int, default=300)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_watch)

    p = subs.add_parser("baseline", help="sellar hashes críticos")
    p.add_argument("paths", nargs="*")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_baseline)

    p = subs.add_parser("panic", help="protocolo de emergencia")
    p.add_argument("--reason", default="protocolo de pánico")
    p.add_argument("--poweroff", action="store_true")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_panic)

    p = subs.add_parser("install", help="servicio systemd + hook + symlink")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_install)

    p = subs.add_parser("report", help="regenerar panel HTML")
    p.add_argument("--open", action="store_true")
    p.set_defaults(func=cmd_report)

    p = subs.add_parser("export-chain", help="exportar cadena de custodia")
    p.add_argument("output")
    p.set_defaults(func=cmd_export)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    engine = AegisEngine(
        home=Path(args.home) if args.home else None,
        project_root=Path(args.project) if args.project else None,
    )
    args.engine = engine
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
    except Exception as exc:
        print(f"{CODENAME}: error interno · {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

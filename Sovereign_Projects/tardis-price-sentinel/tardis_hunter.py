#!/usr/bin/env python3
"""
TARDIS Syntropic Price Sentinel & Deal Oracle - Sovereign CLI
Commands: scan, glitches, search, coupons, stack, watch, monitor, serve, status
"""

import sys
import os
import argparse
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from core.storage import Storage
from core.models import Deal, WatchItem
from core.detector import SyntropicDetector
from core.banking import BankingEngine
from core.notifier import Notifier
from scrapers.aggregator import DealAggregator
from sentinel.daemon import SentinelDaemon

console = Console()


def print_banner():
    banner = """
    ╔════════════════════════════════════════════════════════════════════╗
    ║  ₪ TARDIS :: CAZADOR SOBERANO DE PRECIOS BAJOS & GLITCH ORACLE     ║
    ║  Vigilancia Sintrópica Multitienda • 100% Ético & Legítimo • v1.0 ║
    ╚════════════════════════════════════════════════════════════════════╝
    """
    console.print(f"[bold cyan]{banner}[/bold cyan]")


from core.validity import ValidityEngine


def cmd_scan(args):
    console.print("[bold yellow]⚡ Iniciando barrido multitienda de OFERTAS VIGENTES (Promodescuentos, Mercado Libre, Liquidaciones)...[/bold yellow]")
    storage = Storage()
    notifier = Notifier()
    aggregator = DealAggregator(storage=storage, notifier=notifier)

    res = aggregator.scan_all()
    console.print(f"[bold green]✔ Barrido completado:[/bold green] {res['total_collected']} vigentes analizadas | {res['new_deals']} nuevas | {res['glitches_detected']} glitches vigentes | {res.get('purged_expired', 0)} expiradas depuradas")

    # Display top deals
    deals = storage.list_deals(limit=12, include_expired=False, sort_by="syntropy_score")
    display_deals_table(deals, "Top Ofertas Vigentes por Nivel de Sintropía")


def cmd_glitches(args):
    console.print("[bold red]🚨 Rastreando errores de precio y glitches VIGENTES en tiempo real...[/bold red]")
    storage = Storage()
    glitches = storage.list_deals(is_glitch=True, include_expired=False, limit=15, sort_by="syntropy_score")
    if not glitches:
        # Run live scan for glitches
        aggregator = DealAggregator(storage=storage)
        raw_glitches = aggregator.pd_scraper.fetch_glitches_and_errors()
        glitches = [g for g in raw_glitches if ValidityEngine.is_vigente(g) and not g.expired][:15]

    display_deals_table(glitches, "🚨 Radar de Errores de Precio & Glitches VIGENTES")


def cmd_search(args):
    query = " ".join(args.query)
    console.print(f"[bold cyan]🔍 Analizando arbitraje de precios para:[/bold cyan] '[bold white]{query}[/bold white]'...")

    storage = Storage()
    aggregator = DealAggregator(storage=storage)
    res = aggregator.search_arbitrage(query)

    if res["found"] == 0:
        console.print(f"[yellow]No se encontraron ofertas activas para '{query}'.[/yellow]")
        return

    # Print summary panel
    summary_text = (
        f"🏷️ [bold]Mejor Precio:[/bold] [bold cyan]${res['lowest_price']:,.2f}[/bold cyan] en [bold green]{res['best_store']}[/bold green]\n"
        f"📈 [bold]Precio Máximo Observado:[/bold] ${res['highest_price']:,.2f}\n"
        f"💰 [bold]Ahorro Potencial:[/bold] [bold green]${res['max_savings']:,.2f} ({res['savings_pct']}%) [/bold green]"
    )
    console.print(Panel(summary_text, title="⚖️ Resumen de Arbitraje Intertienda", border_style="cyan"))

    table = Table(title=f"Publicaciones Encontradas para '{query}'")
    table.add_column("Rank", style="cyan", width=6)
    table.add_column("Tienda", style="green", width=16)
    table.add_column("Título", style="white", min_width=30)
    table.add_column("Precio", style="bold cyan", width=14)
    table.add_column("Descuento", style="yellow", width=12)
    table.add_column("Enlace", style="blue")

    for idx, off in enumerate(res["offers"][:15], 1):
        disc = f"-{off['discount_percent']}%" if off['discount_percent'] > 0 else "Normal"
        table.add_row(
            f"#{idx}",
            off["merchant"],
            off["title"][:50],
            f"${off['price']:,.2f}",
            disc,
            off["link"][:55] + "..." if len(off["link"]) > 55 else off["link"]
        )
    console.print(table)


def cmd_coupons(args):
    console.print("[bold yellow]💳 Matriz de Bonificaciones Bancarias Activas en México:[/bold yellow]")
    table = Table(title="Bonificaciones Bancarias y Reembolsos")
    table.add_column("Banco / Tarjeta", style="cyan", width=22)
    table.add_column("Tasa", style="bold green", width=10)
    table.add_column("Min. Compra", style="yellow", width=14)
    table.add_column("Descripción y Condiciones", style="white")

    for p in BankingEngine.get_promos():
        table.add_row(
            p.bank_name,
            f"{int(p.discount_rate * 100)}% OFF",
            f"${p.min_purchase:,.2f}",
            p.description
        )
    console.print(table)

    storage = Storage()
    vouchers = [d for d in storage.list_deals(limit=50) if d.voucher_code]
    if vouchers:
        console.print("\n[bold cyan]🎟️ Cupones de Tienda Descubiertos en Vivo:[/bold cyan]")
        v_table = Table()
        v_table.add_column("Tienda", style="green", width=16)
        v_table.add_column("Código", style="bold cyan", width=16)
        v_table.add_column("Oferta", style="white")
        for v in vouchers[:10]:
            v_table.add_row(v.merchant, v.voucher_code, v.title[:60])
        console.print(v_table)


def cmd_stack(args):
    price = args.price
    coupon_pct = args.coupon or 0.0
    bank = args.bank

    res = BankingEngine.calculate_stacking(
        base_price=price,
        coupon_percent=coupon_pct,
        bank_name=bank
    )

    text = (
        f"💵 [bold]Precio Base:[/bold] ${res['original_price']:,.2f}\n"
        f"🎟️ [bold]Precio tras Cupón (-{coupon_pct}%):[/bold] ${res['coupon_effective_price']:,.2f}\n"
        f"🏦 [bold]Bonificación Aplicada:[/bold] {res['bank_promo']} (-${res['bank_bonus_amount']:,.2f})\n"
        f"🎯 [bold green]PRECIO EFECTIVO FINAL:[/bold green] [bold cyan]${res['final_effective_price']:,.2f}[/bold cyan]\n"
        f"⚡ [bold yellow]AHORRO TOTAL COMBINADO:[/bold yellow] [bold green]${res['total_savings']:,.2f} ({res['total_savings_pct']}%) [/bold green]"
    )
    console.print(Panel(text, title="⚡ Simulación de Stacking Multicapa", border_style="green"))


def cmd_watch(args):
    storage = Storage()
    if args.watch_action == "list":
        items = storage.list_watchlist()
        if not items:
            console.print("[yellow]Tu watchlist está vacía. Usa: tardis-hunter watch add <keyword>[/yellow]")
            return

        table = Table(title="🎯 Artículos Monitoreados en Watchlist")
        table.add_column("ID", style="cyan", width=6)
        table.add_column("Palabra Clave", style="bold white", width=22)
        table.add_column("Precio Máximo", style="green", width=14)
        table.add_column("Desc. Mínimo", style="yellow", width=14)
        table.add_column("Último Match", style="blue")

        for it in items:
            table.add_row(
                str(it.id),
                it.keyword,
                f"${it.max_price:,.2f}" if it.max_price else "Cualquiera",
                f"{it.min_discount}%" if it.min_discount else "Cualquiera",
                it.last_matched_at or "Pendiente"
            )
        console.print(table)

    elif args.watch_action == "add":
        item = WatchItem(
            keyword=args.keyword,
            max_price=args.max_price,
            min_discount=args.min_discount
        )
        new_id = storage.add_watch_item(item)
        console.print(f"[bold green]✔ Alerta registrada exitosamente con ID #{new_id}:[/bold green] '{args.keyword}'")

    elif args.watch_action == "remove":
        ok = storage.delete_watch_item(args.id)
        if ok:
            console.print(f"[green]✔ Alerta #{args.id} eliminada correctamente.[/green]")
        else:
            console.print(f"[red]Error: Alerta #{args.id} no encontrada.[/red]")


def cmd_monitor(args):
    console.print("[bold green]🛡️ Iniciando Centinela TARDIS en Modo Continuo (Presiona Ctrl+C para salir)...[/bold green]")
    daemon = SentinelDaemon()
    daemon.interval = args.interval or 300
    try:
        daemon.run_loop()
    except KeyboardInterrupt:
        daemon.stop()
        console.print("\n[yellow]Centinela detenido con éxito.[/yellow]")


def cmd_serve(args):
    import uvicorn
    from web.app import app
    host = args.host or "127.0.0.1"
    port = args.port or 8787
    console.print(f"[bold cyan]🚀 Desplegando Dashboard Web en http://localhost:{port}[/bold cyan]")
    uvicorn.run(app, host=host, port=port)


def cmd_audit(args):
    console.print("[bold yellow]🧹 Iniciando auditoría sintrópica de vigencia sobre la base de datos...[/bold yellow]")
    storage = Storage()
    res = ValidityEngine.audit_and_purge_expired(storage, verify_live=args.live)
    console.print(f"[bold green]✔ Auditoría completada:[/bold green] {res['total_audited']} ofertas analizadas | [bold red]{res['marked_expired']} marcadas como expiradas[/bold red] | [bold cyan]{res['active_vigentes']} ofertas vigentes activas[/bold cyan]")


def cmd_status(args):
    storage = Storage()
    stats = storage.get_stats()
    daemon = SentinelDaemon()
    d_status = daemon.get_status()

    info = (
        f"📊 [bold]Ofertas Vigentes Activas:[/bold] [bold cyan]{stats['total_deals']:,}[/bold cyan] (Histórico total: {stats.get('all_time_history', stats['total_deals']):,})\n"
        f"🚨 [bold]Errores de Precio Vigentes:[/bold] [bold red]{stats['active_glitches']:,}[/bold red]\n"
        f"🎁 [bold]Artículos 100% Gratis Vigentes:[/bold] [bold green]{stats['active_free']:,}[/bold green]\n"
        f"🏬 [bold]Tiendas Registradas:[/bold] {stats['merchants_count']}\n"
        f"🎯 [bold]Alertas Activas en Watchlist:[/bold] {stats['active_watches']}\n"
        f"🤖 [bold]Estado del Demonio Centinela:[/bold] {d_status.get('state', 'inactivo').upper()} ({d_status.get('message', '')})"
    )
    console.print(Panel(info, title="📡 Telemetría y Estado de TARDIS Deal Oracle (Solo Vigentes)", border_style="cyan"))


def display_deals_table(deals, title: str):
    if not deals:
        console.print("[yellow]No hay ofertas para mostrar.[/yellow]")
        return

    table = Table(title=title)
    table.add_column("Score", style="cyan", width=6)
    table.add_column("Tienda", style="green", width=15)
    table.add_column("Título", style="white", min_width=32)
    table.add_column("Precio", style="bold cyan", width=12)
    table.add_column("Desc.", style="bold yellow", width=10)
    table.add_column("Tipo / Notas", style="magenta", width=22)

    for d in deals:
        price_str = "GRATIS" if d.is_free or d.price <= 0 else f"${d.price:,.2f}"
        disc_str = f"-{d.discount_percent}%" if d.discount_percent > 0 else ""
        type_str = "🚨 GLITCH" if d.is_glitch else ("FASE .0" + str(d.liquidation_phase) if d.liquidation_phase > 0 else "")
        if d.voucher_code:
            type_str += f" | 🎟️ {d.voucher_code}"

        table.add_row(
            str(int(d.syntropy_score)),
            d.merchant[:14],
            d.title[:45],
            price_str,
            disc_str,
            type_str[:22]
        )
    console.print(table)


def cmd_gui(args):
    console.print("[bold green]🚀 Iniciando Interfaz de Escritorio Local TARDIS...[/bold green]")
    from tardis_deals_gui import main as gui_main
    gui_main()


def cmd_cart(args):
    target = args.id_or_url
    storage = Storage()
    deal = storage.get_deal(target)
    from core.cart_resolver import CartResolver
    if deal:
        console.print(f"[bold cyan]🛒 Resolviendo carrito para:[/bold cyan] {deal.title} ({deal.merchant})...")
        res = CartResolver.resolve(deal.link, deal.merchant, deal.title)
    else:
        console.print(f"[bold cyan]🛒 Resolviendo enlace:[/bold cyan] {target}...")
        res = CartResolver.resolve(target)

    console.print(f"[bold green]✔ Carrito:[/bold green] [underline]{res['cart_url']}[/underline]")
    console.print(f"[bold yellow]⚡ Acción:[/bold yellow] {res['action_name']}")
    console.print("[bold cyan]🚀 Abriendo navegador del sistema en el carrito de compra...[/bold cyan]")
    CartResolver.open_in_browser(res["cart_url"])


def main():
    parser = argparse.ArgumentParser(description="TARDIS Syntropic Price Sentinel & Deal Oracle")
    subparsers = parser.add_subparsers(dest="command", help="Comandos disponibles")

    # gui
    subparsers.add_parser("gui", help="Inicia la interfaz gráfica de escritorio local")

    # cart
    p_cart = subparsers.add_parser("cart", help="Abre una oferta directamente en el carrito de compra")
    p_cart.add_argument("id_or_url", help="ID de la oferta o URL del producto")

    # scan
    subparsers.add_parser("scan", help="Ejecuta un barrido inmediato multitienda")

    # glitches
    subparsers.add_parser("glitches", help="Muestra errores de precio y liquidaciones activas")

    # search
    p_search = subparsers.add_parser("search", help="Busca un producto y compara precios entre tiendas")
    p_search.add_argument("query", nargs="+", help="Término a buscar (ej: RTX 4060)")

    # coupons
    subparsers.add_parser("coupons", help="Muestra cupones y promociones bancarias")

    # stack
    p_stack = subparsers.add_parser("stack", help="Calcula el precio final con cupón y bonificación bancaria")
    p_stack.add_argument("price", type=float, help="Precio original en tienda")
    p_stack.add_argument("--coupon", type=float, help="Porcentaje de descuento de cupón", default=0.0)
    p_stack.add_argument("--bank", type=str, help="Nombre del banco participante", default=None)

    # watch
    p_watch = subparsers.add_parser("watch", help="Administra la lista de vigilancia de alertas")
    w_sub = p_watch.add_subparsers(dest="watch_action", help="Acción de watch")
    w_sub.add_parser("list", help="Lista alertas activas")

    p_w_add = w_sub.add_parser("add", help="Agrega una alerta a la watchlist")
    p_w_add.add_argument("keyword", help="Palabra clave")
    p_w_add.add_argument("--max-price", type=float, help="Precio máximo", default=None)
    p_w_add.add_argument("--min-discount", type=float, help="Descuento mínimo (%%)", default=None)

    p_w_rem = w_sub.add_parser("remove", help="Elimina una alerta por ID")
    p_w_rem.add_argument("id", type=int, help="ID de la alerta")

    # monitor
    p_mon = subparsers.add_parser("monitor", help="Inicia centinela en modo continuo")
    p_mon.add_argument("--interval", type=int, help="Intervalo en segundos", default=300)

    # serve
    p_serve = subparsers.add_parser("serve", help="Inicia el servidor y dashboard web")
    p_serve.add_argument("--port", type=int, help="Puerto HTTP", default=8787)
    p_serve.add_argument("--host", type=str, help="Host HTTP", default="127.0.0.1")

    # status
    subparsers.add_parser("status", help="Muestra estado del sistema y telemetría")

    # audit
    p_audit = subparsers.add_parser("audit", help="Audita y depura ofertas expiradas en la base de datos")
    p_audit.add_argument("--live", action="store_true", help="Verifica también el estado en vivo contra la web")

    args = parser.parse_args()

    if not args.command:
        print_banner()
        parser.print_help()
        sys.exit(0)

    print_banner()
    cmds = {
        "gui": cmd_gui,
        "cart": cmd_cart,
        "scan": cmd_scan,
        "glitches": cmd_glitches,
        "search": cmd_search,
        "coupons": cmd_coupons,
        "stack": cmd_stack,
        "watch": cmd_watch,
        "monitor": cmd_monitor,
        "serve": cmd_serve,
        "status": cmd_status,
        "audit": cmd_audit,
    }

    if args.command in cmds:
        cmds[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

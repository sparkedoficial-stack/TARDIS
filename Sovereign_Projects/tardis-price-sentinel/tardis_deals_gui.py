#!/usr/bin/env python3
"""
₪ TARDIS :: Interfaz de Escritorio Local de Ofertas & Carrito Directo
Permite visualizar todas las ofertas actualizadas en tiempo real y,
al seleccionar o presionar una oferta, abre automáticamente el navegador
en el carrito de compras o pasarela de compra express.
"""

import sys
import os
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

# Set environment paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.storage import Storage
from core.models import Deal
from core.cart_resolver import CartResolver
from scrapers.aggregator import DealAggregator


class TardisDealsGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("₪ TARDIS :: Cazador de Ofertas & Carrito Directo")
        self.geometry("1120x700")
        self.minsize(900, 550)

        # Storage & Engine
        self.storage = Storage()
        self.aggregator = DealAggregator(storage=self.storage)
        self.all_deals = []
        self.filtered_deals = []

        # Theme Colors
        self.COLOR_BG = "#070a13"
        self.COLOR_CARD = "#0d1222"
        self.COLOR_PANEL = "#11182c"
        self.COLOR_CYAN = "#00f3ff"
        self.COLOR_GREEN = "#06d6a0"
        self.COLOR_RED = "#ff2a5f"
        self.COLOR_AMBER = "#ffb703"
        self.COLOR_TEXT = "#f0f4fc"
        self.COLOR_MUTED = "#8b9bb4"

        self.configure(bg=self.COLOR_BG)
        self._setup_styles()
        self._build_ui()
        self._bind_events()

        # Initial load
        self.load_deals_from_db()

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        # Treeview styling
        style.configure(
            "Tardis.Treeview",
            background=self.COLOR_CARD,
            foreground=self.COLOR_TEXT,
            fieldbackground=self.COLOR_CARD,
            font=("Segoe UI", 10),
            rowheight=32,
            borderwidth=0
        )
        style.configure(
            "Tardis.Treeview.Heading",
            background=self.COLOR_PANEL,
            foreground=self.COLOR_CYAN,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padding=(6, 8)
        )
        style.map(
            "Tardis.Treeview",
            background=[("selected", "#1b2a4a")],
            foreground=[("selected", "#00f3ff")]
        )

        # Combobox styling
        style.configure(
            "Tardis.TCombobox",
            fieldbackground=self.COLOR_CARD,
            background=self.COLOR_PANEL,
            foreground=self.COLOR_TEXT,
            darkcolor=self.COLOR_CYAN,
            lightcolor=self.COLOR_PANEL
        )

    def _build_ui(self):
        # 1. Top Header Banner
        header_frame = tk.Frame(self, bg=self.COLOR_PANEL, padx=16, pady=12)
        header_frame.pack(fill=tk.X)

        title_box = tk.Frame(header_frame, bg=self.COLOR_PANEL)
        title_box.pack(side=tk.LEFT)

        badge_lbl = tk.Label(
            title_box, text=" ₪ TARDIS ", bg=self.COLOR_CYAN, fg="#000",
            font=("Segoe UI", 12, "bold"), padx=6, pady=2
        )
        badge_lbl.pack(side=tk.LEFT, padx=(0, 10))

        title_lbl = tk.Label(
            title_box, text="RADAR SOBERANO DE OFERTAS VIGENTES & CARRITO DIRECTO",
            bg=self.COLOR_PANEL, fg=self.COLOR_TEXT,
            font=("Segoe UI", 12, "bold")
        )
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(
            title_box, text="Solo ofertas 100% vigentes y verificadas • Doble clic o 'Abrir en Carrito' para compra inmediata",
            bg=self.COLOR_PANEL, fg=self.COLOR_CYAN, font=("Segoe UI", 8)
        )
        sub_lbl.pack(anchor="w")

        # Top Action Buttons
        actions_box = tk.Frame(header_frame, bg=self.COLOR_PANEL)
        actions_box.pack(side=tk.RIGHT)

        self.btn_refresh = tk.Button(
            actions_box, text="🔄 Sincronizar (F5)",
            bg="#162238", fg=self.COLOR_CYAN, activebackground=self.COLOR_CYAN, activeforeground="#000",
            font=("Segoe UI", 9, "bold"), padx=12, pady=6, relief=tk.FLAT, cursor="hand2",
            command=self.sync_all_scrapers
        )
        self.btn_refresh.pack(side=tk.LEFT, padx=5)

        self.btn_web = tk.Button(
            actions_box, text="🌐 Dashboard Web",
            bg="#162238", fg=self.COLOR_TEXT, activebackground=self.COLOR_CYAN, activeforeground="#000",
            font=("Segoe UI", 9), padx=10, pady=6, relief=tk.FLAT, cursor="hand2",
            command=lambda: CartResolver.open_in_browser("http://localhost:8787")
        )
        self.btn_web.pack(side=tk.LEFT, padx=5)

        # 2. Filter & Search Toolbar
        filter_frame = tk.Frame(self, bg=self.COLOR_BG, padx=16, pady=10)
        filter_frame.pack(fill=tk.X)

        # Search Input
        tk.Label(filter_frame, text="🔍 Buscar:", bg=self.COLOR_BG, fg=self.COLOR_MUTED, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(
            filter_frame, textvariable=self.search_var, bg=self.COLOR_CARD, fg=self.COLOR_TEXT,
            insertbackground=self.COLOR_CYAN, font=("Segoe UI", 10), width=30, relief=tk.FLAT,
            highlightthickness=1, highlightbackground="#1e2c4c", highlightcolor=self.COLOR_CYAN
        )
        self.search_entry.pack(side=tk.LEFT, padx=(0, 15), ipady=4)
        self.search_var.trace_add("write", lambda *args: self.apply_filters())

        # Store Selector
        tk.Label(filter_frame, text="Tienda:", bg=self.COLOR_BG, fg=self.COLOR_MUTED, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 6))
        self.merchant_var = tk.StringVar(value="Todas las Tiendas")
        self.merchant_combo = ttk.Combobox(
            filter_frame, textvariable=self.merchant_var, state="readonly", width=18, style="Tardis.TCombobox",
            values=["Todas las Tiendas", "Amazon", "Mercado Libre", "Walmart", "Bodega Aurrera", "Steam", "Nintendo", "PlayStation", "Chedraui", "AliExpress"]
        )
        self.merchant_combo.pack(side=tk.LEFT, padx=(0, 15))
        self.merchant_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        # Glitch Toggle
        self.glitch_var = tk.BooleanVar(value=False)
        self.glitch_chk = tk.Checkbutton(
            filter_frame, text="🚨 Solo Glitches / Errores", variable=self.glitch_var,
            bg=self.COLOR_BG, fg=self.COLOR_RED, selectcolor=self.COLOR_CARD,
            activebackground=self.COLOR_BG, activeforeground=self.COLOR_RED,
            font=("Segoe UI", 9, "bold"), cursor="hand2", command=self.apply_filters
        )
        self.glitch_chk.pack(side=tk.LEFT, padx=(0, 15))

        # Free Toggle
        self.free_var = tk.BooleanVar(value=False)
        self.free_chk = tk.Checkbutton(
            filter_frame, text="🎁 Solo Gratis (100% OFF)", variable=self.free_var,
            bg=self.COLOR_BG, fg=self.COLOR_GREEN, selectcolor=self.COLOR_CARD,
            activebackground=self.COLOR_BG, activeforeground=self.COLOR_GREEN,
            font=("Segoe UI", 9, "bold"), cursor="hand2", command=self.apply_filters
        )
        self.free_chk.pack(side=tk.LEFT, padx=(0, 15))

        # 3. Main Treeview (Deals Table)
        table_container = tk.Frame(self, bg=self.COLOR_BG, padx=16, pady=4)
        table_container.pack(fill=tk.BOTH, expand=True)

        columns = ("glitch", "merchant", "title", "price", "orig_price", "discount", "score")
        self.tree = ttk.Treeview(
            table_container, columns=columns, show="headings", style="Tardis.Treeview", selectmode="browse"
        )

        self.tree.heading("glitch", text="Tipo")
        self.tree.heading("merchant", text="Tienda")
        self.tree.heading("title", text="Producto / Oferta")
        self.tree.heading("price", text="Precio Actual")
        self.tree.heading("orig_price", text="Antes")
        self.tree.heading("discount", text="Descuento")
        self.tree.heading("score", text="Sintropía")

        self.tree.column("glitch", width=110, anchor="center")
        self.tree.column("merchant", width=130, anchor="w")
        self.tree.column("title", width=480, anchor="w")
        self.tree.column("price", width=110, anchor="e")
        self.tree.column("orig_price", width=90, anchor="e")
        self.tree.column("discount", width=95, anchor="center")
        self.tree.column("score", width=80, anchor="center")

        scrollbar = ttk.Scrollbar(table_container, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 4. Action Banner / Bottom Toolbar
        bottom_action_frame = tk.Frame(self, bg=self.COLOR_PANEL, padx=16, pady=10)
        bottom_action_frame.pack(fill=tk.X)

        self.btn_cart = tk.Button(
            bottom_action_frame,
            text="🛒 ABRIR EN EL CARRITO DE COMPRA (Enter)",
            bg=self.COLOR_GREEN, fg="#000", activebackground=self.COLOR_CYAN, activeforeground="#000",
            font=("Segoe UI", 11, "bold"), padx=20, pady=8, relief=tk.FLAT, cursor="hand2",
            command=self.open_selected_in_cart
        )
        self.btn_cart.pack(side=tk.LEFT, padx=(0, 15))

        self.btn_open_store = tk.Button(
            bottom_action_frame,
            text="🌐 Ver Publicación Original",
            bg="#162238", fg=self.COLOR_TEXT, activebackground=self.COLOR_CYAN, activeforeground="#000",
            font=("Segoe UI", 9), padx=12, pady=8, relief=tk.FLAT, cursor="hand2",
            command=self.open_selected_direct_link
        )
        self.btn_open_store.pack(side=tk.LEFT)

        self.selection_label = tk.Label(
            bottom_action_frame, text="Selecciona una oferta de la lista para comprar",
            bg=self.COLOR_PANEL, fg=self.COLOR_CYAN, font=("Segoe UI", 9, "italic")
        )
        self.selection_label.pack(side=tk.RIGHT, padx=10)

        # 5. Status Bar
        status_frame = tk.Frame(self, bg="#05070e", padx=16, pady=4)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.status_left = tk.Label(
            status_frame, text="Inicializando centinela sintrópico...",
            bg="#05070e", fg=self.COLOR_MUTED, font=("Segoe UI", 8)
        )
        self.status_left.pack(side=tk.LEFT)

        self.status_right = tk.Label(
            status_frame, text="TARDIS Local Engine v26.4 • Modo 100% Autónomo",
            bg="#05070e", fg=self.COLOR_GREEN, font=("Segoe UI", 8, "bold")
        )
        self.status_right.pack(side=tk.RIGHT)

    def _bind_events(self):
        self.tree.bind("<Double-1>", lambda e: self.open_selected_in_cart())
        self.tree.bind("<Return>", lambda e: self.open_selected_in_cart())
        self.tree.bind("<<TreeviewSelect>>", self._on_row_selected)
        self.bind("<F5>", lambda e: self.sync_all_scrapers())
        self.bind("<Control-f>", lambda e: self.search_entry.focus_set())

    def _on_row_selected(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        item_id = selected[0]
        deal = next((d for d in self.filtered_deals if d.id == item_id), None)
        if deal:
            self.selection_label.config(
                text=f"Seleccionado: {deal.merchant} • {deal.title[:50]}... (${deal.price:,.2f})",
                fg=self.COLOR_TEXT
            )

    def load_deals_from_db(self):
        """Loads all stored deals into memory and applies filters (strictly vigentes)."""
        from core.validity import ValidityEngine
        raw_deals = self.storage.list_deals(limit=300, include_expired=False, sort_by="syntropy_score")
        self.all_deals = [d for d in raw_deals if ValidityEngine.is_vigente(d) and not d.expired]
        self.apply_filters()
        self.status_left.config(
            text=f"Total: {len(self.all_deals)} ofertas VIGENTES en base de datos local | Última lectura: {datetime.now().strftime('%H:%M:%S')}"
        )

    def apply_filters(self):
        query = self.search_var.get().strip().lower()
        merchant = self.merchant_var.get()
        only_glitch = self.glitch_var.get()
        only_free = self.free_var.get()

        filtered = []
        for d in self.all_deals:
            if d.expired:
                continue
            if query and (query not in d.title.lower() and query not in d.merchant.lower()):
                continue
            if merchant != "Todas las Tiendas" and merchant.lower() not in d.merchant.lower():
                continue
            if only_glitch and not d.is_glitch:
                continue
            if only_free and not d.is_free:
                continue
            filtered.append(d)

        self.filtered_deals = filtered
        self._populate_tree()

    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        for d in self.filtered_deals:
            # Badge
            if d.is_glitch:
                type_badge = "🚨 GLITCH VIGENTE"
            elif d.is_free:
                type_badge = "🎁 GRATIS VIGENTE"
            elif d.liquidation_phase > 0:
                type_badge = f"FASE {d.liquidation_phase} (.0{d.liquidation_phase})"
            else:
                type_badge = "🟢 VIGENTE"

            price_str = "GRATIS" if d.price <= 0 else f"${d.price:,.2f}"
            orig_str = f"${d.original_price:,.2f}" if d.original_price > d.price else "-"
            disc_str = f"-{int(d.discount_percent)}%" if d.discount_percent > 0 else "-"
            score_str = f"{int(d.syntropy_score)}"

            self.tree.insert(
                "", tk.END, iid=d.id,
                values=(type_badge, d.merchant, d.title, price_str, orig_str, disc_str, score_str)
            )

    def open_selected_in_cart(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("TARDIS Sentinel", "Selecciona una oferta primero en la lista.")
            return

        deal_id = selected[0]
        deal = next((d for d in self.filtered_deals if d.id == deal_id), None)
        if not deal:
            return

        self.selection_label.config(
            text=f"🛒 Resolviendo carrito de {deal.merchant}... ¡Lanzando navegador!",
            fg=self.COLOR_GREEN
        )

        # Background resolution so GUI doesn't freeze
        def _jump():
            resolved = CartResolver.resolve(deal.link, deal.merchant, deal.title)
            cart_url = resolved["cart_url"]
            CartResolver.open_in_browser(cart_url)
            self.after(500, lambda: self.selection_label.config(
                text=f"✅ Carrito abierto en el navegador: {resolved['merchant']}",
                fg=self.COLOR_CYAN
            ))

        threading.Thread(target=_jump, daemon=True).start()

    def open_selected_direct_link(self):
        selected = self.tree.selection()
        if not selected:
            return
        deal_id = selected[0]
        deal = next((d for d in self.filtered_deals if d.id == deal_id), None)
        if deal and deal.link:
            CartResolver.open_in_browser(deal.link)

    def sync_all_scrapers(self):
        self.btn_refresh.config(text="⚡ Sincronizando...", state=tk.DISABLED)
        self.selection_label.config(text="Escaneando tiendas en segundo plano...", fg=self.COLOR_AMBER)

        def _worker():
            try:
                res = self.aggregator.scan_all()
                self.after(0, lambda: self._on_sync_finished(res))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Error al sincronizar: {e}"))
                self.after(0, lambda: self.btn_refresh.config(text="🔄 Sincronizar (F5)", state=tk.NORMAL))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_sync_finished(self, res):
        self.load_deals_from_db()
        self.btn_refresh.config(text="🔄 Sincronizar (F5)", state=tk.NORMAL)
        self.selection_label.config(
            text=f"✅ Sincronización exitosa: {res.get('new_deals', 0)} ofertas nuevas, {res.get('glitches_detected', 0)} errores de precio.",
            fg=self.COLOR_GREEN
        )


def main():
    app = TardisDealsGUI()
    app.mainloop()


if __name__ == "__main__":
    main()

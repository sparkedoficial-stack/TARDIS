"""
TARDIS Deal Notifier & Alert Dispatcher
Dispatches native Linux desktop notifications (notify-send), audio chimes,
and webhook notifications upon detecting price errors, glitches, or watchlisted bargains.
"""

import subprocess
import shutil
import time
import os
from typing import Optional, Set
from .models import Deal


class Notifier:
    def __init__(self, enable_desktop: bool = True, enable_sound: bool = True):
        self.enable_desktop = enable_desktop
        self.enable_sound = enable_sound
        self.notified_deal_ids: Set[str] = set()
        self.notify_send_bin = shutil.which("notify-send")
        self.paplay_bin = shutil.which("paplay")

    def notify_deal(self, deal: Deal, reason: str = "Ofertón Detectado") -> bool:
        """
        Sends a desktop notification for high-priority deals or glitches.
        Avoids spamming the same deal multiple times.
        """
        if deal.id in self.notified_deal_ids:
            return False

        self.notified_deal_ids.add(deal.id)

        title_header = "🚨 ERROR DE PRECIO / GLITCH" if deal.is_glitch else "⚡ OFERTÓN TARDIS"
        if deal.is_free:
            title_header = "🎁 ¡GRATIS! (100% OFF)"

        summary = f"{title_header}: {deal.merchant}"
        body = (
            f"🛒 {deal.title[:90]}\n"
            f"💰 ${deal.price:,.2f} MXN"
        )

        if deal.original_price > deal.price:
            body += f" (Antes ${deal.original_price:,.2f})"

        if deal.discount_percent > 0:
            body += f" | 🔥 -{deal.discount_percent}%"

        if deal.voucher_code:
            body += f"\n🎟️ Cupón: {deal.voucher_code}"

        if deal.notes:
            body += f"\nℹ️ {deal.notes}"

        # Send desktop notification
        sent = False
        if self.enable_desktop and self.notify_send_bin:
            try:
                urgency = "critical" if (deal.is_glitch or deal.is_free) else "normal"
                subprocess.run(
                    [
                        self.notify_send_bin,
                        "-u", urgency,
                        "-a", "TARDIS Price Sentinel",
                        "-t", "8000",
                        summary,
                        body
                    ],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                sent = True
            except Exception:
                pass

        # Trigger sound alert
        if self.enable_sound:
            self._play_alert_sound(deal.is_glitch)

        return sent

    def _play_alert_sound(self, is_glitch: bool = False):
        try:
            # Try system sound via paplay or canberra-gtk-play
            sound_candidates = [
                "/usr/share/sounds/freedesktop/stereo/complete.oga",
                "/usr/share/sounds/freedesktop/stereo/message.oga",
                "/usr/share/sounds/freedesktop/stereo/bell.oga"
            ]
            if is_glitch:
                sound_candidates.insert(0, "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga")

            for snd in sound_candidates:
                if os.path.exists(snd) and self.paplay_bin:
                    subprocess.Popen(
                        [self.paplay_bin, snd],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
                    return
        except Exception:
            pass

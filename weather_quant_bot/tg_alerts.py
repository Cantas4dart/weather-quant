from __future__ import annotations

import logging
import re

import requests

from .db import BotDB
from .models import StrategySignal
from .profit_signal import ProfitSignal
from .utils import format_temperature, format_temp_range

log = logging.getLogger(__name__)


class TelegramAlerter:
    def __init__(
        self,
        token: str,
        chat_ids: str | list[str],
        timeout: int = 12,
        public_subscribe: bool = True,
    ) -> None:
        self.token = token
        self.public_subscribe = public_subscribe
        if isinstance(chat_ids, str):
            self.chat_ids = [chat_id.strip() for chat_id in chat_ids.split(",") if chat_id.strip()]
        else:
            self.chat_ids = [str(chat_id).strip() for chat_id in chat_ids if str(chat_id).strip()]
        self.timeout = timeout

    def send_signal(self, signal: StrategySignal, db: BotDB | None = None) -> None:
        self.send_text(format_signal(signal), db=db)

    def send_profit(self, signal: ProfitSignal, db: BotDB | None = None) -> None:
        p = signal.position
        text = (
            f"<b>PROFIT SIGNAL - {signal.action}</b>\n"
            f"{p.city_name} {p.side} | gain {signal.gain_percent:.0f}%\n"
            f"Entry {p.entry_price:.0%} -> Current {p.current_price or 0:.0%}\n"
            f"Why: {signal.rationale}"
        )
        self.send_text(text, db=db)

    def poll_subscriptions(self, db: BotDB) -> None:
        if not self.token or not self.public_subscribe:
            return
        offset_raw = db.get_state("telegram_update_offset", "0")
        offset = int(offset_raw) if offset_raw.isdigit() else 0
        response = requests.get(
            f"https://api.telegram.org/bot{self.token}/getUpdates",
            params={"offset": offset + 1, "timeout": 0, "allowed_updates": '["message"]'},
            timeout=self.timeout,
        )
        response.raise_for_status()
        updates = response.json().get("result", [])
        for update in updates:
            offset = max(offset, int(update.get("update_id", 0)))
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            text = str(message.get("text") or "").strip().lower()
            chat_id = str(chat.get("id") or "")
            if not chat_id:
                continue
            title = str(chat.get("title") or chat.get("username") or chat.get("first_name") or "")
            if text.startswith("/start") or text.startswith("/subscribe"):
                db.add_telegram_subscriber(chat_id, title)
                self.send_text(
                    "Subscribed to Weather Terminal alerts. Send /stop to unsubscribe.",
                    db=None,
                    chat_ids=[chat_id],
                )
            elif text.startswith("/stop") or text.startswith("/unsubscribe"):
                db.remove_telegram_subscriber(chat_id)
                self.send_text("Unsubscribed from Weather Terminal alerts.", db=None, chat_ids=[chat_id])
            elif text.startswith("/help"):
                self.send_text("Commands: /start subscribe, /stop unsubscribe.", db=None, chat_ids=[chat_id])
        db.set_state("telegram_update_offset", str(offset))

    def _target_chat_ids(self, db: BotDB | None) -> list[str]:
        chat_ids = list(self.chat_ids)
        if db is not None:
            chat_ids.extend(db.list_telegram_subscribers())
        return sorted(set(chat_ids))

    def send_text(
        self,
        text: str,
        db: BotDB | None = None,
        chat_ids: list[str] | None = None,
    ) -> None:
        target_chat_ids = sorted(set(chat_ids or self._target_chat_ids(db)))
        if not self.token or not target_chat_ids:
            log.warning("Telegram credentials missing; alert suppressed")
            return
        for chat_id in target_chat_ids:
            response = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False},
                timeout=self.timeout,
            )
            response.raise_for_status()


def format_signal(signal: StrategySignal) -> str:
    snap = signal.snapshot
    fc = signal.forecast
    market = signal.market
    is_us = snap.city.is_us_city
    reasons = "\n".join(f"- {reason}" for reason in signal.reasons[:6])
    failures = "\n".join(f"- {reason}" for reason in signal.failure_modes[:4])
    confirmations = "\n".join(f"- {rule}" for rule in signal.confirmation_rules[:4])
    risk_plan = "\n".join(f"- {rule}" for rule in signal.risk_plan[:5])
    station = snap.city.station_id or "lat/lon fallback"
    metar = snap.metar_raw or "No METAR; fallback sources active"
    taf = snap.taf_summary or "No TAF confirmation layer"
    current_temp = format_temperature(snap.current_temp_c, is_us) if snap.current_temp_c is not None else 'n/a'
    max_temp = format_temperature(snap.max_so_far_c, is_us) if snap.max_so_far_c is not None else 'n/a'
    gp_high = format_temperature(fc.mean_high_c, is_us)
    gp_range = format_temp_range(fc.p10_c, fc.p90_c, is_us)
    gp_sigma = f"{fc.sigma_c * (9 / 5):.2f}°{'F' if is_us else 'C'}"
    bias = format_temperature(fc.bias_c, is_us)
    return (
        f"<b>{signal.strategy}</b>\n"
        f"<b>{signal.recommendation}</b>\n\n"
        f"City: {signal.city_name}\n"
        f"Resolution station: {station}\n"
        f"Current obs: {current_temp} | max so far {max_temp}\n"
        f"METAR: <code>{metar}</code>\n"
        f"TAF: {taf}\n"
        f"GP high: {gp_high} ({gp_range}), sigma {gp_sigma}, bias {bias}\n"
        f"Model prob: {signal.model_probability:.1%} | Market: {signal.implied_probability:.1%} | "
        f"Edge: {signal.edge:+.1%} | EV: {signal.expected_value:+.1%}\n\n"
        f"Why it works:\n{reasons}\n\n"
        f"Failure modes:\n{failures}\n\n"
        f"Confirmation rules:\n{confirmations}\n\n"
        f"Suggested TP/SL plan:\n{risk_plan}\n\n"
        f"Market: {market.question}\n"
        f"Link: {market.url or 'n/a'}"
    )


def format_signal_plain(signal: StrategySignal) -> str:
    text = format_signal(signal)
    text = re.sub(r"</?b>", "", text)
    text = re.sub(r"</?code>", "", text)
    return text


def format_profit_plain(signal: ProfitSignal) -> str:
    p = signal.position
    return (
        f"EXIT SIGNAL - {signal.action}\n"
        f"{p.city_name} {p.side} token {p.token_id}\n"
        f"Entry: {p.entry_price:.1%} | Current: {(p.current_price or 0):.1%} | Gain: {signal.gain_percent:.0f}%\n"
        f"Size: ${p.size_usd:.2f} | Market: {p.market_id}\n"
        f"Why: {signal.rationale}\n"
        f"Notes: {p.notes or 'n/a'}"
    )

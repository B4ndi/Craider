"""
Daily Telegram market check for Craider, plus an instant alert when the BTC regime flips.

Craider is often in cash for weeks (it only buys while BTC is above its 200-day average and a
coin is in an uptrend). Without this, Telegram stays silent and you can't tell "waiting on
purpose" from "broken". Once a day the strategy sends one message with:
  * the paper wallet, open trades and what was bought/sold in the last 24 hours,
  * whether the bot may buy at all (BTC vs its 200-day average) and how far away that is,
  * for every watched coin, how many of the three buy rules it meets and what is missing.
When BTC closes a day across its 200-day average the bot also sends an alert right away,
because that is when buying becomes possible (or everything gets sold).

Options live in user_data/config.json under "market_check" (see DEPLOY.md):

    "market_check": {"enabled": true, "hour": 7, "timezone": "UTC", "regime_alerts": true}

No Freqtrade imports, so it can be unit tested on its own (tests/).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from weekly_digest import TELEGRAM_LIMIT, DigestSchedule, _signed

logger = logging.getLogger(__name__)

DEFAULTS = {
    "enabled": True,
    "hour": 7,                 # 0-23, in "timezone"
    "timezone": "UTC",         # any IANA name, e.g. "Europe/Oslo"
    "send_on_startup": False,  # true: send one right after every start (to test setup)
    "regime_alerts": True,     # alert as soon as BTC closes a day across its 200-day average
}
STATE_FILE = "market_check_state.json"
REGIME_FILE = "regime_state.json"


def settings(config: dict) -> dict:
    cfg = {**DEFAULTS, **(config.get("market_check") or {})}
    cfg["hour"] = int(cfg["hour"])
    if not 0 <= cfg["hour"] <= 23:
        raise ValueError(f"market_check.hour must be 0-23, got {cfg['hour']}")
    ZoneInfo(cfg["timezone"])  # raises on an unknown timezone
    return cfg


def last_daily_slot(now: datetime, cfg: dict) -> datetime:
    """The most recent daily send time at or before `now`."""
    tz = ZoneInfo(cfg["timezone"])
    local = now.astimezone(tz)
    slot = datetime(local.year, local.month, local.day, cfg["hour"], tzinfo=tz)
    if slot > local:
        slot -= timedelta(days=1)
    return slot.astimezone(now.tzinfo)


class DailySchedule(DigestSchedule):
    """Like the weekly digest's schedule, but daily, and the very first run sends right away
    (so you see a message as soon as this feature is deployed, then once a day)."""

    def _slot(self, now: datetime) -> datetime:
        return last_daily_slot(now, self.cfg)

    def is_due(self, now: datetime) -> bool:
        if self.cfg["enabled"] and self._last_sent is None:
            return True
        return super().is_due(now)


class RegimeWatch:
    """Remembers whether BTC was above its 200-day average, so a flip is reported once,
    also across restarts."""

    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            self.bull = json.loads(self.path.read_text())["bull"]
        except (OSError, ValueError, KeyError, TypeError):
            self.bull = None

    def update(self, bull: bool) -> bool | None:
        """Store the new state. Returns the new state if it flipped, else None.
        The first observation ever is stored silently (the daily check reports it)."""
        bull = bool(bull)
        previous, self.bull = self.bull, bull
        if previous == bull:
            return None
        try:
            self.path.write_text(json.dumps({"bull": bull}))
        except OSError as e:
            logger.warning("Market check: could not save regime state to %s: %s", self.path, e)
        return None if previous is None else bull


def coin_status(close: float, ema50: float, ema100: float, ema200: float) -> dict:
    """Craider's three per-coin buy rules and how far each one is from being met (in %)."""
    rules = {
        "uptrend": ema50 > ema200,
        "above EMA50": close > ema50,
        "above EMA100": close >= ema100,
    }
    price_needed = max(ema50, ema100) / close - 1 if close > 0 else 0.0
    return {
        "met": sum(rules.values()),
        "missing": [name for name, ok in rules.items() if not ok],
        "trend_gap_pct": max(0.0, (ema200 / ema50 - 1) * 100) if ema50 > 0 else 0.0,
        "price_gap_pct": max(0.0, price_needed * 100),
    }


def regime_text(regime: dict | None) -> str:
    if not regime or not regime.get("sma200"):
        return "Not enough BTC daily data yet to tell."
    btc, sma = regime["btc"], regime["sma200"]
    gap = (btc / sma - 1) * 100
    if btc > sma:
        return (f"Yes. BTC {btc:,.0f} is {gap:+.1f}% above its 200-day average ({sma:,.0f}), "
                "so the bot buys any watched coin that meets all 3 rules.")
    return (f"No. BTC {btc:,.0f} is {abs(gap):.1f}% below its 200-day average ({sma:,.0f}). "
            f"Buying starts after a daily close above it (BTC +{(sma / btc - 1) * 100:.1f}% from here).")


def compose_regime_alert(bull: bool, regime: dict | None, open_trades: int) -> str:
    head = ("🟢 *Craider: BTC closed above its 200-day average*" if bull
            else "🔴 *Craider: BTC closed below its 200-day average*")
    tail = ("The bot may buy again; you'll get a message for every buy."
            if bull else
            ("It now sells its open trades and stays in cash." if open_trades
             else "It stays in cash until BTC recovers."))
    return "\n".join([head, regime_text(regime), tail])


def compose(d: dict) -> str:
    """
    Expected keys: stake, dry_run, starting_balance, realized_total, unrealized,
      open_trades: [{pair, profit_abs, profit_pct, days}], max_open_trades, closed_count,
      bought_24h: [pair], sold_24h: [{pair, profit_pct}], regime: {btc, sma200} or None,
      coins: [{pair, met, missing, trend_gap_pct, price_gap_pct}] (may be empty)
    """
    stake = d["stake"]
    lines = [f"*Craider daily check*{'  (paper trading)' if d['dry_run'] else ''}", ""]

    start = d["starting_balance"]
    pnl = d["realized_total"] + d["unrealized"]
    pct = f" ({_signed(pnl / start * 100, '%')})" if start else ""
    lines.append(f"Trading capital: {start + pnl:,.2f} {stake}, profit {_signed(pnl)} {stake}{pct}")
    lines.append(f"Trades: {len(d['open_trades'])}/{d['max_open_trades']} open, "
                 f"{d['closed_count']} closed so far")
    for t in sorted(d["open_trades"], key=lambda t: t["profit_pct"], reverse=True):
        lines.append(f"  {t['pair']}: {_signed(t['profit_pct'], '%')} "
                     f"({_signed(t['profit_abs'])} {stake}), {t['days']:.0f}d")
    bought = ", ".join(p.split("/")[0] for p in d["bought_24h"]) or "nothing"
    sold = ", ".join(f"{t['pair'].split('/')[0]} {_signed(t['profit_pct'], '%')}"
                     for t in d["sold_24h"]) or "nothing"
    lines += [f"Last 24h: bought {bought}; sold {sold}", ""]

    lines += ["*Can it buy?*", regime_text(d.get("regime")), ""]

    coins = sorted(d["coins"], key=lambda c: (-c["met"], c["price_gap_pct"] + c["trend_gap_pct"]))
    lines.append("*Watched coins* (rules met of 3: uptrend, above EMA50, above EMA100)")
    if not coins:
        lines.append("No analysed coins yet.")
    for c in coins:
        name = c["pair"].split("/")[0]
        if not c["missing"]:
            lines.append(f"✅ {name}: 3/3, buy signal")
            continue
        needs = []
        if c["price_gap_pct"] > 0:
            needs.append(f"price +{c['price_gap_pct']:.1f}%")
        if "uptrend" in c["missing"]:
            needs.append(f"EMA50 {c['trend_gap_pct']:.1f}% under EMA200")
        lines.append(f"{name}: {c['met']}/3, needs {', '.join(needs)}")
    ready = sum(1 for c in coins if not c["missing"])
    regime = d.get("regime")
    if ready and regime and regime.get("sma200") and regime["btc"] <= regime["sma200"]:
        lines.append(f"{ready} coin(s) pass all 3, but nothing is bought while BTC is below its average.")

    text = "\n".join(lines).rstrip()
    return text if len(text) <= TELEGRAM_LIMIT else text[: TELEGRAM_LIMIT - 3] + "..."

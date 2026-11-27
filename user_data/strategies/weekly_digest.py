"""
Weekly Telegram digest for Craider.

Once a week the strategy sends one Telegram message that combines what /profit, /status and
/whitelist show, plus the market regime and any alarms the bot logged during the week.

Schedule and options live in user_data/config.json under "weekly_digest" (see DEPLOY.md):

    "weekly_digest": {"enabled": true, "weekday": "sun", "hour": 18, "timezone": "UTC"}

This module has no Freqtrade imports, so it can be unit tested on its own (tests/).
The strategy collects the numbers; this module decides when to send and formats the text.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULTS = {
    "enabled": True,
    "weekday": "sun",        # mon..sun
    "hour": 18,              # 0-23, in "timezone"
    "timezone": "UTC",       # any IANA name, e.g. "Europe/Oslo"
    "send_on_startup": False,  # true: send one digest right after the bot starts (to test setup)
}
STATE_FILE = "weekly_digest_state.json"
TELEGRAM_LIMIT = 4000        # Telegram's hard limit is 4096 characters

# Freqtrade log line: "2026-11-27 11:34:23,123 - freqtrade.exchange.common - WARNING - text"
_LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ - (\S+) - (\w+) - (.*)$")


def settings(config: dict) -> dict:
    """Merge config["weekly_digest"] over the defaults and validate it."""
    cfg = {**DEFAULTS, **(config.get("weekly_digest") or {})}
    cfg["weekday"] = str(cfg["weekday"]).lower()[:3]
    if cfg["weekday"] not in WEEKDAYS:
        raise ValueError(f"weekly_digest.weekday must be one of {WEEKDAYS}, got {cfg['weekday']!r}")
    cfg["hour"] = int(cfg["hour"])
    if not 0 <= cfg["hour"] <= 23:
        raise ValueError(f"weekly_digest.hour must be 0-23, got {cfg['hour']}")
    ZoneInfo(cfg["timezone"])  # raises on an unknown timezone
    return cfg


def last_slot(now: datetime, cfg: dict) -> datetime:
    """The most recent scheduled send time at or before `now` (returned in UTC)."""
    tz = ZoneInfo(cfg["timezone"])
    local = now.astimezone(tz)
    days_back = (local.weekday() - WEEKDAYS.index(cfg["weekday"])) % 7
    day = (local - timedelta(days=days_back)).date()
    slot = datetime(day.year, day.month, day.day, cfg["hour"], tzinfo=tz)
    if slot > local:
        slot -= timedelta(days=7)
    return slot.astimezone(timezone.utc)


class DigestSchedule:
    """Decides when a digest is due and remembers the last one in a small JSON file,
    so restarting the bot neither repeats nor skips a week."""

    def __init__(self, cfg: dict, state_path: Path):
        self.cfg = cfg
        self.state_path = Path(state_path)
        self._last_sent = self._load()
        self._startup_pending = bool(cfg["send_on_startup"])

    def _load(self) -> datetime | None:
        try:
            return datetime.fromisoformat(json.loads(self.state_path.read_text())["last_sent"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def is_due(self, now: datetime) -> bool:
        if not self.cfg["enabled"]:
            return False
        if self._startup_pending:
            return True
        slot = last_slot(now, self.cfg)
        if self._last_sent is None:
            # First run ever: don't fire straight away, wait for the next scheduled slot.
            self.mark_sent(slot)
            return False
        return self._last_sent < slot

    def mark_sent(self, when: datetime) -> None:
        self._startup_pending = False
        self._last_sent = when
        try:
            self.state_path.write_text(json.dumps({"last_sent": when.isoformat()}))
        except OSError as e:
            logger.warning("Weekly digest: could not save state to %s: %s", self.state_path, e)


def read_alarms(logfile: str | Path | None, since: datetime, top: int = 3) -> tuple[int, list]:
    """
    Alarms logged since `since`: every ERROR/CRITICAL line, plus WARNINGs from the exchange
    code (Binance errors, retries, rejected orders, stoploss trouble).
    Returns (total count, [(count, message), ...] for the `top` most frequent messages).
    Reads the rotated files too (craider.log.1 ... .10).
    """
    if not logfile:
        return 0, []
    since_local = since.astimezone().replace(tzinfo=None)  # log timestamps are local, naive
    base = Path(logfile)
    files = [base] + [base.with_name(f"{base.name}.{i}") for i in range(1, 11)]
    counts: Counter = Counter()
    for path in files:
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            m = _LOG_LINE.match(line)
            if not m:
                continue
            stamp, name, level, msg = m.groups()
            if datetime.fromisoformat(stamp) < since_local:
                continue
            if level in ("ERROR", "CRITICAL") or (
                level == "WARNING" and name.startswith("freqtrade.exchange")
            ):
                # Collapse repeats that only differ in numbers (ids, prices, retry counts).
                counts[re.sub(r"\d+(\.\d+)?", "#", msg)[:150]] += 1
    return sum(counts.values()), [(n, msg) for msg, n in counts.most_common(top)]


def _md(text: str) -> str:
    """Make free text safe for Telegram's (legacy) Markdown, which Freqtrade uses."""
    return re.sub(r"[_*`\[]", " ", str(text))


def _signed(x: float, unit: str = "") -> str:
    return f"{x:+,.2f}{unit}"


def compose(d: dict) -> str:
    """
    Build the message from the numbers the strategy collected. Expected keys:
      stake, starting_balance, realized_total, unrealized,
      week_closed: [{pair, profit_abs, profit_pct, exit_reason}],
      open_trades: [{pair, profit_abs, profit_pct, days}],
      max_open_trades, whitelist: [pair], regime: {btc, sma200} or None,
      alarms_total, alarms: [(count, message)], dry_run
    """
    stake = d["stake"]
    lines = [f"*Craider weekly digest*{'  (paper trading)' if d['dry_run'] else ''}", ""]

    # Profit (like /profit)
    total = d["realized_total"] + d["unrealized"]
    start = d["starting_balance"]
    total_pct = f" ({_signed(total / start * 100, '%')})" if start else ""
    week = d["week_closed"]
    week_abs = sum(t["profit_abs"] for t in week)
    wins = sum(1 for t in week if t["profit_abs"] > 0)
    lines += [
        "*Profit*",
        f"Overall: {_signed(total)} {stake}{total_pct}",
        f"  realized {_signed(d['realized_total'])}, open {_signed(d['unrealized'])}",
        f"This week: {_signed(week_abs)} {stake} from {len(week)} closed trade(s)"
        + (f", {wins} won" if week else ""),
        "",
    ]

    # Open trades (like /status)
    opened = d["open_trades"]
    lines.append(f"*Open trades* ({len(opened)}/{d['max_open_trades']})")
    if opened:
        for t in sorted(opened, key=lambda t: t["profit_pct"], reverse=True):
            lines.append(
                f"{t['pair']}: {_signed(t['profit_pct'], '%')} "
                f"({_signed(t['profit_abs'])} {stake}), {t['days']:.0f}d"
            )
    else:
        lines.append("None, all in cash.")
    lines.append("")

    # Regime
    regime = d.get("regime")
    lines.append("*Regime*")
    if regime and regime.get("sma200"):
        btc, sma = regime["btc"], regime["sma200"]
        gap = (btc / sma - 1) * 100
        state = "above" if btc > sma else "below"
        verdict = "bot may buy" if btc > sma else "bot stays in cash"
        lines.append(f"BTC {btc:,.0f} is {gap:+.1f}% {state} its 200-day average ({sma:,.0f}): {verdict}.")
    else:
        lines.append("Not enough BTC daily data yet.")
    lines.append("")

    # Watched coins (like /whitelist)
    wl = d["whitelist"]
    lines += [f"*Watching* ({len(wl)})", ", ".join(p.split("/")[0] for p in wl) or "nothing", ""]

    # Alarms
    stops = [t for t in week if "stop" in (t.get("exit_reason") or "")]
    lines.append("*Alarms this week*")
    if not d["alarms_total"] and not stops:
        lines.append("None.")
    for t in stops:
        lines.append(f"Stoploss hit: {t['pair']} {_signed(t['profit_pct'], '%')}")
    if d["alarms_total"]:
        lines.append(f"{d['alarms_total']} error/exchange warning(s) in the log. Most frequent:")
        lines += [f"  {n}x {_md(msg)}" for n, msg in d["alarms"]]

    text = "\n".join(lines).rstrip()
    return text if len(text) <= TELEGRAM_LIMIT else text[: TELEGRAM_LIMIT - 3] + "..."

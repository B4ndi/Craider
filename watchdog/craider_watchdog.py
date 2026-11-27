"""Craider watchdog: tells you on Telegram when the bot is down.

The bot is silent by design while it sits in cash, so silence alone can't tell
you whether it is quiet or dead. This small process runs next to the bot (its
own container, see docker-compose.yml) and checks once a minute:

  bot       - the bot answers on its API, its main loop finished a cycle
              recently, and it is not stopped
  exchange  - Binance is reachable from the server and, when an API key is
              set, still accepts that key (keys expire, IP lists change)

A problem that lasts DOWN_MINUTES sends a Telegram alert, repeats every
REMIND_HOURS while it lasts, and sends an "OK again" message when it clears.

Optionally it also pings a dead-man's switch (HEALTHCHECK_URL, e.g.
healthchecks.io) after every good check, so you hear about it even if the whole
server dies and nothing on it can send a message.

Standard library only, so it runs on the freqtrade image as-is.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("watchdog")

PLACEHOLDER_PREFIX = "PASTE_"
BINANCE_API = "https://api.binance.com"
HTTP_TIMEOUT = 15


# --------------------------------------------------------------------------- config


@dataclass
class Settings:
    telegram_token: str
    telegram_chat_id: str
    api_url: str
    api_username: str
    api_password: str
    binance_key: str = ""
    binance_secret: str = ""
    check_seconds: int = 60
    down_minutes: float = 10
    remind_hours: float = 6
    stale_minutes: float = 3
    healthcheck_url: str = ""


def _real(value: object) -> str:
    """Return value as a string, or "" when it is empty or still a placeholder."""
    text = str(value or "").strip()
    return "" if text.startswith(PLACEHOLDER_PREFIX) else text


def load_settings(config_path: str, env: dict[str, str]) -> Settings:
    """Read Telegram, API and Binance settings from config.private.json, timings from env."""
    with open(config_path, encoding="utf-8") as fh:
        cfg = json.load(fh)

    telegram = cfg.get("telegram") or {}
    api = cfg.get("api_server") or {}
    exchange = cfg.get("exchange") or {}

    missing = []
    token, chat_id = _real(telegram.get("token")), _real(telegram.get("chat_id"))
    if not token or not chat_id:
        missing.append("telegram.token / telegram.chat_id")
    if not api.get("enabled") or not _real(api.get("username")) or not _real(api.get("password")):
        missing.append("api_server (enabled, username, password)")
    if missing:
        raise ValueError(f"{config_path} is missing: {', '.join(missing)}. See DEPLOY.md, step 7.")

    port = int(api.get("listen_port", 8080))
    return Settings(
        telegram_token=token,
        telegram_chat_id=chat_id,
        api_url=env.get("WATCHDOG_BOT_URL", f"http://craider:{port}").rstrip("/"),
        api_username=_real(api.get("username")),
        api_password=_real(api.get("password")),
        binance_key=_real(exchange.get("key")),
        binance_secret=_real(exchange.get("secret")),
        check_seconds=int(env.get("WATCHDOG_CHECK_SECONDS", 60)),
        down_minutes=float(env.get("WATCHDOG_DOWN_MINUTES", 10)),
        remind_hours=float(env.get("WATCHDOG_REMIND_HOURS", 6)),
        stale_minutes=float(env.get("WATCHDOG_STALE_MINUTES", 3)),
        healthcheck_url=env.get("HEALTHCHECK_URL", "").strip(),
    )


# --------------------------------------------------------------------------- http


class HttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


def http(method: str, url: str, headers: dict[str, str] | None = None, data: bytes | None = None):
    """Small urllib wrapper. Returns parsed JSON (or text); raises HttpError / OSError."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        raise HttpError(err.code, err.read().decode("utf-8", "replace")) from None
    try:
        return json.loads(body)
    except ValueError:
        return body


# --------------------------------------------------------------------------- checks

CheckResult = tuple[bool, str]  # (ok, what is wrong)


def check_bot(s: Settings, now: float, request=http) -> CheckResult:
    try:
        request("GET", f"{s.api_url}/api/v1/ping")
    except (OSError, HttpError) as err:
        return False, f"The bot is not answering (container stopped or crashed?). {err}"

    auth = base64.b64encode(f"{s.api_username}:{s.api_password}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    try:
        health = request("GET", f"{s.api_url}/api/v1/health", headers)
        config = request("GET", f"{s.api_url}/api/v1/show_config", headers)
    except HttpError as err:
        if err.status == 401:
            return False, "The bot's API rejected the watchdog's login. Check api_server in config.private.json."
        return False, f"The bot's API returned an error. {err}"
    except OSError as err:
        return False, f"The bot's API stopped answering. {err}"

    state = str(config.get("state", "")).lower()
    if state not in ("running", "paused"):
        return False, f"The bot is {state or 'not running'}. Send /start in Telegram to resume."

    last = health.get("last_process_ts")
    if not last:
        # Right after a (re)start the first cycle can take a while.
        return False, "The bot has not finished a single cycle since it started."
    age_min = (now - float(last)) / 60
    if age_min > s.stale_minutes:
        return False, f"The bot's main loop is stuck: last cycle finished {age_min:.0f} min ago."
    return True, ""


def check_exchange(s: Settings, now: float, request=http) -> CheckResult:
    try:
        request("GET", f"{BINANCE_API}/api/v3/ping")
    except (OSError, HttpError) as err:
        return False, f"Binance is unreachable from the server. {err}"

    if not (s.binance_key and s.binance_secret):
        return True, ""  # paper trading without a key: reachability is all we can check

    query = urllib.parse.urlencode({"timestamp": int(now * 1000), "recvWindow": 10000})
    sig = hmac.new(s.binance_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    try:
        request(
            "GET",
            f"{BINANCE_API}/api/v3/account?{query}&signature={sig}",
            {"X-MBX-APIKEY": s.binance_key},
        )
    except HttpError as err:
        if err.status in (401, 403) or '"code":-2015' in err.body or '"code":-2014' in err.body:
            return False, (
                "Binance rejects the API key (expired, deleted, or the server IP is not on "
                f"its allow list). {err}"
            )
        return False, f"Binance answered with an error for the account check. {err}"
    except OSError as err:
        return False, f"Binance stopped answering during the account check. {err}"
    return True, ""


# --------------------------------------------------------------------------- alerting


@dataclass
class CheckState:
    failing_since: float | None = None
    last_alert: float | None = None
    detail: str = ""


@dataclass
class Watchdog:
    settings: Settings
    send: Callable[[str], None]
    checks: dict[str, Callable[[float], CheckResult]]
    states: dict[str, CheckState] = field(default_factory=dict)

    def run_once(self, now: float) -> bool:
        """Run every check once and send whatever alerts are due.

        Returns False only while some check has been failing for DOWN_MINUTES or more,
        so short blips don't trip the dead-man's switch either.
        """
        s = self.settings
        healthy = True
        for name, check in self.checks.items():
            st = self.states.setdefault(name, CheckState())
            try:
                ok, detail = check(now)
            except Exception as err:  # a bug in a check must not kill the watchdog
                log.exception("check %s crashed", name)
                ok, detail = False, f"Watchdog check crashed: {err!r}"

            if ok:
                if st.last_alert is not None and st.failing_since is not None:
                    down = _fmt_duration(now - st.failing_since)
                    self._notify(f"✅ Craider {name}: OK again (was down for {down}).")
                if st.failing_since is not None:
                    log.info("%s recovered", name)
                self.states[name] = CheckState()
                continue

            if st.failing_since is None:
                st.failing_since = now
                log.warning("%s failing: %s", name, detail)
            st.detail = detail
            down_for = now - st.failing_since
            if down_for < s.down_minutes * 60:
                continue
            healthy = False
            if st.last_alert is None:
                self._notify(f"🚨 Craider {name} problem for {_fmt_duration(down_for)}:\n{detail}")
                st.last_alert = now
            elif now - st.last_alert >= s.remind_hours * 3600:
                self._notify(f"⏰ Craider {name} still down ({_fmt_duration(down_for)}):\n{detail}")
                st.last_alert = now
        return healthy

    def _notify(self, text: str) -> None:
        log.info("telegram: %s", text.replace("\n", " | "))
        try:
            self.send(text)
        except Exception:
            log.exception("could not send Telegram message")


def _fmt_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {minutes} min"
    return f"{hours // 24} days {hours % 24} h"


def telegram_sender(s: Settings, request=http) -> Callable[[str], None]:
    url = f"https://api.telegram.org/bot{s.telegram_token}/sendMessage"

    def send(text: str) -> None:
        data = urllib.parse.urlencode({"chat_id": s.telegram_chat_id, "text": text}).encode()
        request("POST", url, {"Content-Type": "application/x-www-form-urlencoded"}, data)

    return send


def ping_deadman(url: str, ok: bool, request=http) -> None:
    """healthchecks.io style: GET <url> when healthy, <url>/fail when not."""
    if not url:
        return
    try:
        request("GET", url if ok else url.rstrip("/") + "/fail")
    except (OSError, HttpError) as err:
        log.warning("dead-man's switch ping failed: %s", err)


# --------------------------------------------------------------------------- main


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout
    )
    config_path = os.environ.get(
        "WATCHDOG_CONFIG", "/freqtrade/user_data/config.private.json"
    )
    try:
        s = load_settings(config_path, dict(os.environ))
    except (OSError, ValueError) as err:
        log.error("watchdog not started: %s", err)
        time.sleep(300)  # don't spin in a tight restart loop under Docker
        return 1

    dog = Watchdog(
        settings=s,
        send=telegram_sender(s),
        checks={
            "bot": lambda now: check_bot(s, now),
            "exchange": lambda now: check_exchange(s, now),
        },
    )
    dog._notify(
        f"👀 Craider watchdog started. It checks every {s.check_seconds}s and alerts after "
        f"{s.down_minutes:g} min of trouble. No news is good news."
    )
    while True:
        started = time.time()
        ok = dog.run_once(started)
        ping_deadman(s.healthcheck_url, ok)
        time.sleep(max(1.0, s.check_seconds - (time.time() - started)))


if __name__ == "__main__":
    sys.exit(main())

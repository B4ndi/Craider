import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "strategies"))
import weekly_digest as wd  # noqa: E402

UTC = timezone.utc


def cfg(**kw):
    return wd.settings({"weekly_digest": kw})


def test_defaults_and_validation():
    c = wd.settings({})
    assert (c["weekday"], c["hour"], c["timezone"]) == ("sun", 18, "UTC")
    assert cfg(weekday="Monday")["weekday"] == "mon"
    with pytest.raises(ValueError):
        cfg(weekday="xyz")
    with pytest.raises(ValueError):
        cfg(hour=24)
    with pytest.raises(Exception):
        cfg(timezone="Mars/Base")


def test_last_slot_utc():
    c = cfg(weekday="sun", hour=18)
    # Friday 2026-11-27 -> previous Sunday 2026-11-22 18:00
    assert wd.last_slot(datetime(2026, 11, 27, 12, tzinfo=UTC), c) == datetime(2026, 11, 22, 18, tzinfo=UTC)
    # Sunday before 18:00 -> a week earlier; at 18:00 -> today
    assert wd.last_slot(datetime(2026, 11, 29, 17, 59, tzinfo=UTC), c) == datetime(2026, 11, 22, 18, tzinfo=UTC)
    assert wd.last_slot(datetime(2026, 11, 29, 18, 0, tzinfo=UTC), c) == datetime(2026, 11, 29, 18, tzinfo=UTC)


def test_last_slot_timezone():
    c = cfg(weekday="mon", hour=8, timezone="Europe/Oslo")  # UTC+1 in winter
    assert wd.last_slot(datetime(2026, 11, 30, 7, 30, tzinfo=UTC), c) == datetime(2026, 11, 30, 7, tzinfo=UTC)


def test_schedule_fires_once_per_week_and_survives_restart(tmp_path):
    state = tmp_path / "state.json"
    c = cfg(weekday="sun", hour=18)
    s = wd.DigestSchedule(c, state)
    t = datetime(2026, 11, 27, 12, tzinfo=UTC)
    assert not s.is_due(t)  # first run ever: wait for the next slot
    assert not s.is_due(datetime(2026, 11, 29, 17, tzinfo=UTC))
    sunday = datetime(2026, 11, 29, 18, 0, 5, tzinfo=UTC)
    assert s.is_due(sunday)
    s.mark_sent(sunday)
    assert not s.is_due(sunday + timedelta(minutes=1))
    # restart: state is read back, no duplicate
    assert not wd.DigestSchedule(c, state).is_due(sunday + timedelta(hours=1))
    # bot was down over the slot: sends late once
    s2 = wd.DigestSchedule(c, state)
    late = datetime(2026, 12, 7, 9, tzinfo=UTC)
    assert s2.is_due(late)


def test_send_on_startup_and_disabled(tmp_path):
    now = datetime(2026, 11, 27, 12, tzinfo=UTC)
    s = wd.DigestSchedule(cfg(send_on_startup=True), tmp_path / "a.json")
    assert s.is_due(now)
    s.mark_sent(now)
    assert not s.is_due(now)
    assert not wd.DigestSchedule(cfg(enabled=False, send_on_startup=True), tmp_path / "b.json").is_due(now)


def test_read_alarms(tmp_path):
    def stamp(dt):
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S") + ",123"

    now = datetime.now(UTC)
    old, new = stamp(now - timedelta(days=9)), stamp(now - timedelta(hours=1))
    log = tmp_path / "craider.log"
    log.write_text("\n".join([
        f"{old} - freqtrade.freqtradebot - ERROR - too old",
        f"{new} - freqtrade.freqtradebot - ERROR - Order 123 failed",
        f"{new} - freqtrade.freqtradebot - ERROR - Order 456 failed",
        f"{new} - freqtrade.exchange.common - WARNING - retrying fetch_ticker() 3 times",
        f"{new} - freqtrade.strategy - WARNING - not an exchange warning",
        f"{new} - freqtrade.worker - INFO - heartbeat",
        "Traceback continuation line",
    ]))
    (tmp_path / "craider.log.1").write_text(f"{new} - freqtrade.rpc - CRITICAL - boom\n")
    total, top = wd.read_alarms(log, now - timedelta(days=7))
    assert total == 4
    assert top[0] == (2, "Order # failed")
    assert wd.read_alarms(None, now) == (0, [])
    assert wd.read_alarms(tmp_path / "missing.log", now) == (0, [])


def sample(**kw):
    d = {
        "stake": "USDT", "dry_run": False, "starting_balance": 1000.0,
        "realized_total": 50.0, "unrealized": -10.0,
        "week_closed": [
            {"pair": "ETH/USDT", "profit_abs": 30.0, "profit_pct": 12.0, "exit_reason": "exit_signal"},
            {"pair": "SOL/USDT", "profit_abs": -20.0, "profit_pct": -20.5, "exit_reason": "stoploss_on_exchange"},
        ],
        "open_trades": [{"pair": "BTC/USDT", "profit_abs": -10.0, "profit_pct": -2.0, "days": 3.4}],
        "max_open_trades": 8, "whitelist": ["BTC/USDT", "ETH/USDT"],
        "regime": {"btc": 90000.0, "sma200": 80000.0},
        "alarms_total": 2, "alarms": [(2, "Binance_error *bad* `x`")],
    }
    d.update(kw)
    return d


def test_compose_full():
    text = wd.compose(sample())
    assert "Overall: +40.00 USDT (+4.00%)" in text
    assert "This week: +10.00 USDT from 2 closed trade(s), 1 won" in text
    assert "*Open trades* (1/8)" in text and "BTC/USDT: -2.00% (-10.00 USDT), 3d" in text
    assert "+12.5% above its 200-day average" in text and "bot may buy" in text
    assert "BTC, ETH" in text
    assert "Stoploss hit: SOL/USDT -20.50%" in text
    assert "2x Binance error  bad   x" in text  # markdown characters neutralised
    assert "paper trading" not in text


def test_compose_empty_bear_market():
    text = wd.compose(sample(
        dry_run=True, week_closed=[], open_trades=[], realized_total=0.0, unrealized=0.0,
        regime={"btc": 60000.0, "sma200": 72000.0}, alarms_total=0, alarms=[], starting_balance=0,
    ))
    assert "paper trading" in text
    assert "None, all in cash." in text
    assert "bot stays in cash" in text
    assert "*Alarms this week*\nNone." in text
    assert wd.compose(sample(regime=None)).count("Not enough BTC daily data") == 1


def test_compose_respects_telegram_limit():
    many = [(1, "x" * 150)] * 40
    assert len(wd.compose(sample(alarms=many, alarms_total=40))) <= wd.TELEGRAM_LIMIT

"""Daily market check and regime alert: pure functions, plus the strategy hook with mocked internals."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))
import market_check as mc  # noqa: E402

NOW = datetime(2026, 11, 28, 7, 0, 5, tzinfo=timezone.utc)


def test_settings_and_daily_slot():
    cfg = mc.settings({})
    assert cfg["hour"] == 7 and cfg["regime_alerts"]
    with pytest.raises(ValueError):
        mc.settings({"market_check": {"hour": 24}})
    assert mc.last_daily_slot(NOW, cfg) == datetime(2026, 11, 28, 7, tzinfo=timezone.utc)
    assert mc.last_daily_slot(NOW - timedelta(minutes=1), cfg) == datetime(2026, 11, 27, 7, tzinfo=timezone.utc)
    oslo = mc.settings({"market_check": {"hour": 8, "timezone": "Europe/Oslo"}})
    assert mc.last_daily_slot(NOW, oslo) == datetime(2026, 11, 28, 7, tzinfo=timezone.utc)


def test_daily_schedule_sends_on_first_run_then_daily(tmp_path):
    cfg = mc.settings({})
    state = tmp_path / mc.STATE_FILE
    s = mc.DailySchedule(cfg, state)
    assert s.is_due(NOW - timedelta(hours=3))      # first ever: right away
    s.mark_sent(NOW - timedelta(hours=3))
    assert not s.is_due(NOW - timedelta(hours=1))
    assert s.is_due(NOW)                            # 07:00 slot
    s.mark_sent(NOW)
    s2 = mc.DailySchedule(cfg, state)               # restart: no duplicate
    assert not s2.is_due(NOW + timedelta(hours=5))
    assert s2.is_due(NOW + timedelta(days=1))
    assert not mc.DailySchedule(mc.settings({"market_check": {"enabled": False}}),
                                tmp_path / "x.json").is_due(NOW)


def test_regime_watch_reports_flips_once(tmp_path):
    path = tmp_path / mc.REGIME_FILE
    w = mc.RegimeWatch(path)
    assert w.update(False) is None                  # first observation: silent
    assert w.update(False) is None
    assert w.update(True) is True
    assert mc.RegimeWatch(path).update(True) is None  # survives restart
    assert mc.RegimeWatch(path).update(False) is False


def test_coin_status():
    ok = mc.coin_status(close=110, ema50=100, ema100=95, ema200=90)
    assert ok["met"] == 3 and ok["missing"] == [] and ok["price_gap_pct"] == 0
    bad = mc.coin_status(close=90, ema50=100, ema100=99, ema200=110)
    assert bad["met"] == 0
    assert bad["price_gap_pct"] == pytest.approx(100 / 90 * 100 - 100)
    assert bad["trend_gap_pct"] == pytest.approx(10.0)


def base_data(**kw):
    d = {
        "stake": "USDT", "dry_run": True, "starting_balance": 1000.0,
        "realized_total": 0.0, "unrealized": 0.0, "open_trades": [], "max_open_trades": 8,
        "closed_count": 0, "bought_24h": [], "sold_24h": [],
        "regime": {"btc": 59920.0, "sma200": 72291.0},
        "coins": [
            {"pair": "ETH/USDT", **mc.coin_status(1662, 1750, 1800, 1900)},
            {"pair": "BCH/USDT", **mc.coin_status(207, 205, 210, 215)},
        ],
    }
    d.update(kw)
    return d


def test_compose_bear_market_explains_why_no_trades():
    text = mc.compose(base_data())
    assert "(paper trading)" in text
    assert "Trading capital: 1,000.00 USDT, profit +0.00 USDT (+0.00%)" in text
    assert "Trades: 0/8 open, 0 closed so far" in text
    assert "No. BTC 59,920 is 17.1% below its 200-day average (72,291)" in text
    assert "+20.6% from here" in text
    assert text.index("BCH: 1/3") < text.index("ETH: 0/3")  # closest to a buy first
    assert "Last 24h: bought nothing; sold nothing" in text


def test_compose_bull_market_with_trades():
    text = mc.compose(base_data(
        regime={"btc": 80000.0, "sma200": 72000.0},
        realized_total=12.0, unrealized=8.0, closed_count=3,
        open_trades=[{"pair": "SOL/USDT", "profit_abs": 8.0, "profit_pct": 6.5, "days": 2.2}],
        bought_24h=["SOL/USDT"], sold_24h=[{"pair": "XRP/USDT", "profit_pct": -3.0}],
        coins=[{"pair": "SOL/USDT", **mc.coin_status(110, 100, 95, 90)}],
    ))
    assert "Trading capital: 1,020.00 USDT, profit +20.00 USDT (+2.00%)" in text
    assert "SOL/USDT: +6.50% (+8.00 USDT), 2d" in text
    assert "bought SOL; sold XRP -3.00%" in text
    assert text.count("Yes. BTC 80,000") == 1
    assert "✅ SOL: 3/3, buy signal" in text


def test_regime_alert_text():
    up = mc.compose_regime_alert(True, {"btc": 73000.0, "sma200": 72000.0}, 0)
    assert "above its 200-day average" in up and "may buy again" in up
    down = mc.compose_regime_alert(False, {"btc": 70000.0, "sma200": 72000.0}, 2)
    assert "sells its open trades" in down


# --- strategy hook -------------------------------------------------------------------------

freqtrade = pytest.importorskip("freqtrade")
from freqtrade.enums import RunMode  # noqa: E402
from Craider import Craider  # noqa: E402


def btc_daily(last_close):
    dates = pd.date_range("2026-01-01", periods=250, freq="D", tz="UTC")
    return pd.DataFrame({"date": dates, "close": [100.0] * 249 + [last_close]})


def make_strategy(tmp_path):
    config = json.loads((ROOT / "user_data" / "config.json").read_text())
    config["weekly_digest"]["enabled"] = False
    config["user_data_dir"] = tmp_path
    config["logfile"] = None
    strat = Craider(config)
    strat.dp = MagicMock(runmode=RunMode.DRY_RUN)
    coin = pd.DataFrame({"close": [207.0], "ema50": [205.0], "ema100": [210.0], "ema200": [215.0]})
    strat.dp.get_analyzed_dataframe.return_value = (coin, None)
    strat.dp.get_pair_dataframe.return_value = btc_daily(80.0)
    strat.dp.current_whitelist.return_value = ["BCH/USDT"]
    strat.wallets = MagicMock()
    strat.wallets.get_starting_balance.return_value = 1000.0
    strat.bot_start()
    return strat


@patch("Craider.Trade")
def test_strategy_sends_daily_check_and_regime_alert(trade, tmp_path):
    trade.get_trades_proxy.return_value = []
    trade.get_total_closed_profit.return_value = 0.0
    strat = make_strategy(tmp_path)

    strat.bot_loop_start(current_time=NOW)          # first run: daily check right away
    strat.bot_loop_start(current_time=NOW + timedelta(seconds=5))
    strat.dp.send_msg.assert_called_once()
    text = strat.dp.send_msg.call_args.args[0]
    assert "Craider daily check" in text and "No. BTC 80" in text and "BCH: 1/3" in text

    strat.dp.send_msg.reset_mock()
    strat.dp.get_pair_dataframe.return_value = btc_daily(150.0).assign(
        date=lambda df: df["date"] + pd.Timedelta(days=1))  # new daily candle, BTC above SMA
    strat.bot_loop_start(current_time=NOW + timedelta(hours=1))
    strat.bot_loop_start(current_time=NOW + timedelta(hours=2))
    strat.dp.send_msg.assert_called_once()
    assert "closed above its 200-day average" in strat.dp.send_msg.call_args.args[0]


def test_no_messages_in_backtesting(tmp_path):
    config = json.loads((ROOT / "user_data" / "config.json").read_text())
    config["user_data_dir"] = tmp_path
    strat = Craider(config)
    strat.dp = MagicMock(runmode=RunMode.BACKTEST)
    strat.bot_start()
    strat.bot_loop_start(current_time=NOW)
    strat.dp.send_msg.assert_not_called()
    assert not (tmp_path / mc.STATE_FILE).exists()

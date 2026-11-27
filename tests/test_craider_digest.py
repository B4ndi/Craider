"""Runs the strategy's digest hook with Freqtrade's real Craider class and mocked bot internals."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

pytest.importorskip("freqtrade")
from freqtrade.enums import RunMode  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))
from Craider import Craider  # noqa: E402

NOW = datetime(2026, 11, 29, 18, 0, 5, tzinfo=timezone.utc)


def make_strategy(tmp_path, runmode=RunMode.DRY_RUN, **digest):
    config = json.loads((ROOT / "user_data" / "config.json").read_text())
    config["weekly_digest"].update(digest)
    config["user_data_dir"] = tmp_path
    config["logfile"] = None
    strat = Craider(config)
    strat.dp = MagicMock(runmode=runmode)
    strat.dp.get_analyzed_dataframe.return_value = (pd.DataFrame({"close": [110.0]}), None)
    strat.dp.get_pair_dataframe.return_value = pd.DataFrame({"close": [100.0] * 199 + [150.0]})
    strat.dp.current_whitelist.return_value = ["BTC/USDT", "ETH/USDT"]
    strat.wallets = MagicMock()
    strat.wallets.get_starting_balance.return_value = 1000.0
    strat.bot_start()
    return strat


def open_trade():
    t = MagicMock(pair="ETH/USDT", open_rate=100.0, open_date_utc=NOW - timedelta(days=2))
    t.calc_profit.return_value = 5.0
    t.calc_profit_ratio.return_value = 0.1
    return t


@patch("Craider.Trade")
def test_digest_sent_once_at_slot(trade, tmp_path):
    trade.get_trades_proxy.side_effect = lambda is_open, **kw: [open_trade()] if is_open else []
    trade.get_total_closed_profit.return_value = 20.0
    strat = make_strategy(tmp_path)
    strat.bot_loop_start(current_time=NOW - timedelta(days=3))  # first run: only records state
    strat.dp.send_msg.assert_not_called()
    strat.bot_loop_start(current_time=NOW)
    strat.bot_loop_start(current_time=NOW + timedelta(seconds=5))
    strat.dp.send_msg.assert_called_once()
    text = strat.dp.send_msg.call_args.args[0]
    assert "Overall: +25.00 USDT (+2.50%)" in text
    assert "ETH/USDT: +10.00%" in text
    assert "above its 200-day average" in text
    assert "BTC, ETH" in text


@patch("Craider.Trade")
def test_error_does_not_retry_every_loop(trade, tmp_path):
    trade.get_trades_proxy.side_effect = RuntimeError("db down")
    strat = make_strategy(tmp_path, send_on_startup=True)
    strat.bot_loop_start(current_time=NOW)
    strat.bot_loop_start(current_time=NOW + timedelta(seconds=5))
    strat.dp.send_msg.assert_not_called()
    assert trade.get_trades_proxy.call_count == 1


def test_no_digest_in_backtesting(tmp_path):
    strat = make_strategy(tmp_path, RunMode.BACKTEST, send_on_startup=True)
    strat.bot_loop_start(current_time=NOW)
    strat.dp.send_msg.assert_not_called()
    assert not (tmp_path / "weekly_digest_state.json").exists()

import json
import os
import tempfile
import unittest

import craider_watchdog as wd


def settings(**kw):
    base = dict(
        telegram_token="t",
        telegram_chat_id="c",
        api_url="http://craider:8080",
        api_username="u",
        api_password="p",
    )
    base.update(kw)
    return wd.Settings(**base)


class FakeHttp:
    """Maps URL substrings to a response value or an exception."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, headers=None, data=None):
        self.calls.append((method, url, headers, data))
        for key, value in self.routes.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"unexpected url {url}")


NOW = 1_800_000_000.0


class CheckBotTest(unittest.TestCase):
    def routes(self, **over):
        r = {
            "/ping": {"status": "pong"},
            "/health": {"last_process_ts": NOW - 30},
            "/show_config": {"state": "running"},
        }
        r.update(over)
        return r

    def test_ok(self):
        self.assertEqual(wd.check_bot(settings(), NOW, FakeHttp(self.routes())), (True, ""))

    def test_paused_is_ok(self):
        http = FakeHttp(self.routes(**{"/show_config": {"state": "paused"}}))
        self.assertTrue(wd.check_bot(settings(), NOW, http)[0])

    def test_container_down(self):
        http = FakeHttp(self.routes(**{"/ping": OSError("connection refused")}))
        ok, detail = wd.check_bot(settings(), NOW, http)
        self.assertFalse(ok)
        self.assertIn("not answering", detail)

    def test_stopped(self):
        http = FakeHttp(self.routes(**{"/show_config": {"state": "stopped"}}))
        ok, detail = wd.check_bot(settings(), NOW, http)
        self.assertFalse(ok)
        self.assertIn("/start", detail)

    def test_stale_loop(self):
        http = FakeHttp(self.routes(**{"/health": {"last_process_ts": NOW - 600}}))
        ok, detail = wd.check_bot(settings(), NOW, http)
        self.assertFalse(ok)
        self.assertIn("10 min ago", detail)

    def test_no_cycle_yet(self):
        http = FakeHttp(self.routes(**{"/health": {"last_process_ts": None}}))
        self.assertFalse(wd.check_bot(settings(), NOW, http)[0])

    def test_bad_login(self):
        http = FakeHttp(self.routes(**{"/health": wd.HttpError(401, "nope")}))
        ok, detail = wd.check_bot(settings(), NOW, http)
        self.assertFalse(ok)
        self.assertIn("login", detail)

    def test_sends_basic_auth(self):
        http = FakeHttp(self.routes())
        wd.check_bot(settings(), NOW, http)
        health_call = [c for c in http.calls if "/health" in c[1]][0]
        self.assertEqual(health_call[2]["Authorization"], "Basic dTpw")  # u:p


class CheckExchangeTest(unittest.TestCase):
    def test_ok_without_key_only_pings(self):
        http = FakeHttp({"/api/v3/ping": {}})
        self.assertEqual(wd.check_exchange(settings(), NOW, http), (True, ""))
        self.assertEqual(len(http.calls), 1)

    def test_unreachable(self):
        http = FakeHttp({"/api/v3/ping": OSError("timed out")})
        ok, detail = wd.check_exchange(settings(), NOW, http)
        self.assertFalse(ok)
        self.assertIn("unreachable", detail)

    def test_signed_account_check(self):
        http = FakeHttp({"/api/v3/ping": {}, "/api/v3/account": {"balances": []}})
        s = settings(binance_key="k", binance_secret="s")
        self.assertTrue(wd.check_exchange(s, NOW, http)[0])
        _, url, headers, _ = http.calls[1]
        self.assertIn("signature=", url)
        self.assertEqual(headers["X-MBX-APIKEY"], "k")

    def test_rejected_key(self):
        err = wd.HttpError(401, '{"code":-2015,"msg":"Invalid API-key, IP, or permissions"}')
        http = FakeHttp({"/api/v3/ping": {}, "/api/v3/account": err})
        ok, detail = wd.check_exchange(settings(binance_key="k", binance_secret="s"), NOW, http)
        self.assertFalse(ok)
        self.assertIn("rejects the API key", detail)


class WatchdogAlertTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.result = (True, "")
        self.dog = wd.Watchdog(
            settings=settings(down_minutes=10, remind_hours=6),
            send=self.sent.append,
            checks={"bot": lambda now: self.result},
        )

    def run_at(self, minutes):
        return self.dog.run_once(NOW + minutes * 60)

    def test_quiet_while_ok(self):
        for m in range(30):
            self.assertTrue(self.run_at(m))
        self.assertEqual(self.sent, [])

    def test_short_blip_is_ignored(self):
        self.result = (False, "down")
        self.assertTrue(self.run_at(0))
        self.assertTrue(self.run_at(5))
        self.result = (True, "")
        self.run_at(6)
        self.assertEqual(self.sent, [])

    def test_alert_reminder_and_recovery(self):
        self.result = (False, "container gone")
        self.run_at(0)
        self.run_at(9)
        self.assertEqual(self.sent, [])
        self.assertFalse(self.run_at(10))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("container gone", self.sent[0])
        self.run_at(11)
        self.run_at(60)
        self.assertEqual(len(self.sent), 1)  # no spam
        self.run_at(10 + 6 * 60)
        self.assertEqual(len(self.sent), 2)
        self.assertIn("still down", self.sent[1])
        self.result = (True, "")
        self.assertTrue(self.run_at(400))
        self.assertEqual(len(self.sent), 3)
        self.assertIn("OK again", self.sent[2])
        self.assertIn("6 h 40 min", self.sent[2])

    def test_crashing_check_counts_as_failure(self):
        def boom(now):
            raise RuntimeError("bug")

        self.dog.checks = {"bot": boom}
        self.run_at(0)
        self.run_at(10)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("crashed", self.sent[0])

    def test_telegram_failure_does_not_crash(self):
        def bad_send(text):
            raise OSError("telegram down")

        self.dog.send = bad_send
        self.result = (False, "x")
        self.run_at(0)
        self.run_at(10)  # must not raise


class LoadSettingsTest(unittest.TestCase):
    def write(self, cfg):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(cfg, fh)
        self.addCleanup(os.remove, path)
        return path

    def full(self):
        return {
            "exchange": {"key": "PASTE_BINANCE_API_KEY", "secret": "PASTE_BINANCE_API_SECRET"},
            "telegram": {"enabled": True, "token": "tok", "chat_id": "123"},
            "api_server": {
                "enabled": True,
                "listen_port": 8080,
                "username": "craider",
                "password": "pw",
            },
        }

    def test_loads_and_ignores_placeholder_keys(self):
        s = wd.load_settings(self.write(self.full()), {"WATCHDOG_DOWN_MINUTES": "15"})
        self.assertEqual(s.api_url, "http://craider:8080")
        self.assertEqual(s.binance_key, "")
        self.assertEqual(s.down_minutes, 15)

    def test_missing_api_server_is_explained(self):
        cfg = self.full()
        del cfg["api_server"]
        with self.assertRaisesRegex(ValueError, "api_server"):
            wd.load_settings(self.write(cfg), {})

    def test_example_config_has_everything_but_secrets(self):
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "user_data", "config.private.example.json")
        with open(path) as fh:
            cfg = json.load(fh)
        self.assertTrue(cfg["api_server"]["enabled"])
        self.assertEqual(cfg["api_server"]["listen_ip_address"], "0.0.0.0")


class DeadmanTest(unittest.TestCase):
    def test_ok_and_fail_urls(self):
        http = FakeHttp({"hc-ping": "OK"})
        wd.ping_deadman("https://hc-ping.com/abc", True, http)
        wd.ping_deadman("https://hc-ping.com/abc", False, http)
        self.assertEqual([c[1] for c in http.calls], ["https://hc-ping.com/abc", "https://hc-ping.com/abc/fail"])

    def test_disabled(self):
        http = FakeHttp({})
        wd.ping_deadman("", True, http)
        self.assertEqual(http.calls, [])


if __name__ == "__main__":
    unittest.main()

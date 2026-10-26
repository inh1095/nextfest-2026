import copy
import json
import sys
import tempfile
import unittest
import urllib.error
from urllib.parse import parse_qs, urlsplit
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import UTC, stamp
from fleet import (Client, Paused, adjacent, blank_history, collect_fleet,
                   history_path, load_json, range_summary, reserve, save)

NOW = datetime(2026, 10, 20, 9, tzinfo=UTC)


def sample(value, at=NOW, status="ok", gid="a"):
    return {"game_id": gid, "metric": "demo_ccu", "observed_at": stamp(at),
            "status": status, "value": value, "error_code": None,
            "source_url": "https://api.steampowered.com/example"}


class FakeClient:
    calls = []
    failed_app = None

    def __init__(self, stop, allowance, **kwargs):
        self.used = 0
        self.allowance = allowance
        self.reason = None

    def get(self, url, channel):
        if self.used >= self.allowance or channel["used"] >= channel["limit"]:
            raise Paused("request_budget")
        self.used += 1
        channel["used"] += 1
        self.calls.append(url)
        if self.failed_app and f"appid={self.failed_app}" in url:
            raise ValueError("invalid_response")
        if "GetNewsForApp" in url:
            return {"appnews": {"newsitems": []}}
        return {"response": {"result": 1, "player_count": 0}}


class FleetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        actual = datetime.now(UTC)
        self.config = {
            "schema_version": 2,
            "event": {"starts_at": stamp(actual - timedelta(days=1)),
                      "ends_at": stamp(actual + timedelta(days=1))},
            "collection": {"stops_at": stamp(actual + timedelta(days=1)),
                           "interval_minutes": 20, "ccu_request_budget": 2,
                           "news_request_budget": 4, "daily_request_budget": 100,
                           "priority_game_ids": [], "min_request_interval_seconds": .5},
            "games": [],
        }
        self.catalog = {"games": [{"id": "a", "app_id": 10, "demo_app_id": 11},
                                 {"id": "b", "app_id": 20, "demo_app_id": 21}]}
        save(self.root / "config/manifest.json", self.config)
        save(self.root / "site/data/catalog.json", self.catalog)
        FakeClient.calls = []
        FakeClient.failed_app = None

    def test_full_news_scan_retains_source_summary_and_appends_only_new_candidate_versions(self):
        class FullNewsClient(FakeClient):
            def get(client, url, channel):
                result = super().get(url, channel)
                if 'GetNewsForApp' not in url:
                    return result
                query = parse_qs(urlsplit(url).query)
                self.assertEqual(query['maxlength'], ['0'])
                app = int(query['appid'][0])
                return {'appnews': {'appid': app, 'newsitems': [{
                    'appid': app, 'gid': str(app * 100), 'date': int(datetime.now(UTC).timestamp()) - 60,
                    'title': 'Development news', 'feedname': 'steam_community_announcements',
                    'url': f'https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/{app * 100}',
                    'contents': 'Development details. ' * 50 + 'We reached 10000 wishlists.'}]}}
        self.config['collection']['news_fulltext_enabled'] = True
        save(self.root / 'config/manifest.json', self.config)
        collect_fleet(self.root, mode='news', client_factory=FullNewsClient, run_id='full-news')
        before = load_json(history_path(self.root, 'a'))
        self.assertEqual(len(before['numeric_mentions']), 2)
        self.assertNotIn('10000', before['events'][0]['summary'])
        self.assertIn('10000', before['numeric_mentions'][0]['quote'])
        collect_fleet(self.root, mode='news', client_factory=FullNewsClient, run_id='full-news-again')
        after = load_json(history_path(self.root, 'a'))
        self.assertEqual(before['events'], after['events'])
        self.assertEqual(before['numeric_mentions'], after['numeric_mentions'])
    def tearDown(self):
        self.temp.cleanup()

    def test_missing_only_skips_retained_game_and_persists_new_zero(self):
        hist = blank_history(NOW)
        old = sample(5, datetime.now(UTC) - timedelta(hours=1))
        hist["samples"] = [old]
        save(history_path(self.root, "a"), hist)
        result = collect_fleet(self.root, full=True, mode="ccu", missing_only=True,
                               client_factory=FakeClient, run_id="initial")
        self.assertEqual(len(FakeClient.calls), 1)
        self.assertIn("appid=21", FakeClient.calls[0])
        self.assertEqual(load_json(history_path(self.root, "a"))["samples"], [old])
        self.assertEqual(load_json(history_path(self.root, "b"))["samples"][0]["value"], 0)
        self.assertEqual(result["coverage"]["ccu_ok"], 2)

    def test_one_failed_game_does_not_erase_another_game(self):
        FakeClient.failed_app = 11
        result = collect_fleet(self.root, mode="ccu", client_factory=FakeClient, run_id="failed")
        self.assertEqual(result["coverage"]["ccu_error"], 1)
        self.assertEqual(result["coverage"]["ccu_ok"], 1)
        self.assertIsNone(load_json(history_path(self.root, "a"))["samples"][0]["value"])

    def test_repeated_run_id_does_not_repeat_requests(self):
        collect_fleet(self.root, mode="ccu", client_factory=FakeClient, run_id="once")
        count = len(FakeClient.calls)
        collect_fleet(self.root, mode="ccu", client_factory=FakeClient, run_id="once")
        self.assertEqual(len(FakeClient.calls), count)

    def test_fair_cursor_moves_after_failure(self):
        self.config["collection"]["ccu_request_budget"] = 1
        save(self.root / "config/manifest.json", self.config)
        FakeClient.failed_app = 11
        collect_fleet(self.root, mode="ccu", client_factory=FakeClient, run_id="first")
        collect_fleet(self.root, mode="ccu", client_factory=FakeClient, run_id="second")
        self.assertEqual(len(FakeClient.calls), 2)
        self.assertIn("appid=11", FakeClient.calls[0])
        self.assertIn("appid=21", FakeClient.calls[1])

    def test_news_checks_both_base_and_demo_without_inventing_events(self):
        result = collect_fleet(self.root, mode="news", client_factory=FakeClient, run_id="news")
        self.assertEqual(len(FakeClient.calls), 4)
        self.assertEqual(result["coverage"]["news_checked"], 2)
        self.assertEqual(load_json(history_path(self.root, "a"))["events"], [])

    def test_reserved_budget_counts_abandoned_runs(self):
        self.config["collection"]["daily_request_budget"] = 7
        first = reserve(self.root, self.config, "interrupted", 6)
        second = reserve(self.root, self.config, "next", 6)
        self.assertEqual(first["allowance"], 6)
        self.assertEqual(second["allowance"], 1)
        self.assertEqual(reserve(self.root, self.config, "next", 6), second)

    def test_end_guard_never_calls_client(self):
        self.config["collection"]["stops_at"] = stamp(datetime.now(UTC) - timedelta(seconds=1))
        save(self.root / "config/manifest.json", self.config)
        result = collect_fleet(self.root, client_factory=lambda *args, **kwargs: self.fail("network client created"))
        self.assertEqual(result["collection_status"], "archived")

    def test_retry_budget_counts_and_preserves_http_failure(self):
        calls = []
        def opener(*args, **kwargs):
            calls.append(1)
            raise urllib.error.HTTPError("https://api.steampowered.com/test", 503, "down", {}, None)
        client = Client(NOW + timedelta(hours=1), 1, clock=lambda: NOW, opener=opener, spacing=.001)
        with self.assertRaises(urllib.error.HTTPError):
            client.get("https://api.steampowered.com/test", {"used": 0, "limit": 1})
        self.assertEqual(len(calls), 1)
        self.assertEqual(client.used, 1)

    def test_cutoff_and_empty_budget_never_open_connection(self):
        for stop, budget in [(NOW, 2), (NOW + timedelta(hours=1), 0)]:
            client = Client(stop, budget, clock=lambda: NOW,
                            opener=lambda *args, **kwargs: self.fail("unexpected request"))
            with self.assertRaises(Paused):
                client.get("https://api.steampowered.com/test", {"used": 0, "limit": 2})

    def test_window_peak_zero_denominator_and_failed_gap(self):
        rows = [sample(999, NOW - timedelta(days=2)), sample(0),
                sample(10, NOW + timedelta(minutes=20))]
        result = range_summary(rows, NOW - timedelta(hours=6), NOW + timedelta(hours=1), 70)
        self.assertEqual(result["peak"], 10)
        self.assertIsNone(result["max_increase"]["percent"])
        rows.insert(2, sample(None, NOW + timedelta(minutes=10), "error"))
        result = range_summary(rows, NOW - timedelta(hours=6), NOW + timedelta(hours=1), 70)
        self.assertIsNone(result["max_increase"])
        self.assertIsNone(adjacent(sample(1), sample(10, NOW + timedelta(hours=2)), 70))


if __name__ == "__main__":
    unittest.main()

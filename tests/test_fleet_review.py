"""Independent fleet regressions. All writes use TemporaryDirectory fixtures."""
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import UTC, stamp
from fleet import (
    Paused, blank_history, build_indexes, collect_fleet, history_path,
    load_json, read_state, reserve, save, state_path,
)


class ReviewClient:
    calls = []
    paused_app = None
    lock = threading.Lock()

    def __init__(self, stop, allowance, **kwargs):
        self.used = 0
        self.allowance = allowance
        self.reason = None

    def get(self, url, channel):
        if self.paused_app and f"appid={self.paused_app}" in url:
            raise Paused("runtime_budget")
        with self.lock:
            if self.used >= self.allowance or channel["used"] >= channel["limit"]:
                raise Paused("request_budget")
            self.used += 1
            channel["used"] += 1
            self.calls.append(url)
        if "GetNewsForApp" in url:
            return {"appnews": {"newsitems": []}}
        return {"response": {"result": 1, "player_count": 7}}


class FleetReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = datetime.now(UTC).replace(microsecond=0)
        self.config = {
            "schema_version": 2,
            "event": {
                "starts_at": stamp(self.now - timedelta(days=1)),
                "ends_at": stamp(self.now + timedelta(days=2)),
            },
            "collection": {
                "stops_at": stamp(self.now + timedelta(days=2)),
                "interval_minutes": 20,
                "ccu_request_budget": 2,
                "news_request_budget": 4,
                "daily_request_budget": 100,
                "priority_game_ids": [],
                "min_request_interval_seconds": .5,
            },
            "games": [],
        }
        self.catalog = {
            "games": [
                {"id": "a", "app_id": 10, "demo_app_id": 11},
                {"id": "b", "app_id": 20, "demo_app_id": 21},
                {"id": "c", "app_id": 30, "demo_app_id": 31},
                {"id": "d", "app_id": 40, "demo_app_id": 41},
            ],
        }
        self.persist()
        ReviewClient.calls = []
        ReviewClient.paused_app = None

    def tearDown(self):
        self.temp.cleanup()

    def persist(self):
        save(self.root / "config/manifest.json", self.config)
        save(self.root / "site/data/catalog.json", self.catalog)

    def sample(self, value, when, status="ok", gid="a"):
        return {
            "game_id": gid, "metric": "demo_ccu", "observed_at": stamp(when),
            "value": value, "status": status,
            "source_url": "https://api.steampowered.com/example",
            "error_code": "network_error" if status == "error" else None,
        }

    def run_collection(self, run_id, *, clock_now=None, mode="ccu", **kwargs):
        fixed_now = clock_now or self.now

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now if tz else fixed_now.replace(tzinfo=None)

        with patch("fleet.datetime", FixedDatetime):
            return collect_fleet(
                self.root, run_id=run_id, mode=mode,
                client_factory=ReviewClient, **kwargs,
            )

    def test_started_incomplete_reservation_cannot_be_reused(self):
        reserve(self.root, self.config, "crashed", 10, now=self.now)
        state = read_state(self.root)
        state["reservations"]["crashed"]["started_at"] = stamp(self.now)
        save(state_path(self.root), state)
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_collection("crashed")
        self.assertEqual(ReviewClient.calls, [])

    def test_partial_full_scan_does_not_change_regular_cursor_coordinates(self):
        self.config["collection"]["priority_game_ids"] = ["a"]
        self.persist()
        state = read_state(self.root)
        state.update(ccu_cursor=1, full_ccu_cursor=2)
        save(state_path(self.root), state)
        ReviewClient.paused_app = 31
        self.run_collection("full-paused", full=True)
        state = read_state(self.root)
        self.assertEqual(state["ccu_cursor"], 1)
        self.assertEqual(state["full_ccu_cursor"], 2)
        ReviewClient.paused_app = None
        ReviewClient.calls = []
        self.run_collection("normal-after-full")
        self.assertTrue(any("appid=31" in url for url in ReviewClient.calls))
        self.assertEqual(read_state(self.root)["ccu_cursor"], 2)

    def test_reservation_cannot_be_reused_on_another_utc_day(self):
        reserve(self.root, self.config, "old-day", 10, now=self.now)
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_collection("old-day", clock_now=self.now + timedelta(days=1))
        self.assertEqual(ReviewClient.calls, [])

    def test_completed_unused_reservation_stays_conservatively_charged(self):
        self.config["collection"]["daily_request_budget"] = 10
        reserve(self.root, self.config, "first", 6, now=self.now)
        state = read_state(self.root)
        state["reservations"]["first"].update(completed=True, used=1)
        save(state_path(self.root), state)
        second = reserve(self.root, self.config, "second", 6, now=self.now)
        self.assertEqual(second["allowance"], 4)

    def test_same_slot_skip_advances_the_completed_fair_prefix(self):
        hist = blank_history(self.now)
        hist["samples"] = [self.sample(5, self.now)]
        save(history_path(self.root, "a"), hist)
        self.run_collection("skip-prefix")
        self.assertEqual(read_state(self.root)["ccu_cursor"], 2)
        self.assertEqual(len(ReviewClient.calls), 1)
        self.assertIn("appid=21", ReviewClient.calls[0])
        self.assertEqual(load_json(history_path(self.root, "a"))["samples"], hist["samples"])

    def test_paused_front_item_is_not_skipped_by_later_completion(self):
        ReviewClient.paused_app = 11
        self.run_collection("out-of-order")
        self.assertEqual(read_state(self.root)["ccu_cursor"], 0)
        self.assertTrue(load_json(history_path(self.root, "b"))["samples"])

    def test_priority_attempt_is_not_counted_as_fair_progress(self):
        self.config["collection"]["priority_game_ids"] = ["a"]
        self.persist()
        self.run_collection("priority")
        self.assertEqual(read_state(self.root)["ccu_cursor"], 1)
        self.assertEqual(
            set(ReviewClient.calls),
            {
                "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=11",
                "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=21",
            },
        )

    def test_prior_comparable_pair_survives_latest_error_in_coverage(self):
        hist = blank_history(self.now)
        hist["samples"] = [
            self.sample(10, self.now - timedelta(minutes=40)),
            self.sample(20, self.now - timedelta(minutes=20)),
            self.sample(None, self.now - timedelta(minutes=1), "error"),
        ]
        save(history_path(self.root, "a"), hist)
        summary = build_indexes(self.root, now=self.now)
        row = next(g for g in summary["games"] if g["game_id"] == "a")
        self.assertEqual(summary["coverage"]["comparison_ready"], 1)
        self.assertIsNone(row["ranges"]["all"]["latest_adjacent"])
        self.assertEqual(row["ranges"]["all"]["max_increase"]["delta"], 10)

    def test_news_all_checked_uses_oldest_source_success(self):
        self.config["collection"]["news_request_budget"] = 1
        self.persist()
        hist = blank_history(self.now)
        old_success = stamp(self.now - timedelta(hours=4))
        latest_attempt = stamp(self.now - timedelta(minutes=1))
        hist["news_sources"] = {
            "10": {
                "status": "ok", "error_codes": [],
                "last_attempt_at": stamp(self.now - timedelta(minutes=10)),
                "last_success_at": stamp(self.now - timedelta(minutes=10)),
            },
            "11": {
                "status": "error", "error_codes": ["http_503"],
                "last_attempt_at": latest_attempt,
                "last_success_at": old_success,
            },
        }
        hist["news_status"]["a"] = {
            "status": "error", "error_codes": ["http_503"],
            "last_attempt_at": latest_attempt,
        }
        save(history_path(self.root, "a"), hist)
        summary = self.run_collection("news-refresh-one-source", mode="news")
        row = next(g for g in summary["games"] if g["game_id"] == "a")
        self.assertEqual(row["news_all_checked_at"], old_success)
        self.assertEqual(row["last_news_attempt_at"], stamp(self.now))
        self.assertEqual(row["news_status"], "error")
        persisted = load_json(history_path(self.root, "a"))
        self.assertEqual(persisted["news_sources"]["11"]["last_success_at"], old_success)

    def test_partial_news_cannot_claim_all_sources_checked(self):
        self.config["collection"]["news_request_budget"] = 1
        self.persist()
        summary = self.run_collection("news-first-source-only", mode="news")
        row = next(g for g in summary["games"] if g["game_id"] == "a")
        self.assertIsNone(row["news_all_checked_at"])
        self.assertEqual(row["news_status"], "partial")
        self.assertEqual(summary["coverage"]["news_checked"], 0)

    def test_archive_time_is_actual_first_processing_and_remains_fixed(self):
        stop = self.now - timedelta(minutes=20)
        self.config["collection"]["stops_at"] = stamp(stop)
        self.config["event"]["ends_at"] = stamp(stop)
        self.persist()
        first = build_indexes(self.root, now=self.now)
        later = build_indexes(self.root, now=self.now + timedelta(hours=1))
        self.assertEqual(first["collection_status"], "archived")
        self.assertEqual(first["archived_at"], stamp(self.now))
        self.assertEqual(later["archived_at"], first["archived_at"])


if __name__ == "__main__":
    unittest.main()

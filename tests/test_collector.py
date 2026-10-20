import copy
import sys
import unittest
import urllib.error
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import CollectionClosed, collect, fetch_json, news_events, parse_ccu

NOW = datetime(2026, 10, 20, 7, 0, tzinfo=timezone.utc)
CONFIG = {
    "event": {"starts_at": "2026-10-19T17:00:00Z", "ends_at": "2026-10-26T17:00:00Z"},
    "collection": {"stops_at": "2026-10-26T17:00:00Z", "interval_minutes": 20, "news_interval_minutes": 180},
    "games": [
        {"id": "a", "app_id": 10, "demo_app_id": 11, "metrics": [
            {"key": "demo_ccu", "availability": "available", "source_url": "https://example.test"},
            {"key": "followers", "availability": "unavailable", "source_url": "https://example.test"},
        ]},
        {"id": "b", "app_id": 20, "demo_app_id": 21, "metrics": [
            {"key": "demo_ccu", "availability": "available", "source_url": "https://example.test"},
        ]},
    ],
}


def fake_fetch(url):
    if "GetNewsForApp" in url:
        return {"appnews": {"newsitems": []}}
    return {"response": {"result": 1, "player_count": 0}}


class CollectorTests(unittest.TestCase):
    def test_real_zero_and_unavailable_are_distinct(self):
        data = collect(CONFIG, {}, now=NOW, fetch=fake_fetch)
        self.assertEqual(data["samples"][0]["value"], 0)
        unavailable = [s for s in data["samples"] if s["metric"] == "followers"][0]
        self.assertIsNone(unavailable["value"])
        self.assertEqual(unavailable["status"], "unavailable")

    def test_collection_end_makes_no_network_requests_and_archives_once(self):
        calls = []
        config = copy.deepcopy(CONFIG)
        config["collection"]["stops_at"] = "2026-10-20T07:00:00Z"
        data = collect(config, {}, now=NOW, fetch=lambda url: calls.append(url))
        self.assertEqual(data["collection_status"], "archived")
        again = collect(config, copy.deepcopy(data), now=NOW.replace(hour=8), fetch=lambda url: calls.append(url))
        self.assertEqual(data, again)
        self.assertEqual(calls, [])

    def test_before_event_does_not_collect(self):
        calls = []
        data = collect(CONFIG, {}, now=NOW.replace(day=18), fetch=lambda url: calls.append(url))
        self.assertEqual(data["collection_status"], "pending")
        self.assertEqual(calls, [])

    def test_retry_does_not_start_after_cutoff(self):
        moments = iter([NOW, NOW.replace(minute=1)])
        cutoff = NOW.replace(second=30)
        with patch("collect.urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            "https://api.steampowered.com/test", 429, "rate limited", {}, None
        )) as request, patch("collect.time.sleep"):
            with self.assertRaises(CollectionClosed):
                fetch_json("https://api.steampowered.com/test", cutoff=cutoff, clock=lambda: next(moments))
        self.assertEqual(request.call_count, 1)

    def test_same_slot_is_idempotent(self):
        data = collect(CONFIG, {}, now=NOW, fetch=fake_fetch)
        count = len(data["samples"])
        data = collect(CONFIG, data, now=NOW.replace(minute=8), fetch=lambda _: self.fail("duplicate request"))
        self.assertEqual(len(data["samples"]), count)

    def test_one_game_error_preserves_others_and_prior_readings(self):
        data = collect(CONFIG, {}, now=NOW, fetch=fake_fetch)
        prior = copy.deepcopy(data["samples"])
        def failure(url):
            if "appid=11" in url:
                raise ValueError("bad_response")
            return fake_fetch(url)
        data = collect(CONFIG, data, now=NOW.replace(minute=25), fetch=failure)
        for sample in prior:
            self.assertIn(sample, data["samples"])
        recent = [s for s in data["samples"] if s["observed_at"].endswith("07:25:00Z")]
        self.assertEqual([(s["game_id"], s["status"], s["value"]) for s in recent],
                         [("a", "error", None), ("b", "ok", 0)])

    def test_invalid_ccu_is_not_zero(self):
        for payload in (
            {"response": {"result": 42, "player_count": 0}},
            {"response": {"result": 1, "player_count": -1}},
            {"response": {"result": 1, "player_count": True}},
            {"response": {"result": 1, "player_count": "10"}},
            {"html": "challenge"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_ccu(payload)

    def test_news_publication_does_not_invent_occurrence(self):
        payload = {"appnews": {"newsitems": [{
            "feedname": "steam_community_announcements", "gid": "1234",
            "url": "https://store.steampowered.com/news/app/10/view/1234",
            "date": 1792472400, "title": "<b>Demo tomorrow</b>",
            "contents": "Coming <script>hidden</script> soon",
        }]}}
        event = news_events(payload, "a", "2026-10-20T07:00:00Z")[0]
        self.assertIsNone(event["occurred_at"])
        self.assertIsNotNone(event["published_at"])
        self.assertNotIn("<", event["title"])

    def test_unofficial_news_is_filtered(self):
        payload = {"appnews": {"newsitems": [{
            "feedname": "external_blog", "gid": "1234", "url": "https://evil.test",
            "date": 1792472400, "title": "News",
        }]}}
        self.assertEqual(news_events(payload, "a", "2026-10-20T07:00:00Z"), [])

    def test_official_steam_cdn_news_url_is_preserved(self):
        source = "https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/1846651706691546"
        item = {"feedname": "steam_community_announcements", "gid": "1846651706691546",
                "url": source, "date": 1792429502, "title": "Hela Is at Steam Next Fest!"}
        events = news_events({"appnews": {"newsitems": [item]}}, "a", "2026-10-20T07:00:00Z")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source_url"], source)
        item["url"] = "https://steamstore-a.akamaihd.net/news/externalpost/unverified_blog/1846651706691546"
        self.assertEqual(news_events({"appnews": {"newsitems": [item]}}, "a", "2026-10-20T07:00:00Z"), [])


if __name__ == "__main__":
    unittest.main()

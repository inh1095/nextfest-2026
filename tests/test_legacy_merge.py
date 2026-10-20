"""Migration must preserve both incoming legacy rows and newer fleet readings."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from merge_legacy import merge_history


class LegacyMergeTests(unittest.TestCase):
    def setUp(self):
        self.a = dict(game_id="hela", metric="demo_ccu", observed_at="2026-10-20T08:00:00Z", value=0)
        self.b = dict(self.a, observed_at="2026-10-20T08:20:00Z", value=8)
        self.c = dict(self.a, observed_at="2026-10-20T09:00:00Z", value=9)
        self.legacy = dict(samples=[self.a, self.b], events=[], analyses=[], news_status={})
        self.history = dict(samples=[self.a, self.c], events=[], analyses=[], news_status={})

    def test_union_preserves_existing_and_new_records_and_is_idempotent(self):
        before = copy.deepcopy(self.history)
        merged, added = merge_history(self.history, self.legacy, "hela")
        self.assertEqual(added, 1)
        self.assertEqual(merged["samples"], [self.a, self.b, self.c])
        self.assertEqual(self.history, before)
        again, added = merge_history(merged, self.legacy, "hela")
        self.assertEqual(added, 0)
        self.assertEqual(again, merged)

    def test_conflict_does_not_overwrite_evidence(self):
        self.legacy["samples"][0] = dict(self.a, value=100)
        with self.assertRaisesRegex(ValueError, "conflicting_legacy_samples"):
            merge_history(self.history, self.legacy, "hela")
        self.assertEqual(self.history["samples"][0]["value"], 0)

    def test_source_status_from_new_collector_is_not_replaced(self):
        self.history["news_sources"] = {"123": {"status": "ok"}}
        self.legacy["news_status"] = {"hela": {"last_attempt_at": "2026-10-20T10:00:00Z", "status": "ok"}}
        merged, _ = merge_history(self.history, self.legacy, "hela")
        self.assertEqual(merged["news_status"], {})

    def test_review_without_id_is_preserved(self):
        review = dict(game_id="hela", **{"from": "2026-10-20T08:00:00Z",
                      "to": "2026-10-20T08:20:00Z"}, reviewed_at="2026-10-20T09:00:00Z")
        self.legacy["analyses"] = [review]
        merged, _ = merge_history(self.history, self.legacy, "hela")
        self.assertEqual(merged["analyses"], [review])


if __name__ == "__main__":
    unittest.main()

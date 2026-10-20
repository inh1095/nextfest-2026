import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import parse
from fleet import collection_due


class CadenceTests(unittest.TestCase):
    config = {"event": {"starts_at": "2026-10-19T17:00:00Z"},
              "collection": {"stops_at": "2026-10-26T17:00:00Z"}}

    def test_schedule_backup_race_does_not_reserve_twice(self):
        state = {"last_run": {"started_at": "2026-10-20T10:00:00Z"}}
        self.assertFalse(collection_due(self.config, state, parse("2026-10-20T10:10:00Z")))
        self.assertTrue(collection_due(self.config, state, parse("2026-10-20T10:20:00Z")))

    def test_end_archive_overrides_cadence(self):
        state = {"last_run": {"started_at": "2026-10-26T16:59:00Z"}}
        self.assertTrue(collection_due(self.config, state, parse("2026-10-26T17:00:00Z")))

    def test_no_collection_before_event_and_first_run_allowed(self):
        self.assertFalse(collection_due(self.config, {}, parse("2026-10-19T16:00:00Z")))
        self.assertTrue(collection_due(self.config, {}, parse("2026-10-20T10:00:00Z")))

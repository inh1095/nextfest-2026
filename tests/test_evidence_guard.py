"""Mutate disposable Git evidence to verify the publication guard fails closed."""
import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from evidence_guard import check_evidence, require_preserved


class EvidenceGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "site/data/games/competitor.json"
        self.path.parent.mkdir(parents=True)
        self.original = {
            "samples": [{"game_id": "competitor", "observed_at": "2026-10-20T10:00:00Z",
                         "value": 0, "status": "ok", "source_url": "https://example.test/ccu"}],
            "events": [{"id": "news-1", "title": "Announcement"}],
            "analyses": [{"assessment": "insufficient", "reviewed_at": "2026-10-20T10:00:00Z"}],
            "generated_at": "2026-10-20T10:00:00Z",
        }
        self.write(self.original)
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                 "commit", "-qm", "Original evidence")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              capture_output=True).stdout

    def write(self, data):
        self.path.write_text(json.dumps(data))

    def check(self, baseline="HEAD"):
        with contextlib.redirect_stdout(io.StringIO()):
            return check_evidence(self.root, baseline)

    def test_new_observations_and_metadata_updates_preserve_old_evidence(self):
        new = copy.deepcopy(self.original)
        new["samples"].append({**new["samples"][0], "observed_at": "2026-10-20T11:00:00Z", "value": 7})
        new["samples"].reverse()
        new["generated_at"] = "2026-10-20T11:00:00Z"
        self.write(new)
        self.assertEqual(self.check()["preserved_records"], 3)

    def test_changes_to_zero_source_timestamp_or_status_are_rejected(self):
        for field, replacement in (("value", 12345), ("value", False),
                                   ("source_url", "https://example.test/other"),
                                   ("observed_at", "2026-10-20T09:00:00Z"),
                                   ("status", "error")):
            with self.subTest(field=field, replacement=replacement):
                new = copy.deepcopy(self.original)
                new["samples"][0][field] = replacement
                self.write(new)
                with self.assertRaisesRegex(ValueError, "evidence_changed_or_removed"):
                    self.check()

    def test_event_analysis_and_sample_removal_are_rejected(self):
        for field in ("samples", "events", "analyses"):
            with self.subTest(field=field):
                new = copy.deepcopy(self.original)
                new[field] = []
                self.write(new)
                with self.assertRaisesRegex(ValueError, "evidence_changed_or_removed"):
                    self.check()

    def test_deleted_history_is_rejected(self):
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, "evidence_file_removed_or_replaced"):
            self.check()

    def test_committed_change_is_checked_against_pre_push_revision(self):
        baseline = self.git("rev-parse", "HEAD").decode().strip()
        new = copy.deepcopy(self.original)
        new["events"][0]["title"] = "Changed old announcement"
        self.write(new)
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                 "commit", "-qm", "Change old evidence")
        with self.assertRaisesRegex(ValueError, "evidence_changed_or_removed"):
            self.check(baseline)

    def test_duplicate_record_removal_is_not_hidden_by_set_comparison(self):
        old = copy.deepcopy(self.original)
        old["samples"] *= 2
        with self.assertRaisesRegex(ValueError, "evidence_changed_or_removed"):
            require_preserved(old, self.original, "fixture")

    def test_wishlist_sources_and_methods_are_immutable_but_new_versions_are_allowed(self):
        before = {
            'disclosures': [{'id': 'statement-1', 'value': 1000, 'operator': 'gte'}],
            'follower_checks': [{'id': 'check-1', 'value': None, 'status': 'conflict'}],
            'methods': [{'id': 'method-v1', 'lower_multiplier': 7, 'upper_multiplier': 20}],
        }
        after = copy.deepcopy(before)
        after['methods'].append({'id': 'method-v2', 'lower_multiplier': 8, 'upper_multiplier': 21})
        self.assertEqual(require_preserved(before, after, 'wishlist-fixture'), 3)
        for field in before:
            with self.subTest(field=field):
                altered = copy.deepcopy(before)
                altered[field] = []
                with self.assertRaisesRegex(ValueError, 'evidence_changed_or_removed'):
                    require_preserved(before, altered, 'wishlist-fixture')

    def test_wishlist_config_is_checked_from_git_baseline(self):
        path = self.root / 'config/wishlist-evidence.json'
        path.parent.mkdir()
        path.write_text(json.dumps({'disclosures': [{'id': 'one', 'value': 1000}]}))
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                 'commit', '-qm', 'Reviewed wishlist disclosure')
        path.write_text(json.dumps({'disclosures': [{'id': 'one', 'value': 2000}]}))
        with self.assertRaisesRegex(ValueError, 'evidence_changed_or_removed'):
            self.check()

    def test_failed_push_cannot_reset_the_next_scheduled_run_baseline(self):
        self.git("branch", "evidence-approved")
        new = copy.deepcopy(self.original)
        new["samples"][0]["value"] = 12345
        self.write(new)
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                 "commit", "-qm", "Invalid evidence push")
        for event in ("push", "schedule", "workflow_dispatch"):
            with self.subTest(event=event):
                with self.assertRaisesRegex(ValueError, "evidence_changed_or_removed"):
                    self.check("evidence-approved")
        self.write(self.original)
        self.assertEqual(self.check("evidence-approved")["preserved_records"], 3)


if __name__ == "__main__":
    unittest.main()

"""Derived cadence uses stored attempts, without manufacturing samples or news logs."""
import copy
import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from collect import parse, stamp
from fleet import build_indexes, collection_metadata, history_path, news_history, observation_history
import test_validate_integrity as fixtures


class CadenceMetadataTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ValidateIntegrityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_actual_attempt_and_success_gaps_are_distinct_and_raw_files_unchanged(self):
        f = self.fixture
        paths = list((f.root / 'site/data/games').glob('*.json'))
        before = {p: p.read_bytes() for p in paths}
        summary = build_indexes(f.root, now=f.now)
        a = summary['games'][0]['observation_history']
        self.assertEqual((a['attempt_count'], a['valid_count'], a['error_count']), (5, 4, 1))
        self.assertEqual(a['first_attempt_at'], stamp(f.now - timedelta(minutes=1500)))
        self.assertEqual(a['first_valid_at'], a['first_attempt_at'])
        self.assertEqual(a['latest_attempt_interval_minutes'], 70)
        self.assertEqual(a['median_attempt_interval_minutes'], 45)
        self.assertEqual(a['latest_valid_interval_minutes'], 20)
        self.assertEqual(a['median_valid_interval_minutes'], 20)
        self.assertEqual(before, {p: p.read_bytes() for p in paths})
        f.check(summary)

    def test_empty_single_and_failed_observations_never_create_zero_gaps(self):
        f = self.fixture
        empty = observation_history([], f.now)
        self.assertEqual(empty['attempt_count'], 0)
        self.assertIsNone(empty['first_valid_at'])
        for records in ([], [f.sample('a', 0, 20)], [f.sample('a', None, 10, 'error')]):
            with self.subTest(records=records):
                h = observation_history(records, f.now)
                for key in h:
                    if 'interval_minutes' in key:
                        self.assertIsNone(h[key])
        rows = [f.sample('a', 0, 60), f.sample('a', None, 40, 'error'), f.sample('a', 10, 20)]
        h = observation_history(rows, f.now)
        self.assertEqual(h['latest_attempt_interval_minutes'], 20)
        self.assertEqual(h['latest_valid_interval_minutes'], 40)
        bounded = observation_history(rows, parse(rows[1]['observed_at']))
        self.assertEqual(bounded['attempt_count'], 2)
        self.assertEqual(bounded['valid_count'], 1)
        self.assertIsNone(bounded['latest_valid_interval_minutes'])

    def test_source_rotation_not_wishlist_collection_and_no_fabricated_news_cadence(self):
        f = self.fixture
        catalog = {'games': [{'app_id': 1, 'demo_app_id': 2}, {'app_id': 3, 'demo_app_id': None}]}
        metadata = collection_metadata(f.config, catalog)
        self.assertEqual(metadata['news_source_count'], 3)
        self.assertEqual(metadata['news_target_cycle_minutes'], 20)
        self.assertEqual(metadata['wishlist_numeric_collection'], {
            'mode': 'reviewed_disclosures_only', 'scheduled': False, 'target_interval_minutes': None})
        disabled = copy.deepcopy(f.config)
        disabled['collection']['news_request_budget'] = 0
        self.assertIsNone(collection_metadata(disabled, catalog)['news_target_cycle_minutes'])
        news = news_history([{'kind': 'video', 'published_at': '2026-01-01T00:00:00Z'},
                             {'kind': 'announcement', 'published_at': '2026-10-20T00:00:00Z'},
                             {'kind': 'update', 'published_at': '2026-10-19T00:00:00Z'}])
        self.assertEqual(news, {'event_count': 2, 'first_published_at': '2026-10-19T00:00:00Z',
                                'last_published_at': '2026-10-20T00:00:00Z'})

    def test_validator_rejects_forged_cadence_counts_bounds_and_scheduler_claims(self):
        f = self.fixture
        for field, value in [('attempt_count', 999), ('valid_count', True),
                             ('first_attempt_at', stamp(f.now)),
                             ('median_attempt_interval_minutes', 20),
                             ('latest_valid_interval_minutes', float('nan'))]:
            with self.subTest(field=field):
                f.mutate(['games', 0, 'observation_history', field], value,
                         'summary_observation_history_mismatch')
        f.mutate(['games', 0, 'news_history', 'event_count'], 1, 'summary_news_history_mismatch')
        f.mutate(['collection', 'news_target_cycle_minutes'], 1,
                 'summary_collection_news_target_cycle_minutes_mismatch')
        f.mutate(['collection', 'wishlist_numeric_collection', 'scheduled'], True,
                 'summary_collection_wishlist_numeric_collection_mismatch')


if __name__ == '__main__':
    unittest.main()

"""Recomputed public summaries reject mutations; only temporary fixtures are written."""
import copy
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from collect import UTC, stamp
from fleet import blank_history, build_indexes, history_path, read_state, save, state_path
from validate import validate


class ValidateIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 10, 21, 12, tzinfo=UTC)
        self.config = {
            'schema_version': 2,
            'event': {'starts_at': stamp(self.now - timedelta(days=2)),
                      'ends_at': stamp(self.now + timedelta(days=2))},
            'collection': {'stops_at': stamp(self.now + timedelta(days=2)),
                           'interval_minutes': 20, 'ccu_request_budget': 2,
                           'news_request_budget': 4, 'daily_request_budget': 100,
                           'priority_game_ids': ['a']},
            'games': [{'id': 'a'}],
        }
        games = []
        for i, gid in enumerate(('a', 'b', 'c'), start=1):
            demo = i * 10 + 1 if gid != 'c' else None
            games.append({'id': gid, 'app_id': i * 10, 'demo_app_id': demo,
                          'demo_app_ids': [demo] if demo else [],
                          'participation': {'source_url': 'https://store.steampowered.com/sale/nextfest',
                                            'evidence_excerpt': 'fixture registration'}})
        catalog = {'coverage': {'unique_total': 3, 'official_total': 3, 'complete': True},
                   'games': games}
        save(self.root / 'config/manifest.json', self.config)
        save(self.root / 'site/data/catalog.json', catalog)
        a = blank_history(self.now)
        a['samples'] = [self.sample('a', 999, 25 * 60), self.sample('a', 0, 120),
                        self.sample('a', 10, 100), self.sample('a', 15, 80),
                        self.sample('a', None, 10, 'error')]
        b = blank_history(self.now)
        b['samples'] = [self.sample('b', 1, 30), self.sample('b', 2, 10)]
        for gid, history in [('a', a), ('b', b), ('c', blank_history(self.now))]:
            save(history_path(self.root, gid), history)
        original = blank_history(self.now)
        original['samples'] = [copy.deepcopy(a['samples'][0])]
        save(self.root / 'site/data/observations.json', original)
        save(state_path(self.root), read_state(self.root))
        self.summary = build_indexes(self.root, now=self.now)

    def sample(self, gid, value, minutes_ago, status='ok'):
        return {'game_id': gid, 'metric': 'demo_ccu',
                'observed_at': stamp(self.now - timedelta(minutes=minutes_ago)),
                'status': status, 'value': value,
                'error_code': 'network_error' if status == 'error' else None,
                'source_url': 'https://api.steampowered.com/example'}

    def check(self, summary=None):
        save(self.root / 'site/data/summary.json', summary or self.summary)
        with redirect_stdout(io.StringIO()):
            validate(self.root)

    def mutate(self, path, value, pattern):
        changed = copy.deepcopy(self.summary)
        target = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with self.assertRaisesRegex(ValueError, pattern):
            self.check(changed)

    def test_valid_summary_uses_its_recorded_time_and_preserves_error_and_missing(self):
        self.check()
        a, b, c = self.summary['games']
        self.assertEqual(a['status'], 'error')
        self.assertEqual(a['current'], 15)
        self.assertEqual(a['ranges']['all']['peak'], 999)
        self.assertEqual(a['ranges']['24']['peak'], 15)
        self.assertEqual(a['ranges']['6']['max_increase']['delta'], 10)
        self.assertIsNone(a['ranges']['6']['max_increase']['percent'])
        self.assertIsNone(a['ranges']['6']['latest_adjacent'])
        self.assertEqual(b['ranges']['all']['max_increase']['percent'], 100)
        self.assertEqual(b['target_interval_minutes'], 40)
        self.assertIsNone(c['current'])
        self.assertEqual(c['status'], 'unavailable')

    def test_peak_mutation_rejected_in_every_window(self):
        for period in ('all', '6', '24'):
            with self.subTest(period=period):
                self.mutate(['games', 0, 'ranges', period, 'peak'], 987654321,
                            'summary_ranges_mismatch')

    def test_fractional_build_time_keeps_exact_published_window_boundaries(self):
        history = blank_history(self.now)
        history['samples'] = [self.sample('b', 999, 24 * 60),
                              self.sample('b', 0, 6 * 60),
                              self.sample('b', 10, 6 * 60 - 20)]
        path = history_path(self.root, 'b')
        save(path, history)
        before = path.read_bytes()
        self.summary = build_indexes(self.root, now=self.now.replace(microsecond=543210))
        row = self.summary['games'][1]
        self.assertEqual(self.summary['generated_at'], stamp(self.now))
        self.assertEqual(row['ranges']['6']['valid_count'], 2)
        self.assertEqual(row['ranges']['24']['valid_count'], 3)
        self.assertEqual(row['ranges']['6']['first']['observed_at'],
                         stamp(self.now - timedelta(hours=6)))
        self.assertEqual(row['ranges']['24']['peak'], 999)
        self.assertEqual(row['ranges']['6']['latest_adjacent']['delta'], 10)
        self.assertIsNone(row['ranges']['6']['latest_adjacent']['percent'])
        self.check()
        self.assertEqual(path.read_bytes(), before)

    def test_delta_percent_and_zero_denominator_mutations_rejected(self):
        for field, value in [('delta', 999), ('percent', 99), ('elapsed_minutes', 1)]:
            with self.subTest(field=field):
                self.mutate(['games', 1, 'ranges', 'all', 'max_increase', field], value,
                            'summary_ranges_mismatch')
        self.mutate(['games', 0, 'ranges', 'all', 'max_increase', 'percent'], 0,
                    'summary_ranges_mismatch')

    def test_window_bounds_are_derived_from_generated_at(self):
        for period in ('all', '6', '24'):
            for boundary in ('from', 'to'):
                with self.subTest(period=period, boundary=boundary):
                    changed = self.now if boundary == 'from' else self.now - timedelta(minutes=1)
                    self.mutate(['games', 0, 'ranges', period, boundary], stamp(changed),
                                'summary_ranges_mismatch')
        self.mutate(['window_end'], stamp(self.now - timedelta(minutes=1)),
                    'summary_window_end_mismatch')

    def test_latest_value_status_attempt_and_target_mutations_rejected(self):
        for field, value in [('current', 0), ('status', 'ok'), ('last_attempt_at', None),
                             ('last_ok_at', None), ('last_error_code', None),
                             ('target_interval_minutes', 1)]:
            with self.subTest(field=field):
                self.mutate(['games', 0, field], value, f'summary_{field}_mismatch')

    def test_boolean_and_nonfinite_statistics_are_not_numbers(self):
        for value in (True, float('nan'), float('inf')):
            with self.subTest(value=value):
                self.mutate(['games', 1, 'ranges', 'all', 'max_increase', 'delta'], value,
                            'summary_ranges_mismatch')
        self.mutate(['coverage', 'ccu_unavailable'], True, 'summary_coverage_mismatch')
        self.mutate(['games', 2, 'current'], False, 'summary_current_mismatch')

    def test_missing_range_and_fake_latest_pair_rejected(self):
        self.mutate(['games', 0, 'ranges'], {}, 'summary_ranges_mismatch')
        self.mutate(['games', 0, 'ranges', 'all', 'latest_adjacent'],
                    self.summary['games'][1]['ranges']['all']['latest_adjacent'],
                    'summary_ranges_mismatch')

    def test_original_observation_subset_check_remains_active(self):
        history = blank_history(self.now)
        history['samples'] = [self.sample('a', 1, 20)]
        save(history_path(self.root, 'a'), history)
        self.summary = build_indexes(self.root, now=self.now)
        with self.assertRaisesRegex(ValueError, 'original_evidence_not_preserved'):
            self.check()


if __name__ == '__main__':
    unittest.main()

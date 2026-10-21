"""Disabling CCU applies to every fleet mode and reservation, without deleting history."""
import copy
import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from collect import UTC
from fleet import (blank_history, collect_fleet, history_path, load_json, main,
                   read_state, request_limits, save)
import test_fleet as fixtures


class NewsOnlyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FleetTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        f = self.fixture
        f.config['collection'].update(ccu_enabled=False, default_mode='news')
        save(f.root / 'config/manifest.json', f.config)
        history = blank_history(datetime.now(UTC))
        history['samples'] = [fixtures.sample(5, datetime.now(UTC) - timedelta(hours=1))]
        save(history_path(f.root, 'a'), history)
        self.original = copy.deepcopy(history['samples'])

    def test_all_modes_full_and_missing_only_cannot_request_ccu(self):
        f = self.fixture
        for mode in (None, 'news', 'both', 'ccu'):
            for full in (False, True):
                with self.subTest(mode=mode, full=full):
                    fixtures.FakeClient.calls = []
                    summary = collect_fleet(f.root, mode=mode, full=full, missing_only=True,
                                            client_factory=fixtures.FakeClient,
                                            run_id=f'{mode}-{full}')
                    self.assertTrue(all('GetNewsForApp' in url for url in fixtures.FakeClient.calls))
                    if mode == 'ccu':
                        self.assertEqual(fixtures.FakeClient.calls, [])
                    self.assertEqual(load_json(history_path(f.root, 'a'))['samples'], self.original)
                    self.assertEqual(summary['games'][0]['current'], 5)
                    self.assertEqual(summary['games'][0]['target_interval_minutes'], 20)
                    self.assertFalse(summary['games'][0]['ccu_collection_enabled'])
                    self.assertEqual(summary['collection']['ccu_collection'],
                                     {'enabled': False, 'mode': 'stopped_preserved_history'})

    def test_cli_reserves_only_the_active_channel_even_with_full_ccu_mode(self):
        f = self.fixture
        for extra, expected in [([], 4), (['--mode', 'ccu', '--full'], 0),
                                (['--mode', 'both'], 4)]:
            run_id = 'reserve-' + str(len(read_state(f.root)['reservations']))
            argv = ['fleet.py', '--root', str(f.root), '--reserve-only', '--run-id', run_id, *extra]
            with patch.object(sys, 'argv', argv), redirect_stdout(io.StringIO()):
                main()
            self.assertEqual(read_state(f.root)['reservations'][run_id]['allowance'], expected)
        self.assertEqual(request_limits(f.config, f.catalog, 'ccu', True), (0, 0))

    def test_flag_is_boolean_and_cannot_be_truthy_string(self):
        f = self.fixture
        for invalid in (0, 1, 'false', None):
            with self.subTest(invalid=invalid):
                config = copy.deepcopy(f.config)
                config['collection']['ccu_enabled'] = invalid
                with self.assertRaisesRegex(ValueError, 'ccu_enabled_must_be_boolean'):
                    request_limits(config, f.catalog)


if __name__ == '__main__':
    unittest.main()

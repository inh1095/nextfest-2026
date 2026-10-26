"""Network-free tests for the dated public StoreBrowse context contract."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import context_metrics as cm

GAME = {'id': 'hela', 'app_id': 3161310}
AT = '2026-10-26T06:00:48Z'


def source():
    return {'id': 3161310, 'appid': 3161310, 'item_type': 0, 'success': 1,
            'basic_info': {'developers': [{'name': 'Windup'}],
                           'publishers': [{'name': ' Shochiku'}]},
            'release': {'steam_release_date': 1796119200, 'is_coming_soon': True,
                        'coming_soon_display': 'date_full'},
            'trailers': {'highlights': [{'trailer_name': 'Adventure Trailer',
                'trailer_base_id': 1378074, 'trailer_url_format': 'steam/apps/${FILENAME}?t=1791819277',
                'microtrailer': [{'filename': '3161310/example/microtrailer.webm', 'type': 'video/webm'}],
                'adaptive_trailers': [{'cdn_path': '3161310/example/hls.m3u8', 'encoding': 'hls_h264'}]}]}}


class ContextMetricsTests(unittest.TestCase):
    def test_real_field_projection_preserves_planned_dates_paths_and_whitespace(self):
        item = source(); before = deepcopy(item)
        s = cm.parse_snapshot(GAME, item, AT, batch_size=4)
        cm.validate_snapshot(s, GAME)
        self.assertEqual(s['status'], 'ok')
        self.assertEqual(s['publishers'], [' Shochiku'])
        self.assertEqual(s['source_fields'], {k: item[k] for k in cm.FIELDS})
        self.assertEqual(s['release']['steam_release_date'], 1796119200)
        self.assertNotIn('published_at', s['trailers']['highlights'][0])
        self.assertEqual(item, before)
        item['release']['steam_release_date'] = 0
        self.assertEqual(s['release']['steam_release_date'], 1796119200)

    def test_missing_fields_and_explicit_empty_are_distinct(self):
        item = source(); del item['trailers']
        s = cm.parse_snapshot(GAME, item, AT)
        self.assertEqual(s['field_status']['trailers'], 'unavailable')
        self.assertIsNone(s['trailers'])
        item['trailers'] = {'highlights': []}
        s = cm.parse_snapshot(GAME, item, AT)
        self.assertEqual(s['field_status']['trailers'], 'ok')
        self.assertEqual(s['trailers'], {'highlights': []})

    def test_tba_and_zero_original_epoch_are_preserved_not_reinterpreted(self):
        item = source(); item['release'] = {'is_coming_soon': True,
            'custom_release_date_message': '발표 예정', 'coming_soon_display': 'text_tba'}
        s = cm.parse_snapshot(GAME, item, AT)
        self.assertNotIn('steam_release_date', s['release'])
        item['release'] = {'steam_release_date': 1373389200, 'original_release_date': 0}
        self.assertEqual(cm.parse_snapshot(GAME, item, AT)['release']['original_release_date'], 0)

    def test_failed_item_uses_requested_id_but_never_copies_its_fields(self):
        item = source(); item.update(success=15, appid=0)
        s = cm.parse_snapshot(GAME, item, AT)
        self.assertEqual(s['status'], 'unavailable')
        self.assertEqual(s['store_item_success'], 15)
        self.assertEqual(s['developers'], [])
        self.assertTrue(all(v is None for v in s['source_fields'].values()))
        cm.validate_snapshot(s, GAME)

    def test_mapping_error_does_not_contaminate_other_game(self):
        for field, value in [('appid', 999), ('id', 999), ('item_type', 1), ('appid', True)]:
            item = source(); item[field] = value
            s = cm.parse_snapshot(GAME, item, AT)
            self.assertEqual(s['status'], 'error')
            self.assertEqual(s['developers'], [])

    def test_invalid_known_fields_keep_raw_evidence_and_null_projection(self):
        item = source(); item['release']['is_coming_soon'] = 'true'
        s = cm.parse_snapshot(GAME, item, AT)
        self.assertEqual(s['status'], 'error')
        self.assertEqual(s['field_status']['release'], 'error')
        self.assertIsNone(s['release'])
        self.assertEqual(s['source_fields']['release']['is_coming_soon'], 'true')
        self.assertEqual(s['developers'], ['Windup'])
        cm.validate_snapshot(s, GAME)

    def test_network_error_is_not_empty_context_success(self):
        s = cm.parse_snapshot(GAME, None, AT, error='http_429', batch_size=100)
        self.assertEqual(s['status'], 'error')
        self.assertEqual(s['error_code'], 'http_429')
        self.assertIsNone(s['raw_item_sha256'])
        cm.validate_snapshot(s, GAME)

    def test_invalid_numbers_lists_timestamps_and_batch_rejected(self):
        for value in [True, -1, float('nan')]:
            item = source(); item['release']['steam_release_date'] = value
            self.assertEqual(cm.parse_snapshot(GAME, item, AT)['status'], 'error')
        item = source(); item['basic_info']['developers'] = ['Windup']
        self.assertEqual(cm.parse_snapshot(GAME, item, AT)['status'], 'error')
        for at in ['2026-10-26', '2026-10-26T06:00:48', None]:
            with self.assertRaises(ValueError): cm.parse_snapshot(GAME, source(), at)
        with self.assertRaises(ValueError): cm.parse_snapshot(GAME, source(), AT, batch_size=True)

    def test_validator_rejects_projected_or_provenance_mutation(self):
        s = cm.parse_snapshot(GAME, source(), AT)
        for field, value in [('developers', ['Other studio']), ('app_id', 123),
                             ('raw_item_sha256', 'bad'), ('app_scope', 'demo')]:
            bad = deepcopy(s); bad[field] = value
            with self.assertRaises(ValueError): cm.validate_snapshot(bad, GAME)

    def test_request_flags_are_fresh_mutable_copy(self):
        flags = cm.request_fields(); flags['include_trailers'] = False
        self.assertTrue(cm.request_fields()['include_trailers'])

    def test_coverage_deduplicates_ids_and_uses_latest_attempt_only(self):
        item = source()
        item['trailers']['other_trailers'] = deepcopy(item['trailers']['highlights'])
        first = cm.parse_snapshot(GAME, item, AT)
        c = cm.coverage([[first], []])
        self.assertEqual(c, {'attempted_games': 1, 'ok_games': 1, 'developers_games': 1,
                             'publishers_games': 1, 'release_games': 1, 'trailer_games': 1,
                             'trailers': 1, 'last_observed_at': AT})
        failed = cm.parse_snapshot(GAME, None, '2026-10-26T07:00:48Z', error='http_429')
        c = cm.coverage({'hela': [first, failed]})
        self.assertEqual(c['attempted_games'], 1)
        self.assertEqual(c['ok_games'], 0)
        self.assertEqual(c['developers_games'], 0)
        self.assertEqual(c['trailers'], 0)
        self.assertEqual(c['last_observed_at'], failed['observed_at'])

    def test_coverage_does_not_count_blank_names_or_zero_release_timestamp(self):
        item = source(); item['basic_info']['developers'] = [{'name': ' '}]
        item['release'] = {'original_release_date': 0}; item['trailers'] = {'highlights': []}
        c = cm.coverage([[cm.parse_snapshot(GAME, item, AT)]])
        self.assertEqual(c['developers_games'], 0)
        self.assertEqual(c['release_games'], 0)
        self.assertEqual(c['trailer_games'], 0)


if __name__ == '__main__':
    unittest.main()

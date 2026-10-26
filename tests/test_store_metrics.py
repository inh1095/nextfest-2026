"""Network-free parser, preservation, cadence and public-summary regressions."""
import copy
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
import io
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import store_metrics as sm
from collect import UTC, stamp
from fleet import (collect_fleet, history_path, load_json, range_summary, save,
                   read_state, state_path, build_indexes)
from validate import validate_history
from validate import validate
from evidence_guard import require_preserved
import test_fleet
import test_validate_integrity
from test_fleet import FakeClient

GAME = {'id': 'a', 'app_id': 10}
NOW = datetime(2026, 10, 26, tzinfo=UTC)


def item(app=10, count=20, percent=80):
    return {'id': app, 'appid': app, 'item_type': 0, 'success': 1,
            'reviews': {'summary_filtered': {'review_count': count, 'percent_positive': percent}},
            'best_purchase_option': {'final_price_in_cents': '1100000',
                                     'formatted_final_price': '₩ 11,000', 'packageid': 123,
                                     'included_game_count': 1}}


class StoreParserTests(unittest.TestCase):
    def test_separate_review_scope_price_units_and_missing_discount(self):
        rows = sm.observations(GAME, item(), stamp(NOW))
        self.assertEqual([s['value'] for s in rows], [20, 80, 1100000])
        self.assertEqual(rows[0]['context']['review_scope'], 'store_summary_filtered')
        self.assertEqual(rows[2]['context']['divisor'], 100)
        self.assertIsNone(rows[2]['context']['initial'])
        self.assertIsNone(rows[2]['context']['discount_percent'])
        for row in rows:
            sm.validate_sample(row, GAME)

    def test_zero_reviews_has_unknown_percentage_and_free_is_actual_zero(self):
        value = item(count=0, percent=0)
        value.pop('best_purchase_option')
        value['is_free'] = True
        rows = sm.observations(GAME, value, stamp(NOW))
        self.assertEqual(rows[0]['value'], 0)
        self.assertIsNone(rows[1]['value'])
        self.assertEqual(rows[1]['error_code'], 'no_reviews')
        self.assertEqual(rows[2]['value'], 0)
        sm.validate_sample(rows[2], GAME)
        value['is_free'] = False
        value['is_coming_soon'] = True
        price = sm.observations(GAME, value, stamp(NOW))[2]
        self.assertIsNone(price['value'])
        self.assertEqual(price['error_code'], 'price_not_announced')

    def test_foreign_currency_display_mismatch_negative_bool_and_nonfinite_rejected(self):
        for number in [True, -1, float('nan'), float('inf'), 9007199254740992]:
            with self.subTest(number=number):
                self.assertEqual(sm.observations(GAME, item(count=number), stamp(NOW))[0]['status'], 'error')
        value = item()
        value['best_purchase_option']['formatted_final_price'] = '$11.00'
        price = sm.observations(GAME, value, stamp(NOW))[2]
        self.assertEqual(price['error_code'], 'price_currency_unverified')
        self.assertIsNone(price['value'])
        value['best_purchase_option']['formatted_final_price'] = '₩ 110'
        self.assertEqual(sm.observations(GAME, value, stamp(NOW))[2]['status'], 'error')

    def test_response_mapping_missing_is_per_game_and_duplicates_fail(self):
        self.assertEqual(sm.response_items({'response': {'store_items': []}}, [GAME]), {})
        for items in [[item(999)], [item(), item()]]:
            with self.assertRaises(ValueError):
                sm.response_items({'response': {'store_items': items}}, [GAME])

    def test_failed_item_zero_appid_is_isolated_without_relaxing_success_mapping(self):
        other = {'id': 'b', 'app_id': 20}
        failed = {'id': 20, 'appid': 0, 'item_type': 0, 'success': 15}
        result = sm.response_items({'response': {'store_items': [item(), failed]}}, [GAME, other])
        self.assertEqual(sm.observations(GAME, result[10], stamp(NOW))[0]['value'], 20)
        for row in sm.observations(other, result[20], stamp(NOW)):
            self.assertEqual(row['status'], 'unavailable')
            self.assertIsNone(row['value'])
            self.assertEqual(row['context']['store_item_success'], 15)
        for app in (None, 20):
            allowed = dict(failed, appid=app)
            if app is None:
                allowed.pop('appid')
            self.assertEqual(len(sm.response_items({'response': {'store_items': [allowed]}}, [other])), 1)
        for changed in [dict(failed, success=1), dict(failed, appid=10),
                        dict(failed, appid=False), dict(failed, id=999), dict(failed, success=True)]:
            with self.assertRaises(ValueError):
                sm.response_items({'response': {'store_items': [changed]}}, [GAME, other])
        with self.assertRaises(ValueError):
            sm.response_items({'response': {'store_items': [failed, failed]}}, [other])

    def test_retry_requires_latest_complete_same_time_error_batch(self):
        errors = sm.observations(GAME, None, stamp(NOW), error='network_error')
        self.assertTrue(sm.retryable_failure(errors))
        self.assertFalse(sm.retryable_failure(errors[:2]))
        changed = copy.deepcopy(errors)
        changed[2]['observed_at'] = stamp(NOW + timedelta(seconds=1))
        self.assertFalse(sm.retryable_failure(changed))
        for status in ('ok', 'unavailable'):
            changed = copy.deepcopy(errors)
            changed[0]['status'] = status
            changed[0]['value'] = 0 if status == 'ok' else None
            self.assertFalse(sm.retryable_failure(changed))

    def test_bundle_offer_is_not_single_game_price(self):
        value = item()
        value['best_purchase_option']['included_game_count'] = 3
        price = sm.observations(GAME, value, stamp(NOW))[2]
        self.assertEqual(price['status'], 'unavailable')
        self.assertIsNone(price['value'])
        self.assertEqual(price['context']['included_game_count'], 3)

    def test_invalid_original_price_is_one_metric_error_not_publish_failure(self):
        value = item()
        value['best_purchase_option']['original_price_in_cents'] = '1'
        rows = sm.observations(GAME, value, stamp(NOW))
        self.assertEqual(rows[0]['status'], 'ok')
        self.assertEqual(rows[2]['status'], 'error')
        self.assertIsNone(rows[2]['value'])
        self.assertFalse(rows[2]['context']['is_free_field_present'])

    def test_positive_percentage_requires_same_time_positive_review_count(self):
        rows = sm.observations(GAME, item(), stamp(NOW))
        rows[0]['value'] = 0
        history = {'samples': rows, 'events': [], 'analyses': [], 'collection_status': 'active'}
        with self.assertRaisesRegex(ValueError, 'review_percentage_without_reviews'):
            validate_history(history, {'a'}, NOW - timedelta(days=1), NOW + timedelta(days=1))

    def test_summary_keeps_good_context_after_later_failure_without_eager_ranges(self):
        config = {'collection': {'metadata_enabled': True, 'metadata_interval_minutes': 240,
                                 'interval_minutes': 20, 'metadata_request_budget': 100}}
        rows = sm.observations(GAME, item(), stamp(NOW))
        next_item = item()
        next_item['best_purchase_option']['packageid'] = 999
        newer = sm.observations(GAME, next_item, stamp(NOW + timedelta(hours=4)))
        failed = sm.observations(GAME, None, stamp(NOW + timedelta(hours=5)), error='network_error')
        summary = sm.summaries(rows + newer + failed, config, {'games': [GAME]}, GAME,
                               NOW + timedelta(hours=6))
        price = summary['price_final']
        self.assertEqual(price['status'], 'error')
        self.assertEqual(price['current'], 1100000)
        self.assertEqual(price['context']['package_id'], 999)
        self.assertNotIn('ranges', price)
        self.assertEqual(price['observation_count'], 3)
        self.assertIsNone(summary['followers']['current'])

    def test_validator_rejects_unit_or_appid_mutation(self):
        row = sm.observations(GAME, item(), stamp(NOW))[2]
        for key, value in [('divisor', True), ('currency', 'USD'), ('app_id', 99)]:
            mutated = copy.deepcopy(row)
            mutated['context'][key] = value
            with self.assertRaises(ValueError):
                sm.validate_sample(mutated, GAME)
        bad = copy.deepcopy(row)
        bad['value'] = 12
        with self.assertRaisesRegex(ValueError, 'scale'):
            sm.validate_sample(bad, GAME)


class StoreFakeClient(FakeClient):
    fail_metadata = False

    def get(self, url, channel):
        if 'IStoreBrowseService' not in url:
            return super().get(url, channel)
        # Let the original fake enforce both channel and durable allowance.
        super().get(url, channel)
        if self.fail_metadata:
            raise ValueError('network_error')
        query = json.loads(parse_qs(urlsplit(url).query)['input_json'][0])
        return {'response': {'store_items': [item(x['appid']) for x in query['ids']]}}


class StoreCollectionTests(unittest.TestCase):
    setUp = test_fleet.FleetTests.setUp
    tearDown = test_fleet.FleetTests.tearDown
    def enable(self):
        self.config['collection'].update(metadata_enabled=True, metadata_interval_minutes=240,
                                         metadata_request_budget=2)
        save(self.root / 'config/manifest.json', self.config)
        StoreFakeClient.fail_metadata = False

    def test_batch_ttl_and_restart_preserve_old_records(self):
        self.enable()
        first = collect_fleet(self.root, mode='both', client_factory=StoreFakeClient, run_id='one')
        old = load_json(history_path(self.root, 'a'))
        self.assertEqual(first['last_run']['metadata_requests'], 1)
        self.assertEqual(len([s for s in old['samples'] if s['metric'] in sm.METRICS]), 3)
        second = collect_fleet(self.root, mode='both', client_factory=StoreFakeClient, run_id='two')
        self.assertEqual(second['last_run']['metadata_requests'], 0)
        self.assertEqual(old['samples'], load_json(history_path(self.root, 'a'))['samples'])
        lease = read_state(self.root)['reservations']['one']
        self.assertEqual(lease['allowance'], 8)
        self.assertEqual(lease['used'], 7)

    def test_metadata_error_records_null_and_keeps_historical_good(self):
        self.enable()
        collect_fleet(self.root, mode='metadata', client_factory=StoreFakeClient, run_id='good')
        hist = load_json(history_path(self.root, 'a'))
        for sample in hist['samples']:
            sample['observed_at'] = stamp(datetime.now(UTC) - timedelta(hours=5))
        save(history_path(self.root, 'a'), hist)
        old = copy.deepcopy(hist['samples'])
        StoreFakeClient.fail_metadata = True
        result = collect_fleet(self.root, mode='metadata', client_factory=StoreFakeClient, run_id='bad')
        current = load_json(history_path(self.root, 'a'))['samples']
        self.assertEqual(current[:3], old)
        self.assertTrue(all(x['value'] is None and x['status'] == 'error' for x in current[3:]))
        metric = result['games'][0]['metrics']['review_count']
        self.assertEqual(metric['current'], 20)
        self.assertEqual(metric['status'], 'error')
        # The existing preservation guard covers new metrics without relaxing any rule.
        require_preserved({'samples': old}, {'samples': current}, 'fixture')
        changed = copy.deepcopy(current)
        changed[0]['value'] = 9
        with self.assertRaises(Exception):
            require_preserved({'samples': old}, {'samples': changed}, 'fixture')

    def test_disabled_metadata_and_event_end_do_not_call_source(self):
        result = collect_fleet(self.root, mode='metadata', client_factory=StoreFakeClient, run_id='off')
        self.assertFalse(FakeClient.calls)
        self.enable()
        self.config['collection']['stops_at'] = stamp(datetime.now(UTC) - timedelta(seconds=1))
        save(self.root / 'config/manifest.json', self.config)
        collect_fleet(self.root, mode='metadata', client_factory=StoreFakeClient, run_id='closed')
        self.assertFalse(FakeClient.calls)

    def test_partial_batch_budget_resumes_at_unvisited_game(self):
        self.enable()
        self.config['collection']['metadata_request_budget'] = 1
        save(self.root / 'config/manifest.json', self.config)
        self.catalog['games'] = [{'id': f'g-{i}', 'app_id': i + 100, 'demo_app_id': None}
                                  for i in range(101)]
        save(self.root / 'site/data/catalog.json', self.catalog)
        collect_fleet(self.root, mode='metadata', client_factory=StoreFakeClient, run_id='first100')
        self.assertEqual(read_state(self.root)['metadata_cursor'], 100)
        self.assertFalse(history_path(self.root, 'g-100').exists())
        result = collect_fleet(self.root, mode='metadata', client_factory=StoreFakeClient, run_id='last1')
        self.assertEqual(result['last_run']['metadata_requests'], 1)
        self.assertEqual(len(load_json(history_path(self.root, 'g-100'))['samples']), 3)
        self.assertEqual(len(load_json(history_path(self.root, 'g-0'))['samples']), 3)

    def test_missing_only_recovers_recent_errors_without_rewriting_or_retrying_normal_zero(self):
        self.enable()
        StoreFakeClient.fail_metadata = True
        collect_fleet(self.root, mode='metadata', client_factory=StoreFakeClient, run_id='failed')
        a_before = load_json(history_path(self.root, 'a'))
        b = load_json(history_path(self.root, 'b'))
        b['samples'] = sm.observations({'id': 'b', 'app_id': 20}, item(20, count=0, percent=0),
                                        b['samples'][0]['observed_at'])
        save(history_path(self.root, 'b'), b)
        StoreFakeClient.fail_metadata = False
        ordinary = collect_fleet(self.root, mode='metadata', client_factory=StoreFakeClient, run_id='ttl')
        self.assertEqual(ordinary['last_run']['metadata_requests'], 0)
        # Recovery is a later actual observation; the immutable failure timestamp remains unchanged.
        import time
        while stamp(datetime.now(UTC)) == a_before['samples'][0]['observed_at']:
            time.sleep(.02)
        recovered = collect_fleet(self.root, mode='metadata', missing_only=True,
                                  client_factory=StoreFakeClient, run_id='retry')
        self.assertEqual(recovered['last_run']['metadata_requests'], 1)
        after = load_json(history_path(self.root, 'a'))
        self.assertEqual(after['samples'][:3], a_before['samples'])
        self.assertEqual(len(after['samples']), 6)
        self.assertTrue(all(s['status'] == 'ok' for s in after['samples'][3:]))
        self.assertEqual(load_json(history_path(self.root, 'b'))['samples'], b['samples'])


class StoreSummaryIntegrityTests(unittest.TestCase):
    setUp = test_validate_integrity.ValidateIntegrityTests.setUp
    sample = test_validate_integrity.ValidateIntegrityTests.sample

    def test_recomputed_metadata_summary_and_preserved_old_observations(self):
        history = load_json(history_path(self.root, 'a'))
        history['samples'].extend(sm.observations(GAME, item(), stamp(self.now - timedelta(minutes=1))))
        save(history_path(self.root, 'a'), history)
        summary = build_indexes(self.root, now=self.now)
        with redirect_stdout(io.StringIO()):
            validate(self.root)
        for field, wrong in [('current', 999), ('observation_count', True),
                             ('target_interval_minutes', 0)]:
            altered = copy.deepcopy(summary)
            altered['games'][0]['metrics']['review_count'][field] = wrong
            save(self.root / 'site/data/summary.json', altered)
            with self.assertRaisesRegex(ValueError, 'summary_store_metrics_mismatch'):
                validate(self.root)


if __name__ == '__main__':
    unittest.main()

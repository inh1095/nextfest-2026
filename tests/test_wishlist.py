"""Wishlist evidence contracts. All fixtures remain in temporary directories."""
import copy
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from collect import UTC
from fleet import save
from wishlist import build_index


class WishlistTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 10, 21, 12, tzinfo=UTC)
        self.catalog = {'games': [{'id': 'a', 'app_id': 10, 'demo_app_id': 11},
                                  {'id': 'b', 'app_id': 20, 'demo_app_id': 21}]}
        self.events = [{'id': 'news-a', 'game_id': 'a', 'title': 'Please wishlist our game',
                        'summary': 'We have 10000 wishlists. Thank you!',
                        'published_at': '2026-10-20T10:00:00Z',
                        'source_url': 'https://steamcommunity.com/games/10/announcements/detail/1'},
                       {'id': 'news-b', 'game_id': 'b', 'title': '데모 출시',
                        'summary': '플레이해 주셔서 감사합니다.',
                        'published_at': '2026-10-20T11:00:00Z',
                        'source_url': 'https://steamcommunity.com/games/20/announcements/detail/2'}]
        self.source = {
            'disclosures': [{'id': 'disclosure-a', 'game_id': 'a', 'app_id': 10,
                             'event_id': 'news-a', 'published_at': '2026-10-20T10:00:00Z',
                             'value': 10000, 'kind': 'milestone_lower_bound', 'operator': 'gte',
                             'stock_definition': 'unspecified', 'quote': 'We have 10000 wishlists.',
                             'source_url': self.events[0]['source_url'],
                             'verified_at': '2026-10-21T10:00:00Z',
                             'usable_as_current_stock': False, 'as_of': None}],
            'follower_checks': [{'id': 'followers-a', 'game_id': 'a', 'app_id': 10,
                                 'status': 'conflict', 'value': None,
                                 'observed_at': '2026-10-21T10:00:00Z',
                                 'source_url': 'https://steamcommunity.com/games/10/memberslistxml/',
                                 'candidates': [{'path': 'memberCount', 'value': 100},
                                                {'path': 'groupDetails/memberCount', 'value': 112}],
                                 'mapping': 'Reviewed official base AppID group mapping',
                                 'estimate_eligible': False}],
            'methods': [{'id': 'historical-example', 'label': 'Historical reference fixture',
                         'lower_multiplier': 7, 'upper_multiplier': 20, 'median_multiplier': 12,
                         'source_url': 'https://newsletter.gamediscover.co/p/example',
                         'source_date': '2023-01-01', 'sample_description': 'Fixture survey',
                         'uncertainty_kind': 'historical_reference_not_confidence_interval',
                         'validation_status': 'not_validated_for_this_event'}],
        }

    def build(self, source=None):
        save(self.root / 'config/wishlist-evidence.json', source if source is not None else self.source)
        return build_index(self.root, self.catalog, self.now, events=self.events)

    def reject(self, section, key, value):
        source = copy.deepcopy(self.source)
        source[section][0][key] = value
        with self.assertRaises(ValueError):
            self.build(source)

    def test_real_claim_and_unreviewed_mention_are_distinct(self):
        index = self.build()
        self.assertEqual(index['coverage'], {'disclosure_games': 1, 'disclosures': 1,
                                            'mention_games': 1, 'mentions': 1,
                                            'followers_ok': 0, 'followers_conflict': 1})
        self.assertIsNone(index['follower_checks'][0]['value'])
        self.assertFalse(index['disclosures'][0]['usable_as_current_stock'])
        self.assertEqual(index['mentions'][0]['event_id'], 'news-a')
        self.assertNotIn('value', index['mentions'][0])
        self.assertNotIn('estimates', index)

    def test_missing_source_still_indexes_news_without_claiming_numbers(self):
        index = build_index(self.root, self.catalog, self.now, events=self.events)
        self.assertEqual(index['disclosures'], [])
        self.assertEqual(index['methods'], [])
        self.assertEqual(len(index['mentions']), 1)
        self.assertEqual(index['coverage']['disclosures'], 0)

    def test_duplicate_ids_unknown_games_and_demo_id_substitution_rejected(self):
        for key, value in [('game_id', 'unknown'), ('app_id', 11), ('app_id', True),
                           ('event_id', 'news-b'), ('event_id', 'absent')]:
            with self.subTest(key=key, value=value):
                self.reject('disclosures', key, value)
        source = copy.deepcopy(self.source)
        source['disclosures'].append(copy.deepcopy(source['disclosures'][0]))
        with self.assertRaises(ValueError):
            self.build(source)

    def test_invalid_numbers_and_future_dates_rejected(self):
        for value in (True, -1, 1.5, float('nan'), float('inf')):
            with self.subTest(value=value):
                self.reject('disclosures', 'value', value)
        for field in ('published_at', 'verified_at', 'as_of'):
            with self.subTest(field=field):
                self.reject('disclosures', field, '2027-01-01T00:00:00Z')
        self.reject('follower_checks', 'observed_at', '2027-01-01T00:00:00Z')

    def test_linked_source_publication_and_quote_must_match_stored_event(self):
        for field, value in [('source_url', 'https://example.com/unrelated'),
                             ('published_at', '2026-10-19T10:00:00Z'),
                             ('quote', 'A different invented wishlist claim')]:
            with self.subTest(field=field):
                self.reject('disclosures', field, value)
        source = copy.deepcopy(self.source)
        source['disclosures'][0].update(quote='WE HAVE  10000\n WISHLISTS.',
            period_text='Period not specified', review_scope='Stored summary only',
            source_context_url='https://publisher.example.com/press')
        row = self.build(source)['disclosures'][0]
        self.assertEqual(row['period_text'], 'Period not specified')
        self.assertEqual(row['review_scope'], 'Stored summary only')
        self.assertEqual(row['source_context_url'], 'https://publisher.example.com/press')

    def test_claim_semantics_cannot_be_promoted_to_current_stock(self):
        for field, value in [('usable_as_current_stock', True), ('usable_as_current_stock', 0),
                             ('operator', 'eq'), ('stock_definition', 'verified_balance')]:
            with self.subTest(field=field):
                self.reject('disclosures', field, value)
        self.reject('disclosures', 'kind', 'period_additions')

    def test_conflicting_follower_counts_never_get_a_representative_value(self):
        self.reject('follower_checks', 'value', 100)
        self.reject('follower_checks', 'status', 'ok')
        self.reject('follower_checks', 'estimate_eligible', True)
        self.reject('follower_checks', 'candidates', [{'path': 'one', 'value': 100}])
        self.reject('follower_checks', 'candidates', [{'path': 'one', 'value': True}])

    def test_matching_follower_counts_preserve_measured_zero(self):
        source = copy.deepcopy(self.source)
        source['follower_checks'][0].update(status='ok', value=0,
                                          candidates=[{'path': 'count', 'value': 0}])
        index = self.build(source)
        self.assertEqual(index['follower_checks'][0]['value'], 0)
        self.assertEqual(index['coverage']['followers_ok'], 1)

    def test_method_is_only_historical_reference(self):
        for field, value in [('lower_multiplier', True), ('upper_multiplier', float('inf')),
                             ('lower_multiplier', 21), ('median_multiplier', -1),
                             ('uncertainty_kind', '95_percent_confidence_interval'),
                             ('validation_status', 'validated_for_this_event')]:
            with self.subTest(field=field):
                self.reject('methods', field, value)

    def test_date_only_evidence_keeps_date_precision_and_external_claim_can_lack_event(self):
        source = copy.deepcopy(self.source)
        source['disclosures'][0].update(as_of='2026-10-20', event_id=None)
        index = self.build(source)
        self.assertEqual(index['disclosures'][0]['as_of'], '2026-10-20')

    def test_external_day_publication_and_conflict_window_keep_original_precision(self):
        source = copy.deepcopy(self.source)
        source['disclosures'][0].update(published_at='2026-07-16', time_precision='day',
                                        event_id=None, platform_scope='unspecified')
        source['follower_checks'][0].update(observed_at=None,
            observation_window_utc=['2026-10-21T09:00:00Z', '2026-10-21T09:04:00Z'],
            verified_at='2026-10-21T10:00:00Z')
        index = self.build(source)
        self.assertEqual(index['disclosures'][0]['published_at'], '2026-07-16')
        self.assertEqual(index['disclosures'][0]['time_precision'], 'day')
        self.assertEqual(index['disclosures'][0]['platform_scope'], 'unspecified')
        self.assertIsNone(index['follower_checks'][0]['observed_at'])
        self.assertEqual(index['coverage']['followers_conflict'], 1)
        source['follower_checks'][0].update(status='ok', value=100,
                                          candidates=[{'path': 'count', 'value': 100}])
        with self.assertRaises(ValueError):
            self.build(source)

    def test_news_update_refreshes_mentions_without_changing_reviewed_claims(self):
        first = self.build()
        self.events[1]['summary'] = '위시리스트에 추가해주세요. 찜 20000이라는 숫자는 미검토입니다.'
        second = self.build()
        self.assertEqual(second['disclosures'], first['disclosures'])
        self.assertEqual(second['coverage']['mentions'], 2)
        self.assertNotIn('value', second['mentions'][0])


if __name__ == '__main__':
    unittest.main()

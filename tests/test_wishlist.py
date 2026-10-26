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
from wishlist import build_index, disclosure_comparisons


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
                                            'candidate_games': 0, 'candidates': 0, 'current_stock_games': 0,
                                            'followers_ok': 0, 'followers_conflict': 1,
                                            'reviewed_candidates': 0, 'excluded_candidates': 0,
                                            'unresolved_candidates': 0})
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

    def test_numeric_review_queue_never_extracts_values_or_promotes_goals(self):
        self.events[1].update(title='Wishlist goal', summary='If we reach 10000 wishlists, we will add a level.')
        result = self.build()
        self.assertEqual(len(result['candidates']), 1)
        candidate = result['candidates'][0]
        self.assertEqual(candidate['event_id'], 'news-b')
        self.assertEqual(candidate['review_status'], 'unreviewed_numeric_mention')
        self.assertIn('If we reach', candidate['quote'])
        self.assertNotIn('value', candidate)
        self.assertEqual(result['coverage']['disclosures'], 1)
        self.assertEqual(result['coverage']['current_stock_games'], 0)
        self.events[1].update(title='Please wishlist', summary='Thank you for your support')
        result = self.build()
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['coverage']['mentions'], 2)

    def test_numbers_after_a_second_keyword_are_queued_without_mutating_evidence(self):
        self.events[1].update(title='Wishlist our game', summary='Support us. ' * 40 + 'We reached 20,000 wishlists!')
        before = copy.deepcopy(self.events)
        result = self.build()
        self.assertEqual(result['candidates'][0]['event_id'], 'news-b')
        self.assertIn('20,000', result['candidates'][0]['quote'])
        self.assertEqual(self.events, before)

    def test_dates_game_names_versions_and_other_metrics_are_not_quantity_candidates(self):
        cases = [('Launch date', 'Coming November 6. Wishlist our game!'),
                 ('Launch date', 'Coming November 6.Wishlist our game!'),
                 ('Wishlist Vanakan 405', 'Wishlist now!'),
                 ('Vanakan 405', 'Wishlist our game!'),
                 ('Patch v1.0', 'Wishlist now! 400,000 downloads and 100 CCU.'),
                 ('Steam ranking', 'Top 1000 wishlists ranking. Wishlist now!'),
                 ('Sale', 'Only $10. Wishlist now!')]
        for title, summary in cases:
            with self.subTest(title=title, summary=summary):
                self.events[1].update(title=title, summary=summary)
                result = self.build()
                self.assertEqual(result['candidates'], [])
                self.assertEqual(result['coverage']['mentions'], 2)

    def test_mixed_milestone_period_and_future_goal_remain_one_unreviewed_snippet(self):
        self.events[1].update(title='Worm Capitalist update', summary=(
            'We passed 500 wishlists. Since demo launch we gained around 200 wishlists. '
            'Next goal: 1000 wishlists.'))
        before = copy.deepcopy(self.events)
        result = self.build()
        self.assertEqual(len(result['candidates']), 1)
        candidate = result['candidates'][0]
        self.assertEqual(candidate['matched_phrase_kind'], 'quantity_phrase')
        self.assertEqual(candidate['quote'], self.events[1]['summary'])
        self.assertEqual(candidate['review_status'], 'unreviewed_numeric_mention')
        self.assertFalse({'value', 'delta', 'total', 'count'} & candidate.keys())
        self.assertEqual(result['coverage']['disclosures'], 1)
        self.assertEqual(self.events, before)

    def test_narrow_quantity_forms_are_recognized_without_parsing(self):
        for text in ('We reached 1,000 Steam wishlists!', 'Wishlist count: 1000',
                     'One thousand wishlists!', '1000명이 위시리스트에 추가했습니다.',
                     '20,000 people have wishlisted our game.'):
            with self.subTest(text=text):
                self.events[1].update(title='News', summary=text)
                self.assertEqual(len(self.build()['candidates']), 1)

    def test_lower_bounds_dates_platforms_and_unspecified_stocks_never_produce_growth(self):
        base = copy.deepcopy(self.source['disclosures'][0])
        base.update(platform_scope='steam', kind='reported_count', operator='eq',
                    stock_definition='balance', as_of='2026-10-20T09:00:00Z')
        latest = copy.deepcopy(base)
        latest.update(id='later', published_at='2026-10-21T09:00:00Z',
                      as_of='2026-10-21T08:00:00Z', value=12000,
                      event_id='later-event', source_url='https://example.com/later')
        for field, value in [('operator', 'gte'), ('operator', 'approx'),
                             ('stock_definition', 'unspecified'), ('platform_scope', 'unspecified'),
                             ('as_of', None), ('as_of', '2026-10-20'),
                             ('as_of', base['as_of']), ('as_of', '2026-10-19T09:00:00Z')]:
            with self.subTest(field=field, value=value):
                changed = dict(latest, **{field: value})
                row = disclosure_comparisons([base, changed])[0]
                self.assertEqual(row['status'], 'unavailable')
                self.assertIsNone(row['delta'])
                self.assertIsNone(row['percent'])
        rows = disclosure_comparisons([base, dict(latest, game_id='b')])
        self.assertTrue(all(r['delta'] is None for r in rows))
        row = disclosure_comparisons([latest, base])[0]
        self.assertEqual(row['delta'], 2000)
        self.assertEqual(row['percent'], 20)
        self.assertEqual(row['status'], 'reported_balance_difference')
        self.assertIsNone(disclosure_comparisons([dict(base, value=0), latest])[0]['percent'])

    def test_same_announcement_period_statement_is_not_a_previous_publication(self):
        milestone = dict(self.source['disclosures'][0], platform_scope='steam')
        period = dict(milestone, id='z-period', kind='period_additions',
                      stock_definition='period_adds', value=200, operator='approx')
        previous = dict(milestone, id='previous', event_id='previous-event',
                        source_url='https://example.com/previous', published_at='2026-10-19T10:00:00Z')
        before = copy.deepcopy([milestone, period, previous])
        row = disclosure_comparisons([period, milestone, previous])[0]
        self.assertEqual(row['latest_disclosure_id'], milestone['id'])
        self.assertEqual(row['previous_disclosure_id'], 'previous')
        self.assertIsNone(row['delta'])
        self.assertEqual([milestone, period, previous], before)
        # The same article with another timestamp/statement is still not another publication.
        duplicate = dict(milestone, id='older-statement', published_at='2026-10-18T10:00:00Z')
        self.assertIsNone(disclosure_comparisons([milestone, period, duplicate])[0]['previous_disclosure_id'])

    def test_date_only_same_day_does_not_infer_an_earlier_publication(self):
        base = dict(self.source['disclosures'][0], platform_scope='steam', published_at='2026-10-20')
        timed = dict(base, id='timed', event_id='timed-event',
                     source_url='https://example.com/timed', published_at='2026-10-20T23:00:00Z')
        previous = dict(base, id='previous-day', event_id='previous-event',
                        source_url='https://example.com/previous', published_at='2026-10-19')
        row = disclosure_comparisons([timed, base, previous])[0]
        self.assertTrue(row['publication_order_ambiguous'])
        self.assertEqual(row['previous_disclosure_id'], 'previous-day')
        self.assertIsNone(row['delta'])
        self.assertIsNone(disclosure_comparisons([base, timed])[0]['previous_disclosure_id'])


class FullSourceWishlistTests(unittest.TestCase):
    """Full-body discoveries are pending evidence, including after source changes."""
    def setUp(self):
        WishlistTests.setUp(self)
        save(self.root / 'config/wishlist-evidence.json', self.source)
        save(self.root / 'site/data/games/a.json', {'events': [self.events[0]]})
        self.full_game = self.catalog['games'][1]
        self.full_event = dict(self.events[1], id='steam-b-123', title='Development news',
            summary='A description without any numeric wishlist phrase.',
            source_url='https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/123')
        self.events[1] = self.full_event
        self.body = 'Ordinary game details. ' * 100 + 'We have passed 5,000 wishlists!'

    def full_mention(self, body=None, source_app_id=20, observed_at='2026-10-21T11:00:00Z'):
        from news_evidence import extract_mentions
        item = {'gid': '123', 'appid': source_app_id, 'title': self.full_event['title'],
                'contents': body if body is not None else self.body,
                'date': int(datetime.fromisoformat(self.full_event['published_at'].replace('Z', '+00:00')).timestamp()),
                'feedname': 'steam_community_announcements', 'url': self.full_event['source_url']}
        return extract_mentions(self.full_game, source_app_id,
            {'appnews': {'appid': source_app_id, 'newsitems': [item]}}, observed_at)[0]

    def save_review(self, mention, decision='not_a_claim'):
        source = copy.deepcopy(self.source)
        ids = []
        if decision == 'verified_claim':
            claim = dict(source['disclosures'][0], id='full-source-claim',
                game_id='b', app_id=20, event_id=None, quote='We have passed 5,000 wishlists!',
                source_url=self.full_event['source_url'], published_at=self.full_event['published_at'],
                value=5000)
            source['disclosures'].append(claim)
            ids.append(claim['id'])
        save(self.root / 'config/wishlist-evidence.json', source)
        review = {'id': 'review-full-source', 'game_id': 'b', 'app_id': 20,
                  'event_id': self.full_event['id'], 'candidate_id': 'candidate-' + self.full_event['id'],
                  'source_url': self.full_event['source_url'],
                  'published_at': self.full_event['published_at'],
                  'reviewed_at': '2026-10-21T10:00:00Z', 'reviewer': 'gpt-6.1-sol',
                  'decision': decision, 'reason': 'Reviewed source context',
                  'disclosure_ids': ids, 'source_check': {'http_status': 200,
                      'app_id_matches': True, 'publication_matches': True,
                      'observed_at': '2026-10-21T09:00:00Z',
                      'request_url': 'https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=20',
                      'body_sha256': mention['body_sha256']}}
        save(self.root / 'config/source-reviews.json',
             {'schema_version': 1, 'candidate_reviews': [review]})
        return source

    def full_build(self, mentions):
        return build_index(self.root, self.catalog, self.now,
                           events=self.events, numeric_mentions=mentions)

    def test_full_source_new_candidate_outside_summary_without_keyword_match(self):
        self.full_event.update(title='Patch notes', summary='Controls improved.')
        mention = self.full_mention()
        before = copy.deepcopy((self.events, mention))
        result = self.full_build([mention])
        self.assertEqual(len(result['candidates']), 1)
        row = result['candidates'][0]
        self.assertEqual(row['id'], 'candidate-' + self.full_event['id'])
        self.assertEqual(row['body_sha256'], mention['body_sha256'])
        self.assertEqual(row['source_app_id'], 20)
        self.assertEqual(row['discovery_method'], 'official_steam_news_full_text_numeric_scan')
        self.assertIn('5,000', row['quote'])
        self.assertEqual(row['review_status'], 'unreviewed_numeric_mention')
        self.assertNotIn('value', row)
        self.assertEqual((self.events, mention), before)
        self.assertEqual(result['coverage']['mentions'], 2)
        self.assertEqual(len(result['disclosures']), 1)

    def test_full_and_summary_candidates_merge_without_duplicate_event(self):
        self.full_event['summary'] = 'We passed 5,000 wishlists!'
        mention = self.full_mention()
        result = self.full_build([mention])
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['candidates'][0]['id'], 'candidate-' + self.full_event['id'])
        self.assertEqual(result['candidates'][0]['numeric_mention_id'], mention['id'])

    def test_same_reviewed_body_is_not_reregistered_for_verified_or_excluded(self):
        mention = self.full_mention()
        for decision in ('verified_claim', 'not_a_claim'):
            with self.subTest(decision=decision):
                self.save_review(mention, decision)
                self.assertEqual(self.full_build([mention])['candidates'], [])

    def test_changed_body_requeues_despite_old_verified_or_excluded_review(self):
        original = self.full_mention()
        changed = self.full_mention(self.body + ' We now have 6,000 wishlists!')
        for decision in ('verified_claim', 'not_a_claim'):
            with self.subTest(decision=decision):
                source = self.save_review(original, decision)
                before = copy.deepcopy((source, self.events, original, changed))
                unchanged_index = self.full_build([original])
                result = self.full_build([original, changed])
                row = result['candidates'][0]
                self.assertEqual(row['review_status'], 'source_changed')
                self.assertEqual(row['review_reason'], '원문 변경으로 재확인 필요')
                self.assertEqual(row['previous_review_decision'], decision)
                self.assertEqual(row['body_sha256'], changed['body_sha256'])
                self.assertEqual(result['disclosures'], unchanged_index['disclosures'])
                self.assertEqual((source, self.events, original, changed), before)

    def test_older_cache_does_not_reopen_a_newer_source_review(self):
        original = self.full_mention()
        self.save_review(original)
        older = self.full_mention(self.body + ' Previous version.', observed_at='2026-10-21T08:00:00Z')
        self.assertEqual(self.full_build([older])['candidates'], [])

    def test_latest_observation_wins_and_candidate_id_is_stable(self):
        older = self.full_mention(observed_at='2026-10-21T09:00:00Z')
        latest = self.full_mention(self.body + ' 6,000 wishlists!', observed_at='2026-10-21T11:00:00Z')
        a = self.full_build([older, latest])['candidates'][0]
        b = self.full_build([latest, older])['candidates'][0]
        self.assertEqual(a, b)
        self.assertEqual(a['body_sha256'], latest['body_sha256'])
        self.assertEqual(a['id'], self.full_build([older])['candidates'][0]['id'])

    def test_historic_linked_disclosure_without_candidate_review_stays_reviewed(self):
        self.full_event['summary'] = 'We have passed 5,000 wishlists!'
        source = copy.deepcopy(self.source)
        source['disclosures'].append(dict(source['disclosures'][0], id='legacy-linked',
            game_id='b', app_id=20, event_id=self.full_event['id'], value=5000,
            quote=self.full_event['summary'], source_url=self.full_event['source_url'],
            published_at=self.full_event['published_at']))
        save(self.root / 'config/wishlist-evidence.json', source)
        self.assertEqual(self.full_build([self.full_mention()])['candidates'], [])

    def test_amended_linked_original_stays_reviewed_in_summary_and_full_scan(self):
        self.full_event['summary'] = 'We have passed 5,000 wishlists!'
        source = copy.deepcopy(self.source)
        original = dict(source['disclosures'][0], id='legacy-linked-original',
            game_id='b', app_id=20, event_id=self.full_event['id'], value=5000,
            quote=self.full_event['summary'], source_url=self.full_event['source_url'],
            published_at=self.full_event['published_at'])
        corrected = dict(original, id='legacy-corrected', event_id=None, operator='gt')
        source['disclosures'].extend([original, corrected])
        save(self.root / 'config/wishlist-evidence.json', source)
        mention = self.full_mention()
        amendment = {'id': 'legacy-amendment', 'previous_disclosure_id': original['id'],
            'replacement_disclosure_id': corrected['id'], 'reason': 'Full source confirms passed.',
            'reviewer': 'gpt-6.1-sol', 'reviewed_at': '2026-10-21T11:30:00Z',
            'source_check': {'http_status': 200, 'app_id_matches': True,
                'publication_matches': True, 'observed_at': mention['observed_at'],
                'request_url': 'https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=20',
                'body_sha256': mention['body_sha256']}}
        save(self.root / 'config/source-reviews.json', {'schema_version': 1,
            'candidate_reviews': [], 'disclosure_amendments': [amendment]})
        before = copy.deepcopy((source, self.events, mention))
        for discoveries in ([], [mention]):
            with self.subTest(full_scan=bool(discoveries)):
                result = self.full_build(discoveries)
                self.assertEqual(result['candidates'], [])
                self.assertEqual(result['coverage']['candidates'], 0)
                self.assertEqual(result['active_disclosure_ids'], ['disclosure-a', corrected['id']])
                self.assertEqual(result['coverage']['disclosures'], 2)
                self.assertEqual(len(result['disclosures']), 3)
                self.assertIn(original['id'], {row['id'] for row in result['disclosures']})
                comparison = next(row for row in result['comparisons'] if row['game_id'] == 'b')
                self.assertEqual(comparison['latest_disclosure_id'], corrected['id'])
        self.assertEqual((source, self.events, mention), before)

    def test_full_mentions_validate_base_demo_and_other_game_mapping(self):
        demo = self.full_mention(source_app_id=21)
        self.assertEqual(self.full_build([demo])['candidates'][0]['source_app_id'], 21)
        for key, value in [('game_id', 'a'), ('app_id', 21), ('source_app_id', 10),
                           ('source_kind', 'base'), ('event_id', 'news-a'),
                           ('published_at', '2026-10-20T10:00:00Z'),
                           ('observed_at', '2026-10-22T11:00:00Z')]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.full_build([dict(demo, **{key: value})])

    def test_history_is_read_when_numeric_mentions_are_not_passed(self):
        mention = self.full_mention()
        save(self.root / 'site/data/games/b.json',
             {'events': [self.full_event], 'numeric_mentions': [mention]})
        with_events = build_index(self.root, self.catalog, self.now, events=self.events)
        from_history = build_index(self.root, self.catalog, self.now)
        self.assertEqual(with_events['candidates'][0]['body_sha256'], mention['body_sha256'])
        self.assertEqual(from_history['candidates'][0]['body_sha256'], mention['body_sha256'])
        self.assertEqual(self.full_build([])['candidates'], [])


if __name__ == '__main__':
    unittest.main()

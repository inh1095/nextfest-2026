"""Full-source candidate discovery remains distinct from reviewed wishlist claims."""
import copy
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from news_evidence import extract_mentions, validate_mention


class NewsEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.game = {'id': 'steam-10', 'app_id': 10, 'demo_app_id': 11}
        self.at = '2026-10-26T10:00:00Z'
        self.item = {'gid': '123', 'appid': 10, 'title': 'Development update',
                     'contents': 'We have passed 1,000 wishlists!', 'date': 1793000000,
                     'feedname': 'steam_community_announcements',
                     'url': 'https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/123'}

    def payload(self, item=None, app_id=10):
        return {'appnews': {'appid': app_id, 'newsitems': [item or self.item]}}

    def extract(self, contents=None, title=None):
        item = copy.deepcopy(self.item)
        if contents is not None:
            item['contents'] = contents
        if title is not None:
            item['title'] = title
        return extract_mentions(self.game, 10, self.payload(item), self.at)

    def test_beyond_old_fetch_and_summary_limits_without_modifying_payload(self):
        item = copy.deepcopy(self.item)
        item['contents'] = 'Ordinary patch detail. ' * 150 + '[b]We passed 50,000 wishlists![/b]'
        payload = self.payload(item)
        before = copy.deepcopy(payload)
        rows = extract_mentions(self.game, 10, payload, self.at)
        self.assertEqual(payload, before)
        self.assertEqual(len(rows), 1)
        self.assertIn('50,000', rows[0]['quote'])
        self.assertEqual(rows[0]['body_sha256'], hashlib.sha256(item['contents'].encode()).hexdigest())
        self.assertNotIn('contents', rows[0])
        self.assertNotIn('body', rows[0])

    def test_goals_rankings_and_giveaways_are_only_unreviewed_candidates(self):
        for body in ['Help us reach 10,000 wishlists!', 'Rank 100 on the wishlist chart.',
                     'At 5,000 wishlists we will give away 2 keys.',
                     'We are almost at 7000 wishlists.',
                     'Ten thousand wishlists, thank you!', '위시리스트 수 1만 달성!',
                     '願望清單突破十萬！', 'ウィッシュリスト10万件！']:
            with self.subTest(body=body):
                row = self.extract(body)[0]
                self.assertEqual(row['review_status'], 'unreviewed_numeric_mention')
                self.assertEqual(row['interpretation'], 'machine_candidate_only')
                self.assertTrue({'value', 'operator', 'usable_as_current_stock'}.isdisjoint(row))

    def test_keyword_only_and_unrelated_numeric_article_are_not_candidates(self):
        self.assertEqual(self.extract('Please wishlist our game.'), [])
        self.assertEqual(self.extract('Patch 1.2 fixes 100 bugs.'), [])

    def test_title_only_and_body_or_title_edits_create_new_versions(self):
        first = self.extract('Thank you!', '1,000 wishlists!')[0]
        second = self.extract('Thank you!', '2,000 wishlists!')[0]
        third = self.extract('Thank you again!', '1,000 wishlists!')[0]
        self.assertEqual(first['body_sha256'], second['body_sha256'])
        self.assertNotEqual(first['content_sha256'], second['content_sha256'])
        self.assertNotEqual(first['id'], second['id'])
        self.assertNotEqual(first['id'], third['id'])
        self.assertEqual(first['id'], self.extract('Thank you!', '1,000 wishlists!')[0]['id'])

    def test_demo_provenance_remains_separate_from_base_game(self):
        item = dict(self.item, appid=11)
        row = extract_mentions(self.game, 11, self.payload(item, 11), self.at)[0]
        self.assertEqual((row['app_id'], row['source_app_id'], row['source_kind']), (10, 11, 'demo'))
        self.assertEqual(row['event_id'], 'steam-steam-10-123')
        base = self.extract()[0]
        self.assertEqual(base['content_sha256'], row['content_sha256'])
        self.assertNotEqual(base['id'], row['id'])
        item.pop('appid')
        self.assertEqual(len(extract_mentions(self.game, 11, self.payload(item, 11), self.at)), 1)

    def test_identity_mismatches_reject_instead_of_inventing_evidence(self):
        cases = [(99, self.payload()), (10, self.payload(app_id=11)),
                 (10, self.payload(dict(self.item, appid=11))),
                 (10, self.payload(dict(self.item, appid=True))),
                 (10, self.payload(dict(self.item, url='https://steamcommunity.com/games/11/announcements/detail/9'))),
                 (10, self.payload(dict(self.item, url='https://example.com/news/123'))),
                 (10, self.payload(dict(self.item, url=self.item['url'].replace('/123', '/124'))))]
        for source, payload in cases:
            with self.subTest(source=source, payload=payload):
                with self.assertRaises(ValueError):
                    extract_mentions(self.game, source, payload, self.at)

    def test_invalid_dates_and_future_publication_reject(self):
        for date in [True, None, -1, float('nan'), 1799999999, 1.5]:
            with self.subTest(date=date):
                with self.assertRaises(ValueError):
                    extract_mentions(self.game, 10, self.payload(dict(self.item, date=date)), self.at)
        with self.assertRaises(ValueError):
            extract_mentions(self.game, 10, self.payload(), '2026-10-26')

    def test_single_excerpt_caps_words_and_unbroken_cjk_characters(self):
        for body in ['context ' * 200 + '1000 wishlists ' + 'ending ' * 200,
                     '長' * 1000 + 'ウィッシュリスト10000' + '文' * 1000]:
            row = self.extract(body)[0]
            self.assertLessEqual(len(row['quote']), 280)
            self.assertLessEqual(len(row['quote'].split()), 25)
            self.assertNotIn('[b]', row['quote'])

    def test_validator_checks_event_mapping_and_storage_contract(self):
        row = self.extract()[0]
        events = [{'id': row['event_id'], 'game_id': self.game['id'],
                   'source_url': row['source_url'], 'published_at': row['published_at']}]
        self.assertEqual(validate_mention(row, self.game, events), row)
        for field, bad in [('quote', 'x' * 281), ('review_status', 'confirmed'),
                           ('body_sha256', 'bad'), ('event_id', 'another-event'),
                           ('source_app_id', 99), ('value', 1000), ('contents', 'full body')]:
            with self.subTest(field=field):
                changed = dict(row, **{field: bad})
                with self.assertRaises(ValueError):
                    validate_mention(changed, self.game, events)
        with self.assertRaises(ValueError):
            validate_mention(row, self.game, [])

    def test_duplicate_articles_collapse_and_external_feeds_skip(self):
        payload = self.payload()
        payload['appnews']['newsitems'].extend([dict(self.item), dict(self.item, feedname='external_feed')])
        self.assertEqual(len(extract_mentions(self.game, 10, payload, self.at)), 1)


if __name__ == '__main__':
    unittest.main()

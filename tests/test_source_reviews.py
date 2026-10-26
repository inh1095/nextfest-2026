"""Keep target announcements out of the evidence list without erasing their history."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from fleet import save
from evidence_guard import require_preserved
import test_wishlist


class SourceReviewTests(unittest.TestCase):
    setUp = test_wishlist.WishlistTests.setUp
    build = test_wishlist.WishlistTests.build

    def review(self, decision='not_a_claim'):
        event = self.events[0]
        return {'id': 'review-a', 'candidate_id': 'candidate-news-a',
                'event_id': 'news-a', 'game_id': 'a', 'app_id': 10,
                'source_url': event['source_url'], 'published_at': event['published_at'],
                'reviewed_at': '2026-10-21T11:00:00Z', 'reviewer': 'gpt-6.1-sol',
                'decision': decision, 'reason': 'The number is a future goal.',
                'disclosure_ids': ['disclosure-a'] if decision == 'verified_claim' else [],
                'source_check': {'http_status': 200, 'app_id_matches': True,
                                 'publication_matches': True, 'body_sha256': 'a' * 64,
                                 'observed_at': '2026-10-21T10:55:00Z',
                                 'request_url': 'https://api.steampowered.com/example'}}

    def store(self, rows):
        save(self.root / 'config/source-reviews.json',
             {'schema_version': 1, 'candidate_reviews': rows})

    def test_reviewed_target_is_excluded_but_source_and_decision_survive(self):
        self.events[0]['summary'] = 'Help us reach 10000 wishlists!'
        source = copy.deepcopy(self.source)
        source['disclosures'] = []
        self.assertEqual(len(self.build(source)['candidates']), 1)
        row = self.review()
        self.store([row])
        result = self.build(source)
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['candidate_reviews'], [row])
        self.assertEqual(result['coverage']['excluded_candidates'], 1)
        self.assertEqual(result['mentions'][0]['event_id'], 'news-a')

    def test_ambiguous_review_stays_pending_with_reason(self):
        source = copy.deepcopy(self.source)
        source['disclosures'] = []
        row = self.review('needs_review')
        self.store([row])
        candidate = self.build(source)['candidates'][0]
        self.assertEqual(candidate['review_status'], 'needs_review')
        self.assertEqual(candidate['review_reason'], row['reason'])

    def test_completed_decision_requires_verified_matching_source(self):
        for field, value in [('http_status', 404), ('app_id_matches', False),
                             ('publication_matches', False), ('body_sha256', None),
                             ('observed_at', None), ('request_url', None)]:
            with self.subTest(field=field):
                row = self.review()
                row['source_check'][field] = value
                self.store([row])
                with self.assertRaises(ValueError):
                    self.build()

    def test_game_event_and_disclosure_cannot_be_substituted(self):
        for field, value in [('game_id', 'b'), ('app_id', True), ('candidate_id', 'wrong'),
                             ('published_at', '2026-10-19T10:00:00Z'),
                             ('disclosure_ids', ['missing'])]:
            row = self.review('verified_claim')
            row[field] = value
            self.store([row])
            with self.assertRaises(ValueError):
                self.build()

    def test_new_decision_appends_and_previous_review_is_protected(self):
        previous = self.review('needs_review')
        current = self.review('verified_claim')
        current.update(id='review-a-2', reviewed_at='2026-10-21T11:30:00Z')
        self.store([previous, current])
        result = self.build()
        self.assertEqual(result['candidate_reviews'], [previous, current])
        self.assertEqual(result['coverage']['reviewed_candidates'], 1)
        self.assertEqual(result['coverage']['unresolved_candidates'], 0)
        require_preserved({'candidate_reviews': [previous]}, result, 'review fixture')
        with self.assertRaises(ValueError):
            require_preserved({'candidate_reviews': [previous]},
                              {'candidate_reviews': [current]}, 'review fixture')

    def test_correction_keeps_original_and_uses_only_replacement_in_comparisons(self):
        original_index = self.build()
        source = copy.deepcopy(self.source)
        replacement = copy.deepcopy(source['disclosures'][0])
        replacement.update(id='disclosure-corrected', operator='gt')
        source['disclosures'].append(replacement)
        correction = {'id': 'amendment-a', 'previous_disclosure_id': 'disclosure-a',
                      'replacement_disclosure_id': 'disclosure-corrected',
                      'reason': 'The full text says more than.', 'reviewer': 'gpt-6.1-sol',
                      'reviewed_at': '2026-10-21T11:00:00Z',
                      'source_check': self.review()['source_check']}
        save(self.root / 'config/source-reviews.json',
             {'schema_version': 1, 'candidate_reviews': [], 'disclosure_amendments': [correction]})
        result = self.build(source)
        self.assertEqual(len(result['disclosures']), 2)
        self.assertEqual(result['active_disclosure_ids'], ['disclosure-corrected'])
        self.assertEqual(result['coverage']['disclosures'], 1)
        self.assertEqual(result['comparisons'][0]['latest_disclosure_id'], 'disclosure-corrected')
        require_preserved({'disclosures': original_index['disclosures']}, result, 'original claim')
        correction['replacement_disclosure_id'] = 'disclosure-a'
        save(self.root / 'config/source-reviews.json',
             {'schema_version': 1, 'candidate_reviews': [], 'disclosure_amendments': [correction]})
        with self.assertRaisesRegex(ValueError, 'amendment_chain'):
            self.build(source)

    def test_correction_chain_uses_instants_across_fractional_seconds_and_offsets(self):
        source = copy.deepcopy(self.source)
        for did in ('second', 'third', 'fourth'):
            row = copy.deepcopy(source['disclosures'][0])
            row['id'] = did
            source['disclosures'].append(row)
        rows = []
        for previous, replacement, at in (
                ('disclosure-a', 'second', '2026-10-21T11:00:00Z'),
                ('second', 'third', '2026-10-21T11:00:00.100Z'),
                ('third', 'fourth', '2026-10-21T20:00:00.200+09:00')):
            rows.append({'id': 'amendment-' + replacement,
                         'previous_disclosure_id': previous, 'replacement_disclosure_id': replacement,
                         'reviewed_at': at, 'reviewer': 'gpt-6.1-sol', 'reason': 'Fixture correction',
                         'source_check': self.review()['source_check']})
        save(self.root / 'config/source-reviews.json',
             {'schema_version': 1, 'candidate_reviews': [], 'disclosure_amendments': rows[::-1]})
        self.assertEqual(self.build(source)['active_disclosure_ids'], ['fourth'])


if __name__ == '__main__':
    unittest.main()

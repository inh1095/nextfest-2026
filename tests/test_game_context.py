"""Immutable restored context, public-copy parity and typed mapping tests."""
import copy
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from game_context import validate_context, public_config
from fleet import build_indexes, save, load_json
from validate import validate
import test_validate_integrity
import test_evidence_guard


def fixture():
    at = '2026-10-20T07:00:00Z'
    field = {'source_id': 'batch-0', 'path': 'basic_info.developers', 'observed_at': at}
    return {'schema_version': 1, 'generated_at': at, 'source_snapshot_at': at,
            'coverage': {'catalog_games': 1, 'mapped_games': 1, 'developers_games': 1,
                         'publishers_games': 1, 'genres_games': 0, 'release_date_games': 1,
                         'video_games': 0, 'videos': 0},
            'sources': [{'id': 'batch-0', 'source_url': 'https://api.steampowered.com/items',
                         'observed_at': at}],
            'games': [{'game_id': 'a', 'app_id': 10, 'profile_snapshot': {
                'developers': ['Developer'], 'publishers': ['Publisher'], 'genres': [],
                'release_date': {'coming_soon': True, 'date': 'Coming 2027'},
                'observed_at': at, 'source_url': 'https://api.steampowered.com/items',
                'provenance': {'batch_index': 0, 'raw_response_sha256': 'a' * 64,
                               'fields': {'developers': field, 'publishers': field,
                                          'genres': None, 'release_date': field}}},
                'videos_snapshot': []}]}


class ContextValidationTests(unittest.TestCase):
    def test_snapshot_future_release_is_plan_and_bool_mapping_is_rejected(self):
        catalog = {'games': [{'id': 'a', 'app_id': 10}]}
        original = fixture()
        original['games'][0]['profile_snapshot']['developers'].append(' ')
        self.assertEqual(validate_context(original, catalog), original)
        changed = copy.deepcopy(original)
        changed['coverage']['developers_games'] = True
        with self.assertRaisesRegex(ValueError, 'coverage_mismatch'):
            validate_context(changed, catalog)
        for field, wrong in [('game_id', 'unknown'), ('app_id', 11), ('app_id', True)]:
            changed = copy.deepcopy(original)
            changed['games'][0][field] = wrong
            with self.assertRaises(ValueError):
                validate_context(changed, catalog)
        changed = copy.deepcopy(original)
        changed['games'].append(copy.deepcopy(changed['games'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            validate_context(changed, catalog)

    def test_types_provenance_urls_and_actual_observation_time_are_checked(self):
        catalog = {'games': [{'id': 'a', 'app_id': 10}]}
        mutations = [(['developers'], 'Company'), (['source_url'], 'http://example.test'),
                     (['observed_at'], '2099-01-01T00:00:00Z'),
                     (['release_date', 'coming_soon'], 1),
                     (['provenance', 'batch_index'], True),
                     (['provenance', 'fields', 'developers', 'source_id'], 'unknown')]
        for path, value in mutations:
            changed = fixture()
            node = changed['games'][0]['profile_snapshot']
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
            with self.assertRaises(ValueError):
                validate_context(changed, catalog)

    def test_artifact_collection_time_does_not_invent_http_observation_time(self):
        data = fixture()
        source = data['sources'][0]
        source['evidence_collected_at'] = source['observed_at']
        source['observed_at'] = None
        field = data['games'][0]['profile_snapshot']['provenance']['fields']['developers']
        field['evidence_collected_at'] = field['observed_at']
        field['observed_at'] = None
        validate_context(data, {'games': [{'id': 'a', 'app_id': 10}]})
        self.assertIsNone(source['observed_at'])
        self.assertIsNone(field['observed_at'])


class PublicContextTests(unittest.TestCase):
    setUp = test_validate_integrity.ValidateIntegrityTests.setUp
    sample = test_validate_integrity.ValidateIntegrityTests.sample

    def test_optional_context_copy_is_exact_and_mismatch_rejected(self):
        original = load_json(self.root / 'site/data/config.json')
        self.assertNotIn('game_context', original)
        context = fixture()
        context['coverage']['catalog_games'] = 3
        save(self.root / 'config/game-context.json', context)
        build_indexes(self.root, now=self.now)
        public = load_json(self.root / 'site/data/config.json')
        self.assertEqual(public, {**original, 'game_context': context})
        with redirect_stdout(io.StringIO()):
            validate(self.root)
        public['game_context']['games'][0]['profile_snapshot']['developers'] = ['Forged']
        save(self.root / 'site/data/config.json', public)
        with self.assertRaisesRegex(ValueError, 'public_config_mismatch'):
            validate(self.root)


class ContextPreservationTests(unittest.TestCase):
    setUp = test_evidence_guard.EvidenceGuardTests.setUp
    git = test_evidence_guard.EvidenceGuardTests.git
    write = test_evidence_guard.EvidenceGuardTests.write
    check = test_evidence_guard.EvidenceGuardTests.check

    def test_first_add_allowed_then_existing_records_and_sources_are_immutable(self):
        path = self.root / 'config/game-context.json'
        save(path, fixture())
        self.check()  # File absent from baseline: first introduction is allowed.
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                 'commit', '-qm', 'Restore verified context')
        self.check()
        for field in ('games', 'sources'):
            changed = fixture()
            changed[field] = []
            save(path, changed)
            with self.assertRaisesRegex(ValueError, 'evidence_changed_or_removed'):
                self.check()
        changed = fixture()
        changed['games'][0]['profile_snapshot']['developers'][0] = 'Other developer'
        save(path, changed)
        with self.assertRaisesRegex(ValueError, 'evidence_changed_or_removed'):
            self.check()
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'evidence_file_removed_or_replaced'):
            self.check()

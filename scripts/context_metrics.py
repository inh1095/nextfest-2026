"""Validate dated StoreBrowse context without network calls or history writes.

Source fields remain intact. A trailer path or release timestamp is never turned
into an invented public URL, video publication date, or confirmed release date.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re

ENDPOINT = 'https://api.steampowered.com/IStoreBrowseService/GetItems/v1/'
FIELDS = ('basic_info', 'release', 'trailers')
STATUSES = {'ok', 'unavailable', 'error'}


def request_fields():
    """Merge these flags into the existing metadata request's data_request."""
    return {'include_basic_info': True, 'include_release': True, 'include_trailers': True}


def _integer(value, positive=False):
    if type(value) is not int or not (int(positive) <= value <= 9007199254740991):
        raise ValueError('invalid_context_integer')
    return value


def _appid(value):
    if not 0 < _integer(value, True) <= 4294967295:
        raise ValueError('invalid_context_appid')
    return value


def _time(value):
    if not isinstance(value, str):
        raise ValueError('invalid_context_timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('invalid_context_timestamp') from error
    if parsed.tzinfo is None or 'T' not in value:
        raise ValueError('invalid_context_timestamp')
    return parsed


def _json(value):
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _json(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json(item)
        return
    raise ValueError('non_json_context_value')


def _digest(value):
    _json(value)
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _basic(value):
    if not isinstance(value, dict):
        raise ValueError('invalid_basic_info')
    for key in ('developers', 'publishers', 'franchises'):
        if key not in value:
            continue
        if not isinstance(value[key], list):
            raise ValueError('invalid_creator_list')
        for creator in value[key]:
            if not isinstance(creator, dict) or not isinstance(creator.get('name'), str):
                raise ValueError('invalid_creator_name')
            if 'creator_clan_account_id' in creator:
                _integer(creator['creator_clan_account_id'])
    if 'short_description' in value and not isinstance(value['short_description'], str):
        raise ValueError('invalid_description')


def _release(value):
    if not isinstance(value, dict):
        raise ValueError('invalid_release_info')
    for key in ('steam_release_date', 'original_release_date'):
        if key in value:
            _integer(value[key])
    if 'is_coming_soon' in value and type(value['is_coming_soon']) is not bool:
        raise ValueError('invalid_coming_soon')
    for key in ('coming_soon_display', 'custom_release_date_message'):
        if key in value and not isinstance(value[key], str):
            raise ValueError('invalid_release_text')


def _trailers(value):
    if not isinstance(value, dict):
        raise ValueError('invalid_trailers')
    for key in ('highlights', 'other_trailers'):
        if key not in value:
            continue
        if not isinstance(value[key], list):
            raise ValueError('invalid_trailer_list')
        for trailer in value[key]:
            if not isinstance(trailer, dict):
                raise ValueError('invalid_trailer')
            for field in ('trailer_name', 'trailer_url_format', 'screenshot_medium', 'screenshot_full'):
                if field in trailer and not isinstance(trailer[field], str):
                    raise ValueError('invalid_trailer_text')
            for field in ('trailer_base_id', 'trailer_category'):
                if field in trailer:
                    _integer(trailer[field])
            if 'all_ages' in trailer and type(trailer['all_ages']) is not bool:
                raise ValueError('invalid_trailer_flag')
            for field, required in (('microtrailer', ('filename', 'type')),
                                    ('adaptive_trailers', ('cdn_path', 'encoding'))):
                if field not in trailer:
                    continue
                if not isinstance(trailer[field], list):
                    raise ValueError('invalid_trailer_assets')
                for asset in trailer[field]:
                    if not isinstance(asset, dict) or not all(isinstance(asset.get(k), str) for k in required):
                        raise ValueError('invalid_trailer_asset')


VALIDATORS = {'basic_info': _basic, 'release': _release, 'trailers': _trailers}


def parse_snapshot(game, item, observed_at, *, error=None, batch_size=1, response_sha256=None):
    """Return one append-only context_snapshots entry for the requested base AppID.

    A valid response can omit individual fields: field_status then remains
    unavailable. Missing data never means no trailers, no creators, or release
    epoch 0. Failed/unmapped source items never transfer another game's fields.
    """
    app = _appid(game['app_id'])
    if not isinstance(game.get('id'), str) or not game['id']:
        raise ValueError('invalid_context_game_id')
    _time(observed_at)
    if type(batch_size) is not int or not 1 <= batch_size <= 100:
        raise ValueError('invalid_context_batch_size')
    if response_sha256 is not None and (not isinstance(response_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', response_sha256)):
        raise ValueError('invalid_response_sha256')
    if error is not None and (not isinstance(error, str) or not error):
        raise ValueError('invalid_context_error')
    snapshot = {
        'schema_version': 1, 'game_id': game['id'], 'app_id': app, 'app_scope': 'base',
        'observed_at': observed_at, 'source_url': ENDPOINT,
        'context': {'country': 'KR', 'language': 'koreana', 'batch_size': batch_size},
        'status': 'unavailable', 'error_code': None, 'store_item_success': None,
        'raw_item_sha256': None, 'response_sha256': response_sha256,
        'source_fields': dict.fromkeys(FIELDS), 'field_present': dict.fromkeys(FIELDS, False),
        'field_status': dict.fromkeys(FIELDS, 'unavailable'), 'field_errors': {},
        'developers': [], 'publishers': [], 'release': None, 'trailers': None,
    }
    if error or item is None:
        snapshot.update(status='error', error_code=error or 'store_item_missing')
        snapshot['field_status'] = dict.fromkeys(FIELDS, 'error')
        return snapshot
    try:
        if not isinstance(item, dict):
            raise ValueError('invalid_context_item')
        snapshot['raw_item_sha256'] = _digest(item)
        if type(item.get('id')) is not int or item['id'] != app or type(item.get('item_type')) is not int or item['item_type'] != 0:
            raise ValueError('context_item_mapping_mismatch')
        success = _integer(item.get('success'))
        snapshot['store_item_success'] = success
        returned = item.get('appid')
        if success != 1:
            if returned is not None and (type(returned) is not int or returned not in (0, app)):
                raise ValueError('context_item_mapping_mismatch')
            snapshot['error_code'] = 'store_item_unavailable'
            return snapshot
        if type(returned) is not int or returned != app:
            raise ValueError('context_item_mapping_mismatch')
        for key in FIELDS:
            if key not in item:
                continue
            snapshot['field_present'][key] = True
            snapshot['source_fields'][key] = deepcopy(item[key])
            try:
                VALIDATORS[key](item[key])
            except ValueError as exception:
                snapshot['field_status'][key] = 'error'
                snapshot['field_errors'][key] = str(exception)
                continue
            snapshot['field_status'][key] = 'ok'
        if snapshot['field_status']['basic_info'] == 'ok':
            for key in ('developers', 'publishers'):
                snapshot[key] = [row['name'] for row in item['basic_info'].get(key, [])]
        for key in ('release', 'trailers'):
            if snapshot['field_status'][key] == 'ok':
                snapshot[key] = deepcopy(item[key])
        if snapshot['field_errors']:
            snapshot.update(status='error', error_code='invalid_context_field')
        elif any(state == 'ok' for state in snapshot['field_status'].values()):
            snapshot['status'] = 'ok'
        else:
            snapshot['error_code'] = 'context_fields_missing'
    except ValueError as exception:
        snapshot.update(status='error', error_code=str(exception))
        snapshot['field_status'] = dict.fromkeys(FIELDS, 'error')
    validate_snapshot(snapshot, game)
    return snapshot


def validate_snapshot(snapshot, game=None):
    """Validate stored provenance and projections; caller checks history/window bounds."""
    if type(snapshot.get('schema_version')) is not int or snapshot['schema_version'] != 1:
        raise ValueError('invalid_context_schema')
    app = _appid(snapshot.get('app_id'))
    if not isinstance(snapshot.get('game_id'), str) or not snapshot['game_id']:
        raise ValueError('invalid_context_game_id')
    if game and (snapshot['game_id'] != game['id'] or app != game['app_id']):
        raise ValueError('context_game_mismatch')
    if snapshot.get('app_scope') != 'base' or snapshot.get('source_url') != ENDPOINT:
        raise ValueError('context_source_mismatch')
    _time(snapshot.get('observed_at'))
    context = snapshot.get('context', {})
    if context.get('country') != 'KR' or context.get('language') != 'koreana' or type(context.get('batch_size')) is not int or not 1 <= context['batch_size'] <= 100:
        raise ValueError('context_scope_mismatch')
    if snapshot.get('status') not in STATUSES:
        raise ValueError('invalid_context_status')
    for key in ('raw_item_sha256', 'response_sha256'):
        if snapshot.get(key) is not None and (not isinstance(snapshot[key], str) or not re.fullmatch(r'[0-9a-f]{64}', snapshot[key])):
            raise ValueError('invalid_context_hash')
    fields, states, present = (snapshot.get(k, {}) for k in ('source_fields', 'field_status', 'field_present'))
    if set(fields) != set(FIELDS) or set(states) != set(FIELDS) or set(present) != set(FIELDS):
        raise ValueError('context_fields_mismatch')
    for key in FIELDS:
        if states[key] not in STATUSES or type(present[key]) is not bool:
            raise ValueError('invalid_context_field_state')
        if not present[key] and fields[key] is not None:
            raise ValueError('context_missing_field_has_value')
        if states[key] == 'ok':
            if not present[key]:
                raise ValueError('context_valid_field_missing')
            VALIDATORS[key](fields[key])
    _json(fields)
    for key in ('developers', 'publishers'):
        expected = ([row['name'] for row in fields['basic_info'].get(key, [])]
                    if states['basic_info'] == 'ok' else [])
        if snapshot.get(key) != expected:
            raise ValueError('context_name_projection_mismatch')
    for key in ('release', 'trailers'):
        expected = fields[key] if states[key] == 'ok' else None
        if snapshot.get(key) != expected:
            raise ValueError('context_projection_mismatch')
    if snapshot['status'] == 'ok' and ('error' in states.values() or 'ok' not in states.values() or snapshot.get('store_item_success') != 1 or not snapshot.get('raw_item_sha256')):
        raise ValueError('context_success_inconsistent')


def coverage(snapshots_by_game):
    """Summarize each game's latest attempt, without falling back to old successes.

    Accept a catalog-ordered list of snapshot lists, or a game-to-list mapping.
    Only fields marked ok contribute. Empty and missing fields remain distinct
    in the snapshot; neither invents a creator, release description, or trailer.
    Trailer totals are per-game unique source metadata entries, not view counts.
    """
    result = dict.fromkeys(('attempted_games', 'ok_games', 'developers_games',
                           'publishers_games', 'release_games', 'trailer_games', 'trailers'), 0)
    result['last_observed_at'] = None
    groups = snapshots_by_game.values() if isinstance(snapshots_by_game, dict) else snapshots_by_game
    for rows in groups:
        if not rows:
            continue
        _, latest = max(enumerate(rows), key=lambda pair: (_time(pair[1]['observed_at']), pair[0]))
        validate_snapshot(latest)
        result['attempted_games'] += 1
        result['ok_games'] += latest['status'] == 'ok'
        if result['last_observed_at'] is None or _time(latest['observed_at']) > _time(result['last_observed_at']):
            result['last_observed_at'] = latest['observed_at']
        if latest['field_status']['basic_info'] == 'ok':
            for field in ('developers', 'publishers'):
                result[field + '_games'] += any(name.strip() for name in latest[field])
        if latest['field_status']['release'] == 'ok':
            release = latest['release']
            meaningful = (any(type(release.get(k)) is int and release[k] > 0
                              for k in ('steam_release_date', 'original_release_date')) or
                          any(isinstance(release.get(k), str) and release[k].strip()
                              for k in ('coming_soon_display', 'custom_release_date_message')) or
                          type(release.get('is_coming_soon')) is bool)
            result['release_games'] += bool(meaningful)
        if latest['field_status']['trailers'] == 'ok':
            unique = set()
            for group in ('highlights', 'other_trailers'):
                for trailer in latest['trailers'].get(group, []):
                    if not trailer.get('trailer_name', '').strip() and not trailer.get('trailer_base_id'):
                        continue
                    key = (('id', trailer['trailer_base_id']) if trailer.get('trailer_base_id')
                           else ('source_fields', _digest(trailer)))
                    unique.add(key)
            result['trailers'] += len(unique)
            result['trailer_games'] += bool(unique)
    return result

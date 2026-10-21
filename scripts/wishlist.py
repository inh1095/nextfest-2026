"""Validate reviewed wishlist evidence and index unreviewed news mentions.

Publisher statements are claims, not verified Steam balances. This module never
collects data, extracts numeric claims from news, or generates wishlist forecasts.
"""
from __future__ import annotations

import math
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from collect import load_json, parse, plain_text, stamp

KEYWORDS = re.compile(r'wish\s*lists?|위시리스트|위시\s*리스트|찜', re.I)
DISCLOSURE_FIELDS = ('id', 'game_id', 'app_id', 'event_id', 'published_at', 'value',
                     'kind', 'operator', 'stock_definition', 'quote', 'source_url',
                     'verified_at', 'usable_as_current_stock', 'as_of')
FOLLOWER_FIELDS = ('id', 'game_id', 'app_id', 'status', 'value', 'observed_at',
                   'source_url', 'candidates', 'mapping', 'estimate_eligible')
METHOD_FIELDS = ('id', 'label', 'lower_multiplier', 'upper_multiplier', 'median_multiplier',
                 'source_url', 'source_date', 'sample_description', 'uncertainty_kind',
                 'validation_status')


def require(condition, reason):
    if not condition:
        raise ValueError('wishlist_' + reason)


def integer(value):
    return type(value) is int and value >= 0


def text(value):
    return isinstance(value, str) and bool(value.strip())


def source_url(value):
    require(text(value), 'source_url_missing')
    parts = urlsplit(value)
    require(parts.scheme == 'https' and bool(parts.hostname) and
            not parts.username and not parts.password, 'invalid_source_url')


def timestamp(value, now, *, optional=False, date_allowed=False):
    if value is None and optional:
        return
    require(text(value), 'timestamp_missing')
    if date_allowed and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        require(date.fromisoformat(value) <= now.date(), 'future_date')
    else:
        require(parse(value) <= now, 'future_timestamp')


def select_fields(row, fields):
    require(isinstance(row, dict) and all(key in row for key in fields), 'missing_record_fields')
    return {key: row[key] for key in fields}


def normalize_source(source, catalog, now, events):
    require(isinstance(source, dict), 'invalid_source')
    games = {g['id']: g for g in catalog['games']}
    event_map = {e['id']: e for e in events}
    result, seen = {}, set()
    for section, fields in [('disclosures', DISCLOSURE_FIELDS),
                            ('follower_checks', FOLLOWER_FIELDS), ('methods', METHOD_FIELDS)]:
        rows = source.get(section, [])
        require(isinstance(rows, list), 'invalid_' + section)
        result[section] = []
        for raw in rows:
            row = select_fields(raw, fields)
            require(text(row['id']) and row['id'] not in seen, 'duplicate_or_invalid_id')
            seen.add(row['id'])
            source_url(row['source_url'])
            if section != 'methods':
                game = games.get(row['game_id'])
                require(game is not None and type(row['app_id']) is int and
                        row['app_id'] == game['app_id'], 'game_appid_mismatch')
            if section == 'disclosures':
                for field in ('period_text', 'review_scope'):
                    if field in raw:
                        require(text(raw[field]) and len(raw[field]) <= 2000,
                                'invalid_' + field)
                        row[field] = raw[field]
                if 'source_context_url' in raw:
                    source_url(raw['source_context_url'])
                    require(len(raw['source_context_url']) <= 4096, 'invalid_source_context_url')
                    row['source_context_url'] = raw['source_context_url']
                row['platform_scope'] = raw.get('platform_scope', 'unspecified')
                require(row['platform_scope'] in {'steam', 'unspecified'}, 'invalid_platform_scope')
                if 'time_precision' in raw:
                    require(raw['time_precision'] in {'day', 'hour', 'minute', 'second'}, 'invalid_time_precision')
                    row['time_precision'] = raw['time_precision']
                require(integer(row['value']), 'invalid_disclosure_value')
                require(row['kind'] in {'milestone_lower_bound', 'reported_count', 'period_additions'},
                        'invalid_disclosure_kind')
                require(row['operator'] in {'gt', 'gte', 'eq', 'approx'}, 'invalid_operator')
                require(row['stock_definition'] in {'unspecified', 'balance', 'lifetime_adds', 'period_adds'},
                        'invalid_stock_definition')
                require(row['kind'] != 'milestone_lower_bound' or row['operator'] in {'gt', 'gte'},
                        'milestone_requires_lower_bound')
                require(row['kind'] != 'period_additions' or row['stock_definition'] == 'period_adds',
                        'period_additions_definition')
                require(row['usable_as_current_stock'] is False, 'claim_is_not_current_stock')
                require(text(row['quote']), 'quote_missing')
                timestamp(row['published_at'], now, date_allowed=True)
                timestamp(row['verified_at'], now)
                timestamp(row['published_at'], parse(row['verified_at']), date_allowed=True)
                if re.fullmatch(r'\d{4}-\d{2}-\d{2}', row['published_at']):
                    require(row.get('time_precision', 'day') == 'day', 'date_only_precision_mismatch')
                    row['time_precision'] = 'day'
                timestamp(row['as_of'], parse(row['verified_at']), optional=True, date_allowed=True)
                if row['event_id'] is not None:
                    event = event_map.get(row['event_id'])
                    require(event is not None and event['game_id'] == row['game_id'], 'event_reference_mismatch')
                    require(row['source_url'] == event.get('source_url'), 'event_source_mismatch')
                    require(row['published_at'] == event.get('published_at'), 'event_publication_mismatch')
                    normalized = lambda value: re.sub(r'\s+', ' ', value).strip().casefold()
                    excerpt = normalized(row['quote'])
                    stored = normalized(event.get('title', '') + ' ' + event.get('summary', ''))
                    require(excerpt in stored, 'quote_not_in_stored_event')
            elif section == 'follower_checks':
                require(row['status'] in {'ok', 'conflict', 'unavailable'}, 'invalid_follower_status')
                require(row['estimate_eligible'] is False, 'unvalidated_estimate_eligibility')
                timestamp(row['observed_at'], now, optional=row['status'] != 'ok')
                if 'verified_at' in raw:
                    timestamp(raw['verified_at'], now)
                    row['verified_at'] = raw['verified_at']
                if 'observation_window_utc' in raw:
                    window = raw['observation_window_utc']
                    require(isinstance(window, list) and len(window) == 2, 'invalid_observation_window')
                    for at in window:
                        timestamp(at, now)
                    require(parse(window[0]) <= parse(window[1]), 'reversed_observation_window')
                    if row['observed_at'] is not None:
                        require(parse(window[0]) <= parse(row['observed_at']) <= parse(window[1]),
                                'observation_outside_window')
                    row['observation_window_utc'] = window
                require(isinstance(row['mapping'], (str, dict)) and bool(row['mapping']), 'mapping_missing')
                require(isinstance(row['candidates'], list), 'invalid_candidates')
                paths, values = set(), set()
                for candidate in row['candidates']:
                    require(isinstance(candidate, dict) and text(candidate.get('path')) and
                            integer(candidate.get('value')), 'invalid_candidate')
                    require(candidate['path'] not in paths, 'duplicate_candidate_path')
                    paths.add(candidate['path'])
                    values.add(candidate['value'])
                if row['status'] == 'ok':
                    require(integer(row['value']) and values == {row['value']}, 'unresolved_follower_value')
                else:
                    require(row['value'] is None, 'unavailable_follower_must_be_null')
                if row['status'] == 'conflict':
                    require(len(values) > 1, 'conflict_requires_disagreement')
            else:
                require(text(row['label']) and text(row['sample_description']), 'method_description_missing')
                factors = [row[k] for k in ('lower_multiplier', 'median_multiplier', 'upper_multiplier')]
                require(all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in factors),
                        'invalid_multiplier')
                require(factors[0] <= factors[1] <= factors[2], 'unordered_multipliers')
                timestamp(row['source_date'], now, date_allowed=True)
                require(row['uncertainty_kind'] == 'historical_reference_not_confidence_interval' and
                        row['validation_status'] == 'not_validated_for_this_event', 'unsupported_accuracy_claim')
            result[section].append(row)
    return result


def mentions_from_events(events, catalog):
    games = {g['id'] for g in catalog['games']}
    mentions = {}
    for event in events:
        content = plain_text(event.get('summary', ''), 10000)
        title = plain_text(event.get('title', ''), 250)
        match = KEYWORDS.search(title + ' ' + content)
        if not match:
            continue
        require(event.get('game_id') in games, 'mention_unknown_game')
        source_url(event.get('source_url'))
        combined = title + ' ' + content
        begin = max(0, match.start() - 60)
        mentions[event['id']] = {
            'event_id': event['id'], 'game_id': event['game_id'], 'title': title,
            'published_at': event.get('published_at'), 'source_url': event['source_url'],
            'quote': combined[begin:begin + 280],
        }
    return sorted(mentions.values(), key=lambda e: (e['published_at'] or '', e['event_id']), reverse=True)


def build_index(root: Path, catalog, now, *, events=None):
    """Return a deterministic public index; callers own writes. No network calls."""
    now = parse(stamp(now))
    if events is None:
        events = []
        for game in catalog['games']:
            path = root / 'site/data/games' / (game['id'] + '.json')
            if path.exists():
                events.extend(load_json(path).get('events', []))
    source_path = root / 'config/wishlist-evidence.json'
    source = load_json(source_path) if source_path.exists() else {}
    normalized = normalize_source(source, catalog, now, events)
    mentions = mentions_from_events(events, catalog)
    disclosures, followers = normalized['disclosures'], normalized['follower_checks']
    # Multiple immutable checks may exist. Coverage describes each game's latest check.
    latest = {}
    def check_time(row):
        at = row['observed_at'] or row.get('verified_at')
        if not at and row.get('observation_window_utc'):
            at = row['observation_window_utc'][1]
        return parse(at).timestamp() if at else float('-inf')
    for row in sorted(followers, key=lambda r: (check_time(r), r['id'])):
        latest[row['game_id']] = row
    return {'schema_version': 1, 'generated_at': stamp(now), **normalized, 'mentions': mentions,
            'coverage': {'disclosure_games': len({r['game_id'] for r in disclosures}),
                         'disclosures': len(disclosures),
                         'mention_games': len({r['game_id'] for r in mentions}),
                         'mentions': len(mentions),
                         'followers_ok': sum(r['status'] == 'ok' for r in latest.values()),
                         'followers_conflict': sum(r['status'] == 'conflict' for r in latest.values())}}

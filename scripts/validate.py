#!/usr/bin/env python3
"""Validate catalog coverage, per-game histories and preserved original evidence."""
import json
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from collect import ROOT, load_json, parse, stamp
from fleet import (adjacent, range_summary, target_minutes, observation_history,
                   news_history, collection_metadata, ccu_enabled)
from wishlist import build_index as build_wishlist_index
import store_metrics
from game_context import public_config


def require(condition, message):
    if not condition:
        raise ValueError(message)


def url(value):
    require(isinstance(value, str) and urlsplit(value).scheme == 'https', 'https_source_required')
    require(not urlsplit(value).username and not urlsplit(value).password, 'credential_in_url')


def signature(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def require_same_json(actual, expected, message):
    """Compare JSON values without Python's True == 1 or NaN loopholes."""
    try:
        encode = lambda value: json.dumps(value, sort_keys=True, allow_nan=False,
                                           separators=(',', ':'))
        equal = encode(actual) == encode(expected)
    except (TypeError, ValueError):
        equal = False
    require(equal, message)


def expected_ccu_summary(history, game, config, full_interval, start, end):
    samples = sorted((s for s in history['samples'] if s['metric'] == 'demo_ccu'),
                     key=lambda s: s['observed_at'])
    require(all(parse(s['observed_at']) <= end for s in samples),
            'sample_after_summary_window')
    good = [s for s in samples if s['status'] == 'ok']
    last = samples[-1] if samples else None
    latest = good[-1] if good else None
    interval = (int(config['collection']['interval_minutes'])
                if game['id'] in config['collection'].get('priority_game_ids', [])
                else full_interval)
    ranges = {period: range_summary(
        samples, start if period == 'all' else max(start, end - timedelta(hours=int(period))),
        end, interval * 2 + 30) for period in ('all', '6', '24')}
    return {
        'ccu_collection_enabled': ccu_enabled(config),
        'target_interval_minutes': interval,
        'status': last['status'] if last else ('pending' if game.get('demo_app_id') else 'unavailable'),
        'last_attempt_at': last['observed_at'] if last else None,
        'last_ok_at': latest['observed_at'] if latest else None,
        'current': latest['value'] if latest else None,
        'last_error_code': last.get('error_code') if last else None,
        'observation_history': observation_history(samples, end),
        'ranges': ranges,
    }, samples


def validate_history(data, game_ids, start, stop):
    seen = set()
    for sample in data['samples']:
        require(sample['game_id'] in game_ids, 'unknown_sample_game')
        require(sample['metric'] in {'demo_ccu', 'followers', *store_metrics.METRICS}, 'unknown_sample_metric')
        at = parse(sample['observed_at'])
        require(start <= at < stop, 'sample_outside_observation_window')
        key = (sample['game_id'], sample['metric'], sample['observed_at'])
        require(key not in seen, 'duplicate_sample')
        seen.add(key)
        url(sample['source_url'])
        if sample['status'] == 'ok':
            require(type(sample['value']) is int and sample['value'] >= 0, 'invalid_measurement')
            require(sample['metric'] != 'followers', 'followers_not_verified_for_this_project')
        else:
            require(sample['status'] in {'error', 'unavailable'}, 'unknown_sample_status')
            require(sample['value'] is None, 'missing_value_must_be_null')
        if sample['metric'] in store_metrics.METRICS:
            store_metrics.validate_sample(sample)
    review_counts = {(s['game_id'], s['observed_at']): s for s in data['samples']
                     if s['metric'] == 'review_count'}
    for sample in data['samples']:
        if sample['metric'] == 'review_positive_percent' and sample['status'] == 'ok':
            count = review_counts.get((sample['game_id'], sample['observed_at']))
            require(count is not None and count['status'] == 'ok' and count['value'] > 0,
                    'review_percentage_without_reviews')
    events = {}
    for event in data['events']:
        require(event['id'] not in events, 'duplicate_event')
        events[event['id']] = event
        require(event['game_id'] in game_ids, 'unknown_event_game')
        url(event['source_url'])
        for key in ('occurred_at', 'published_at'):
            if event.get(key):
                parse(event[key])
        parse(event['verified_at'])
    for analysis in data['analyses']:
        require(analysis['game_id'] in game_ids, 'unknown_analysis_game')
        require(set(analysis['evidence_event_ids']).issubset(events), 'analysis_evidence_missing')
        require(analysis['assessment'] in {'direct_evidence', 'temporal_association', 'insufficient'}, 'invalid_assessment')
        begins, ends, reviewed = parse(analysis['from']), parse(analysis['to']), parse(analysis['reviewed_at'])
        require(start <= begins <= ends < stop and ends <= reviewed, 'invalid_analysis_window')
        samples = {s['observed_at']: s for s in data['samples']
                   if s['game_id'] == analysis['game_id'] and s['status'] == 'ok'
                   and s['metric'] == analysis.get('metric', 'demo_ccu')}
        require(bool(analysis['evidence_sample_times']), 'analysis_sample_evidence_missing')
        for at in analysis['evidence_sample_times']:
            require(at in samples and begins <= parse(at) <= ends, 'invalid_analysis_sample_reference')
        for event_id in analysis['evidence_event_ids']:
            require(events[event_id]['game_id'] == analysis['game_id'], 'analysis_event_wrong_game')
    require(data['collection_status'] in {'pending', 'active', 'archived'}, 'collection_status')


def validate(root: Path = ROOT):
    config = load_json(root / 'config/manifest.json')
    public = load_json(root / 'site/data/config.json')
    original = load_json(root / 'site/data/observations.json')
    context_catalog = (load_json(root / 'site/data/catalog.json') if config['schema_version'] == 2
                       else {'games': config['games']})
    require_same_json(public_config(root, config, context_catalog), public, 'public_config_mismatch')
    start, stop = parse(config['event']['starts_at']), parse(config['collection']['stops_at'])
    require(start < stop, 'collection_window')
    require(stop == parse(config['event']['ends_at']), 'unexpected_post_event_collection')
    if config['schema_version'] == 1:
        ids = {g['id'] for g in config['games']}
        require(len(ids) == len(config['games']), 'duplicate_game')
        validate_history(original, ids, start, stop)
        print(f"Validated {len(ids)} games, {len(original['samples'])} observations, {len(original['events'])} events.")
        return
    require(config['schema_version'] == 2, 'schema_version')
    catalog = load_json(root / 'site/data/catalog.json')
    summary = load_json(root / 'site/data/summary.json')
    event_index = load_json(root / 'site/data/events-index.json')
    generated = parse(summary['generated_at'])
    window_end = min(generated, stop)
    require(summary['window_end'] == stamp(window_end), 'summary_window_end_mismatch')
    require(summary['collection_status'] == ('archived' if generated >= stop else
            'pending' if generated < start else 'active'), 'summary_collection_status_mismatch')
    games = catalog['games']
    ids = {g['id'] for g in games}
    appids = {g['app_id'] for g in games}
    require(len(ids) == len(appids) == len(games), 'duplicate_game')
    require(len(games) == catalog['coverage']['unique_total'], 'catalog_count_mismatch')
    if catalog['coverage']['complete']:
        require(len(games) == catalog['coverage']['official_total'], 'incomplete_catalog')
    require(set(g['game_id'] for g in summary['games']) == ids, 'summary_game_set_mismatch')
    require(len(summary['games']) == len(games), 'duplicate_summary_game')
    rows = {g['game_id']: g for g in summary['games']}
    expected_coverage = dict.fromkeys(summary['coverage'], 0)
    expected_coverage['catalog_total'] = len(games)
    full_interval = target_minutes(config, catalog, '__all__')
    all_events, counts, original_signatures = {}, Counter(), {}
    for game in games:
        gid = game['id']
        require(bool(re.fullmatch(r'[a-z0-9-]+', gid)), 'unsafe_game_id')
        require(type(game['app_id']) is int and game['app_id'] > 0, 'appid_type')
        demo = game.get('demo_app_id')
        require(demo is None or (type(demo) is int and demo > 0 and demo != game['app_id']), 'base_demo_confusion')
        require(demo is None or game.get('demo_app_ids') == [demo], 'ambiguous_demo_mapping')
        url(game['participation']['source_url'])
        require(bool(game['participation']['evidence_excerpt']), 'participation_evidence_missing')
        hist = load_json(root / 'site/data/games' / f'{gid}.json')
        validate_history(hist, {gid}, start, stop)
        for sample in hist['samples']:
            require(parse(sample['observed_at']) <= window_end, 'sample_after_summary_window')
            if sample['metric'] in store_metrics.METRICS:
                store_metrics.validate_sample(sample, game)
        require_same_json(rows[gid].get('metrics'),
                          store_metrics.summaries(hist['samples'], config, catalog, game,
                                                  window_end),
                          'summary_store_metrics_mismatch:' + gid)
        counts['samples'] += len(hist['samples'])
        counts['events'] += len(hist['events'])
        expected, samples = expected_ccu_summary(hist, game, config, full_interval, start, window_end)
        for field, value in expected.items():
            require(field in rows[gid], f'missing_summary_{field}')
            require_same_json(rows[gid][field], value, f'summary_{field}_mismatch:{gid}')
        news = hist.get('news_status', {}).get(gid, {})
        for field, value in {
            'news_status': news.get('status', 'pending'),
            'last_news_attempt_at': news.get('last_attempt_at'),
            'news_all_checked_at': news.get('all_sources_checked_at'),
            'news_error_codes': news.get('error_codes', []),
            'news_history': news_history(hist['events']),
        }.items():
            require(field in rows[gid], f'missing_summary_{field}')
            require_same_json(rows[gid][field], value, f'summary_{field}_mismatch:{gid}')
        facts = {
            'demo_resolved': bool(demo), 'ccu_attempted': bool(samples),
            'ccu_ok': expected['current'] is not None,
            'ccu_pending': expected['status'] == 'pending',
            'ccu_error': expected['status'] == 'error',
            'ccu_unavailable': expected['status'] == 'unavailable',
            'comparison_ready': any(adjacent(a, b, expected['target_interval_minutes'] * 2 + 30)
                                    is not None for a, b in zip(samples, samples[1:])),
            'growth_candidate_games': expected['ranges']['all']['positive_intervals'] > 0,
            'reviewed_games': bool(hist['analyses']),
            'news_checked': news.get('status') == 'ok',
            'news_pending': not bool(news.get('last_attempt_at')),
        }
        for field, value in facts.items():
            expected_coverage[field] = expected_coverage.get(field, 0) + int(value)
        require(rows[gid]['history_url'] == f'./data/games/{gid}.json', 'unsafe_history_url')
        for event in hist['events']:
            require(event['id'] not in all_events, 'duplicate_global_event')
            all_events[event['id']] = event
        if gid in {g['id'] for g in config['games']}:
            original_signatures[gid] = {field: set(map(signature, hist[field])) for field in ('samples', 'events', 'analyses')}
    require_same_json(summary['coverage'], expected_coverage, 'summary_coverage_mismatch')
    require_same_json(summary['collection'].get('target_cycle_minutes'),
                      full_interval, 'summary_target_cycle_mismatch')
    for field, value in collection_metadata(config, catalog).items():
        require(field in summary['collection'], f'missing_collection_{field}')
        require_same_json(summary['collection'][field], value,
                          f'summary_collection_{field}_mismatch')
    require(len(event_index['events']) == len(all_events), 'event_index_count_mismatch')
    require(len({e['id'] for e in event_index['events']}) == len(all_events), 'duplicate_index_event')
    for event in event_index['events']:
        require(event['id'] in all_events, 'unknown_index_event')
        require(all(all_events[event['id']].get(k) == v for k, v in event.items()), 'event_index_mismatch')
    for field in ('samples', 'events', 'analyses'):
        for item in original[field]:
            require(signature(item) in original_signatures[item['game_id']][field], 'original_evidence_not_preserved')
    state = load_json(root / 'site/data/collection-state.json')
    budgets = Counter()
    for reservation in state['reservations'].values():
        budgets[reservation['day']] += reservation['allowance']
        used = reservation.get('used')
        require(used is None or 0 <= used <= reservation['allowance'], 'request_reservation_exceeded')
    require(all(v <= config['collection']['daily_request_budget'] for v in budgets.values()), 'daily_request_budget_exceeded')
    wishlist_path = root / 'site/data/wishlists.json'
    require(wishlist_path.is_file(), 'wishlist_index_missing')
    require_same_json(load_json(wishlist_path),
                      build_wishlist_index(root, catalog, generated, events=list(all_events.values())),
                      'wishlist_index_mismatch')
    print(f"Validated {len(games)} catalog games, {counts['samples']} observations, {counts['events']} events; original evidence preserved.")


if __name__ == '__main__':
    validate()

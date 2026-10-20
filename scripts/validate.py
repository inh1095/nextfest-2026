#!/usr/bin/env python3
"""Validate catalog coverage, per-game histories and preserved original evidence."""
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from collect import ROOT, load_json, parse


def require(condition, message):
    if not condition:
        raise ValueError(message)


def url(value):
    require(isinstance(value, str) and urlsplit(value).scheme == 'https', 'https_source_required')
    require(not urlsplit(value).username and not urlsplit(value).password, 'credential_in_url')


def signature(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def validate_history(data, game_ids, start, stop):
    seen = set()
    for sample in data['samples']:
        require(sample['game_id'] in game_ids, 'unknown_sample_game')
        require(sample['metric'] in {'demo_ccu', 'followers'}, 'unknown_sample_metric')
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
                   if s['game_id'] == analysis['game_id'] and s['status'] == 'ok'}
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
    require(config == public, 'public_config_mismatch')
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
    require(summary['coverage']['catalog_total'] == len(games), 'summary_coverage_mismatch')
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
        counts['samples'] += len(hist['samples'])
        counts['events'] += len(hist['events'])
        good = [s for s in hist['samples'] if s['metric'] == 'demo_ccu' and s['status'] == 'ok']
        latest = max(good, key=lambda s: s['observed_at']) if good else None
        require(rows[gid]['current'] == (latest['value'] if latest else None), 'stale_summary_value')
        require(rows[gid]['last_ok_at'] == (latest['observed_at'] if latest else None), 'stale_summary_time')
        require(rows[gid]['history_url'] == f'./data/games/{gid}.json', 'unsafe_history_url')
        for event in hist['events']:
            require(event['id'] not in all_events, 'duplicate_global_event')
            all_events[event['id']] = event
        if gid in {g['id'] for g in config['games']}:
            original_signatures[gid] = {field: set(map(signature, hist[field])) for field in ('samples', 'events', 'analyses')}
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
    print(f"Validated {len(games)} catalog games, {counts['samples']} observations, {counts['events']} events; original evidence preserved.")


if __name__ == '__main__':
    validate()

"""Validate append-only decisions about numeric announcement candidates."""
import re

from collect import load_json, parse
from wishlist import source_url, timestamp


DECISIONS = {'verified_claim', 'not_a_claim', 'needs_review', 'source_unavailable'}


def require(condition, reason):
    if not condition:
        raise ValueError('source_review_' + reason)


def verified_check(check, reviewed_at):
    require(isinstance(check, dict), 'source_check')
    require(type(check.get('http_status')) is int and check['http_status'] == 200
            and check.get('app_id_matches') is True and check.get('publication_matches') is True,
            'unverified_source')
    timestamp(check.get('observed_at'), parse(reviewed_at))
    source_url(check.get('request_url'))
    require(isinstance(check.get('body_sha256'), str) and
            re.fullmatch('[a-f0-9]{64}', check['body_sha256']) is not None, 'source_hash')


def load_amendments(root, now, disclosures):
    path = root / 'config/source-reviews.json'
    rows = load_json(path).get('disclosure_amendments', []) if path.exists() else []
    require(isinstance(rows, list), 'amendments')
    claims = {d['id']: d for d in disclosures}
    active, seen = set(claims), set()
    for row in rows:
        require(isinstance(row, dict), 'amendment_record')
        timestamp(row.get('reviewed_at'), now)
    for row in sorted(rows, key=lambda r: (parse(r['reviewed_at']), r.get('id', ''))):
        require(isinstance(row.get('id'), str) and row['id'] and row['id'] not in seen,
                'amendment_id')
        seen.add(row['id'])
        previous, replacement = row.get('previous_disclosure_id'), row.get('replacement_disclosure_id')
        require(previous in active and replacement in active and previous != replacement,
                'amendment_chain')
        old, new = claims[previous], claims[replacement]
        require(all(old.get(k) == new.get(k) for k in ('game_id', 'app_id', 'source_url', 'published_at')),
                'amendment_source_mapping')
        timestamp(row.get('reviewed_at'), now)
        require(parse(new['verified_at']) <= parse(row['reviewed_at']), 'amendment_before_replacement')
        require(row.get('reviewer') == 'gpt-6.1-sol', 'amendment_reviewer')
        require(isinstance(row.get('reason'), str) and row['reason'].strip(), 'amendment_reason')
        verified_check(row.get('source_check'), row['reviewed_at'])
        active.remove(previous)
    return rows, [d for d in disclosures if d['id'] in active]


def load_reviews(root, catalog, now, events, disclosures):
    path = root / 'config/source-reviews.json'
    if not path.exists():
        return [], {}
    data = load_json(path)
    require(data.get('schema_version') == 1, 'schema')
    records = data.get('candidate_reviews')
    require(isinstance(records, list), 'records')
    games = {g['id']: g['app_id'] for g in catalog['games']}
    event_map = {e['id']: e for e in events}
    claims = {d['id']: d for d in disclosures}
    seen, latest = set(), {}
    for row in records:
        require(isinstance(row, dict), 'record')
        require(isinstance(row.get('id'), str) and row['id'] and row['id'] not in seen, 'id')
        seen.add(row['id'])
        require(row.get('game_id') in games and type(row.get('app_id')) is int
                and row['app_id'] == games[row['game_id']], 'game_mapping')
        event = event_map.get(row.get('event_id'))
        require(event is not None and event['game_id'] == row['game_id'], 'event_mapping')
        require(row.get('candidate_id') == 'candidate-' + event['id'], 'candidate_mapping')
        require(row.get('source_url') == event.get('source_url')
                and row.get('published_at') == event.get('published_at'), 'source_mapping')
        source_url(row['source_url'])
        timestamp(row.get('reviewed_at'), now)
        timestamp(row['published_at'], parse(row['reviewed_at']), date_allowed=True)
        require(row.get('decision') in DECISIONS, 'decision')
        require(isinstance(row.get('reason'), str) and bool(row['reason'].strip()), 'reason')
        require(row.get('reviewer') == 'gpt-6.1-sol', 'reviewer')
        check = row.get('source_check')
        require(isinstance(check, dict), 'source_check')
        if check.get('observed_at') is not None:
            timestamp(check['observed_at'], parse(row['reviewed_at']))
        if check.get('request_url') is not None:
            source_url(check['request_url'])
        if row['decision'] in {'verified_claim', 'not_a_claim'}:
            require(check.get('http_status') == 200 and check.get('app_id_matches') is True
                    and check.get('publication_matches') is True, 'unverified_source')
            require(check.get('observed_at') is not None and check.get('request_url') is not None,
                    'missing_check_context')
            require(isinstance(check.get('body_sha256'), str) and
                    re.fullmatch('[a-f0-9]{64}', check['body_sha256']) is not None, 'source_hash')
        ids = row.get('disclosure_ids', [])
        require(isinstance(ids, list) and len(ids) == len(set(ids)), 'disclosure_ids')
        require(row['decision'] != 'verified_claim' or bool(ids), 'verified_without_disclosure')
        require(row['decision'] == 'verified_claim' or not ids, 'unexpected_disclosures')
        for did in ids:
            claim = claims.get(did)
            require(claim is not None and claim['game_id'] == row['game_id']
                    and claim['source_url'] == row['source_url']
                    and claim['published_at'] == row['published_at'], 'disclosure_mapping')
        previous = latest.get(row['event_id'])
        if previous is None or (parse(row['reviewed_at']), row['id']) > (
                parse(previous['reviewed_at']), previous['id']):
            latest[row['event_id']] = row
    return records, latest

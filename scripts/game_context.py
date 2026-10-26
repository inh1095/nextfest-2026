"""Validate and expose immutable, restored game context without touching the catalog."""
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from collect import UTC, load_json, parse


def require(condition, message):
    if not condition:
        raise ValueError('game_context_' + message)


def text(value, *, empty=False):
    require(isinstance(value, str) and (empty or bool(value.strip())), 'invalid_text')


def url(value):
    text(value)
    parsed = urlsplit(value)
    require(parsed.scheme == 'https' and bool(parsed.hostname) and
            not parsed.username and not parsed.password, 'invalid_source_url')


def timestamp(value, now, *, day=False):
    text(value)
    if day and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        require(datetime.strptime(value, '%Y-%m-%d').date() <= now.date(), 'future_date')
        return
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None and parsed <= now, 'invalid_or_future_timestamp')


def provenance(value, source_ids, now):
    require(isinstance(value, dict), 'invalid_provenance')
    require(value.get('source_id') in source_ids, 'unknown_source_id')
    text(value.get('path'))
    observed = value.get('observed_at')
    if observed is not None:
        timestamp(observed, now)
    else:
        timestamp(value.get('evidence_collected_at'), now)
    if value.get('evidence_collected_at') is not None:
        timestamp(value['evidence_collected_at'], now)


def validate_context(data, catalog, now=None):
    now = now or datetime.now(UTC)
    require(isinstance(data, dict) and type(data.get('schema_version')) is int and
            data['schema_version'] == 1, 'schema_version')
    # Forbid non-finite values even inside provenance extensions.
    json.dumps(data, allow_nan=False)
    timestamp(data.get('generated_at'), now)
    timestamp(data.get('source_snapshot_at'), now)
    require(parse(data['source_snapshot_at']) <= parse(data['generated_at']), 'snapshot_after_generation')
    sources, games = data.get('sources'), data.get('games')
    require(isinstance(sources, list) and isinstance(games, list), 'invalid_records')
    source_ids = set()
    for source in sources:
        require(isinstance(source, dict), 'invalid_source')
        text(source.get('id'))
        require(source['id'] not in source_ids, 'duplicate_source')
        source_ids.add(source['id'])
        url(source.get('source_url'))
        if source.get('observed_at') is not None:
            timestamp(source['observed_at'], now)
        else:
            timestamp(source.get('evidence_collected_at'), now)
    mapping = {g['id']: g['app_id'] for g in catalog['games']}
    seen = set()
    for game in games:
        require(isinstance(game, dict), 'invalid_game')
        gid = game.get('game_id')
        require(isinstance(gid, str) and gid in mapping and gid not in seen, 'game_mapping_or_duplicate')
        seen.add(gid)
        require(type(game.get('app_id')) is int and game['app_id'] == mapping[gid], 'appid_mapping')
        profile = game.get('profile_snapshot')
        if profile is not None:
            require(isinstance(profile, dict), 'invalid_profile')
            for key in ('developers', 'publishers'):
                require(isinstance(profile.get(key), list), 'invalid_' + key)
                for name in profile[key]:
                    text(name, empty=True)  # Preserve provider blanks; the UI omits empty labels.
            require(isinstance(profile.get('genres'), list), 'invalid_genres')
            for genre in profile['genres']:
                require(isinstance(genre, dict), 'invalid_genre')
                text(genre.get('id'))
                text(genre.get('description'))
            release = profile.get('release_date')
            if release is not None:
                require(isinstance(release, dict) and type(release.get('coming_soon')) is bool,
                        'invalid_release')
                text(release.get('date'), empty=True)  # Provider text; a future plan is allowed.
            timestamp(profile.get('observed_at'), now)
            url(profile.get('source_url'))
            origin = profile.get('provenance')
            require(isinstance(origin, dict), 'invalid_profile_provenance')
            require(type(origin.get('batch_index')) is int and origin['batch_index'] >= 0, 'invalid_batch')
            require(isinstance(origin.get('raw_response_sha256'), str) and
                    bool(re.fullmatch('[0-9a-f]{64}', origin['raw_response_sha256'])), 'invalid_raw_hash')
            fields = origin.get('fields')
            require(isinstance(fields, dict), 'missing_field_provenance')
            for key in ('developers', 'publishers', 'genres', 'release_date'):
                field = fields.get(key)
                require(not profile.get(key) or field is not None, 'missing_' + key + '_provenance')
                if field is not None:
                    provenance(field, source_ids, now)
        videos = game.get('videos_snapshot', [])
        require(isinstance(videos, list), 'invalid_videos')
        for video in videos:
            require(isinstance(video, dict), 'invalid_video')
            for key in ('source_url', 'author_url', 'relationship_source_url'):
                url(video.get(key))
            text(video.get('title'))
            text(video.get('author_name'))
            timestamp(video.get('published_at'), now, day=True)
            timestamp(video.get('observed_at'), now)
            origin = video.get('provenance')
            provenance(origin, source_ids, now)
            if origin.get('published_at_source') is not None:
                text(origin['published_at_source'])
    expected_coverage = {
        'catalog_games': len(catalog['games']), 'mapped_games': len(games),
        'developers_games': sum(any(name.strip() for name in
                                   (g.get('profile_snapshot') or {}).get('developers', [])) for g in games),
        'publishers_games': sum(any(name.strip() for name in
                                   (g.get('profile_snapshot') or {}).get('publishers', [])) for g in games),
        'genres_games': sum(bool((g.get('profile_snapshot') or {}).get('genres')) for g in games),
        'release_date_games': sum((g.get('profile_snapshot') or {}).get('release_date') is not None
                                  for g in games),
        'video_games': sum(bool(g.get('videos_snapshot')) for g in games),
        'videos': sum(len(g.get('videos_snapshot', [])) for g in games),
    }
    require(json.dumps(data.get('coverage'), sort_keys=True, allow_nan=False) ==
            json.dumps(expected_coverage, sort_keys=True), 'coverage_mismatch')
    return data


def public_config(root, manifest, catalog):
    path = root / 'config/game-context.json'
    if not path.exists():
        return manifest
    context = validate_context(load_json(path), catalog)
    return {**manifest, 'game_context': context}

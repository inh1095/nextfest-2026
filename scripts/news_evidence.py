"""Discover unreviewed numeric mentions in full official news, without storing bodies.

This is a language-pattern detector, not a SOL review or an extractor of measured
wishlist values. Goals, ranks, giveaways and unrelated numbers can be candidates.
The bounded language patterns cannot establish complete semantic coverage.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
from datetime import datetime
from urllib.parse import urlsplit

from collect import UTC, parse, stamp

DETECTOR = 'official_steam_news_full_text_numeric_scan'
STATUS = 'unreviewed_numeric_mention'
KEYWORD = re.compile(
    r'wish\s*list(?:s|ed|ing)?|위시\s*리스트|찜|愿望(?:清)?单|願望(?:清)?單|'
    r'ウ[ィイ]ッシュリスト|Wunschlist\w*|listas?\s+de\s+(?:deseos|desejos)|'
    r'listes?\s+de\s+souhaits|list[ae]\s+dei\s+desideri|списк\w*\s+желан\w*', re.I)
QUANTITY = re.compile(
    r'\d|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|'
    r'thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|'
    r'forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|'
    r'half|dozen)\b|[零〇一二三四五六七八九十百千万萬亿億]|(?:천|만|억)(?:\s|개|명|달성|돌파)', re.I)
FIELDS = {'id', 'game_id', 'app_id', 'source_app_id', 'source_kind', 'news_gid',
          'event_id', 'source_url', 'published_at', 'observed_at', 'body_sha256',
          'content_sha256', 'quote', 'review_status', 'discovery_method',
          'interpretation', 'detector_version'}


def _require(condition, reason):
    if not condition:
        raise ValueError('news_evidence_' + reason)


def _appid(value):
    return type(value) is int and value > 0


def _identity(game, source_app_id):
    _require(isinstance(game, dict) and isinstance(game.get('id'), str)
             and bool(game['id']) and _appid(game.get('app_id')), 'invalid_game')
    _require(_appid(source_app_id), 'invalid_source_appid')
    if source_app_id == game['app_id']:
        return 'base'
    _require(_appid(game.get('demo_app_id')) and source_app_id == game['demo_app_id'],
             'unmapped_source_appid')
    return 'demo'


def _official_url(url, source_app_id, gid):
    _require(isinstance(url, str) and bool(url), 'missing_source_url')
    parts = urlsplit(url)
    _require(parts.scheme == 'https' and not parts.username and not parts.password
             and parts.port in (None, 443), 'invalid_source_url')
    host = parts.hostname
    if host == 'steamstore-a.akamaihd.net':
        m = re.fullmatch(r'/news/externalpost/steam_community_announcements/(\d+)/?', parts.path)
        _require(m is not None and m[1] == gid, 'source_gid_mismatch')
    else:
        _require(host in {'store.steampowered.com', 'steamcommunity.com',
                          'www.steamcommunity.com'}, 'unofficial_source')
        m = re.search(r'/(?:games|ogg|news/app)/(\d+)(?:/|$)', parts.path)
        if m:
            _require(int(m[1]) == source_app_id, 'source_url_appid_mismatch')


def _time(value):
    _require(isinstance(value, str) and bool(value), 'invalid_timestamp')
    try:
        return parse(value)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError('news_evidence_invalid_timestamp') from error


def _plain(value):
    value = html.unescape(value)
    # Do not retain URLs, image placeholders or executable HTML as quotation text.
    value = re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)>', ' ', value,
                   flags=re.I | re.S)
    value = re.sub(r'<[^>]*>|\[(?:/?[a-zA-Z][^\]]*)\]', ' ', value)
    value = re.sub(r'https?://\S+|\{STEAM_CLAN_IMAGE\}\S*', ' ', value)
    return re.sub(r'\s+', ' ', html.unescape(value)).strip()


def _excerpt(text):
    """Return one bounded excerpt; a match remains unreviewed regardless of wording."""
    for keyword in KEYWORD.finditer(text):
        lo, hi = max(0, keyword.start() - 120), min(len(text), keyword.end() + 120)
        quantities = list(QUANTITY.finditer(text, lo, hi))
        if not quantities:
            continue
        nearest = min(quantities, key=lambda m: min(abs(m.start() - keyword.end()),
                                                   abs(m.end() - keyword.start())))
        start, end = min(nearest.start(), keyword.start()), max(nearest.end(), keyword.end())
        # Include the complete quantity token (1,000 / 100k / a written number).
        while start > lo and not text[start - 1].isspace():
            start -= 1
        while end < hi and not text[end].isspace():
            end += 1
        left = max(lo, start - 50)
        while left < start and not (left == 0 or text[left - 1].isspace()):
            left += 1
        excerpt = text[left:min(hi, end + 70)].strip()
        # The core span is <= 240 characters; centre a character cap around it.
        if len(excerpt) > 280:
            excerpt = text[start:min(len(text), start + 280)].strip()
        words = excerpt.split()
        if len(words) > 25:
            # Re-anchor at the numeric/keyword core rather than dropping its end.
            excerpt = ' '.join(text[start:min(len(text), start + 280)].split()[:25])
        return excerpt[:280].strip()
    return None


def extract_mentions(game, source_app_id, payload, observed_at):
    """Scan full contents in memory; return small append-only candidate records.

    API item.appid is optional for compatibility, but if present must agree with
    the requested app and appnews.appid. The caller owns persistence and fetching.
    """
    source_kind = _identity(game, source_app_id)
    observed = _time(observed_at)
    _require(isinstance(payload, dict), 'invalid_payload')
    news = payload.get('appnews')
    _require(isinstance(news, dict) and type(news.get('appid')) is int
             and news['appid'] == source_app_id, 'payload_appid_mismatch')
    _require(isinstance(news.get('newsitems'), list), 'invalid_newsitems')
    result, seen = [], set()
    for item in news['newsitems']:
        _require(isinstance(item, dict), 'invalid_newsitem')
        if item.get('feedname') != 'steam_community_announcements':
            continue
        if 'appid' in item:
            _require(type(item['appid']) is int and item['appid'] == source_app_id,
                     'item_appid_mismatch')
        gid = item.get('gid')
        _require((isinstance(gid, str) or type(gid) is int) and str(gid).isascii()
                 and str(gid).isdigit(), 'invalid_gid')
        gid = str(gid)
        _official_url(item.get('url'), source_app_id, gid)
        published = item.get('date')
        _require(type(published) in (int, float) and math.isfinite(published)
                 and published >= 0 and published == int(published), 'invalid_publication')
        try:
            published_at = stamp(datetime.fromtimestamp(published, UTC))
        except (ValueError, OSError, OverflowError) as error:
            raise ValueError('news_evidence_invalid_publication') from error
        _require(parse(published_at) <= observed, 'future_publication')
        title, body = item.get('title'), item.get('contents')
        _require(isinstance(title, str) and bool(title.strip()) and isinstance(body, str),
                 'invalid_content')
        quote = _excerpt(_plain(title + ' ' + body))
        if quote is None:
            continue
        body_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
        # Separate from body-only source verification hashes: title edits also
        # create a new version, without storing the title or complete body.
        content_hash = hashlib.sha256(json.dumps({'title': title, 'body': body},
            ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        event_id = f"steam-{game['id']}-{gid}"
        row = dict(id=f'numeric-mention-{event_id}-{source_app_id}-{content_hash}', game_id=game['id'],
                   app_id=game['app_id'], source_app_id=source_app_id, source_kind=source_kind,
                   news_gid=gid, event_id=event_id, source_url=item['url'],
                   published_at=published_at, observed_at=stamp(observed), body_sha256=body_hash,
                   content_sha256=content_hash, quote=quote, review_status=STATUS,
                   discovery_method=DETECTOR, interpretation='machine_candidate_only',
                   detector_version=1)
        validate_mention(row, game)
        if row['id'] not in seen:
            seen.add(row['id'])
            result.append(row)
    return result


def validate_mention(row, game, events=None):
    """Validate provenance and bounded storage; never validate a numerical claim."""
    _require(isinstance(row, dict) and set(row) == FIELDS, 'invalid_fields')
    kind = _identity(game, row['source_app_id'])
    _require(row['game_id'] == game['id'] and type(row['app_id']) is int
             and row['app_id'] == game['app_id'] and row['source_kind'] == kind,
             'game_mapping')
    gid = row['news_gid']
    _require(isinstance(gid, str) and gid.isascii() and gid.isdigit(), 'invalid_gid')
    event_id = f"steam-{game['id']}-{gid}"
    _require(row['event_id'] == event_id, 'event_id_mismatch')
    for key in ('body_sha256', 'content_sha256'):
        _require(isinstance(row[key], str) and re.fullmatch('[0-9a-f]{64}', row[key]),
                 'invalid_hash')
    _require(row['id'] == f"numeric-mention-{event_id}-{row['source_app_id']}-{row['content_sha256']}", 'id_mismatch')
    _official_url(row['source_url'], row['source_app_id'], gid)
    _require(_time(row['published_at']) <= _time(row['observed_at']), 'future_publication')
    quote = row['quote']
    _require(isinstance(quote, str) and bool(quote) and len(quote) <= 280
             and len(quote.split()) <= 25 and _plain(quote) == quote, 'invalid_quote')
    _require(row['review_status'] == STATUS and row['discovery_method'] == DETECTOR
             and row['interpretation'] == 'machine_candidate_only'
             and type(row['detector_version']) is int and row['detector_version'] == 1,
             'not_unreviewed_machine_candidate')
    if events is not None:
        event_map = events if isinstance(events, dict) else {e['id']: e for e in events}
        event = event_map.get(event_id)
        _require(isinstance(event, dict) and event.get('game_id') == game['id']
                 and event.get('source_url') == row['source_url']
                 and event.get('published_at') == row['published_at'], 'event_mapping')
    return dict(row)

"""Source semantics in browser-only routes; never write collected public data."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765/'
GAME = 'hela'
APP_ID = 3161310
OBSERVED = '2026-10-26T06:00:00Z'
PUBLISHED = '2026-10-20T12:00:00Z'
RELEASE_SECONDS = int(datetime(2027, 2, 19, 12, tzinfo=timezone.utc).timestamp())


def read_data(name):
    return json.loads((ROOT / 'site/data' / name).read_text())


def wishlist_fixture():
    data = copy.deepcopy(read_data('wishlists.json'))
    common = dict(game_id=GAME, app_id=APP_ID, event_id=None,
                  published_at=PUBLISHED, value=10000, stock_definition='unspecified',
                  source_url='https://store.steampowered.com/news/app/3161310/view/100',
                  verified_at=OBSERVED, usable_as_current_stock=False, as_of=None,
                  platform_scope='unspecified')
    old = dict(common, id='fixture-old', kind='reported_count', operator='eq',
               quote='10,000 wishlists')
    new = dict(common, id='fixture-new', kind='milestone_lower_bound', operator='gt',
               quote='Over 10,000 wishlists',
               review_scope='공식 원문 전체 확인 · 저장 발췌문 밖 수치')
    data.update(disclosures=[old, new], active_disclosure_ids=[new['id']],
                follower_checks=[], methods=[], candidates=[],
                comparisons=[dict(game_id=GAME, latest_disclosure_id=new['id'],
                                  previous_disclosure_id=None, status='unavailable',
                                  delta=None, percent=None)])
    data['candidate_reviews'] = [dict(id='fixture-review', game_id=GAME,
        event_id='fixture-full-source', decision='verified_claim',
        disclosure_ids=[new['id']], reviewed_at=OBSERVED)]
    data['disclosure_amendments'] = [dict(id='fixture-amendment',
        previous_disclosure_id=old['id'], replacement_disclosure_id=new['id'],
        reason='전체 원문의 over를 반영한 정정', reviewed_at=OBSERVED,
        source_check={'source_event_id': 'fixture-amended-source'})]
    data['mentions'] = [dict(event_id=event, game_id=GAME, title=title,
        source_url='https://store.steampowered.com/news/app/3161310/view/101',
        published_at=PUBLISHED, quote='Wishlist source fixture') for event, title in [
            ('fixture-full-source', 'VERIFIED_SOURCE_MUST_NOT_BE_PROMOTIONAL'),
            ('fixture-amended-source', 'AMENDED_SOURCE_MUST_NOT_BE_PROMOTIONAL'),
            ('fixture-generic', 'GENERIC_SOURCE_REMAINS')]]
    data['coverage'] = dict(disclosures=1, disclosure_games=1, candidates=0,
                            candidate_games=0, mentions=3, mention_games=1,
                            current_stock_games=0)
    return data


def history_fixture(release):
    history = copy.deepcopy(read_data('games/hela.json'))
    trailer = dict(trailer_name='SOURCE_FIXTURE Trailer', trailer_base_id=901100,
                   trailer_url_format='steam/apps/${FILENAME}?t=1793354400')
    context = dict(schema_version=1, game_id=GAME, app_id=APP_ID, app_scope='base',
        observed_at=OBSERVED, status='ok',
        field_status={'basic_info': 'ok', 'release': 'ok', 'trailers': 'ok'},
        developers=['SOURCE_FIXTURE Developer'], publishers=['SOURCE_FIXTURE Publisher'],
        release=release, trailers={'highlights': [trailer], 'other_trailers': [
            copy.deepcopy(trailer), dict(trailer_name='SOURCE_FIXTURE Gameplay',
                                        trailer_base_id=901101)]})
    history['context_snapshots'] = [context]
    return history


def expand(page, key):
    details = page.locator('[data-wish-disclosure="' + key + '"]')
    ancestors = details.locator('xpath=ancestor::details')
    for i in range(ancestors.count()):
        parent = ancestors.nth(i)
        if not parent.evaluate('(el) => el.open'):
            parent.locator(':scope > summary').click()
    if not details.evaluate('(el) => el.open'):
        details.locator(':scope > summary').click()
    return details


def open_page(browser, release):
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    fixtures = {'**/data/wishlists.json*': wishlist_fixture(),
                '**/data/games/hela.json*': history_fixture(release)}
    for pattern, data in fixtures.items():
        page.route(pattern, lambda route, request, data=data: route.fulfill(
            content_type='application/json', body=json.dumps(data, ensure_ascii=False)))
    page.goto(BASE.rstrip('/') + '/#/analysis?game=hela&metric=wishlists',
              wait_until='networkidle')
    expect(page.locator('#game-background')).to_contain_text('SOURCE_FIXTURE Developer')
    return page, errors


def assert_mobile_and_errors(page, errors):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), '390px overflow'
    assert not errors, errors


def main():
    cases = [
        ('month', dict(is_coming_soon=True, coming_soon_display='date_month',
                       steam_release_date=RELEASE_SECONDS), '2027년 2월'),
        ('quarter', dict(is_coming_soon=True, coming_soon_display='date_quarter',
                         steam_release_date=RELEASE_SECONDS), '2027년 1분기'),
        ('year', dict(is_coming_soon=True, coming_soon_display='date_year',
                      steam_release_date=RELEASE_SECONDS), '2027년'),
        ('full', dict(is_coming_soon=True, coming_soon_display='date_full',
                      steam_release_date=RELEASE_SECONDS), '2027.02.19'),
        ('custom', dict(is_coming_soon=True, coming_soon_display='date_full',
                        steam_release_date=RELEASE_SECONDS,
                        custom_release_date_message='SOURCE_FIXTURE 출시 계획'),
         'SOURCE_FIXTURE 출시 계획'),
        ('zero', dict(is_coming_soon=True, coming_soon_display='date_full',
                      steam_release_date=0), '출시 예정'),
        ('tba', dict(is_coming_soon=True, coming_soon_display='text_tba'), '발표 예정'),
    ]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for name, release, expected in cases:
            page, errors = open_page(browser, release)
            field = page.locator('#game-background .game-info-fields > div').filter(
                has=page.locator('dt', has_text='출시'))
            expect(field).to_contain_text(expected)
            if name in {'month', 'quarter', 'year', 'custom'}:
                expect(field).not_to_contain_text('2027.02.19')
            expect(field).not_to_contain_text('1970')
            expect(field).to_contain_text('2026.10.26 15:00 KST 확인')
            expect(page.locator('#game-background')).to_contain_text('SOURCE_FIXTURE Publisher')
            assert_mobile_and_errors(page, errors)
            page.close()
            print('PASS source release precision: ' + name)

        page, errors = open_page(browser, cases[0][1])
        trailers = page.locator('.store-trailers')
        expect(trailers).to_contain_text('Steam 상점 영상 2개')
        expect(trailers.locator('.context-video')).to_have_count(2)
        expect(trailers).to_contain_text('2026.10.26 15:00 KST 상점 확인')
        expect(trailers).to_contain_text('게시일·조회수 미제공')
        expect(trailers).not_to_contain_text('2026.10.20')
        expect(trailers).not_to_contain_text('2026.10.30')
        assert trailers.locator('a').first.get_attribute('href').startswith(
            'https://store.steampowered.com/app/3161310')

        expect(page.locator('#wishlist-current')).to_contain_text('10,000건 초과')
        expand(page, 'disclosure-fixture-new')
        expect(page.locator('#wishlist-disclosures')).to_contain_text('수치 기록 1건')
        expect(page.locator('#wishlist-disclosures')).to_contain_text('2026.10.20 21:00 KST 발표')
        expect(page.locator('[data-wish-disclosure="disclosure-fixture-old"]')).to_have_count(0)
        corrections = expand(page, 'disclosure-corrections-hela')
        expect(corrections).to_contain_text('10,000건 발표 → 위시리스트(찜) 10,000건 초과 달성')
        expect(corrections).to_contain_text('이전 기록 보존')
        expect(corrections).to_contain_text('전체 원문의 over를 반영한 정정')
        assert len(wishlist_fixture()['disclosures']) == 2, 'retired evidence remains in source fixture'

        mentions = expand(page, 'wish-mentions-hela')
        expect(mentions).to_contain_text('일반 위시리스트(찜) 홍보 언급 1건')
        expect(mentions).to_contain_text('GENERIC_SOURCE_REMAINS')
        expect(mentions).not_to_contain_text('VERIFIED_SOURCE_MUST_NOT_BE_PROMOTIONAL')
        expect(mentions).not_to_contain_text('AMENDED_SOURCE_MUST_NOT_BE_PROMOTIONAL')
        assert_mobile_and_errors(page, errors)
        page.close()
        browser.close()
        print('PASS trailer provenance, immutable corrections, active rows, full-source mention exclusion, 390px layout and page errors')


if __name__ == '__main__':
    main()

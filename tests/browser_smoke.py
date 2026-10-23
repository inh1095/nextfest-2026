"""Fleet UI regression checks. Fixtures remain in browser memory, never public files.

Start a local static server, then run: python3 tests/browser_smoke.py [base_url]
"""
import copy
import csv as csv_module
import io
import json
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from fleet import blank_history, range_summary, observation_history
from collect import parse

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765/'
CONFIG = json.loads((ROOT / 'site/data/config.json').read_text())
CATALOG = json.loads((ROOT / 'site/data/catalog.json').read_text())
SUMMARY = json.loads((ROOT / 'site/data/summary.json').read_text())
OUTPUT = ROOT / 'test-results'
OUTPUT.mkdir(exist_ok=True)
NOW = '2026-10-20T10:30:00Z'


def sample(value, at, game='hela', status='ok'):
    return dict(game_id=game, metric='demo_ccu', observed_at=at, value=value,
                status=status, source_url='https://api.steampowered.com/example',
                error_code='network_error' if status == 'error' else None)


def fixture(samples=None, events=None, now=NOW):
    if samples is None:
        samples = [sample(0, '2026-10-20T08:00:00Z'), sample(10, '2026-10-20T08:20:00Z'),
                   sample(0, '2026-10-20T08:00:00Z', 'lethal-wedding'),
                   sample(0, '2026-10-20T08:20:00Z', 'lethal-wedding')]
    if events is None:
        events = [dict(id='fixture-before', game_id='hela', kind='announcement', title='공식 데모 업데이트',
                       summary='브라우저 내부 검증용 이벤트', occurred_at=None, published_at='2026-10-20T08:10:00Z',
                       time_precision='minute', source_url='https://store.steampowered.com/', verified_at=NOW),
                  dict(id='fixture-after', game_id='hela', kind='video', title='공식 개발 영상',
                       summary='증가 구간 이후 게시', occurred_at=None, published_at='2026-10-20T08:25:00Z',
                       time_precision='minute', source_url='https://www.youtube.com/', verified_at=NOW)]
    summary = copy.deepcopy(SUMMARY)
    summary.update(generated_at=now, window_end=now)
    history = {}
    for row in summary['games']:
        gid = row['game_id']
        hist = blank_history(parse(now))
        hist['samples'] = sorted([s for s in samples if s['game_id'] == gid], key=lambda s:s['observed_at'])
        hist['events'] = [e for e in events if e['game_id'] == gid]
        good = [s for s in hist['samples'] if s['status'] == 'ok']
        latest = hist['samples'][-1] if hist['samples'] else None
        last = good[-1] if good else None
        row.update(current=last['value'] if last else None, last_ok_at=last['observed_at'] if last else None,
                   last_attempt_at=latest['observed_at'] if latest else None,
                   status=latest['status'] if latest else 'pending', last_error_code=latest['error_code'] if latest else None)
        row['observation_history']=observation_history(hist['samples'],parse(now))
        row['ranges'] = {k:range_summary(hist['samples'], parse(CONFIG['event']['starts_at']) if k == 'all'
                        else max(parse(CONFIG['event']['starts_at']), parse(now)-timedelta(hours=int(k))),
                        parse(now), row['target_interval_minutes']*2+30) for k in ('all','6','24')}
        if gid == 'steam-4483570':
            row['status'] = 'unavailable'
        if hist['samples'] or hist['events']:
            history[gid] = hist
    summary['coverage'].update(ccu_ok=len({s['game_id'] for s in samples if s['status']=='ok'}),
                               ccu_pending=7161, comparison_ready=sum(bool(r['ranges']['all']['latest_adjacent']) for r in summary['games']))
    return {'summary':summary, 'history':history, 'events-index':dict(schema_version=2, generated_at=now, events=events)}


def load_page(browser, data=None, *, route='compare', mobile=False, now=NOW):
    if route.split('?')[0] in ('analysis','compare'):
        key,value=('metric','demo_ccu') if route.split('?')[0]=='analysis' else ('view','ccu')
        if key+'=' not in route:route+=('&' if '?' in route else '?')+key+'='+value
    page = browser.new_page(viewport={'width':390 if mobile else 1440,'height':900})
    page.emulate_media(reduced_motion='reduce')
    page.add_init_script('window.__reviewTimers=[];const nativeInterval=window.setInterval;window.setInterval=(fn,ms,...args)=>{window.__reviewTimers.push({fn,ms});return nativeInterval(fn,ms,...args)};')
    page.add_init_script('Date.now = () => Date.parse('+json.dumps(now)+');')
    errors, requests = [], []
    page.on('pageerror', lambda e:errors.append(str(e)))
    page.on('request', lambda r:requests.append(r.url))
    if data is not None:
        def respond(request):
            path = urlsplit(request.request.url).path
            name = path.rsplit('/',1)[-1].removesuffix('.json')
            if '/games/' in path:
                payload = data['history'].get(name, blank_history(parse(now)))
            else:
                payload = {'config':CONFIG,'catalog':CATALOG,**data}.get(name)
            if payload is None:
                request.continue_()
            else:
                request.fulfill(content_type='application/json',body=json.dumps(payload,ensure_ascii=False))
        page.route('**/data/**', respond)
    page.goto(BASE.rstrip('/')+'/#/'+route, wait_until='networkidle')
    page.locator('#route-view[data-page="'+route.split('?')[0]+'"]').wait_for()
    assert not errors, errors
    return page, errors, requests


def navigate(page, route):
    quick = page.locator('.mobile-nav a[data-route="'+route+'"]')
    if quick.count() and quick.is_visible():
        quick.click()
    else:
        if page.locator('#menu-toggle').is_visible():
            page.locator('#menu-toggle').click()
        page.locator('#sidebar a[data-route="'+route+'"]').click()
    if route in ('analysis','compare'):
        query='metric=demo_ccu' if route=='analysis' else 'view=ccu'
        page.evaluate('(q)=>{const p=new URLSearchParams(location.hash.split("?")[1]||"");const [k,v]=q.split("=");p.set(k,v);location.hash=location.hash.split("?")[0]+"?"+p}',query)
    page.locator('#route-view[data-page="'+route+'"]').wait_for()


def reveal(page, selector):
    """Reach secondary controls through their visible disclosure, as a user would."""
    control = page.locator(selector)
    while control.locator('xpath=ancestor::details[not(@open)]').count():
        parent = control.locator('xpath=ancestor::details[not(@open)]').first
        parent.locator('summary').first.click()
    return control


def choose(page, control, gid):
    row = next(g for g in CATALOG['games'] if g['id']==gid)
    page.locator('#'+control).fill(str(row['app_id']))
    page.locator('#'+control+'-results [data-picker-id="'+gid+'"]').click()


def width(page):
    assert page.locator('body').evaluate('(e)=>e.scrollWidth') <= page.viewport_size['width']


def readable_table(page, selector):
    """Primary mobile metrics must fit the screen, not just a scroll container."""
    table = page.locator(selector)
    assert table.evaluate('(e)=>e.scrollWidth <= e.clientWidth + 1'), selector
    assert table.evaluate('e => {const r=e.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth+1;}'), selector


def screenshot(page,name):
    page.evaluate('window.scrollTo(0,0)')
    page.screenshot(path=str(OUTPUT/name),full_page=True)


def checked(page):
    return page.locator('[data-compare-game]:checked').count()


with sync_playwright() as playwright:
    browser=playwright.chromium.launch(headless=True)
    page,errors,requests=load_page(browser)
    width(page)
    assert not any('/games/' in u or 'observations.json' in u for u in requests)
    assert '7,164' in page.locator('#comparison-table').locator('xpath=ancestor::section').inner_text()
    screenshot(page,'fleet-desktop-overview.png')
    navigate(page,'compare')
    expect(page.locator('#comparison-table tbody tr')).to_have_count(25)
    assert not any('/games/' in u for u in requests)
    first=page.locator('[data-compare-game]').first.get_attribute('data-compare-game')
    page.locator('#catalog-pagination button').last.click()
    assert page.locator('[data-compare-game]').first.get_attribute('data-compare-game')!=first
    page.locator('#catalog-search').fill('4483570')
    expect(page.locator('[data-compare-game]')).to_have_count(1)
    assert '데모 미확보' in page.locator('#comparison-table').inner_text()
    page.locator('#catalog-search').fill('')
    reveal(page, '#catalog-page-size').select_option('50')
    expect(page.locator('[data-compare-game]')).to_have_count(50)
    for _ in range(4):
        gid=page.locator('[data-compare-game]:not(:checked):enabled').first.get_attribute('data-compare-game')
        page.locator('[data-compare-game="'+gid+'"]').check()
    expect(page.locator('#selected-comparison-table tbody tr')).to_have_count(4)
    assert page.locator('[data-compare-game]:not(:checked):enabled').count()==0
    page.wait_for_load_state('networkidle')
    assert len({urlsplit(u).path for u in requests if '/games/' in u})==4
    page.locator('#clear-compare').click()
    page.locator('[data-favorite]').first.click()
    reveal(page, '#favorites-only').check()
    expect(page.locator('[data-favorite]')).to_have_count(1)
    page.reload(wait_until='networkidle')
    reveal(page, '#favorites-only').check()
    expect(page.locator('[data-favorite]')).to_have_count(1)
    screenshot(page,'fleet-desktop-compare.png')
    for route in ('analysis','events','collection'):
        navigate(page,route)
        width(page)
    page.go_back()
    page.locator('#route-view[data-page="events"]').wait_for()
    navigate(page,'analysis')
    choose(page,'game-select','lethal-wedding')
    expect(page.locator('#samples-table tbody tr')).not_to_have_count(0)
    page.locator('[data-range="6"]').click()
    navigate(page,'overview')
    navigate(page,'analysis')
    expect(page.locator('#game-select')).to_have_value('Lethal Wedding')
    assert page.locator('[data-range="6"]').get_attribute('aria-pressed')=='true'
    # CCU collection is stopped: the current six-hour window can be empty.
    page.locator('[data-range="all"]').click()
    page.wait_for_load_state('networkidle')
    with page.expect_download() as download:
        reveal(page, '#download-csv').click()
    assert 'lethal-wedding' in Path(download.value.path()).read_text(encoding='utf-8-sig')
    assert not errors,errors
    page.close()
    print('PASS 7,164 catalog, bounded DOM, paging/search, 4-game lazy comparison, favorites, routes and CSV')

    page,errors,_=load_page(browser,fixture(),route='analysis',mobile=True)
    width(page)
    readable_table(page, '#intervals-table')
    expect(page.locator('[data-interval-id]')).to_have_count(1)
    screenshot(page,'fleet-mobile-analysis.png')
    for route in ('compare','events'):
        navigate(page,route);width(page)
        readable_table(page, {'overview':'#latest-changes-table','compare':'#comparison-table','events':'#events-table','collection':'#collection-table'}[route])
        if route == 'compare':
            first_game = page.locator('#comparison-table .game-name').first
            assert first_game.bounding_box()['y'] < 640
            assert first_game.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)') >= 16
            assert page.locator('#catalog-search').evaluate('e=>parseFloat(getComputedStyle(e).fontSize)') >= 16
            reveal(page, '#catalog-status').select_option('pending')
            expect(page.locator('#catalog-status')).to_be_visible()
            page.locator('#catalog-search').fill('4483570')
            expect(page.locator('#catalog-status')).to_be_visible()
            page.locator('#catalog-search').fill('')
            page.locator('#catalog-status').select_option('all')
    if page.locator('#menu-toggle').is_visible():
        page.locator('#menu-toggle').click();page.keyboard.press('Escape')
        assert page.locator('#menu-toggle').get_attribute('aria-expanded')=='false'
    assert not errors,errors
    page.close()
    print('PASS 390px: visible metrics without sideways scrolling, readable names, persistent filters and navigation')

    page,errors,_=load_page(browser,fixture(),route='analysis')
    expect(page.locator('[data-interval-id]')).to_have_count(1)
    assert '+10' in page.locator('#intervals-table').inner_text()
    assert 'Infinity' not in page.locator('#route-view').inner_text()
    assert '공식 데모 업데이트' in page.locator('#interval-detail').inner_text()
    assert '원인 미확인' in page.locator('#interval-detail').inner_text()
    page.locator('[data-related-event="fixture-after"]').click()
    assert '구간 이후' in page.locator('#interval-detail').inner_text()
    screenshot(page,'fleet-desktop-analysis.png')
    reveal(page, '#metric-select').select_option('followers')
    assert '미확보' in page.locator('#route-view').inner_text()
    assert page.locator('#analysis-chart polyline').count()==0
    assert not errors,errors
    page.close()
    print('PASS zero denominator, related events, unverified causality and missing followers')

    cases=[('single',[sample(0,'2026-10-20T08:00:00Z')]),
           ('gap',[sample(0,'2026-10-20T08:00:00Z'),sample(10,'2026-10-20T10:00:00Z')]),
           ('error-between',[sample(0,'2026-10-20T08:00:00Z'),sample(None,'2026-10-20T08:10:00Z',status='error'),sample(10,'2026-10-20T08:20:00Z')])]
    for name,samples in cases:
        page,errors,_=load_page(browser,fixture(samples),route='analysis')
        assert page.locator('[data-interval-id]').count()==0,name
        assert page.locator('#analysis-chart polyline').count()==0,name
        expect(page.locator('#samples-table tbody tr')).to_have_count(len(samples))
        assert not errors,errors
        page.close()
    print('PASS single observation, long gap and failed samples cannot become growth')

    failing=[sample(5,'2026-10-20T08:00:00Z'),sample(None,'2026-10-20T10:00:00Z',status='error')]
    page,errors,_=load_page(browser,fixture(failing),route='analysis')
    expect(page.locator('#samples-table tbody tr')).to_have_count(2)
    reveal(page, '#samples-table')
    assert '수집 오류' in page.locator('#samples-table').inner_text()
    expect(page.locator('#analysis-history')).to_contain_text('2건 저장')
    expect(page.locator('#analysis-history')).to_contain_text('오류 1건')
    expect(page.locator('#analysis-chart circle')).to_have_count(1)
    with page.expect_download() as download:reveal(page, '#download-csv').click()
    assert 'network_error' in Path(download.value.path()).read_text(encoding='utf-8-sig')
    page.route('**/data/summary.json*',lambda r:r.fulfill(status=503,body='unavailable'))
    page.locator('#refresh-data').click()
    expect(page.locator('#refresh-status')).to_be_visible()
    expect(page.locator('#samples-table tbody tr')).to_have_count(2)
    assert page.locator('#refresh-data').is_enabled()
    assert not errors,errors
    page.close()
    print('PASS trailing failures remain in all-range CSV; refresh failure preserves data')

    page,errors,_=load_page(browser,fixture(),route='compare')
    page.locator('#catalog-direction').click()
    first=page.locator('#comparison-table tbody tr').first
    assert 'Lethal Wedding' in first.inner_text()
    assert first.locator('td').nth(3).locator('.number-main').inner_text()=='0'
    reveal(page, '#catalog-status').select_option('pending')
    assert page.locator('#comparison-table tbody tr').first.locator('td').nth(3).inner_text()=='—'
    assert not errors,errors
    page.close()
    print('PASS real zero sorts before missing; missing stays visibly distinct')

    past_spike=[sample(0,'2026-10-20T08:00:00Z'),sample(100,'2026-10-20T08:20:00Z'),
                sample(10,'2026-10-20T08:40:00Z')]
    page,errors,_=load_page(browser,fixture(past_spike),route='compare')
    page.locator('#catalog-sort').select_option('max_increase')
    spike=page.locator('[data-max-increase="hela"]')
    assert '+100' in spike.inner_text()
    spike.click()
    page.locator('#route-view[data-page="analysis"]').wait_for()
    expect(page.locator('#interval-detail .detail-value')).to_contain_text('+100')
    assert not errors,errors
    page.close()
    historical=[sample(999,'2026-10-19T18:00:00Z'),sample(0,'2026-10-20T08:00:00Z'),
                sample(10,'2026-10-20T08:20:00Z')]
    page,errors,_=load_page(browser,fixture(historical),route='compare')
    hela=page.locator('#comparison-table tbody tr').filter(has_text='Hela')
    assert hela.locator('td').nth(5).inner_text()=='999'
    page.locator('[data-range="6"]').click()
    assert hela.locator('td').nth(5).inner_text()=='10'
    assert not errors,errors
    page.close()
    print('PASS past spikes survive later declines and period filters exclude old peaks')
    page,errors,_=load_page(browser,fixture(historical),route='collection?game=hela&range=6',mobile=True)
    selected=reveal(page, '#selected-game-history')
    expect(selected).to_contain_text('마지막 관측 동접')
    expect(selected.locator('.last-observation strong')).to_have_text('10')
    expect(selected).to_contain_text('3건 저장')
    expect(selected).to_contain_text('정상 관측 3회')
    expect(selected).to_contain_text('2026.10.20 03:00 KST')
    expect(selected.locator('.last-observation-time')).to_contain_text('2026.10.20 17:20 KST')
    expect(page.locator('#collection-cadence')).to_contain_text('화면 갱신')
    expect(page.locator('#collection-cadence')).to_contain_text('위시리스트(찜) 공개 수치')
    expect(page.locator('#wishlist-status')).to_contain_text('정기 수집 없음')
    page.locator('#open-full-history').click()
    expect(page.locator('[data-range="all"]')).to_have_attribute('aria-pressed','true')
    expect(page.locator('#analysis-chart circle')).to_have_count(3)
    expect(page.locator('#analysis-history')).to_contain_text('3건 저장')
    expect(page.locator('#analysis-history')).to_contain_text('누적 이용자 수가 아닙니다')
    page.locator('[data-range="6"]').click()
    expect(page.locator('#analysis-chart circle')).to_have_count(2)
    expect(page.locator('#analysis-history')).to_contain_text('3건 저장')
    expect(page.locator('#analysis-history')).to_contain_text('2026.10.20 03:00 KST')
    assert not errors,errors
    page.close()
    print('PASS explicit CCU units, saved history survives range filters, full-history link and separate cadence')


    events=fixture()['events-index']['events']
    events[0]['published_at']='2026-10-19T14:59:00Z'
    events[1]['published_at']='2026-10-19T15:01:00Z'
    page,errors,_=load_page(browser,fixture(events=events),route='events')
    reveal(page, '#events-from').fill('2026-10-20');reveal(page, '#events-to').fill('2026-10-20');page.locator('#events-to').press('Tab')
    expect(page.locator('[data-event-id]')).to_have_count(1)
    assert page.locator('[data-event-id]').get_attribute('data-event-id')=='fixture-after'
    page.locator('#events-search').fill('없는제목')
    expect(page.locator('[data-event-id]')).to_have_count(0)
    assert not errors,errors
    page.close()
    print('PASS event search and KST midnight filtering')

    events=fixture()['events-index']['events']
    events[0]['title']='<img src=x onerror="window.bad=1">'
    page,errors,_=load_page(browser,fixture(events=events),route='events')
    assert page.locator('#route-view img').count()==0
    assert page.evaluate('window.bad||null') is None
    assert not errors,errors
    page.close()
    page,errors,_=load_page(browser,fixture(),now='2026-10-27T00:00:00Z')
    assert '종료' in page.locator('#sidebar-collection').inner_text()
    page.close()
    print('PASS event text escaping and end-date display')
    integrated=fixture(samples=[sample(0,'2026-10-20T08:00:00Z'),sample(0,'2026-10-20T08:20:00Z'),
        sample(None,'2026-10-20T08:40:00Z',status='error'),sample(10,'2026-10-20T09:00:00Z'),
        sample(20,'2026-10-20T10:30:00Z')])
    page,errors,_=load_page(browser,integrated,route='analysis?game=hela&metric=wishlists&range=all',mobile=True)
    expect(page.locator('#game-ccu-chart circle')).to_have_count(4)
    expect(page.locator('#game-ccu-chart polyline')).to_have_count(1)
    expect(page.locator('.integrated-increases')).to_have_count(0)
    expect(page.locator('#game-news-chart [data-news-day]')).to_have_count(1)
    expect(page.locator('#game-news-chart .mini-chart-legend')).to_contain_text('소식 1건')
    expect(page.locator('#game-news-chart .mini-chart-legend')).to_contain_text('영상·방송 1건')
    with page.expect_download() as download:page.locator('#download-overview-csv').click()
    csv=Path(download.value.path()).read_text(encoding='utf-8-sig')
    exported=list(csv_module.DictReader(io.StringIO(csv)))
    assert all(r['metric']=='demo_ccu' for r in exported)
    assert sum(r['value']=='0' and r['status']=='ok' for r in exported)==2
    assert any(r['status']=='error' and r['value']=='' and r['error_code']=='network_error' for r in exported)
    assert page.locator('body').evaluate('e=>e.scrollWidth')<=390
    assert not errors,errors
    page.close()
    page,errors,_=load_page(browser,fixture(samples=[],events=[]),route='analysis?game=hela&metric=wishlists')
    assert page.locator('#game-ccu-chart svg, #game-news-chart svg').count()==0
    expect(page.locator('#game-ccu-panel')).to_contain_text('선택 기간의 정상 관측 없음')
    assert not errors,errors
    page.close()
    print('PASS integrated CCU chart zero/errors/gaps and correct CSV metric; news day counts and empty state')
    page,errors,_=load_page(browser,integrated,route='analysis?game=hela&metric=wishlists&range=all',mobile=True)
    plot=page.locator('#game-ccu-chart-plot')
    plot.focus();page.keyboard.press('Home')
    expect(page.locator('#game-ccu-chart .chart-reading')).to_contain_text('2026.10.20 17:00:00 KST · 0명')
    page.keyboard.press('End')
    expect(page.locator('#game-ccu-chart .chart-reading')).to_contain_text('2026.10.20 19:30:00 KST · 20명')
    page.locator('#game-ccu-chart circle').nth(2).click(force=True)
    expect(page.locator('#game-ccu-chart .chart-reading')).to_contain_text('2026.10.20 18:00:00 KST · 10명')
    page.locator('[data-game-range="6"]').click()
    expect(page.locator('#game-ccu-chart .chart-reading')).to_contain_text('점을 누르거나')
    assert not errors,errors
    page.close()
    stopped=fixture(now='2026-10-23T00:00:00Z')
    for metric,chart in [('wishlists','game-ccu-chart'),('demo_ccu','analysis-chart')]:
        page,errors,_=load_page(browser,stopped,route='analysis?game=hela&metric='+metric+'&range=6',mobile=True,now='2026-10-23T00:00:00Z')
        expect(page.locator('.period-context')).to_contain_text('2026.10.23 03:00')
        expect(page.locator('.period-context')).to_contain_text('2026.10.23 09:00')
        expect(page.locator('.period-context')).to_contain_text('마지막 기록 2026.10.20 17:20')
        expect(page.locator('#'+chart+' circle')).to_have_count(0)
        page.locator('.period-context a').click()
        expect(page.locator('#'+chart+' circle')).to_have_count(2)
        assert 'range=all' in page.url
        assert not errors,errors
        page.close()
    events=fixture()['events-index']['events']
    for i in range(30):events.append({**events[0],'id':'extra-'+str(i),'published_at':'2026-10-20T09:00:00Z'})
    page,errors,_=load_page(browser,fixture(events=events),route='events?event=fixture-before',mobile=True)
    expect(page.locator('#event-detail')).to_be_focused()
    expect(page.locator('#event-detail h3')).to_be_in_viewport(ratio=1)
    page.evaluate('window.scrollTo(0,0)')
    page.evaluate('window.__reviewTimers.find(t=>t.ms===60000).fn()')
    assert page.evaluate('scrollY')==0, 'status redraw must not repeat explicit-event navigation'
    page.evaluate('location.hash="#/events?event=fixture-after"')
    expect(page.locator('#event-detail')).to_be_focused()
    expect(page.locator('#event-detail h3')).to_contain_text('공식 개발 영상')
    expect(page.locator('#event-detail h3')).to_be_in_viewport(ratio=1)
    assert not errors,errors
    page.close()
    print('PASS exact actual-point touch/keyboard reading, range reset, stopped-period dates/full history, one-shot event focus')
    browser.close()

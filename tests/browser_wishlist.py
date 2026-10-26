"""Wishlist UI fixtures stay in browser memory; no collection or public-data writes."""
import copy
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765/'
FIXTURE = {
    'schema_version': 1, 'generated_at': '2026-10-21T01:00:00Z',
    'disclosures': [dict(id='fixture-public', game_id='hela', app_id=3161310, event_id=None,
        published_at='2026-10-20T12:00:00Z', value=100000, kind='milestone_lower_bound',
        operator='gt', stock_definition='unspecified', quote='Over 100,000 wishlists <img src=x onerror=window.bad=1>',
        source_url='https://example.test/announcement', verified_at='2026-10-21T01:00:00Z',
        usable_as_current_stock=False, as_of='2026-10-20')],
    'follower_checks': [dict(id='fixture-conflict', game_id='hela', app_id=3161310,
        status='conflict', value=None, observed_at='2026-10-21T01:00:00Z',
        source_url='https://example.test/followers', candidates=[dict(path='main', value=500),dict(path='direct',value=700)],
        mapping='base_app', estimate_eligible=False)],
    'methods': [dict(id='reference-2023', label='Historical reference', lower_multiplier=7,
        upper_multiplier=20, median_multiplier=12, source_url='https://example.test/method',
        source_date='2023-01-01', sample_description='Historical sample',
        uncertainty_kind='historical_reference_not_confidence_interval',
        validation_status='not_validated_for_this_event')],
    'mentions': [dict(event_id='fixture-unreviewed', game_id='hela', title='Wishlist news',
        published_at='2026-10-20T12:00:00Z', source_url='javascript:window.bad=2', quote='20,000 mentioned, not reviewed'),
        dict(event_id='fixture-numeric',game_id='hela',title='100 wishlist target',published_at='2026-10-21T01:00:00Z',source_url='https://example.test/candidate',quote='A target of 100 wishlists')],
    'candidates':[dict(id='numeric-candidate',event_id='fixture-numeric',game_id='hela',title='100 wishlist target',published_at='2026-10-21T01:00:00Z',quote='A target of 100 wishlists',source_url='https://example.test/candidate',review_status='unreviewed_numeric_mention')],
    'comparisons':[dict(game_id='hela',previous_disclosure_id=None,latest_disclosure_id='fixture-public',delta=None,percent=None,status='unavailable',reason='insufficient')],
    'coverage':dict(current_stock_games=0,candidates=1,candidate_games=1,disclosure_games=1,disclosures=1,mention_games=1,mentions=1,followers_ok=0,followers_conflict=1),
}


def open_page(browser, data=FIXTURE, width=390, route='analysis?game=hela&metric=wishlists', catalog=None):
    page=browser.new_page(viewport={'width':width,'height':844})
    errors=[];requests=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:requests.append(r.url))
    def response(r):
        if data is None:r.fulfill(status=404,body='not found')
        else:r.fulfill(content_type='application/json',body=json.dumps(data,ensure_ascii=False))
    page.route('**/data/wishlists.json*',response)
    if catalog is not None:page.route('**/data/catalog.json*',lambda r:r.fulfill(content_type='application/json',body=json.dumps(catalog,ensure_ascii=False)))
    page.goto(BASE.rstrip('/')+'/#/'+route,wait_until='networkidle')
    return page,errors,requests


def expand(page,key):
    d=page.locator('[data-wish-disclosure="'+key+'"]')
    ancestors=d.locator('xpath=ancestor::details')
    for i in range(ancestors.count()):
        parent=ancestors.nth(i)
        if not parent.evaluate('(el)=>el.open'):parent.locator(':scope > summary').click()
    if not d.evaluate('(el)=>el.open'):d.locator(':scope > summary').click()
    return d


with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page,errors,requests=open_page(browser,route='overview')
    expect(page.locator('#wishlist-overview-kpis')).to_contain_text('위시리스트(찜) 수치 기록')
    expect(page.locator('#wishlist-overview-kpis')).to_contain_text('1건')
    expect(page.locator('#overview-ccu-signals')).to_be_visible()
    expect(page.locator('#overview-news')).to_be_visible()
    expect(page.locator('#wishlist-latest-reviews')).to_contain_text('100,000건 초과')
    expect(page.locator('#wishlist-candidates')).to_contain_text('공개 수치로 확정하지 않은')
    assert page.locator('#latest-changes-table').count()==0
    before_url=page.url
    page.locator('[data-overview-section="overview-news"]').click()
    expect(page.locator('#overview-news')).to_be_in_viewport()
    assert page.url==before_url
    assert not any('/games/' in u for u in requests)
    page.locator('.mobile-nav [data-route="analysis"]').click()
    expect(page.locator('#metric-select')).to_have_value('wishlists')
    expect(page.locator('#wishlist-change')).to_contain_text('증가량 미확인')
    expect(page.locator('#wishlist-candidates')).to_contain_text('100 wishlist target')
    assert page.locator('#analysis-chart').count()==0
    expand(page,'wish-mentions-hela')
    assert '100 wishlist target' not in page.locator('[data-wish-disclosure="wish-mentions-hela"]').inner_text()
    assert not errors,errors
    page.close()
    print('PASS wishlist-first overview/default navigation, candidates separate from announcements, visible archived CCU signals and official news')
    page,errors,_=open_page(browser)
    expect(page.locator('#game-profile-metrics')).to_have_count(0)
    expect(page.locator('#game-background')).to_contain_text('본편 3161310')
    expect(page.locator('#game-background')).to_contain_text('Windup')
    expect(page.locator('#game-background')).to_contain_text('Knights Peak')
    expect(page.locator('#game-background')).to_contain_text('2026.12.01')
    expect(page.locator('#game-background')).to_contain_text('2026.10.20 자료 저장')
    expand(page,'profile-source-hela-genres')
    expect(page.locator('#game-background')).to_contain_text('개별 확인시각 미기재')
    expect(page.locator('.game-video-list').first).to_contain_text('Hela: of Mice & Magic by Windup Games')
    expect(page.locator('#game-reviews')).to_contain_text('저장된 검토 기록')
    expand(page,'saved-review-hela-0')
    expect(page.locator('#game-reviews')).to_contain_text('검토 대상 기간')
    expect(page.locator('#game-reviews')).to_contain_text('2026.10.20 15:59')
    expect(page.locator('#game-reviews')).to_contain_text('근거 부족')
    expect(page.locator('#game-reviews')).to_contain_text('159명')
    assert page.locator('#game-reviews .review-sources a').count()>0
    expect(page.locator('.integrated-increases li').first).to_contain_text('%')
    expect(page.locator('.integrated-increases li').first).to_contain_text('간격')
    summaries=page.locator('.context-news details');assert summaries.count()>0
    summaries.first.locator('summary').click()
    expect(summaries.first.locator('.context-summary')).to_be_visible()
    expect(page.locator('.game-video-list').first).to_contain_text('공식 영상')
    expect(page.locator('.game-video-list:not(.store-trailers) .context-video')).to_have_count(2)
    expect(page.locator('.store-trailers')).to_contain_text('게시일·조회수 미제공')
    assert page.locator('.store-trailers .context-video').count() > 0
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');assert not errors,errors
    page.close()
    print('PASS integrated game context: increase percentages/gaps, news summaries, videos and dated historical review sources')


    page,errors,requests=open_page(browser)
    expect(page.locator('#wishlist-disclosures')).to_contain_text('100,000건 초과')
    expect(page.locator('#wishlist-disclosures')).to_contain_text('실제 잔액 추이와 다름')
    expect(page.locator('#wishlist-disclosures')).to_contain_text('2026.10.20 · 시각 미확인')
    assert all('/games/hela.json' in u for u in requests if '/games/' in u), 'only selected game history loads for contextual sources'
    expand(page,'disclosure-fixture-public')
    assert page.locator('#wishlist-disclosures img').count()==0
    assert page.evaluate('window.bad||null') is None
    expand(page,'followers-panel')
    expect(page.locator('#wishlist-followers')).to_contain_text('출처 불일치')
    expand(page,'wish-calculator')
    expect(page.locator('#wish-followers')).to_have_value('')
    storage=page.evaluate('JSON.stringify({...localStorage})')
    requests_before=list(requests)
    url_before=page.url
    for invalid in ['', '-1','NaN','Infinity','1e3']:
        page.locator('#wish-followers').fill(invalid)
        page.locator('#wish-scenario-form button').click()
        expect(page.locator('#wish-scenario-output')).to_contain_text('정수')
    page.locator('#wish-followers').fill('1000')
    page.locator('#wish-scenario-form button').click()
    expect(page.locator('#wish-scenario-output')).to_contain_text('7,000–20,000')
    expect(page.locator('#wish-scenario-output')).to_contain_text('이 게임의 추정값 아님')
    page.locator('#wish-followers').fill('0');page.locator('#wish-scenario-form button').click()
    expect(page.locator('#wish-scenario-output')).to_contain_text('0–0')
    page.locator('#wish-estimate').fill('100');page.locator('#wish-actual').fill('0')
    page.locator('#wish-estimateDate').fill('2026-10-20');page.locator('#wish-actualDate').fill('2026-10-21')
    page.locator('#wish-error-form button').click()
    expect(page.locator('#wish-error-output')).to_contain_text('같은 기준일')
    page.locator('#wish-actualDate').fill('2026-10-20');page.locator('#wish-error-form button').click()
    expect(page.locator('#wish-error-output')).to_contain_text('절대 오차 100개')
    expect(page.locator('#wish-error-output')).to_contain_text('— (실제 잔액 0)')
    assert page.evaluate('JSON.stringify({...localStorage})')==storage
    page.wait_for_timeout(250)  # Also catch deferred requests triggered by input or submit.
    assert requests==requests_before, 'calculator input/submit must not create network requests'
    assert page.url==url_before, 'private calculator inputs must not change the URL'
    assert '1000' not in page.url and 'estimate' not in page.url
    assert page.evaluate('document.documentElement.scrollWidth')==390
    assert not errors,errors
    page.screenshot(path='/tmp/wishlist-analysis-390.png',full_page=True)
    page.reload(wait_until='networkidle');expand(page,'wish-calculator')
    expect(page.locator('#wish-followers')).to_have_value('')
    page.close()
    print('PASS disclosures, date precision, conflict, input validation, zero, privacy and mobile width')

    old_ok={**copy.deepcopy(FIXTURE['follower_checks'][0]),'id':'old-ok',
            'status':'ok','value':500,'observed_at':'2026-10-21T01:00:00Z',
            'verified_at':'2026-10-24T01:00:00Z'}
    verified_conflict={**copy.deepcopy(FIXTURE['follower_checks'][0]),'id':'verified-conflict',
                       'observed_at':None,'verified_at':'2026-10-22T01:00:00Z'}
    window_ok={**old_ok,'id':'a-window-ok','observed_at':None,'verified_at':None,
               'observation_window_utc':['2026-10-23T00:00:00Z','2026-10-23T01:00:00Z']}
    tie_conflict={**verified_conflict,'id':'z-tie-conflict','verified_at':'2026-10-23T01:00:00Z'}
    for checks,expected_badge,expected_first in [
        ([old_ok,verified_conflict],'출처 불일치','경로별 값이 달라'),
        ([verified_conflict,old_ok,window_ok],'확인 기록','500명'),
        ([tie_conflict,window_ok],'출처 불일치','경로별 값이 달라'),
        ([window_ok,tie_conflict],'출처 불일치','경로별 값이 달라'),
    ]:
        data=copy.deepcopy(FIXTURE);data['follower_checks']=checks
        page,errors,_=open_page(browser,data=data)
        expand(page,'followers-panel')
        expect(page.locator('#wishlist-followers .card-header .badge')).to_have_text(expected_badge)
        expect(page.locator('.wish-follower-record').first).to_contain_text(expected_first)
        assert not errors,errors
        page.close()
    print('PASS latest follower badge uses observed/verified/window time and deterministic ID tie-break')

    page,errors,_=open_page(browser,route='compare')
    expect(page.locator('#wishlist-catalog')).to_contain_text('Hela')
    assert page.locator('#catalog-sort').count()==0
    expect(page.locator('.ledger-entry')).to_have_count(25)
    expect(page.locator('#catalog-pagination-top')).to_be_visible()
    first_game=page.locator('.ledger-entry').first.get_attribute('data-ledger-game')
    page.locator('#catalog-pagination-top button').last.click()
    assert page.locator('.ledger-entry').first.get_attribute('data-ledger-game')!=first_game
    assert page.locator('#catalog-pagination').count()==1
    assert page.locator('#catalog-pagination-top').count()==1
    page.locator('#catalog-pagination-top button').first.click()
    expand(page,'ledger-filters')
    page.locator('#wish-evidence-filter').select_option('reviewed')
    expect(page.locator('.ledger-entry')).to_have_count(1)
    expand(page,'ledger-filters')
    page.locator('#wish-evidence-filter').select_option('all')
    page.locator('#catalog-search').fill('nothing matches')
    expect(page.locator('#wishlist-catalog')).to_contain_text('조건에 맞는')
    page.locator('#catalog-search').fill('Hela')
    page.locator('#wishlist-catalog .game-name[href*="game=hela&"]').click()
    expect(page.locator('#metric-select')).to_have_value('wishlists')
    page.locator('#metric-select').select_option('demo_ccu')
    expect(page.locator('#analysis-chart')).to_be_visible()
    assert not errors,errors
    page.close()
    print('PASS separate evidence catalog, search, deep link and CCU transition')
    timeline=copy.deepcopy(FIXTURE)
    original=timeline['disclosures'][0]
    timeline['disclosures']=[original,{**original,'id':'fixture-earlier','published_at':'2026-09-01',
        'value':50000,'operator':'gte','stock_definition':'lifetime_adds','platform_scope':'steam'},
        {**original,'id':'fixture-period','published_at':'2026-10-21T01:00:00Z',
         'value':500,'operator':'approx','kind':'period_additions','stock_definition':'period_adds'}]
    timeline['comparisons']=[dict(game_id='hela',latest_disclosure_id='fixture-period',previous_disclosure_id='fixture-public',status='unavailable',delta=None,percent=None)]
    page,errors,_=open_page(browser,data=timeline)
    expect(page.locator('.wish-timeline > li')).to_have_count(3)
    items=page.locator('.wish-timeline > li')
    expect(items.nth(0)).to_contain_text('50,000건 이상')
    expect(items.nth(1)).to_contain_text('100,000건 초과')
    expect(items.nth(2)).to_contain_text('약 500건')
    expect(items.nth(2)).to_contain_text('기간 중 추가량')
    expect(page.locator('#wishlist-current')).to_contain_text('약 500건')
    expect(page.locator('#wishlist-change')).to_contain_text('증가량 미확인')
    expect(page.locator('#wishlist-disclosures')).to_contain_text('실제 잔액 추이와 다름')
    assert page.locator('#wishlist-disclosures svg').count()==0
    assert not errors,errors
    page.close()
    print('PASS disclosure timeline preserves date/operator/definition without inventing a wishlist trend')


    representatives=copy.deepcopy(FIXTURE)
    base=representatives['disclosures'][0]
    representatives['disclosures']=[
        {**base,'id':'old-stock','value':50000,'published_at':'2026-09-01','operator':'gte'},
        {**base,'id':'latest-total','value':100000,'published_at':'2026-10-20T12:00:00Z','operator':'gte'},
        {**base,'id':'latest-period','value':5000,'published_at':'2026-10-20T12:00:00Z',
            'kind':'period_additions','stock_definition':'period_adds','operator':'eq'},
    ]
    representatives['comparisons']=[dict(game_id='hela',latest_disclosure_id='latest-total',
        previous_disclosure_id='old-stock',delta=None,percent=None,status='unavailable',publication_order_ambiguous=True)]
    page,errors,_=open_page(browser,data=representatives)
    expect(page.locator('#wishlist-current .wish-record-heading strong')).to_have_text('위시리스트(찜) 100,000건 이상 달성')
    expect(page.locator('#wishlist-current .wish-previous strong')).to_have_text('위시리스트(찜) 50,000건 이상 달성')
    expect(page.locator('#wishlist-current')).to_contain_text('선후 미확인')
    expect(page.locator('#wishlist-change')).to_contain_text('증가량 미확인')
    expect(page.locator('.wish-timeline > li')).to_have_count(3)
    expect(page.locator('.wish-timeline')).to_contain_text('위시리스트(찜) 5,000건 추가')
    expect(page.locator('#game-ccu-chart svg')).to_be_visible()
    expect(page.locator('#game-publication-chart [data-publication-point]')).to_have_count(2)
    expect(page.locator('#game-publication-chart .publication-selection > li')).to_have_count(2)
    expect(page.locator('#game-publication-chart')).to_contain_text('수치 기록 2건')
    expect(page.locator('#wishlist-current')).to_contain_text('수치 기준 2026.10.20')
    expect(page.locator('.publication-selection')).to_contain_text('수치 기준 2026.10.20')
    assert page.locator('#game-publication-chart polyline, #game-publication-chart path').count()==0
    page.locator('#publication-day').select_option('2026-09-01')
    expect(page.locator('.publication-selection > li')).to_have_count(1)
    expect(page.locator('.publication-selection')).to_contain_text('2026.09.01 · 시각 미확인')
    page.locator('[data-publication-point="2026-10-20"]').focus()
    page.keyboard.press('Enter')
    expect(page.locator('.publication-selection > li')).to_have_count(2)
    expect(page.locator('#publication-day')).to_have_value('2026-10-20')
    assert not errors,errors
    page.close()
    page,errors,_=open_page(browser,data=representatives,route='compare?view=wishlists&evidence=reviewed')
    expect(page.locator('#wishlist-catalog .wish-list-value strong')).to_have_text('위시리스트(찜) 100,000건 이상 달성')
    expect(page.locator('#wish-evidence-filter')).to_have_value('reviewed')
    link_href=page.locator('#wishlist-catalog a[href*="/analysis"]').first.get_attribute('href')
    assert 'metric=wishlists' in link_href and 'range=all' in link_href
    expand(page,'ledger-filters')
    page.locator('#wish-evidence-filter').select_option('candidate')
    assert 'evidence=candidate' in page.url
    page.reload(wait_until='networkidle')
    expect(page.locator('#wish-evidence-filter')).to_have_value('candidate')
    assert not errors,errors
    page.close()
    print('PASS backend representative IDs prevent period additions becoming stock; evidence filters survive reload')

    hope=copy.deepcopy(FIXTURE)
    hope['disclosures']=[{**hope['disclosures'][0],'id':'hope-claim','value':500,'kind':'reported_count',
        'period_text':'1일','quote':'We just crossed 500 wishlists in a day','as_of':None,
        'source_url':'https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/example'}]
    hope['comparisons']=[dict(game_id='hela',latest_disclosure_id='hope-claim',previous_disclosure_id=None,status='unavailable',delta=None,percent=None)]
    for width in (360,390,1440):
        for route,selector in [('overview','#wishlist-latest-reviews'),('compare?evidence=reviewed','#wishlist-catalog'),('analysis?game=hela','#wishlist-current')]:
            page,errors,_=open_page(browser,data=hope,width=width,route=route)
            expect(page.locator(selector)).to_contain_text('하루 만에 위시리스트(찜) 500건 초과')
            expect(page.locator(selector)).to_contain_text('총량/하루 추가 구분 미기재')
            expect(page.locator(selector)).to_contain_text('Steam 공식 공지')
            expect(page.locator(selector)).to_contain_text('집계 범위 미기재')
            assert page.locator('body').evaluate('e=>e.scrollWidth')<=width
            assert not errors,errors
            page.close()
    page,errors,_=open_page(browser,route='compare')
    for _ in range(4):
        gid=page.locator('[data-compare-game]:not(:checked):enabled').first.get_attribute('data-compare-game')
        page.locator('[data-compare-game="'+gid+'"]').check()
    assert page.locator('[data-compare-game]:not(:checked):enabled').count()==0
    page.locator('[data-compare-view="ccu"]').click()
    expect(page.locator('#selected-comparison-table tbody tr')).to_have_count(4)
    expect(page.locator('#comparison-chart svg')).to_be_visible()
    assert not errors,errors
    page.close()
    print('PASS semantic claims across three routes/widths and visible four-game statistics comparison')

    for data in [None,{**copy.deepcopy(FIXTURE),'methods':[]}]:
        page,errors,_=open_page(browser,data=data)
        expand(page,'wish-calculator')
        assert page.locator('#wish-followers').count()==0
        if data is None:expect(page.locator('#wishlist-disclosures')).to_contain_text('불러오지 못했습니다')
        page.locator('#metric-select').select_option('demo_ccu')
        expect(page.locator('#analysis-chart')).to_be_visible()
        assert not errors,errors
        page.close()
    print('PASS missing file/method never fabricates estimates or blocks CCU')
    page,errors,requests=open_page(browser,route='compare?view=wishlists&range=6')
    expect(page.locator('.ledger-entry')).to_have_count(25)
    assert not any('/games/' in u for u in requests)
    page.locator('#catalog-search').fill('3161310')
    button=page.locator('[data-expand-game="hela"]')
    button.focus();page.keyboard.press('Enter')
    hela_samples=json.loads((Path(__file__).resolve().parents[1]/'site/data/games/hela.json').read_text())['samples']
    hela_ccu_count=sum(s['metric']=='demo_ccu' and s['status']=='ok' and isinstance(s.get('value'),(int,float)) and s['value']>=0 for s in hela_samples)
    expect(page.locator('#catalog-preview-chart circle')).to_have_count(hela_ccu_count)
    expect(page.locator('.ledger-preview')).to_have_count(1)
    expect(page.locator('#expand-hela')).to_have_attribute('aria-expanded','true')
    assert 'range=6' in page.url
    assert {u.split('/games/')[1].split('.json')[0] for u in requests if '/games/' in u}=={'hela'}
    expect(page.locator('.preview-claims')).to_contain_text('누적 추가/잔액 구분 미기재')
    expect(page.locator('.preview-claims')).to_contain_text('집계 범위 미기재')
    expect(page.locator('.preview-claims')).to_contain_text('수치 기준')
    page.locator('[data-favorite="hela"]').click()
    expand(page,'ledger-filters')
    page.locator('#favorites-only').check()
    expect(page.locator('[data-wish-disclosure="ledger-filters"]')).to_have_attribute('open','')
    expect(page.locator('.ledger-entry')).to_have_count(1)
    page.locator('#catalog-search').fill('not-found-in-fixture')
    expect(page.locator('.ledger-preview')).to_have_count(0)
    page.locator('#catalog-search').fill('')
    expect(page.locator('[data-expand-game="hela"]')).to_have_attribute('aria-expanded','false')
    page.locator('#favorites-only').uncheck()
    page.locator('#ledger-sort').select_option('name')
    assert 'evidence_sort=name' in page.url
    page.reload(wait_until='networkidle')
    expect(page.locator('#ledger-sort')).to_have_value('name')
    assert page.locator('body').evaluate('e=>e.scrollWidth')<=390
    assert not errors,errors
    page.close()
    print('PASS multi-metric ledger: bounded rows, keyboard expansion, one lazy history, all-range preview, semantics, filters and sort')
    catalog=json.loads((Path(__file__).resolve().parents[1]/'site/data/catalog.json').read_text())
    catalog['games']=[g for g in catalog['games'] if g['id'] in ('hela','lethal-wedding','steam-4483570')]
    ordering=copy.deepcopy(FIXTURE);base=ordering['disclosures'][0]
    ordering['disclosures']=[{**base,'id':'hela-representative','published_at':'2026-10-01'},
        {**base,'id':'hela-later-period','published_at':'2026-10-21','kind':'period_additions','stock_definition':'period_adds'},
        {**base,'id':'lethal-representative','game_id':'lethal-wedding','app_id':4624120,'published_at':'2026-10-10'}]
    ordering['comparisons']=[dict(game_id='hela',latest_disclosure_id='hela-representative',previous_disclosure_id=None,status='unavailable'),
        dict(game_id='lethal-wedding',latest_disclosure_id='lethal-representative',previous_disclosure_id=None,status='unavailable')]
    def row_ids(page):return page.locator('.ledger-entry').evaluate_all('(els)=>els.map(e=>e.dataset.ledgerGame)')
    page,errors,_=open_page(browser,data=ordering,catalog=catalog,width=1440,route='compare')
    assert row_ids(page)==['lethal-wedding','hela','steam-4483570']
    page.locator('#ledger-header-reviewed').focus();page.keyboard.press('Enter')
    assert row_ids(page)==['hela','lethal-wedding','steam-4483570']
    assert 'evidence_dir=asc' in page.url
    expect(page.locator('#ledger-direction')).to_contain_text('오래된순')
    page.locator('#expand-hela').click();page.locator('#catalog-preview-chart svg').wait_for()
    page.locator('#ledger-header-reviewed').focus();page.keyboard.press('Space')
    assert row_ids(page)==['lethal-wedding','hela','steam-4483570']
    expect(page.locator('.ledger-preview')).to_have_attribute('id','preview-hela')
    page.locator('#ledger-sort').select_option('news')
    page.locator('#ledger-header-reviewed').click()
    expect(page.locator('#ledger-direction')).to_contain_text('최신순')
    assert row_ids(page)==['lethal-wedding','hela','steam-4483570']
    expand(page,'ledger-filters');page.locator('#wish-evidence-filter').select_option('missing')
    page.locator('#ledger-header-reviewed').click()
    expect(page.locator('#wish-evidence-filter')).to_have_value('missing')
    assert row_ids(page)==['steam-4483570']
    page.reload(wait_until='networkidle')
    expect(page.locator('#ledger-direction')).to_contain_text('오래된순')
    assert 'evidence_dir=asc' in page.url and 'evidence=missing' in page.url
    assert not errors,errors
    page.close()
    for width in (360,390):
        page,errors,_=open_page(browser,data=ordering,catalog=catalog,width=width,route='compare?evidence_dir=asc')
        assert row_ids(page)==['hela','lethal-wedding','steam-4483570']
        page.locator('#ledger-direction').click()
        assert row_ids(page)==['lethal-wedding','hela','steam-4483570']
        expect(page.locator('#ledger-direction')).to_contain_text('최신순')
        assert page.locator('#ledger-direction').bounding_box()['height']>=44
        assert page.locator('body').evaluate('e=>e.scrollWidth')<=width
        assert not errors,errors
        page.close()
    print('PASS publication-date header sort: representative date, both directions, missing last, keyboard, URL/filter/preview and mobile')
    for route in ('overview','compare','analysis?game=hela&metric=wishlists','collection?game=hela'):
        page,errors,_=open_page(browser,data=None,route=route)
        expect(page.locator('#wish-load-status')).to_contain_text('기록이 없는 상태와 다릅니다')
        expect(page.locator('[data-wish-retry]')).to_be_visible()
        expect(page.locator('#header-freshness')).to_contain_text('자료 갱신')
        expect(page.locator('#header-freshness')).not_to_contain_text('확인 중')
        if route=='compare':
            expect(page.locator('.ledger-wish').first).to_contain_text('조회 실패')
            assert '위시리스트(찜) 발표 미확보' not in page.locator('.ledger-wish').first.inner_text()
        if route.startswith('analysis'):
            expect(page.locator('#analysis-followers-status')).to_have_count(0)
            expect(page.locator('#game-publications-panel')).to_contain_text('조회 실패')
            expand(page,'game-candidates')
            expect(page.locator('#wishlist-candidates')).to_contain_text('조회 실패')
            expand(page,'wish-mentions-hela')
            expect(page.locator('[data-wish-disclosure="wish-mentions-hela"]')).not_to_contain_text('언급이 없습니다')
        page.unroute('**/data/wishlists.json*')
        page.route('**/data/wishlists.json*',lambda r:r.fulfill(content_type='application/json',body=json.dumps(FIXTURE)))
        page.locator('[data-wish-retry]').click()
        expect(page.locator('#wish-load-status')).to_have_count(0)
        assert not errors,errors
        page.close()
    page,errors,_=open_page(browser,route='analysis?game=hela&metric=wishlists')
    single=page.locator('[data-wish-disclosure="single-claim-history-hela"]')
    assert not single.evaluate('(e)=>e.open')
    assert '100,000' not in page.locator('.publication-selection').inner_text()
    expand(page,'disclosure-fixture-public')
    expect(page.locator('#wishlist-disclosures blockquote')).to_contain_text('100,000 wishlists')
    page.unroute('**/data/wishlists.json*')
    page.route('**/data/wishlists.json*',lambda r:r.fulfill(status=503,body='unavailable'))
    page.locator('#refresh-data').click()
    expect(page.locator('#wish-load-status')).to_contain_text('이전 기록 표시')
    expect(page.locator('#wishlist-current')).to_contain_text('위시리스트(찜) 100,000건 초과')
    assert not errors,errors
    page.close()
    empty={**copy.deepcopy(FIXTURE),'disclosures':[],'comparisons':[],'follower_checks':[],'mentions':[],'candidates':[]}
    page,errors,_=open_page(browser,data=empty,route='analysis?game=hela&metric=wishlists')
    expect(page.locator('#wish-load-status')).to_have_count(0)
    expect(page.locator('#wishlist-current')).to_contain_text('검토된 공개 위시리스트(찜) 수치 없음')
    expect(page.locator('#game-publications-panel')).to_have_count(0)
    expect(page.locator('#wishlist-disclosures')).to_have_count(0)
    assert not errors,errors
    page.close()
    page=browser.new_page(viewport={'width':390,'height':844})
    pending=[]
    page.route('**/data/wishlists.json*',lambda r:pending.append(r))
    page.goto(BASE.rstrip('/')+'/#/compare',wait_until='domcontentloaded')
    expect(page.locator('#wish-load-status')).to_contain_text('확인하고 있습니다')
    expect(page.locator('.ledger-wish').first).to_contain_text('확인 중')
    assert '위시리스트(찜) 발표 미확보' not in page.locator('.ledger-wish').first.inner_text()
    assert pending
    pending[0].fulfill(content_type='application/json',body=json.dumps(FIXTURE))
    expect(page.locator('#wish-load-status')).to_have_count(0)
    page.close()
    print('PASS first loading/failure/empty distinction across four routes, retry, retained records and single-claim disclosure')
    browser.close()

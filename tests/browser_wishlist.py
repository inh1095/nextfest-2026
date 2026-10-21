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


def open_page(browser, data=FIXTURE, width=390, route='analysis?game=hela&metric=wishlists'):
    page=browser.new_page(viewport={'width':width,'height':844})
    errors=[];requests=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:requests.append(r.url))
    def response(r):
        if data is None:r.fulfill(status=404,body='not found')
        else:r.fulfill(content_type='application/json',body=json.dumps(data,ensure_ascii=False))
    page.route('**/data/wishlists.json*',response)
    page.goto(BASE.rstrip('/')+'/#/'+route,wait_until='networkidle')
    return page,errors,requests


def expand(page,key):
    d=page.locator('[data-wish-disclosure="'+key+'"]')
    if not d.evaluate('(el)=>el.open'):d.locator(':scope > summary').click()
    return d


with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page,errors,requests=open_page(browser,route='overview')
    expect(page.locator('#wishlist-overview-kpis')).to_contain_text('현재 잔액 확보')
    expect(page.locator('#wishlist-overview-kpis .kpi-card').last.locator('.kpi-value')).to_contain_text('0')
    expect(page.locator('#wishlist-latest-reviews')).to_contain_text('100,000개 초과')
    expect(page.locator('#wishlist-candidates')).to_contain_text('미검토')
    assert page.locator('#latest-changes-table').count()==0
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
    print('PASS wishlist-first overview/default navigation, candidates separate from announcements, no CCU ranking')

    page,errors,requests=open_page(browser)
    expect(page.locator('#wishlist-disclosures')).to_contain_text('100,000개 초과')
    expect(page.locator('#wishlist-disclosures')).to_contain_text('현재 잔액 미확보')
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
    expect(page.locator('.wish-game-list>li')).to_have_count(25)
    page.locator('#wish-evidence-filter').select_option('reviewed')
    expect(page.locator('.wish-game-list>li')).to_have_count(1)
    page.locator('#wish-evidence-filter').select_option('all')
    page.locator('#catalog-search').fill('nothing matches')
    expect(page.locator('#wishlist-catalog')).to_contain_text('조건에 맞는')
    page.locator('#catalog-search').fill('Hela')
    page.locator('#wishlist-catalog a.button[href*="game=hela&"]').click()
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
    expect(items.nth(0)).to_contain_text('50,000개 이상')
    expect(items.nth(1)).to_contain_text('100,000개 초과')
    expect(items.nth(2)).to_contain_text('약 500개')
    expect(items.nth(2)).to_contain_text('기간 추가')
    expect(page.locator('#wishlist-current')).to_contain_text('약 500개')
    expect(page.locator('#wishlist-change')).to_contain_text('증가량 미확인')
    expect(page.locator('#wishlist-disclosures')).to_contain_text('실제 찜 잔액 추이 미확보')
    expect(page.locator('#wishlist-disclosures')).to_contain_text('정기 수집 없음')
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
    expect(page.locator('#wishlist-current .wish-record-heading strong')).to_have_text('100,000개 이상')
    expect(page.locator('#wishlist-current .wish-previous strong')).to_have_text('50,000개 이상')
    expect(page.locator('#wishlist-current')).to_contain_text('선후 미확인')
    expect(page.locator('#wishlist-change')).to_contain_text('증가량 미확인')
    expect(page.locator('.wish-timeline > li')).to_have_count(3)
    assert not errors,errors
    page.close()
    page,errors,_=open_page(browser,data=representatives,route='compare?view=wishlists&evidence=reviewed')
    expect(page.locator('#wishlist-catalog .wish-list-value strong')).to_have_text('100,000개 이상')
    expect(page.locator('#wish-evidence-filter')).to_have_value('reviewed')
    page.locator('#wish-evidence-filter').select_option('candidate')
    assert 'evidence=candidate' in page.url
    page.reload(wait_until='networkidle')
    expect(page.locator('#wish-evidence-filter')).to_have_value('candidate')
    assert not errors,errors
    page.close()
    print('PASS backend representative IDs prevent period additions becoming stock; evidence filters survive reload')

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
    browser.close()

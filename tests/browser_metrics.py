"""Multi-metric UI checks with in-memory observations; never writes public evidence."""
import copy
import csv
import io
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
BASE=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8765/'
NOW='2026-10-26T12:00:00Z'
config=json.loads((ROOT/'site/data/config.json').read_text());config['collection']['ccu_enabled']=True
catalog=json.loads((ROOT/'site/data/catalog.json').read_text());catalog['games']=[g for g in catalog['games'] if g['id'] in ('hela','lethal-wedding')]
summary=json.loads((ROOT/'site/data/summary.json').read_text());summary.update(generated_at=NOW,window_end=NOW)
summary['collection']['ccu_collection']={'enabled':True};summary['games']=[r for r in summary['games'] if r['game_id'] in ('hela','lethal-wedding')]
ctx={'app_id':3161310,'country':'KR','language':'koreana','currency':'KRW','divisor':100,'package_id':1,'purchase_option_name':'본편','included_game_count':1}
review={'app_id':3161310,'review_scope':'store_summary_filtered'}
def point(key,value,at,context=None,status='ok'):
 return dict(game_id='hela',metric=key,value=value,observed_at=at,status=status,source_url='https://store.steampowered.com/app/3161310',error_code='network_error' if status=='error' else None,context=context or {})
ccu=point('demo_ccu',77,'2026-10-26T08:00:00Z')
price=[point('price_final',500,'2026-10-25T20:00:00Z',{**ctx,'country':'US','currency':'USD'}),
       point('price_final',0,'2026-10-26T08:00:00Z',{**ctx,'is_free':True}),
       point('price_final',100000,'2026-10-26T08:20:00Z',ctx),
       point('price_final',None,'2026-10-26T08:40:00Z',ctx,'error'),
       point('price_final',200000,'2026-10-26T09:00:00Z',ctx),
       point('price_final',300000,'2026-10-26T11:00:00Z',ctx)]
reviews=[point('review_count',0,'2026-10-26T08:00:00Z',review),point('review_count',10,'2026-10-26T08:20:00Z',review),point('review_count',None,'2026-10-26T08:40:00Z',review,'error'),point('review_count',20,'2026-10-26T09:00:00Z',review)]
percent=[point('review_positive_percent',90,'2026-10-26T09:00:00Z',review)]
history=dict(schema_version=2,generated_at=NOW,collection_status='active',samples=sorted([ccu,*price,*reviews,*percent],key=lambda s:s['observed_at']),events=[],analyses=[])
for row in summary['games']:
 row['ccu_collection_enabled']=True
 row['metrics']={}
 for key in ('followers','review_count','review_positive_percent','price_final'):
  good=[s for s in history['samples'] if s['metric']==key and s['status']=='ok'] if row['game_id']=='hela' else []
  last=good[-1] if good else None
  row['metrics'][key]=dict(status='ok' if last else 'unavailable' if key=='followers' else 'pending',current=last['value'] if last else None,last_ok_at=last['observed_at'] if last else None,last_attempt_at=last['observed_at'] if last else None,target_interval_minutes=20 if key!='followers' else None,context=last['context'] if last else {},ranges={},observation_count=len(good))
 if row['game_id']=='hela':row.update(current=77,last_ok_at=ccu['observed_at'],last_attempt_at=ccu['observed_at'],status='ok')
emptywish=dict(schema_version=1,generated_at=NOW,disclosures=[],follower_checks=[],methods=[],mentions=[],candidates=[],comparisons=[],coverage={})

def open_page(browser,width=390,route='analysis?game=hela&metric=wishlists&range=all',hist=None,summ=None):
 page=browser.new_page(viewport={'width':width,'height':900});page.emulate_media(reduced_motion='reduce');errors=[];requests=[]
 page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url))
 page.add_init_script('Date.now=()=>Date.parse('+json.dumps(NOW)+')')
 data={'config':config,'catalog':catalog,'summary':summ or summary,'events-index':{'events':[]},'wishlists':emptywish}
 def respond(r):
  name=r.request.url.split('?')[0].rsplit('/',1)[-1].removesuffix('.json')
  value=(hist or history) if '/games/' in r.request.url else data[name]
  r.fulfill(content_type='application/json',body=json.dumps(value,ensure_ascii=False))
 page.route('**/data/**',respond)
 page.goto(BASE.rstrip('/')+'/#/'+route,wait_until='networkidle')
 return page,errors,requests

with sync_playwright() as p:
 browser=p.chromium.launch()
 for width in (360,390,1440):
  page,errors,requests=open_page(browser,width)
  expect(page.locator('#game-ccu-panel')).not_to_contain_text('수집 중단')
  expect(page.locator('#game-ccu-panel')).to_contain_text('자동 수집')
  expect(page.locator('#profile-panel-followers')).to_contain_text('검증 출처 미확보')
  expect(page.locator('#profile-chart-followers')).to_have_count(0)
  expect(page.locator('#profile-panel-review_count .profile-value strong')).to_have_text('20건')
  expect(page.locator('#profile-chart-review_count circle')).to_have_count(3)
  expect(page.locator('#profile-chart-review_count polyline')).to_have_count(1)
  expect(page.locator('#profile-chart-review_positive_percent circle')).to_have_count(1)
  expect(page.locator('#profile-chart-review_positive_percent polyline')).to_have_count(0)
  expect(page.locator('#profile-panel-price_final .profile-value strong')).to_have_text('₩3,000')
  expect(page.locator('#profile-chart-price_final circle')).to_have_count(4)
  expect(page.locator('#profile-chart-price_final polyline')).to_have_count(1)
  plot=page.locator('#profile-chart-price_final-plot');plot.focus();page.keyboard.press('Home')
  expect(page.locator('#profile-chart-price_final .chart-reading')).to_contain_text('무료 (₩0)')
  page.keyboard.press('End');expect(page.locator('#profile-chart-price_final .chart-reading')).to_contain_text('₩3,000')
  assert all('/games/hela.json' in u for u in requests if '/games/' in u)
  assert page.evaluate('document.body.scrollWidth<=innerWidth');assert not errors,errors
  page.close()
 print('PASS multi-metric layouts, actual scoped observations, single point, zero/free, error/gap breaks and one lazy history')
 page,errors,_=open_page(browser,route='analysis?game=hela&metric=price_final&range=all')
 expect(page.locator('#metric-select')).to_have_value('price_final')
 raw=page.locator('#download-csv')
 while raw.locator('xpath=ancestor::details[not(@open)]').count():raw.locator('xpath=ancestor::details[not(@open)]').first.locator('summary').first.click()
 with page.expect_download() as download:raw.click()
 rows=list(csv.DictReader(io.StringIO(Path(download.value.path()).read_text(encoding='utf-8-sig'))))
 assert len(rows)==6 and any(r['value']=='300000' and json.loads(r['context_json'])['currency']=='KRW' for r in rows)
 assert any(r['status']=='error' and r['value']=='' for r in rows)
 page.reload(wait_until='networkidle');expect(page.locator('#metric-select')).to_have_value('price_final');assert not errors,errors;page.close()
 print('PASS metric deep link/reload and raw minor-unit CSV with preserved currency/context and errors')
 changed=copy.deepcopy(history)
 changed['samples']=[point('price_final',0,'2026-10-26T08:00:00Z',{**ctx,'is_free':False}),point('price_final',10000,'2026-10-26T08:20:00Z',{**ctx,'package_id':2})]
 page,errors,_=open_page(browser,hist=changed,route='analysis?game=hela&metric=price_final&range=all')
 expect(page.locator('#profile-chart-price_final circle')).to_have_count(1)
 expect(page.locator('#profile-panel-price_final')).to_contain_text('다른 통화·집계 기준')
 assert not errors,errors;page.close()
 changed['samples']=[point('price_final',0,'2026-10-26T08:00:00Z',{**ctx,'is_free':False})]
 page,errors,_=open_page(browser,hist=changed,route='analysis?game=hela&metric=price_final&range=all')
 expect(page.locator('#profile-panel-price_final .profile-value strong')).to_have_text('₩0')
 assert not errors,errors;page.close()
 page,errors,requests=open_page(browser,route='compare')
 expect(page.locator('[data-ledger-game="hela"] [data-profile-summary="price_final"]')).to_contain_text('₩3,000')
 expect(page.locator('[data-ledger-game="lethal-wedding"] [data-profile-summary="price_final"]')).to_contain_text('첫 관측 대기')
 assert not any('/games/' in u for u in requests);assert not errors,errors;page.close()
 print('PASS purchase-option boundaries, paid zero distinct from free, summary ledger, missing distinct from zero and no catalog history flood')
 expired=copy.deepcopy(summary)
 row=next(r for r in expired['games'] if r['game_id']=='hela')
 row['metrics']['price_final'].update(status='unavailable',last_error_code='price_not_offered',last_attempt_at=NOW)
 row['metrics']['review_count'].update(current=0,last_ok_at=NOW,last_attempt_at=NOW)
 row['metrics']['review_positive_percent'].update(status='unavailable',current=None,last_ok_at=None,last_attempt_at=NOW,last_error_code='no_reviews')
 hist=copy.deepcopy(history)
 hist['samples']=[s for s in hist['samples'] if not s['metric'].startswith('review_')]+[point('review_count',0,NOW,review),point('review_positive_percent',None,NOW,review,'unavailable'),point('price_final',None,NOW,ctx,'unavailable')]
 page,errors,_=open_page(browser,hist=hist,summ=expired)
 expect(page.locator('#profile-panel-price_final')).to_contain_text('판매 가격 미제공 · 이전 관측')
 expect(page.locator('#profile-panel-price_final .profile-value')).to_contain_text('이전 정상 관측')
 expect(page.locator('#profile-panel-review_count .profile-value strong')).to_have_text('0건')
 expect(page.locator('#profile-panel-review_positive_percent .profile-value strong')).to_have_text('미확보')
 expect(page.locator('#profile-chart-review_positive_percent')).to_have_count(0)
 assert not errors,errors;page.close()
 page,errors,_=open_page(browser,summ=expired,route='compare')
 price_row=page.locator('[data-ledger-game="hela"] [data-profile-summary="price_final"]')
 expect(price_row).to_contain_text('이전 관측');expect(price_row).to_contain_text('판매 가격 미제공')
 assert not errors,errors;page.close()
 print('PASS unavailable latest attempt retains explicitly dated previous price; zero reviews never fabricate zero percent')
 browser.close()

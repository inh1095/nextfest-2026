'use strict';
(() => {
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const time = value => {const n=Date.parse(value);return Number.isFinite(n)?n:null;};
  const number = n => new Intl.NumberFormat('ko-KR',{maximumFractionDigits:1}).format(n);
  const signed = n => `${n>0?'+':''}${number(n)}`;
  const safeUrl = (value,relative=false) => {try{const u=relative?new URL(value,location.href):new URL(value);return /^https?:$/.test(u.protocol)?u.href:'';}catch{return '';}};
  const link = (href,label,cls='') => safeUrl(href)?`<a href="${esc(safeUrl(href))}" target="_blank" rel="noopener noreferrer" class="${esc(cls)}">${esc(label)} ↗</a>`:'';
  const date = (value,full=false) => {
    if(time(value)===null)return '시각 미확인';
    const p=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value)).map(x=>[x.type,x.value]));
    return `${full?p.year+'.':''}${p.month}.${p.day} ${p.hour}:${p.minute}`;
  };
  const dateOnly=value=>date(value,true).split(' ')[0];
  const iso=t=>new Date(t).toISOString();
  const metricNames={demo_ccu:'데모 동시접속자',followers:'본편 팔로워'};
  const kinds={announcement:'발표',update:'업데이트',video:'영상',livestream:'라이브 방송',demo_release:'데모 공개'};
  const routes={overview:['개요','게임별 관측 현황과 최근 변화를 확인합니다.'],compare:['게임 비교','동일한 기간의 관측값을 비교합니다.'],analysis:['지표 분석','관측 구간을 선택해 변화와 관련 사건을 확인합니다.'],events:['이벤트 히스토리','공개 발표·업데이트·영상의 시점과 원문을 확인합니다.'],collection:['수집 상태','데이터 갱신 상태와 수집 범위를 확인합니다.']};
  const state={config:null,data:null,page:'overview',game:null,range:'all',metric:'demo_ccu',interval:null,event:null,eventPinned:false,chartEvent:null,eventGame:'all',kind:'all',search:'',from:'',to:'',refreshError:false,refreshing:false,loadedAt:null,catalog:null,summary:null,gameMap:new Map(),summaryMap:new Map(),seedGames:new Map(),details:new Map(),detailLoading:new Map(),detailErrors:new Map(),catalogQuery:'',catalogStatus:'all',catalogTag:'all',catalogSort:'current',catalogDir:'desc',catalogPage:1,pageSize:25,compare:[],favorites:new Set(),favoritesOnly:false,eventPage:1,samplePage:1,intervalPage:1,collectionPage:1,collectionQuery:'',collectionStatus:'all',tags:[],generation:0,focusTo:null};
  const valid=s=>s.status==='ok'&&typeof s.value==='number'&&Number.isFinite(s.value)&&s.value>=0&&time(s.observed_at)!==null;
  const sortSamples=rows=>rows.slice().sort((a,b)=>(time(a.observed_at)||0)-(time(b.observed_at)||0));
  const game=id=>state.gameMap.get(id);
  const summaryGame=id=>state.summaryMap.get(id)||{};
  const rangeSummary=id=>summaryGame(id).ranges?.[state.range]||{valid_count:0,first:null,last:null,peak:null,latest_adjacent:null,max_increase:null,positive_intervals:0};
  const settings=()=>({...state.config.collection,...state.summary.collection});
  const rangeEnd=()=>time(state.summary.window_end)||Date.now();
  const gameHistory=id=>state.details.get(id)?.data||null;
  const metric=(id,key)=>state.seedGames.get(id)?.metrics?.find(m=>m.key===key)||(key==='demo_ccu'?{key,definition:'데모 앱을 실행 중인 Steam 연결 플레이어 수',source_url:game(id)?.demo_app_id?`https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=${game(id).demo_app_id}`:'',availability:game(id)?.demo_app_id?'available':'unavailable',unavailable_reason:'확인된 데모 AppID가 없습니다.'}:{key,definition:'본편의 팔로워 수. 위시리스트·커뮤니티 회원 수와 구분합니다.',availability:'unavailable',unavailable_reason:'팔로워로 검증된 공개 수집원을 확보하지 못했습니다.',source_url:'https://partner.steamgames.com/doc/marketing/followers'});
  const archived=()=>state.data.collection_status==='archived'||(time(state.config.collection.stops_at)!==null&&Date.now()>=time(state.config.collection.stops_at));
  const gapLimit=(id=state.game)=>((summaryGame(id).target_interval_minutes||settings().target_cycle_minutes||20)*2+30)*60000;
  const isStale=(s,id=state.game)=>s&&!archived()&&Date.now()-time(s.observed_at)>gapLimit(id);
  const allRows=(id=state.game,key)=>{const samples=gameHistory(id)?.samples||[];return key?samples.filter(s=>s.metric===key):samples;};
  const eventTime=e=>time(e.occurred_at)??time(e.published_at);
  const exactEvent=e=>['minute','hour'].includes(e.time_precision);
  function bounds(id=state.game){
    const end=rangeEnd();
    if(state.range!=='all')return [end-Number(state.range)*3600000,end];
    const ids=Array.isArray(id)?id:[id],ranges=ids.map(i=>rangeSummary(i));
    const observed=[...ranges.flatMap(r=>[time(r.first?.observed_at),time(r.last?.observed_at)]),...ids.flatMap(i=>allRows(i).map(s=>time(s.observed_at)))].filter(t=>t!==null&&t<=end);
    if(!observed.length)return [end-6*3600000,end];
    const first=Math.min(...observed),last=Math.max(...observed);
    if(first===last)return [first-3600000,last+3600000];
    const pad=Math.max((last-first)*.02,60000);return [first-pad,last+pad];
  }
  function rows(id,key){const end=rangeEnd(),start=state.range==='all'?-Infinity:end-Number(state.range)*3600000;return allRows(id,key).filter(s=>time(s.observed_at)!==null&&time(s.observed_at)>=start&&time(s.observed_at)<=end);}
  const validRows=(id,key)=>rows(id,key).filter(valid);
  function intervals(id,key='demo_ccu',positiveOnly=false){
    const data=rows(id,key),result=[];
    for(let i=1;i<data.length;i++){
      const a=data[i-1],b=data[i],elapsed=time(b.observed_at)-time(a.observed_at);
      if(!valid(a)||!valid(b)||elapsed<=0||elapsed>gapLimit(id))continue;
      const delta=b.value-a.value;
      if(positiveOnly&&delta<=0)continue;
      result.push({id:`${id}|${key}|${a.observed_at}|${b.observed_at}`,game_id:id,metric:key,a,b,delta,percent:a.value===0?null:delta/a.value*100,elapsed});
    }
    return result;
  }
  function latestChange(id){const c=rangeSummary(id).latest_adjacent;return c?{a:{observed_at:c.from,value:c.start_value},b:{observed_at:c.to,value:c.end_value},delta:c.delta,elapsed:c.elapsed_minutes}:null;}
  function periodEvents(){const end=rangeEnd(),start=state.range==='all'?-Infinity:end-Number(state.range)*3600000;return state.data.events.filter(e=>state.range==='all'||(eventTime(e)!==null&&eventTime(e)>=start&&eventTime(e)<=end));}
  function eventDate(e){const t=eventTime(e);return t===null?'시점 미확인':exactEvent(e)?date(iso(t)):dateOnly(iso(t))+' · 시각 미확인';}
  function periodLabel(){return state.range==='all'?'전체 관측 기간':`최근 ${state.range}시간${archived()?' · 수집 종료 기준':''}`;}
  const badge=(text,cls='')=>`<span class="badge ${cls}">${esc(text)}</span>`;
  function sampleState(id,key='demo_ccu'){
    if(key==='followers'){const history=allRows(id,key),last=history.at(-1),lastOk=history.filter(valid).at(-1);return {text:lastOk?'확보':'미확보',cls:lastOk?'ok':'',last,lastOk};}
    const s=summaryGame(id),last=s.last_attempt_at?{observed_at:s.last_attempt_at,status:s.status,error_code:s.last_error_code}:null,lastOk=s.last_ok_at&&typeof s.current==='number'?{observed_at:s.last_ok_at,value:s.current}:null;
    if(s.status==='error')return {text:'수집 오류',cls:'error',last,lastOk};
    if(s.status==='unavailable')return {text:'데모 미확보',cls:'',last,lastOk};
    if(s.status==='pending'||!lastOk)return {text:'첫 관측 대기',cls:'',last,lastOk};
    if(isStale(lastOk,id))return {text:'관측 지연',cls:'warn',last,lastOk};
    return {text:archived()?'보관':'정상',cls:archived()?'':'ok',last,lastOk};
  }
  function routeHref(page,extra={}){const p=new URLSearchParams({game:state.game||'',range:state.range,...extra});if(page==='compare'&&state.compare.length)p.set('compare',state.compare.join(','));if(page==='compare'&&!p.has('sort'))p.set('sort',state.catalogSort);return `#/${page}?${p.toString()}`;}
  function syncQuery(){const params=new URLSearchParams({game:state.game,range:state.range});if(state.page==='analysis')params.set('metric',state.metric);if(state.page==='compare'&&state.compare.length)params.set('compare',state.compare.join(','));if(state.page==='compare')params.set('sort',state.catalogSort);if(state.page==='events'&&state.event)params.set('event',state.event);history.replaceState(null,'',`#/${state.page}?${params.toString()}`);}
  function parseRoute(){
    const [path,query='']=location.hash.replace(/^#\/?/,'').split('?');
    state.page=Object.hasOwn(routes,path)?path:'overview';
    const params=new URLSearchParams(query);
    state.eventPinned=false;
    state.focusTo=params.get('at')||null;
    if(params.has('game')&&game(params.get('game')))state.game=params.get('game');
    if(['all','6','24'].includes(params.get('range')))state.range=params.get('range');
    if(['demo_ccu','followers'].includes(params.get('metric')))state.metric=params.get('metric');
    if(['current','delta','max_increase','percent','peak','samples','last','name'].includes(params.get('sort')))state.catalogSort=params.get('sort');
    if(params.has('compare'))state.compare=[...new Set(params.get('compare').split(',').filter(id=>game(id)))].slice(0,4);
    if(params.has('event')&&state.data.events.some(e=>e.id===params.get('event'))){state.event=params.get('event');state.eventPinned=true;}
  }
  function renderChrome(){
    const now=Date.now(),ev=state.config.event;
    const ended=time(ev.ends_at)!==null&&now>=time(ev.ends_at),upcoming=time(ev.starts_at)!==null&&now<time(ev.starts_at);
    const status=$('#festival-status');status.textContent=ended?'행사 종료':upcoming?'행사 시작 전':'행사 진행 중';status.className=`badge ${ended?'':upcoming?'info':'ok'}`;
    const lastTime=state.summary.games.reduce((latest,s)=>time(s.last_ok_at)>time(latest)?s.last_ok_at:latest,null);
    const last=lastTime?{observed_at:lastTime}:null;
    $('#header-freshness').textContent=`최근 관측 ${last?date(last.observed_at)+' KST':'없음'}`;
    $('#sidebar-collection').textContent=archived()?'수집 종료 · 기록 보관':state.data.collection_status==='pending'?'첫 관측 대기':'관측 수집 중';
    $('#sidebar-collection').classList.toggle('archived',archived());
    $('#sidebar-interval').textContent=`전체 목표 ${settings().target_cycle_minutes}분 · 공지 ${settings().news_target_cycle_minutes}분`;
    $('#footer-updated').textContent=`데이터 갱신 ${date(state.data.generated_at,true)} KST`;
    $('#refresh-data').disabled=state.refreshing;
    $('#refresh-data').setAttribute('aria-busy',String(state.refreshing));
    $$('#sidebar [data-route]').forEach(a=>{a.href=routeHref(a.dataset.route);if(a.dataset.route===state.page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
    $('#page-title').textContent=routes[state.page][0];$('#page-description').textContent=routes[state.page][1];
    document.title=`${routes[state.page][0]} · Next Fest Monitor`;
    const refresh=$('#refresh-status');
    refresh.hidden=!state.refreshError;
    refresh.textContent=state.refreshError?'최신 데이터를 가져오지 못했습니다. 마지막으로 불러온 기록을 유지합니다. 새로고침으로 다시 시도할 수 있습니다.':'';
    $('#page-actions').innerHTML=state.page==='collection'?'':`<div class="period-control" role="group" aria-label="관측 기간">${[['6','6시간'],['24','24시간'],['all','전체']].map(([v,l])=>`<button type="button" data-range="${v}" aria-pressed="${state.range===v}">${l}</button>`).join('')}</div>`;
    $$('[data-range]').forEach(b=>b.addEventListener('click',()=>{state.range=b.dataset.range;state.interval=null;state.samplePage=1;state.intervalPage=1;state.catalogPage=1;state.eventPage=1;syncQuery();render();}));
  }
  const gameCell=g=>`<div class="game-cell">${g.header_image&&safeUrl(g.header_image,true)?`<img class="game-thumb" src="${esc(safeUrl(g.header_image,true))}" alt="" loading="lazy">`:''}<div><a class="game-name" title="${esc(g.name)}" href="${esc(routeHref('analysis',{game:g.id}))}">${esc(g.name)}</a><p class="game-app">${g.demo_app_id?'데모 '+esc(g.demo_app_id):'데모 매핑 미확보'}</p></div></div>`;
  const valueCell=s=>s?`<span class="number-main mono">${number(s.value)}</span><span class="subline">${date(s.observed_at)}</span>`:'<span class="text-muted">미확보</span>';
  const deltaHtml=d=>d===null?'—':`<span class="mono ${d>0?'text-positive':d<0?'text-negative':''}">${signed(d)}</span>`;
  function pager(group,total,size=25){
    const key={catalog:'catalogPage',events:'eventPage',samples:'samplePage',intervals:'intervalPage',collection:'collectionPage'}[group],pages=Math.max(1,Math.ceil(total/size));
    state[key]=Math.max(1,Math.min(state[key],pages));const current=state[key],first=total?(current-1)*size+1:0,last=Math.min(total,current*size);
    return `<div class="pagination" id="${group}-pagination"><span>${number(first)}–${number(last)} / ${number(total)}건</span><div><button class="button" type="button" data-page-group="${group}" data-page-value="${current-1}" ${current===1?'disabled':''}>이전</button><span class="mono">${current} / ${pages}</span><button class="button" type="button" data-page-group="${group}" data-page-value="${current+1}" ${current===pages?'disabled':''}>다음</button></div></div>`;
  }
  function catalogMatches(){
    const q=state.catalogQuery.trim().toLocaleLowerCase();
    const data=state.config.games.filter(g=>(!q||g._search.includes(q))&&(state.catalogStatus==='all'||(state.catalogStatus==='ready'?!!rangeSummary(g.id).latest_adjacent:state.catalogStatus==='stale'?sampleState(g.id).text==='관측 지연':summaryGame(g.id).status===state.catalogStatus))&&(state.catalogTag==='all'||g.tags?.includes(state.catalogTag))&&(!state.favoritesOnly||state.favorites.has(g.id)));
    const sortValue=g=>{const r=rangeSummary(g.id);return state.catalogSort==='name'?g.name.toLocaleLowerCase():state.catalogSort==='delta'?r.latest_adjacent?.delta??null:state.catalogSort==='max_increase'?r.max_increase?.delta??null:state.catalogSort==='percent'?r.latest_adjacent?.percent??null:state.catalogSort==='peak'?r.peak:state.catalogSort==='samples'?r.valid_count:state.catalogSort==='last'?time(summaryGame(g.id).last_ok_at):r.last?.value??null;};
    const direction=state.catalogDir==='asc'?1:-1;
    return data.sort((a,b)=>{const av=sortValue(a),bv=sortValue(b);if(av===null&&bv!==null)return 1;if(bv===null&&av!==null)return -1;if(av===bv||av===null)return a.name.localeCompare(b.name);return (typeof av==='string'?av.localeCompare(bv):av-bv)*direction;});
  }
  function summaryChange(id,includeMax=false){
    const r=rangeSummary(id),c=r.latest_adjacent,max=r.max_increase;
    const latest=c?`${deltaHtml(c.delta)}<span class="subline">${c.percent===null?'증가율 —':signed(c.percent)+'%'} · ${number(c.elapsed_minutes)}분</span>`:'<span class="text-muted">계산 대기</span>';
    const maxLink=includeMax&&max?.delta>0?`<a class="max-increase-link" data-max-increase="${esc(id)}" href="${esc(routeHref('analysis',{game:id,at:max.to}))}" title="기간 최대 증가 구간의 관측과 근거 확인">기간 최대 +${number(max.delta)}명 ↗</a><span class="subline max-increase-period">${date(max.from)} → ${date(max.to)}</span>`:'';
    return latest+maxLink;
  }
  function renderOverview(){
    const c=state.summary.coverage,coverage=state.catalog.coverage;
    const signals=state.config.games.filter(g=>rangeSummary(g.id).latest_adjacent?.delta>0).sort((a,b)=>rangeSummary(b.id).latest_adjacent.delta-rangeSummary(a.id).latest_adjacent.delta).slice(0,10);
    const events=periodEvents();
    return `<div class="kpi-grid" id="overview-kpis">${[['공식 참가 목록',c.catalog_total,'개',coverage.complete?'공식 등록 구성 확보':'목록 확보 진행 중'],['데모 연결',c.demo_resolved,'개','CCU 수집 대상 AppID 확인'],['정상 관측 이력',c.ccu_ok,'개',`첫 관측 대기 ${number(c.ccu_pending)}개`],['변화 비교 가능',c.comparison_ready,'개','비교 가능한 관측 쌍 보유']].map(([l,n,u,d])=>`<article class="kpi-card"><div class="kpi-top">${l}<span class="kpi-indicator"></span></div><p class="kpi-value">${number(n||0)}<span>${u}</span></p><p class="kpi-foot">${esc(d)}</p></article>`).join('')}</div>
    <div class="coverage-strip"><span><strong>${number(c.ccu_ok||0)} / ${number(c.catalog_total||0)}</strong> 게임 정상 관측 확보</span><progress value="${c.ccu_ok||0}" max="${c.catalog_total||1}" aria-label="정상 관측 확보 비율"></progress><span>오류 ${number(c.ccu_error||0)} · 데모 미확보 ${number(c.ccu_unavailable||0)} · 공지 확인 ${number(c.news_checked||0)}${c.reviewed_games!==undefined?' · 근거 검토 '+number(c.reviewed_games):''}${c.growth_candidate_games!==undefined?' · 증가 후보 '+number(c.growth_candidate_games):''}</span><a href="${esc(routeHref('collection'))}">수집 범위 확인 →</a></div>
    <section class="card"><div class="card-header"><div><h2>최근 관측 증가 상위 <span>최대 10개</span></h2><p>선택 기간에서 마지막 두 유효 인접 관측의 양의 변화 · ${esc(periodLabel())}</p></div><a href="${esc(routeHref('compare'))}">전체 ${number(c.catalog_total)}개 탐색 →</a></div><div class="table-scroll"><table class="table" id="latest-changes-table"><thead><tr><th>게임</th><th class="numeric">최근 동접</th><th class="numeric">증가 (명)</th><th class="numeric">기준 → 최근</th><th>비교 구간 (KST)</th><th>신선도</th><th></th></tr></thead><tbody>${signals.length?signals.map(g=>{const r=rangeSummary(g.id),i=r.latest_adjacent,status=sampleState(g.id);return `<tr><td>${gameCell(g)}</td><td class="numeric mono">${number(r.last.value)}</td><td class="numeric">${summaryChange(g.id)}</td><td class="numeric mono">${number(i.start_value)} → ${number(i.end_value)}</td><td class="mono">${date(i.from)}<span class="subline">→ ${date(i.to)}</span></td><td>${badge(status.text,status.cls)}</td><td><a class="table-action" href="${esc(routeHref('analysis',{game:g.id,at:i.to}))}">근거 확인 →</a></td></tr>`;}).join(''):'<tr><td colspan="7" class="table-empty">아직 비교 가능한 증가 구간이 없습니다. 첫 관측만 있는 게임은 증가 순위에 넣지 않습니다.</td></tr>'}</tbody></table></div><p class="table-note">증가량은 게임의 성패 점수가 아닙니다. 관측 시각과 간격이 다를 수 있으며 상세에서 사건 근거를 확인합니다.</p></section>
    <div class="two-column"><section class="card"><div class="card-header"><h2>전체 게임 탐색</h2></div><div class="card-body"><p class="explore-lead">${number(c.catalog_total)}개 참가작에서 관측값과 변화를 찾아보세요.</p><p class="detail-footer">검색·태그·수집 상태로 범위를 좁히고 최대 4개 게임의 추이를 비교할 수 있습니다.</p><div class="explore-actions"><a class="button primary" href="${esc(routeHref('compare'))}">게임 목록 열기</a><a class="button" href="${esc(routeHref('compare',{sort:'max_increase'}))}" id="explore-max-increase">기간 최대 증가 탐색</a><a class="button" href="${esc(routeHref('collection'))}">대기·오류 확인</a></div><p class="detail-footer">${esc(coverage.region_note||'공식 행사 등록 목록이며 국가별 노출과 이용 가능 여부는 다를 수 있습니다.')}</p></div></section><section class="card"><div class="card-header"><h2>최근 공개 사건</h2><a href="${esc(routeHref('events'))}">전체 보기 →</a></div>${events.length?`<ul class="event-short-list">${events.slice(0,5).map(e=>`<li><a href="${esc(routeHref('events',{event:e.id}))}"><span class="event-short-title">${esc(e.title)}</span><span class="event-short-meta"><span>${esc(game(e.game_id)?.name||e.game_id)}</span><time>${esc(eventDate(e))}</time>${badge(kinds[e.kind]||'소식')}</span></a></li>`).join('')}</ul>`:'<p class="compact-empty">선택 기간에 확보된 사건이 없습니다. 공지 미조회 게임은 수집 상태에서 확인할 수 있습니다.</p>'}</section></div>`;
  }
  function renderCompare(){
    const filtered=catalogMatches(),pagination=pager('catalog',filtered.length,state.pageSize),page=filtered.slice((state.catalogPage-1)*state.pageSize,state.catalogPage*state.pageSize);
    return `<div class="catalog-filters"><div class="field catalog-search"><label for="catalog-search">검색</label><input id="catalog-search" type="search" value="${esc(state.catalogQuery)}" placeholder="게임 이름 또는 AppID"></div><div class="field"><label for="catalog-status">관측</label><select id="catalog-status">${[['all','전체 상태'],['ready','최근 인접 비교 가능'],['ok','정상 관측'],['pending','첫 관측 대기'],['stale','관측 지연'],['error','수집 오류'],['unavailable','데모 미확보']].map(([v,l])=>`<option value="${v}" ${state.catalogStatus===v?'selected':''}>${l}</option>`).join('')}</select></div><div class="field"><label for="catalog-tag">태그</label><select id="catalog-tag"><option value="all">전체 태그</option>${state.tags.map(t=>`<option value="${esc(t)}" ${state.catalogTag===t?'selected':''}>${esc(t)}</option>`).join('')}</select></div><label class="check-label"><input id="favorites-only" type="checkbox" ${state.favoritesOnly?'checked':''}>관심 게임만</label><div class="field"><label for="catalog-page-size">표시</label><select id="catalog-page-size"><option value="25" ${state.pageSize===25?'selected':''}>25개</option><option value="50" ${state.pageSize===50?'selected':''}>50개</option></select></div></div>
    ${state.compare.length?`<div class="selection-summary"><span>비교 선택 <strong>${state.compare.length} / 4개</strong></span><span class="selection-names">${state.compare.map(id=>esc(game(id).name)).join(' · ')}</span><button type="button" class="button" id="jump-to-comparison">비교 차트 보기 ↓</button></div>`:''}<section class="card catalog-table"><div class="card-header"><h2>참가 게임 <span>${number(filtered.length)} / ${number(state.config.games.length)}개</span></h2><div class="field"><label for="catalog-sort">정렬</label><select id="catalog-sort">${[['current','최근 동접'],['delta','최근 증가량'],['max_increase','기간 최대 증가'],['percent','최근 증가율'],['peak','관측 최고'],['samples','관측 횟수'],['last','최신 관측'],['name','게임 이름']].map(([v,l])=>`<option value="${v}" ${state.catalogSort===v?'selected':''}>${l}</option>`).join('')}</select><button id="catalog-direction" type="button" class="button" aria-label="정렬 방향">${state.catalogDir==='asc'?'오름차순 ↑':'내림차순 ↓'}</button></div></div><div class="table-scroll"><table class="table" id="comparison-table"><thead><tr><th>관심</th><th>비교</th><th>게임</th><th class="numeric">최근 동접 (명)</th><th class="numeric">최근 변화</th><th class="numeric">관측 최고</th><th class="numeric">유효 관측</th><th>상태 / 목표 주기</th></tr></thead><tbody>${page.length?page.map(g=>{const r=rangeSummary(g.id),status=sampleState(g.id),selected=state.compare.includes(g.id);return `<tr><td><button class="favorite-button" type="button" data-favorite="${esc(g.id)}" aria-pressed="${state.favorites.has(g.id)}" aria-label="${esc(g.name)} 관심 게임">${state.favorites.has(g.id)?'★':'☆'}</button></td><td><input class="compare-check" type="checkbox" data-compare-game="${esc(g.id)}" aria-label="${esc(g.name)} 비교 선택" ${selected?'checked':''} ${!selected&&state.compare.length>=4?'disabled':''}></td><td>${gameCell(g)}</td><td class="numeric">${r.last?`<span class="number-main mono">${number(r.last.value)}</span><span class="subline">${date(r.last.observed_at)} KST</span>`:'<span class="text-muted">—</span>'}</td><td class="numeric">${summaryChange(g.id,true)}</td><td class="numeric mono">${r.peak===null||r.peak===undefined?'—':number(r.peak)}</td><td class="numeric mono">${number(r.valid_count||0)}</td><td>${badge(status.text,status.cls)}<span class="subline">목표 ${summaryGame(g.id).target_interval_minutes||settings().target_cycle_minutes}분</span></td></tr>`;}).join(''):'<tr><td colspan="8" class="table-empty">조건에 맞는 게임이 없습니다.</td></tr>'}</tbody></table></div>${pagination}<p class="table-note">기간 기준 ${date(state.summary.window_end,true)} KST. 미확보는 정렬 방향과 관계없이 뒤에 표시합니다. 별표는 이 브라우저의 관심 목록에 저장됩니다.</p></section>
    <section class="card chart-card" id="selected-comparison"><div class="card-header"><h2>선택 게임 비교 <span>${state.compare.length} / 4개</span></h2>${state.compare.length?'<button class="button" id="clear-compare" type="button">선택 해제</button>':''}</div><div class="compare-tray">${state.compare.length?state.compare.map((id,i)=>`<span class="compare-chip"><i class="legend-dot" style="background:${['#528df8','#01a88d','#8b5cf6','#e38d20'][i]}"></i>${esc(game(id).name)}<button type="button" data-remove-compare="${esc(id)}" aria-label="${esc(game(id).name)} 비교 해제">×</button></span>`).join(''):'<p class="text-muted">목록에서 최대 4개 게임을 선택하면 상세 기록과 공통 축 차트를 불러옵니다.</p>'}</div>${state.compare.length?`<div class="table-scroll"><table class="table" id="selected-comparison-table"><thead><tr><th>게임</th><th class="numeric">첫 관측 → 마지막</th><th class="numeric">기간 변화</th><th>실제 관측 범위 (KST)</th><th>기록</th></tr></thead><tbody>${state.compare.map(id=>{const r=rangeSummary(id);return `<tr><td>${esc(game(id).name)}</td><td class="numeric mono">${r.valid_count>=2?`${number(r.first.value)} → ${number(r.last.value)}`:'계산 대기'}</td><td class="numeric">${deltaHtml(r.valid_count>=2?r.last.value-r.first.value:null)}</td><td class="mono">${r.first?`${date(r.first.observed_at)}<span class="subline">→ ${date(r.last.observed_at)}</span>`:'미확보'}</td><td>${historyStatus(id)}</td></tr>`;}).join('')}</tbody></table></div><div id="comparison-chart" class="chart-container"></div><p class="chart-help">선택 게임만 공통 시간축·공통 눈금으로 비교합니다. 대상별 목표 주기를 기준으로 공백을 판단합니다.</p>`:''}</section>`;
  }
  function historyStatus(id){if(!game(id)?.demo_app_id)return badge('데모 미확보');return state.detailLoading.has(id)?badge('기록 로딩 중','info'):state.detailErrors.has(id)?`<button type="button" class="table-action" data-retry-history="${esc(id)}">다시 불러오기</button>`:gameHistory(id)?(gameHistory(id).samples.length?badge('원자료 로드','ok'):badge('첫 관측 대기')):badge('기록 대기');}
  function gamePicker(id,selected,allowAll=false){return `<div class="game-picker"><input id="${id}" type="search" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="${id}-results" autocomplete="off" placeholder="게임 이름 또는 AppID 검색" value="${esc(selected==='all'?'모든 게임':game(selected)?.name||'')}"><div id="${id}-results" class="game-results" role="listbox" hidden></div>${allowAll?'<span class="sr-only">빈 검색어로 모든 게임 선택 가능</span>':''}</div>`;}
  function renderAnalysis(){
    const g=game(state.game),definition=metric(state.game,state.metric),s=validRows(state.game,state.metric),last=s.at(-1),allIntervals=intervals(state.game,state.metric,true).sort((a,b)=>b.delta-a.delta||time(b.b.observed_at)-time(a.b.observed_at));
    if(state.focusTo){const focus=allIntervals.find(i=>i.b.observed_at===state.focusTo);if(focus)state.interval=focus.id;}
    if(!allIntervals.some(i=>i.id===state.interval))state.interval=allIntervals[0]?.id||null;
    const toolbar=`<div class="analysis-toolbar"><div class="field"><label for="game-select">게임</label>${gamePicker('game-select',state.game)}</div><div class="field"><label for="metric-select">지표</label><select id="metric-select"><option value="demo_ccu" ${state.metric==='demo_ccu'?'selected':''}>데모 동시접속자</option><option value="followers" ${state.metric==='followers'?'selected':''}>본편 팔로워${metric(state.game,'followers').availability==='unavailable'?' · 미확보':''}</option></select></div><div class="toolbar-links">${link(g.demo_url,'데모 상점')}${link(definition.source_url,'지표 출처')}</div></div>`;
    if(state.metric==='demo_ccu'&&!g.demo_app_id)return toolbar+`<section class="card" id="metric-unavailable"><div class="metric-unavailable">${badge('데모 미확보')}<div><h2>수집할 데모 AppID를 확인하지 못했습니다.</h2><p>공식 행사 참가 목록에는 포함되어 있으나 데모 연결 정보가 확보되지 않았습니다. 동접을 0명으로 표시하지 않습니다.</p>${link(g.store_url,'본편 상점에서 확인')}<a href="${esc(routeHref('collection'))}">수집 범위 확인 →</a></div></div></section>`;
    if(!gameHistory(state.game)&&state.metric!=='followers')return toolbar+`<section class="card"><div class="card-body"><h2 class="loading-title">${esc(g.name)} 관측 기록</h2><p class="detail-footer">${state.detailErrors.has(state.game)?'상세 기록을 불러오지 못했습니다. 요약 데이터는 유지됩니다.':'선택한 게임의 상세 기록을 불러오고 있습니다.'}</p>${historyStatus(state.game)}</div></section>`;
    if(state.metric==='followers'&&!allRows(state.game,'followers').some(valid))return toolbar+`<section class="card" id="metric-unavailable"><div class="metric-unavailable">${badge('미확보')}<div><h2>본편 팔로워 데이터를 확보하지 못했습니다.</h2><p>${esc(definition.unavailable_reason||'팔로워로 검증된 공개 수집원이 없습니다.')}</p><a href="${esc(routeHref('collection'))}">수집 상태와 범위 확인 →</a></div></div></section>`+rawTable();
    const status=sampleState(state.game,state.metric);
    const intervalPagination=pager('intervals',allIntervals.length),intervalPage=allIntervals.slice((state.intervalPage-1)*25,state.intervalPage*25);
    return toolbar+(state.detailErrors.has(state.game)?'<p class="inline-alert">상세 기록 갱신에 실패해 이전에 불러온 기록을 표시합니다.</p>':'')+`<div class="analysis-layout"><div class="analysis-main"><section class="card chart-card"><div class="card-header"><div><h2>${esc(metricNames[state.metric])}</h2><p>${esc(g.name)} · ${esc(periodLabel())}</p></div>${badge(status.text,status.cls)}</div><div class="chart-stats"><div class="chart-stat"><span>마지막 유효 관측</span><strong>${last?number(last.value):'—'}<small>${last?'명':'미확보'}</small></strong></div><div class="chart-stat"><span>관측 최고</span><strong>${s.length?number(Math.max(...s.map(x=>x.value))):'—'}<small>명</small></strong></div><div class="chart-stat"><span>유효 관측</span><strong>${number(s.length)}<small>회</small></strong></div><div class="chart-stat note">${last?`관측 ${date(last.observed_at)} KST`:'선택 기간에 관측 없음'}<br>${s.length===1?'기준선 수집 중 · 추세 판단 불가':'단위: 명 · 시간: KST'}</div></div><div id="analysis-chart" class="chart-container"></div><p class="chart-help">${s.length===1?'단일 관측은 점으로 표시합니다. 다음 관측이 확보되면 변화를 비교합니다.':`오류·미확보 및 ${number(gapLimit()/60000)}분 초과 공백은 선을 잇지 않습니다.`}</p></section><section class="card" id="intervals-panel"><div class="card-header"><h2>관측 증가 구간 <span>${number(allIntervals.length)}건</span></h2><span class="text-muted">증가량 순</span></div><div class="table-scroll"><table class="table" id="intervals-table"><thead><tr><th>구간 (KST)</th><th class="numeric">시작 → 끝</th><th class="numeric">증가 (명)</th><th class="numeric">증가율</th><th class="numeric">간격</th></tr></thead><tbody>${allIntervals.length?intervalPage.map(i=>`<tr class="${i.id===state.interval?'selected-row':''}"><td><button class="row-button mono" type="button" data-interval-id="${esc(i.id)}" aria-pressed="${i.id===state.interval}">${date(i.a.observed_at)}<span class="subline">→ ${date(i.b.observed_at)}</span></button></td><td class="numeric">${number(i.a.value)} → ${number(i.b.value)}</td><td class="numeric text-positive">+${number(i.delta)}</td><td class="numeric">${i.percent===null?'—':'+'+number(i.percent)+'%'}</td><td class="numeric">${number(i.elapsed/60000)}분</td></tr>`).join(''):`<tr><td colspan="5" class="table-empty">${s.length<2?'비교 가능한 관측이 부족합니다. 증가 구간을 계산할 수 없습니다.':'연속된 유효 관측 사이에서 양의 증가가 확인되지 않았습니다.'}</td></tr>`}</tbody></table></div>${intervalPagination}<p class="table-note">행을 선택하면 차트의 해당 구간과 전후 공개 사건을 확인할 수 있습니다. 기준값이 0이면 증가율은 계산하지 않습니다.</p></section></div><aside id="interval-detail" class="side-panel" aria-live="polite">${intervalDetail(allIntervals.find(i=>i.id===state.interval))}</aside></div>${rawTable()}`;
  }
  function intervalDetail(interval){
    if(!interval)return `<div class="card-header"><h2>구간 상세</h2></div><div class="card-body"><p class="detail-empty">증가 구간이 확보되면 행을 선택해 관련 소식과 검토 근거를 확인할 수 있습니다.</p><p class="detail-footer">사건의 시간적 근접성만으로 증가 원인을 확정하지 않습니다.</p></div>`;
    const a=time(interval.a.observed_at),b=time(interval.b.observed_at);
    const events=state.data.events.filter(e=>e.game_id===state.game&&exactEvent(e)&&eventTime(e)!==null&&eventTime(e)>=a-6*3600000&&eventTime(e)<=b+3600000).sort((x,y)=>Math.abs(eventTime(x)-b)-Math.abs(eventTime(y)-b)).slice(0,3);
    const reviews=(gameHistory(state.game)?.analyses||[]).filter(r=>r.game_id===state.game&&time(r.from)!==null&&time(r.to)!==null&&time(r.from)<=a&&time(r.to)>=b&&time(r.reviewed_at)>=b);
    const selected=state.data.events.find(e=>e.id===state.chartEvent&&events.some(x=>x.id===e.id));
    return `<div class="card-header"><h2>선택 구간 상세</h2>${badge('인과 미확인')}</div><div class="card-body"><p class="small-heading">${esc(metricNames[interval.metric])}</p><p class="detail-value">+${number(interval.delta)}<small>명 · ${interval.percent===null?'증가율 —':'+'+number(interval.percent)+'%'}</small></p><p class="detail-period">${date(interval.a.observed_at)}<br>→ ${date(interval.b.observed_at)} KST</p><p class="detail-copy">${number(interval.a.value)}명 → ${number(interval.b.value)}명 · ${number(interval.elapsed/60000)}분 간격</p><section class="detail-section"><h4>구간 전후 공개 소식</h4><p class="detail-empty">구간 시작 6시간 전 ~ 종료 1시간 후</p>${events.length?events.map(e=>{const relation=eventTime(e)<a?'선행':eventTime(e)>b?'후행':'구간 내';return `<button type="button" class="related-event" data-related-event="${esc(e.id)}" aria-pressed="${state.chartEvent===e.id}"><span>${date(iso(eventTime(e)))} · ${relation}</span>${esc(e.title)}</button>`;}).join(''):'<p class="detail-copy">수집한 자료에서 인접 소식 미확인</p>'}<p class="detail-footer">세부 시각이 확인된 사건만 표시합니다. 후행 사건은 구간 증가의 선행 원인으로 해석하지 않습니다.</p></section>${selected?`<section class="detail-section"><h4>${esc(selected.title)}</h4><p class="detail-copy">${esc(selected.summary||'원문을 확인해 주세요.')}</p><p class="detail-footer">${eventTime(selected)<bounds()[0]?'차트 시간 범위 이전의 사건입니다.':eventTime(selected)>bounds()[1]?'차트 시간 범위 이후의 사건입니다.':'차트의 점선은 선택한 사건의 시점입니다.'}</p>${link(selected.source_url,'원문 확인','button source-button')}<a class="button source-button" href="${esc(routeHref('events',{event:selected.id}))}">이벤트 상세</a></section>`:''}<section class="detail-section"><h4>검토 근거</h4>${reviews.length?reviews.map(reviewHtml).join(''):'<p class="detail-empty">이 구간을 포함하는 검토 기록이 없습니다. 공개 소식은 설명 후보이며 원인이 확인된 것은 아닙니다.</p>'}</section></div>`;
  }
  function rawTable(){const data=rows(state.game,state.metric).slice().reverse(),pagination=pager('samples',data.length),page=data.slice((state.samplePage-1)*25,state.samplePage*25);return `<section class="card raw-table"><div class="card-header"><h2>관측 원자료 <span>${number(data.length)}건</span></h2><button id="download-csv" type="button" class="button" ${data.length?'':'disabled'}>CSV 내려받기 ↓</button></div><div class="table-scroll"><table class="table" id="samples-table"><thead><tr><th>관측 시각 (KST)</th><th>지표</th><th class="numeric">값 (명)</th><th>상태</th><th>출처</th></tr></thead><tbody>${data.length?page.map(s=>`<tr><td class="mono">${date(s.observed_at,true)}</td><td>${esc(metricNames[s.metric]||s.metric)}</td><td class="numeric">${valid(s)?number(s.value):'—'}</td><td>${badge(valid(s)?'확보':s.status==='error'?'수집 오류':'미확보',valid(s)?'ok':s.status==='error'?'error':'')}</td><td>${link(s.source_url,'출처')}</td></tr>`).join(''):'<tr><td colspan="5" class="table-empty">선택 기간에 수집된 기록이 없습니다.</td></tr>'}</tbody></table></div>${pagination}</section>`;}
  function reviewHtml(r){
    const label={direct_evidence:'직접 근거 확인',temporal_association:'시간적 연관성 · 인과 미확인',insufficient:'근거 부족'};
    return `<div class="review-record">${badge(label[r.assessment]||'검토 기록',r.assessment==='insufficient'?'':'info')}<dl class="review-facts"><dt>관측 사실</dt><dd>${esc(r.observation)}</dd><dt>가능한 설명</dt><dd>${esc(r.hypothesis||'확인된 설명이 없습니다.')}</dd><dt>다른 가능한 설명</dt><dd>${(r.alternative_explanations||[]).length?r.alternative_explanations.map(esc).join('<br>'):'별도 검토 기록이 없습니다.'}</dd><dt>검토 대상 기간 (KST)</dt><dd class="mono">${date(r.from,true)}<br>→ ${date(r.to,true)}</dd></dl><p class="detail-footer">검토 ${date(r.reviewed_at,true)} KST<br>이후 관측에는 이 검토를 자동 적용하지 않습니다.</p></div>`;
  }
  function filteredEvents(){
    const from=state.from?time(state.from+'T00:00:00+09:00'):null,to=state.to?time(state.to+'T23:59:59.999+09:00'):null,q=state.search.trim().toLocaleLowerCase();
    return periodEvents().filter(e=>(state.eventGame==='all'||e.game_id===state.eventGame)&&(state.kind==='all'||e.kind===state.kind)&&(!q||`${e.title} ${e.summary||''} ${game(e.game_id)?.name||''}`.toLocaleLowerCase().includes(q))&&(from===null||(eventTime(e)!==null&&eventTime(e)>=from))&&(to===null||(eventTime(e)!==null&&eventTime(e)<=to)));
  }
  function renderEvents(){
    const events=filteredEvents();
    if(!state.eventPinned&&!events.some(e=>e.id===state.event))state.event=events[0]?.id||null;
    const selected=state.data.events.find(e=>e.id===state.event);
    const pagination=pager('events',events.length),page=events.slice((state.eventPage-1)*25,state.eventPage*25);
    const outside=selected&&!events.some(e=>e.id===selected.id);
    return `<div class="filter-bar"><div class="field"><label for="events-game">게임</label>${gamePicker('events-game',state.eventGame,true)}</div><div class="field"><label for="events-kind">종류</label><select id="events-kind"><option value="all">모든 종류</option>${Object.entries(kinds).map(([k,l])=>`<option value="${k}" ${state.kind===k?'selected':''}>${l}</option>`).join('')}</select></div><div class="field"><label for="events-search">검색</label><input id="events-search" type="search" placeholder="제목 또는 게임 이름 검색" value="${esc(state.search)}"></div><div class="field"><label for="events-from">시작</label><input id="events-from" type="date" value="${esc(state.from)}" aria-label="시작 날짜 KST"></div><div class="field"><label for="events-to">종료</label><input id="events-to" type="date" value="${esc(state.to)}" aria-label="종료 날짜 KST"></div></div>${outside?'<p id="events-pinned-notice" class="inline-alert info">직접 선택한 사건이 현재 목록 필터 범위 밖에 있습니다. 해당 사건의 상세를 표시하며 기간과 필터는 유지합니다.</p>':''}<div class="events-layout"><section class="card events-table"><div class="card-header"><h2>공개 사건 <span id="events-count">${number(events.length)}건</span></h2><span class="text-muted">최신순 · KST</span></div><div class="table-scroll"><table class="table" id="events-table"><thead><tr><th>시각 (KST)</th><th>종류</th><th>게임 / 제목</th></tr></thead><tbody>${events.length?page.map(e=>`<tr class="${e.id===state.event?'selected-row':''}"><td class="mono">${esc(eventDate(e))}<span class="subline">${e.occurred_at?'발생 시각':'공개 시각'}</span></td><td>${badge(kinds[e.kind]||'소식')}</td><td class="event-title-cell"><button type="button" class="row-button" data-event-id="${esc(e.id)}" aria-pressed="${e.id===state.event}">${esc(e.title)}</button><span class="subline">${esc(game(e.game_id)?.name||e.game_id)}</span></td></tr>`).join(''):'<tr><td colspan="3" class="table-empty">조건에 맞는 공개 사건이 없습니다. 기록이 없다는 것은 활동이 없었다는 뜻이 아닙니다.</td></tr>'}</tbody></table></div>${pagination}</section><aside id="event-detail" class="side-panel event-detail-panel" aria-live="polite">${eventDetail(selected)}</aside></div>`;
  }
  function eventDetail(e){
    if(!e)return '<div class="card-header"><h2>이벤트 상세</h2></div><div class="card-body"><p class="detail-empty">목록에서 사건을 선택하면 내용과 원문 출처를 확인할 수 있습니다.</p></div>';
    const full=gameHistory(e.game_id)?.events?.find(x=>x.id===e.id);if(full)e=full;
    const reviews=(gameHistory(e.game_id)?.analyses||[]).filter(r=>r.game_id===e.game_id&&(r.evidence_event_ids||[]).includes(e.id));
    const observed=allRows(e.game_id).map(s=>time(s.observed_at)).filter(t=>t!==null),before=eventTime(e)!==null&&observed.length&&eventTime(e)<Math.min(...observed);
    const news=newsState(e.game_id);
    return `<div class="card-header"><h2>이벤트 상세</h2></div><div class="card-body"><div class="detail-meta">${badge(kinds[e.kind]||'소식')}${badge(game(e.game_id)?.name||e.game_id,'info')}</div><h3>${esc(e.title)}</h3><p class="detail-date">${e.occurred_at?'발생':'공개'} ${esc(eventDate(e))}${exactEvent(e)?' KST':''}${e.time_precision==='hour'?' · 시간 단위 근거':''}</p><p class="detail-copy">${esc(e.summary||(state.detailErrors.has(e.game_id)?'사건 상세를 불러오지 못했습니다. 원문 링크에서 확인할 수 있습니다.':!gameHistory(e.game_id)?'선택한 사건의 본문과 검토 기록을 불러오는 중입니다.':'요약이 없습니다. 원문에서 확인할 수 있습니다.'))}</p>${link(e.source_url,'원문 확인','button primary source-button')}${state.detailErrors.has(e.game_id)?`<button type="button" class="button source-button" data-retry-history="${esc(e.game_id)}">상세 다시 불러오기</button>`:''}<p class="detail-footer">출처 확인 ${date(e.verified_at,true)} KST<br>${before?'최초 관측 이전의 사건입니다. 해당 시점의 지표는 확보되지 않았습니다.':!exactEvent(e)?'세부 시각이 확인되지 않아 선후 관계를 확정할 수 없습니다.':'시간적 근접성이 인과관계를 의미하지 않습니다.'}</p>${reviews.length?`<section class="detail-section"><h4>관련 관측 검토</h4>${reviews.map(reviewHtml).join('')}</section>`:''}<section class="detail-section"><p class="detail-footer">${esc(game(e.game_id)?.name||e.game_id)} 공지 확인<br>${news.at?date(news.at,true)+' KST':'기록 없음'} · ${esc(news.text)}</p></section></div>`;
  }
  function newsState(id){const s=summaryGame(id),at=s.last_news_attempt_at,checkedAt=Object.hasOwn(s,'news_all_checked_at')?s.news_all_checked_at:at,delay=checkedAt&&!archived()&&Date.now()-time(checkedAt)>((settings().news_target_cycle_minutes||800)*2+30)*60000;return {at,checkedAt,text:s.news_status==='pending'?'공지 조회 대기':s.news_status==='error'?'수집 오류':s.news_status==='partial'?'일부 출처 확인':delay?'확인 지연':s.news_status==='ok'?'확인 완료':'상태 미확인',cls:s.news_status==='error'?'error':s.news_status==='partial'||delay?'warn':s.news_status==='ok'?'ok':'',errors:s.news_error_codes||[]};}
  function lastRunPanel(){
    const run=state.summary.last_run;
    if(!run)return '<section class="card last-run-panel" id="last-run-status"><div class="card-header"><h2>마지막 수집 실행</h2></div><p class="compact-empty">현재 요약에 마지막 실행 기록이 없습니다.</p></section>';
    const reasons={request_budget:'요청 예산 소진',daily_budget:'일일 예산 소진',runtime_budget:'실행 시간 제한',source_backoff:'요청 오류 보호',utc_day_boundary:'날짜 경계',event_closed:'행사 종료',interrupted:'중단'};
    const reason=run.pause_reason?(reasons[run.pause_reason]||String(run.pause_reason)):(run.finished_at?'완료':'종료 기록 없음');
    const count=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0?number(value)+'회':'미확보';
    return `<section class="card last-run-panel" id="last-run-status"><div class="card-header"><h2>마지막 수집 실행</h2>${badge(reason,run.pause_reason?'warn':run.finished_at?'ok':'')}</div><div class="run-summary"><span>시작 <strong class="mono">${date(run.started_at,true)}</strong></span><span>종료 <strong class="mono">${run.finished_at?date(run.finished_at,true):'기록 없음'}</strong> KST</span><span>실제 요청 <strong class="mono">${count(run.request_count)}</strong></span><span>CCU <strong class="mono">${count(run.ccu_requests)}</strong></span><span>공지 <strong class="mono">${count(run.news_requests)}</strong></span><span>예약량 <strong class="mono">${count(run.reserved_requests)}</strong></span></div><p class="table-note">예약량은 마지막 실행에 할당한 요청 예산입니다. 실제 요청량이나 일일 누적 예약량이 아닙니다.</p></section>`;
  }
  function renderCollection(){
    const c=settings(),e=state.config.event,coverage=state.summary.coverage,registration=state.catalog.coverage,q=state.collectionQuery.trim().toLocaleLowerCase();
    const filtered=state.config.games.filter(g=>(!q||g._search.includes(q))&&(state.collectionStatus==='all'||(state.collectionStatus==='news_pending'?summaryGame(g.id).news_status==='pending':state.collectionStatus==='stale'?sampleState(g.id).text==='관측 지연':summaryGame(g.id).status===state.collectionStatus)));
    const pagination=pager('collection',filtered.length),page=filtered.slice((state.collectionPage-1)*25,state.collectionPage*25),selected=game(state.game);
    return `<div class="kpi-grid" id="fleet-coverage">${[['정상 관측 이력',coverage.ccu_ok,'과거 성공 후 현재 오류인 게임도 포함'],['첫 관측 대기',coverage.ccu_pending,'아직 정상값이 없는 수집 대기 게임'],['최근 수집 오류',coverage.ccu_error,'마지막 시도 결과 기준'],['공지 조회 대기',coverage.news_pending,'공지 미조회는 소식 없음과 다릅니다']].map(([l,n,d])=>`<article class="kpi-card"><div class="kpi-top">${l}</div><p class="kpi-value">${number(n||0)}<span>개</span></p><p class="kpi-foot">${d}</p></article>`).join('')}</div>
    ${lastRunPanel()}<div class="catalog-filters"><div class="field catalog-search"><label for="collection-search">검색</label><input id="collection-search" type="search" value="${esc(state.collectionQuery)}" placeholder="게임 이름 또는 AppID"></div><div class="field"><label for="collection-status">상태</label><select id="collection-status">${[['all','전체 상태'],['ok','마지막 시도 정상'],['pending','첫 관측 대기'],['stale','관측 지연'],['error','수집 오류'],['unavailable','데모 미확보'],['news_pending','공지 조회 대기']].map(([v,l])=>`<option value="${v}" ${state.collectionStatus===v?'selected':''}>${l}</option>`).join('')}</select></div></div>
    <section class="card"><div class="card-header"><h2>게임별 수집 상태 <span>${number(filtered.length)}개</span></h2>${badge(archived()?'수집 종료':'수집 진행',archived()?'':'ok')}</div><div class="table-scroll"><table class="table" id="collection-table"><thead><tr><th>게임</th><th>동접 상태</th><th class="numeric">최근 값</th><th>마지막 정상 (KST)</th><th>마지막 시도 (KST)</th><th>목표 주기</th><th>공지 상태</th><th>오류 / 근거</th></tr></thead><tbody>${page.length?page.map(g=>{const status=sampleState(g.id),n=newsState(g.id),sg=summaryGame(g.id);return `<tr><td>${gameCell(g)}</td><td>${badge(status.text,status.cls)}</td><td class="numeric mono">${typeof sg.current==='number'?number(sg.current)+'명':'—'}</td><td class="mono">${sg.last_ok_at?date(sg.last_ok_at):'없음'}</td><td class="mono">${sg.last_attempt_at?date(sg.last_attempt_at):'미시도'}</td><td class="mono">${sg.target_interval_minutes||c.target_cycle_minutes}분</td><td>${badge(n.text,n.cls)}<span class="subline">${n.at?'시도 '+date(n.at):'확인 기록 없음'}</span>${n.checkedAt?`<span class="subline">전체 확인 ${date(n.checkedAt)}</span>`:''}</td><td>${esc(sg.last_error_code||'—')}${n.errors.length?`<span class="subline">공지: ${esc(n.errors.join(', '))}</span>`:''}<button type="button" class="table-action evidence-action" data-show-evidence="${esc(g.id)}">게임 근거 확인</button></td></tr>`;}).join(''):'<tr><td colspan="8" class="table-empty">조건에 맞는 게임이 없습니다.</td></tr>'}</tbody></table></div>${pagination}<p class="table-note">관측 지연·차트 공백은 게임별 목표 주기 × 2 + 30분으로 판단합니다. 과거 정상값은 현재 수집 오류와 함께 표시할 수 있습니다.</p></section>
    <div class="settings-grid"><section class="card"><div class="card-header"><h2>수집 설정과 모집단</h2></div><div class="card-body"><dl class="definition-list"><div><dt>공식 참가 목록</dt><dd>${number(registration.unique_total)} / ${number(registration.official_total)}개 · ${registration.complete?'등록 구성 확보':'확보 진행 중'}<br>${link(registration.source_url,'공식 행사 목록')}</dd></div><div><dt>행사 기간</dt><dd class="mono">${date(e.starts_at,true)}<br>~ ${date(e.ends_at,true)} KST</dd></div><div><dt>전체 CCU 목표</dt><dd>${c.target_cycle_minutes}분 / 한 순환<br>우선 관측 게임은 게임별 주기 적용</dd></div><div><dt>공지 목표 순환</dt><dd>${c.news_target_cycle_minutes}분</dd></div><div><dt>예약 실행 간격</dt><dd>${c.scheduled_interval_minutes||c.interval_minutes}분 · 실행당 전체 목록의 일부 처리</dd></div><div><dt>수집 종료</dt><dd class="mono">${date(c.stops_at,true)} KST</dd></div><div><dt>요약 기준 시각</dt><dd class="mono">${date(state.summary.window_end,true)} KST</dd></div><div><dt>화면 새로고침</dt><dd>5분마다 요약 재조회 · 상세는 선택 시 로드</dd></div></dl><p class="detail-footer">GitHub Actions 예약은 지연될 수 있으며 실제 관측 시각을 기준으로 표시합니다. ${esc(registration.region_note||'공식 등록 목록과 국가별 노출·이용 가능 여부는 구분합니다.')}</p></div></section><section class="card"><div class="card-header"><h2>데이터 범위와 해석</h2></div><div class="card-body"><ul class="principles"><li><h3>목록 확보와 분석 완료는 다릅니다</h3><p>전체 참가 목록, 데모 연결, 첫 관측, 인접 변화 비교, 사건 근거 검토는 서로 다른 단계입니다. 첫 관측 대기 게임도 목록에 유지합니다.</p></li><li><h3>정상 관측 이력과 최근 오류는 겹칠 수 있습니다</h3><p>정상값을 확보한 뒤 수집에 실패할 수 있으므로 상태별 수치를 모두 더해 전체 게임 수로 해석하지 않습니다. 0은 정상 응답의 순간값이며 미확보와 구분합니다.</p></li><li><h3>실제 관측 범위 안에서 비교합니다</h3><p>최초 관측 이전의 과거값은 없습니다. 관측 최고는 확보한 표본 중 최고입니다. 기간과 게임별 관측 간격을 함께 확인하며 성패 점수는 만들지 않습니다.</p></li><li><h3>본편 팔로워는 미확보입니다</h3><p>검증된 팔로워 수집원이 없어 동접·커뮤니티 회원 수로 대체하지 않습니다. 위시리스트·구매 수 역시 표시하지 않습니다.</p></li><li><h3>사건의 근접성은 원인의 증명이 아닙니다</h3><p>구간 시작 6시간 전~종료 1시간 후 소식을 찾아 선행·구간 내·후행을 구분합니다. 날짜만 알려진 사건은 시각 비교에서 제외하고 검토 시점 이후 관측에 과거 판단을 자동 적용하지 않습니다.</p></li></ul></div></section></div>
    <section class="card" id="game-evidence"><div class="card-header"><h2>게임 참가 근거</h2><span class="text-muted">${esc(selected.name)}</span></div><div class="card-body"><div class="field evidence-picker"><label for="collection-game">게임 검색</label>${gamePicker('collection-game',state.game)}</div><p class="detail-footer">${esc(state.seedGames.get(selected.id)?.selection_reason||'공식 행사 등록 목록에서 확인한 게임입니다.')}</p><blockquote class="evidence-quote">${esc(selected.participation?.evidence_excerpt||'추가 근거 확인 중')}</blockquote><div class="toolbar-links">${link(selected.participation?.source_url,'행사 참가 근거')}${link(selected.store_url,'본편 상점')}${selected.demo_url?link(selected.demo_url,'데모 상점'):''}</div><p class="detail-footer">확인 ${date(selected.participation?.verified_at,true)} KST · 데모 매핑 ${esc(selected.source_status||'확인 중')}</p></div></section>`;
  }
  function drawChart(container,series,selected=null,selectedEvent=null){
    if(!container)return;
    const width=Math.max(280,Math.round(container.clientWidth-((innerWidth<=720)?16:32))),height=innerWidth<=720?240:290;
    const L=48,R=16,T=26,B=43,[start,end]=bounds(series.map(s=>s.id));
    const all=series.flatMap(s=>s.data.filter(valid));
    if(!all.length){const loading=series.some(s=>state.detailLoading.has(s.id)),failed=series.some(s=>state.detailErrors.has(s.id));container.innerHTML=`<div class="empty-chart">${loading?'선택한 게임의 상세 관측 기록을 불러오는 중입니다.':failed?'일부 상세 기록을 불러오지 못했습니다. 위 표에서 다시 불러올 수 있습니다.':'선택 기간에 유효한 관측값이 없습니다.'}</div>`;return;}
    const max=Math.max(...all.map(s=>s.value));
    let top=max===0?1:max*1.16;
    const power=Math.pow(10,Math.floor(Math.log10(top))),factor=top/power;
    top=(factor<=1?1:factor<=2?2:factor<=2.5?2.5:factor<=5?5:10)*power;
    if(max===0)top=1;
    const x=t=>L+(t-start)/(end-start)*(width-L-R),y=v=>T+(1-v/top)*(height-T-B);
    let out='';
    if(selected){const x1=x(time(selected.a.observed_at)),x2=x(time(selected.b.observed_at));out+=`<rect data-selected-interval="true" x="${x1}" y="${T}" width="${Math.max(x2-x1,2)}" height="${height-T-B}" fill="#528df818"/><line x1="${x1}" x2="${x1}" y1="${T}" y2="${height-B}" stroke="#528df850"/><line x1="${x2}" x2="${x2}" y1="${T}" y2="${height-B}" stroke="#528df850"/>`;}
    for(let i=0;i<3;i++){const v=top*i/2,yy=y(v);out+=`<line class="grid" x1="${L}" x2="${width-R}" y1="${yy}" y2="${yy}"/><text x="${L-9}" y="${yy+4}" text-anchor="end">${number(v)}</text>`;}
    out+=`<line class="axis" x1="${L}" x2="${width-R}" y1="${height-B}" y2="${height-B}"/>`;
    const ticks=width<500?2:3;
    for(let i=0;i<ticks;i++){const t=start+(end-start)*i/(ticks-1),xx=x(t);out+=`<text x="${xx}" y="${height-14}" text-anchor="${i===0?'start':i===ticks-1?'end':'middle'}">${date(iso(t))}</text>`;}
    if(selectedEvent&&exactEvent(selectedEvent)&&eventTime(selectedEvent)>=start&&eventTime(selectedEvent)<=end){const xx=x(eventTime(selectedEvent));out+=`<line class="event-line" x1="${xx}" x2="${xx}" y1="${T-5}" y2="${height-B}"/><text x="${Math.min(width-R-10,Math.max(L+30,xx))}" y="${T-12}" text-anchor="middle">선택 사건</text>`;}
    series.forEach(s=>{
      let segment=[],segments=[];
      for(const sample of s.data){
        if(!valid(sample)){if(segment.length)segments.push(segment);segment=[];continue;}
        if(segment.length&&time(sample.observed_at)-time(segment.at(-1).observed_at)>gapLimit(s.id)){segments.push(segment);segment=[];}
        segment.push(sample);
      }
      if(segment.length)segments.push(segment);
      for(const segment of segments){
        if(segment.length>1)out+=`<polyline class="series" stroke="${s.color}" points="${segment.map(p=>`${x(time(p.observed_at))},${y(p.value)}`).join(' ')}"/>`;
        for(const p of segment)out+=`<circle cx="${x(time(p.observed_at))}" cy="${y(p.value)}" r="${segment.length===1?4:3}" fill="${s.color}" stroke="white" stroke-width="1.5"><title>${esc(s.label)} · ${date(p.observed_at,true)} KST · ${number(p.value)}명</title></circle>`;
      }
    });
    container.innerHTML=`<svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(series.map(s=>s.label).join(', '))} 추이. 유효 관측 ${all.length}회. 단위 명, KST. 원자료 표에서 정확한 값을 확인할 수 있습니다."><title>실제 관측값의 변화</title>${out}</svg>`;
  }
  function renderCharts(){
    if(state.page==='compare'&&state.compare.length)drawChart($('#comparison-chart'),state.compare.map((id,i)=>({id,label:game(id).name,color:['#528df8','#01a88d','#8b5cf6','#e38d20'][i],data:rows(id,'demo_ccu')})));
    if(state.page==='analysis'&&$('#analysis-chart'))drawChart($('#analysis-chart'),[{id:state.game,label:game(state.game).name,color:'#528df8',data:rows(state.game,state.metric)}],intervals(state.game,state.metric,true).find(i=>i.id===state.interval),state.data.events.find(e=>e.id===state.chartEvent));
  }
  function preserveFocus(fn){
    const active=document.activeElement,id=active?.id,interval=active?.dataset?.intervalId,event=active?.dataset?.eventId,related=active?.dataset?.relatedEvent,range=active?.dataset?.range;
    const dataSelector=['favorite','compareGame','removeCompare','pageGroup'].find(k=>active?.dataset?.[k]);
    const dataValue=dataSelector?active.dataset[dataSelector]:null,pickerExpanded=active?.getAttribute('aria-expanded');
    const start=active instanceof HTMLInputElement&&['search','text'].includes(active.type)?active.selectionStart:null;
    const end=start!==null?active.selectionEnd:null;
    fn();
    const attrName=dataSelector?dataSelector.replace(/[A-Z]/g,m=>'-'+m.toLowerCase()):null;
    const target=id?document.getElementById(id):attrName?document.querySelector(`[data-${attrName}="${CSS.escape(dataValue)}"]`):interval?document.querySelector(`[data-interval-id="${CSS.escape(interval)}"]`):event?document.querySelector(`[data-event-id="${CSS.escape(event)}"]`):related?document.querySelector(`[data-related-event="${CSS.escape(related)}"]`):range?document.querySelector(`[data-range="${CSS.escape(range)}"]`):null;
    if(target){target.focus({preventScroll:true});if(start!==null&&target instanceof HTMLInputElement)target.setSelectionRange(start,end);if(pickerExpanded==='false'&&target.getAttribute('role')==='combobox'){target.setAttribute('aria-expanded','false');target.removeAttribute('aria-activedescendant');const list=document.getElementById(target.id+'-results');if(list)list.hidden=true;}}
  }
  function csvDownload(){
    const data=rows(state.game,state.metric),cell=value=>`"${String(value??'').replace(/"/g,'""')}"`;
    const matrix=[['game_id','metric','observed_at_utc','observed_at_kst','value','status','source_url','error_code'],...data.map(s=>[s.game_id,s.metric,s.observed_at,date(s.observed_at,true)+' KST',valid(s)?s.value:'',s.status,s.source_url,s.error_code])];
    const blob=new Blob(['\uFEFF'+matrix.map(r=>r.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8;'}),address=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=address;a.download=`nextfest-${state.game}-${state.metric}-${state.range}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(address),1000);
  }
  function storePreferences(){try{localStorage.setItem('nextfest-favorites-v2',JSON.stringify([...state.favorites]));localStorage.setItem('nextfest-compare-v2',JSON.stringify(state.compare));}catch{}}
  function chooseGame(id,context){
    if(context==='events-game'){state.eventGame=id;state.event=null;state.eventPinned=false;state.eventPage=1;}
    else {state.game=id;state.interval=null;state.focusTo=null;state.chartEvent=null;state.samplePage=1;state.intervalPage=1;syncQuery();}
    render();const input=document.getElementById(context);input?.focus({preventScroll:true});if(input){input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');const list=document.getElementById(context+'-results');if(list)list.hidden=true;}
  }
  function bindPicker(id,allowAll=false){
    const input=document.getElementById(id),list=document.getElementById(id+'-results');if(!input||!list)return;
    let items=[],active=-1;
    const close=()=>{list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');};
    const show=()=>{
      const q=input.value.trim().toLocaleLowerCase();items=[];
      if(allowAll&&(!q||'모든 게임'.includes(q)))items.push({id:'all',name:'모든 게임',app_id:null});
      for(const g of state.config.games){if((!q||g._search.includes(q))&&items.length<20)items.push(g);if(items.length>=20)break;}
      active=-1;list.innerHTML=items.length?items.map((g,i)=>`<button type="button" id="${id}-option-${i}" role="option" aria-selected="false" data-picker-id="${esc(g.id)}"><span>${esc(g.name)}</span><small>${g.app_id?'App '+g.app_id:'전체 참가작'}</small></button>`).join(''):'<p>일치하는 게임이 없습니다.</p>';
      list.hidden=false;input.setAttribute('aria-expanded','true');
      list.querySelectorAll('[data-picker-id]').forEach(b=>b.addEventListener('click',()=>chooseGame(b.dataset.pickerId,id)));
    };
    input.addEventListener('focus',()=>{input.select();show();});input.addEventListener('input',show);
    input.addEventListener('keydown',e=>{
      if(e.key==='Escape'){close();return;}
      if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();if(list.hidden)show();if(!items.length)return;active=(active+(e.key==='ArrowDown'?1:-1)+items.length)%items.length;list.querySelectorAll('[role=option]').forEach((b,i)=>b.setAttribute('aria-selected',String(i===active)));input.setAttribute('aria-activedescendant',`${id}-option-${active}`);document.getElementById(`${id}-option-${active}`)?.scrollIntoView({block:'nearest'});}
      if(e.key==='Enter'&&active>=0){e.preventDefault();chooseGame(items[active].id,id);}
      if(e.key==='Tab')close();
    });
    input.addEventListener('blur',()=>setTimeout(()=>{if(!list.contains(document.activeElement))close();},120));
  }
  function bindPage(){
    bindPicker('game-select');bindPicker('events-game',true);bindPicker('collection-game');
    $('#metric-select')?.addEventListener('change',e=>{state.metric=e.target.value;state.interval=null;state.chartEvent=null;state.samplePage=1;syncQuery();preserveFocus(render);});
    $('#download-csv')?.addEventListener('click',csvDownload);
    $$('[data-interval-id]').forEach(b=>b.addEventListener('click',()=>{state.interval=b.dataset.intervalId;state.focusTo=null;state.chartEvent=null;preserveFocus(render);if(innerWidth<980)$('#interval-detail').scrollIntoView({block:'start',behavior:'smooth'});}));
    $$('[data-related-event]').forEach(b=>b.addEventListener('click',()=>{state.chartEvent=b.dataset.relatedEvent;preserveFocus(render);}));
    $$('[data-event-id]').forEach(b=>b.addEventListener('click',()=>{state.event=b.dataset.eventId;state.eventPinned=false;syncQuery();preserveFocus(render);if(innerWidth<980)$('#event-detail').scrollIntoView({block:'start',behavior:'smooth'});}));
    [['events-kind','kind'],['events-from','from'],['events-to','to']].forEach(([id,key])=>$('#'+id)?.addEventListener('change',e=>{state[key]=e.target.value;state.event=null;state.eventPinned=false;state.eventPage=1;preserveFocus(render);}));
    $('#events-search')?.addEventListener('input',e=>{state.search=e.target.value;state.event=null;state.eventPinned=false;state.eventPage=1;preserveFocus(render);});
    $('#catalog-search')?.addEventListener('input',e=>{state.catalogQuery=e.target.value;state.catalogPage=1;preserveFocus(render);});
    [['catalog-status','catalogStatus'],['catalog-tag','catalogTag'],['catalog-sort','catalogSort']].forEach(([id,key])=>$('#'+id)?.addEventListener('change',e=>{state[key]=e.target.value;state.catalogPage=1;syncQuery();preserveFocus(render);}));
    $('#catalog-direction')?.addEventListener('click',()=>{state.catalogDir=state.catalogDir==='asc'?'desc':'asc';state.catalogPage=1;preserveFocus(render);});
    $('#catalog-page-size')?.addEventListener('change',e=>{state.pageSize=Number(e.target.value)===50?50:25;state.catalogPage=1;preserveFocus(render);});
    $('#favorites-only')?.addEventListener('change',e=>{state.favoritesOnly=e.target.checked;state.catalogPage=1;preserveFocus(render);});
    $$('[data-favorite]').forEach(b=>b.addEventListener('click',()=>{const id=b.dataset.favorite;state.favorites.has(id)?state.favorites.delete(id):state.favorites.add(id);storePreferences();preserveFocus(render);}));
    $$('[data-compare-game]').forEach(b=>b.addEventListener('change',()=>{const id=b.dataset.compareGame;if(b.checked&&state.compare.length<4)state.compare.push(id);else if(!b.checked)state.compare=state.compare.filter(x=>x!==id);storePreferences();syncQuery();preserveFocus(render);}));
    $$('[data-remove-compare]').forEach(b=>b.addEventListener('click',()=>{state.compare=state.compare.filter(id=>id!==b.dataset.removeCompare);storePreferences();syncQuery();render();}));
    $('#jump-to-comparison')?.addEventListener('click',()=>$('#selected-comparison').scrollIntoView({block:'start',behavior:'smooth'}));
    $('#clear-compare')?.addEventListener('click',()=>{state.compare=[];storePreferences();syncQuery();render();});
    $$('[data-page-group]').forEach(b=>b.addEventListener('click',()=>{const key={catalog:'catalogPage',events:'eventPage',samples:'samplePage',intervals:'intervalPage',collection:'collectionPage'}[b.dataset.pageGroup];state[key]=Number(b.dataset.pageValue);preserveFocus(render);}));
    $('#collection-search')?.addEventListener('input',e=>{state.collectionQuery=e.target.value;state.collectionPage=1;preserveFocus(render);});
    $('#collection-status')?.addEventListener('change',e=>{state.collectionStatus=e.target.value;state.collectionPage=1;preserveFocus(render);});
    $$('[data-show-evidence]').forEach(b=>b.addEventListener('click',()=>{state.game=b.dataset.showEvidence;syncQuery();render();$('#game-evidence').scrollIntoView({block:'start',behavior:'smooth'});}));
    $$('[data-retry-history]').forEach(b=>b.addEventListener('click',()=>loadHistory(b.dataset.retryHistory,true)));
  }
  function activeHistoryIds(){
    if(state.page==='analysis')return metric(state.game,state.metric).availability==='available'?[state.game]:[];
    if(state.page==='compare')return state.compare.filter(id=>game(id)?.demo_app_id);
    if(state.page==='events'){const selected=state.data.events.find(e=>e.id===state.event);return selected?[selected.game_id]:[];}
    return [];
  }
  function overlayEventDetails(){
    const detailed=new Map();for(const entry of state.details.values())for(const e of entry.data.events||[])detailed.set(e.id,e);
    state.data.events=state.eventIndex.map(e=>detailed.has(e.id)?{...e,...detailed.get(e.id)}:e);
  }
  function evictHistory(){
    const keep=new Set([...activeHistoryIds(),state.game,...state.compare]);
    for(const id of state.details.keys()){if(state.details.size<=12)break;if(!keep.has(id))state.details.delete(id);}
  }
  async function loadHistory(id,force=false){
    if(!game(id)||state.detailLoading.has(id))return;
    if(!force&&state.details.get(id)?.generation===state.generation)return;
    if(!force&&state.detailErrors.get(id)===state.generation)return;
    const generation=state.generation,token={generation};
    state.detailLoading.set(id,token);
    if(activeHistoryIds().includes(id))preserveFocus(render);
    const task=(async()=>{
      try{
        const path=summaryGame(id).history_url;if(!path)throw new Error('missing history');
        const address=new URL(path,location.href);if(address.origin!==location.origin)throw new Error('invalid history location');address.searchParams.set('v',state.summary.generated_at||String(generation));
        const response=await fetch(address.href,{cache:'no-cache'});if(!response.ok)throw new Error('history unavailable');
        const data=await response.json();if(!Array.isArray(data.samples)||!Array.isArray(data.events)||!Array.isArray(data.analyses))throw new Error('invalid history');
        if(generation!==state.generation)return;
        data.samples=sortSamples(data.samples.filter(s=>s.game_id===id));data.events=data.events.filter(e=>e.game_id===id);data.analyses=data.analyses.filter(a=>a.game_id===id);
        state.details.delete(id);state.details.set(id,{data,generation});state.detailErrors.delete(id);evictHistory();overlayEventDetails();
      }catch{if(generation===state.generation)state.detailErrors.set(id,generation);}
      finally{
        if(state.detailLoading.get(id)===token)state.detailLoading.delete(id);
        if(activeHistoryIds().includes(id)){preserveFocus(render);}
      }
    })();
    await task;
  }
  function render(){
    if(!state.config)return;
    renderChrome();
    const renderers={overview:renderOverview,compare:renderCompare,analysis:renderAnalysis,events:renderEvents,collection:renderCollection};
    $('#route-view').dataset.page=state.page;$('#route-view').innerHTML=renderers[state.page]();
    bindPage();renderCharts();
    for(const id of activeHistoryIds())if(!state.detailLoading.has(id))loadHistory(id);
  }
  function mobile(){return matchMedia('(max-width:720px)').matches;}
  function setMenu(open,restore=true){
    const sidebar=$('#sidebar');sidebar.classList.toggle('open',open&&mobile());
    $('#sidebar-backdrop').hidden=!(open&&mobile());
    $('#menu-toggle').setAttribute('aria-expanded',String(open&&mobile()));
    sidebar.inert=mobile()&&!open;
    if(mobile()&&!open)sidebar.setAttribute('aria-hidden','true');else sidebar.removeAttribute('aria-hidden');
    document.body.style.overflow=open&&mobile()?'hidden':'';
    if(open&&mobile())$('#menu-close').focus();
    else if(restore&&mobile())$('#menu-toggle').focus();
  }
  async function loadData(cacheBust=false,forceMetadata=false){
    const suffix=cacheBust?`?v=${Date.now()}`:'',reloadMetadata=!state.catalog||forceMetadata||Date.now()-(state.catalogLoadedAt||0)>1800000;
    const names=reloadMetadata?['config','catalog','summary','events-index']:['summary','events-index'];
    const responses=await Promise.all(names.map(name=>fetch(`./data/${name}.json${suffix}`,{cache:'no-cache'})));
    if(responses.some(r=>!r.ok))throw new Error('unavailable');
    const payload=Object.fromEntries(await Promise.all(responses.map(async(r,i)=>[names[i],await r.json()])));
    const config=payload.config||state.config,catalog=payload.catalog||state.catalog,summary=payload.summary,index=payload['events-index'];
    if(!config.event||!config.collection||!Array.isArray(catalog.games)||!catalog.games.length||!Array.isArray(summary.games)||!Array.isArray(index.events))throw new Error('invalid schema');
    const generationChanged=!state.summary||state.summary.generated_at!==summary.generated_at;
    if(generationChanged)state.generation++;
    if(reloadMetadata){
      state.seedGames=new Map((payload.config.games||[]).map(g=>[g.id,g]));
      for(const g of catalog.games)g._search=`${g.name} ${g.app_id} ${g.demo_app_id||''}`.toLocaleLowerCase();
      state.gameMap=new Map(catalog.games.map(g=>[g.id,g]));state.tags=[...new Set(catalog.games.flatMap(g=>g.tags||[]))].sort((a,b)=>a.localeCompare(b));state.catalogLoadedAt=Date.now();
    }
    state.config={...config,games:catalog.games};state.catalog=catalog;state.summary=summary;state.summaryMap=new Map(summary.games.map(g=>[g.game_id,g]));
    state.eventIndex=index.events.slice().sort((a,b)=>(eventTime(b)||0)-(eventTime(a)||0));
    state.data={...summary,events:[],analyses:[]};overlayEventDetails();state.refreshError=false;state.loadedAt=new Date().toISOString();
    if(!game(state.game))state.game=state.seedGames.keys().next().value||catalog.games[0].id;
    state.compare=state.compare.filter(id=>game(id)).slice(0,4);state.favorites=new Set([...state.favorites].filter(id=>game(id)));
  }
  async function refresh(forceMetadata=false){
    if(state.refreshing)return;
    const hadData=!!state.config;
    state.refreshing=true;if(state.config)renderChrome();else $('#refresh-data').disabled=true;
    try{await loadData(true,forceMetadata);if(!hadData)parseRoute();preserveFocus(render);}
    catch{state.refreshError=true;if(state.config)renderChrome();else showLoadError();}
    finally{state.refreshing=false;$('#refresh-data').disabled=false;$('#refresh-data').setAttribute('aria-busy','false');}
  }
  function showLoadError(){
    $('#page-description').textContent='관측 데이터를 불러오지 못했습니다.';
    $('#route-view').dataset.page='error';$('#route-view').innerHTML='<section class="card loading-state">데이터를 불러오지 못했습니다. 상단 새로고침으로 다시 시도해 주세요.<br>확보되지 않은 수치는 표시하지 않습니다.</section>';
    $('#header-freshness').textContent='데이터 확인 실패';
  }
  async function init(){
    $('#menu-toggle').addEventListener('click',()=>setMenu(!$('#sidebar').classList.contains('open')));
    $('#menu-close').addEventListener('click',()=>setMenu(false));$('#sidebar-backdrop').addEventListener('click',()=>setMenu(false));
    $('#refresh-data').addEventListener('click',()=>refresh(true));
    $('.skip-link').addEventListener('click',e=>{e.preventDefault();$('#route-view').focus();});
    $('#sidebar').addEventListener('keydown',e=>{
      if(!mobile()||!$('#sidebar').classList.contains('open'))return;
      if(e.key==='Escape'){e.preventDefault();setMenu(false);}
      if(e.key==='Tab'){
        const focusables=$$('#sidebar a,#sidebar button').filter(el=>el.offsetParent!==null),first=focusables[0],last=focusables.at(-1);
        if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
        if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
      }
    });
    $$('#sidebar [data-route]').forEach(a=>a.addEventListener('click',()=>setMenu(false)));
    window.addEventListener('hashchange',()=>{if(!state.config)return;parseRoute();render();setMenu(false,false);window.scrollTo({top:0});$('#page-title').setAttribute('tabindex','-1');$('#page-title').focus({preventScroll:true});});
    let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(!mobile())setMenu(false,false);else if(!$('#sidebar').classList.contains('open'))setMenu(false,false);if(state.config)renderCharts();},120);});
    setMenu(false,false);
    try{await loadData();try{state.favorites=new Set(JSON.parse(localStorage.getItem('nextfest-favorites-v2')||'[]').filter(id=>game(id)).slice(0,2000));state.compare=JSON.parse(localStorage.getItem('nextfest-compare-v2')||'[]').filter(id=>game(id)).slice(0,4);}catch{}parseRoute();render();}
    catch{showLoadError();}
    setInterval(()=>{if(state.config)preserveFocus(render);},60000);
    setInterval(()=>refresh(false),300000);
  }
  init();
})();

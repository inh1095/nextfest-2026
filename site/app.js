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
  const state={config:null,data:null,page:'overview',game:null,range:'all',metric:'demo_ccu',interval:null,event:null,eventPinned:false,chartEvent:null,eventGame:'all',kind:'all',search:'',from:'',to:'',refreshError:false,refreshing:false,loadedAt:null};
  const valid=s=>s.status==='ok'&&typeof s.value==='number'&&Number.isFinite(s.value)&&s.value>=0&&time(s.observed_at)!==null;
  const sortSamples=rows=>rows.slice().sort((a,b)=>(time(a.observed_at)||0)-(time(b.observed_at)||0));
  const game=id=>state.config.games.find(g=>g.id===id);
  const metric=(id,key)=>game(id)?.metrics?.find(m=>m.key===key)||{};
  const archived=()=>state.data.collection_status==='archived'||(time(state.config.collection.stops_at)!==null&&Date.now()>=time(state.config.collection.stops_at));
  const gapLimit=()=>((state.config.collection.interval_minutes||20)*2+30)*60000;
  const isStale=s=>s&&!archived()&&Date.now()-time(s.observed_at)>gapLimit();
  const allRows=(id,key)=>sortSamples(state.data.samples.filter(s=>(!id||s.game_id===id)&&(!key||s.metric===key)));
  const eventTime=e=>time(e.occurred_at)??time(e.published_at);
  const exactEvent=e=>['minute','hour'].includes(e.time_precision);
  function bounds(id=null){
    const times=allRows(id).map(s=>time(s.observed_at)).filter(t=>t!==null);
    const last=times.length?Math.max(...times):Date.now();
    if(state.range!=='all'){
      const end=archived()?Math.max(last,time(state.config.collection.stops_at)||last):Math.max(last,Date.now());
      return [end-Number(state.range)*3600000,end];
    }
    const first=times.length?Math.min(...times):last-6*3600000;
    if(first===last)return [first-3600000,last+3600000];
    const pad=Math.max((last-first)*.02,60000);return [first-pad,last+pad];
  }
  function rows(id,key){const [start,end]=bounds();return allRows(id,key).filter(s=>time(s.observed_at)!==null&&time(s.observed_at)>=start&&time(s.observed_at)<=end);}
  const validRows=(id,key)=>rows(id,key).filter(valid);
  function intervals(id,key='demo_ccu',positiveOnly=false){
    const data=rows(id,key),result=[];
    for(let i=1;i<data.length;i++){
      const a=data[i-1],b=data[i],elapsed=time(b.observed_at)-time(a.observed_at);
      if(!valid(a)||!valid(b)||elapsed<=0||elapsed>gapLimit())continue;
      const delta=b.value-a.value;
      if(positiveOnly&&delta<=0)continue;
      result.push({id:`${id}|${key}|${a.observed_at}|${b.observed_at}`,game_id:id,metric:key,a,b,delta,percent:a.value===0?null:delta/a.value*100,elapsed});
    }
    return result;
  }
  function latestChange(id){
    const data=rows(id,'demo_ccu');
    if(data.length<2)return null;
    const a=data.at(-2),b=data.at(-1),elapsed=time(b.observed_at)-time(a.observed_at);
    if(!valid(a)||!valid(b)||elapsed<=0||elapsed>gapLimit())return null;
    return {a,b,delta:b.value-a.value};
  }
  function periodEvents(){const [start,end]=bounds();return state.data.events.filter(e=>state.range==='all'||(eventTime(e)!==null&&eventTime(e)>=start&&eventTime(e)<=end)).sort((a,b)=>(eventTime(b)||0)-(eventTime(a)||0));}
  function eventDate(e){const t=eventTime(e);return t===null?'시점 미확인':exactEvent(e)?date(iso(t)):dateOnly(iso(t))+' · 시각 미확인';}
  function periodLabel(){return state.range==='all'?'전체 관측 기간':`최근 ${state.range}시간${archived()?' · 수집 종료 기준':''}`;}
  const badge=(text,cls='')=>`<span class="badge ${cls}">${esc(text)}</span>`;
  function sampleState(id,key){
    const attempts=allRows(id,key),last=attempts.at(-1),lastOk=attempts.filter(valid).at(-1);
    if(last?.status==='error')return {text:'수집 오류',cls:'error',last,lastOk};
    if(last?.status==='unavailable'||(!lastOk&&metric(id,key).availability==='unavailable'))return {text:'미확보',cls:'',last,lastOk};
    if(isStale(lastOk))return {text:'관측 지연',cls:'warn',last,lastOk};
    if(lastOk)return {text:archived()?'보관':'정상',cls:archived()?'':'ok',last,lastOk};
    return {text:'수집 대기',cls:'',last,lastOk};
  }
  function routeHref(page,extra={}){const p=new URLSearchParams({game:state.game||'',range:state.range,...extra});return `#/${page}?${p.toString()}`;}
  function syncQuery(){const params=new URLSearchParams({game:state.game,range:state.range});if(state.page==='analysis')params.set('metric',state.metric);if(state.page==='events'&&state.event)params.set('event',state.event);history.replaceState(null,'',`#/${state.page}?${params.toString()}`);}
  function parseRoute(){
    const [path,query='']=location.hash.replace(/^#\/?/,'').split('?');
    state.page=Object.hasOwn(routes,path)?path:'overview';
    const params=new URLSearchParams(query);
    state.eventPinned=false;
    if(params.has('game')&&game(params.get('game')))state.game=params.get('game');
    if(['all','6','24'].includes(params.get('range')))state.range=params.get('range');
    if(['demo_ccu','followers'].includes(params.get('metric')))state.metric=params.get('metric');
    if(params.has('event')&&state.data.events.some(e=>e.id===params.get('event'))){state.event=params.get('event');state.eventPinned=true;}
  }
  function renderChrome(){
    const now=Date.now(),ev=state.config.event;
    const ended=time(ev.ends_at)!==null&&now>=time(ev.ends_at),upcoming=time(ev.starts_at)!==null&&now<time(ev.starts_at);
    const status=$('#festival-status');status.textContent=ended?'행사 종료':upcoming?'행사 시작 전':'행사 진행 중';status.className=`badge ${ended?'':upcoming?'info':'ok'}`;
    const last=allRows().filter(valid).at(-1);
    $('#header-freshness').textContent=`최근 관측 ${last?date(last.observed_at)+' KST':'없음'}`;
    $('#sidebar-collection').textContent=archived()?'수집 종료 · 기록 보관':state.data.collection_status==='pending'?'첫 관측 대기':'관측 수집 중';
    $('#sidebar-collection').classList.toggle('archived',archived());
    $('#sidebar-interval').textContent=`목표: 지표 ${state.config.collection.interval_minutes}분 · 공지 ${state.config.collection.news_interval_minutes}분`;
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
    $$('[data-range]').forEach(b=>b.addEventListener('click',()=>{state.range=b.dataset.range;state.interval=null;syncQuery();render();}));
  }
  const gameCell=g=>`<div class="game-cell">${g.header_image&&safeUrl(g.header_image,true)?`<img class="game-thumb" src="${esc(safeUrl(g.header_image,true))}" alt="" loading="lazy">`:''}<div><a class="game-name" href="${esc(routeHref('analysis',{game:g.id}))}">${esc(g.name)}</a><p class="game-app">데모 ${esc(g.demo_app_id)}</p></div></div>`;
  const valueCell=s=>s?`<span class="number-main mono">${number(s.value)}</span><span class="subline">${date(s.observed_at)}</span>`:'<span class="text-muted">미확보</span>';
  const deltaHtml=d=>d===null?'—':`<span class="mono ${d>0?'text-positive':d<0?'text-negative':''}">${signed(d)}</span>`;
  function latestTable(){return `<div class="table-scroll"><table class="table" id="latest-changes-table"><thead><tr><th>게임</th><th>비교 시각 (KST)</th><th class="numeric">직전 → 최근</th><th class="numeric">변화</th></tr></thead><tbody>${state.config.games.map(g=>{const c=latestChange(g.id);return `<tr><td><a href="${esc(routeHref('analysis',{game:g.id}))}">${esc(g.name)}</a></td><td class="mono">${c?`${date(c.a.observed_at)}<span class="subline">→ ${date(c.b.observed_at)}</span>`:'비교 가능한 인접 관측 없음'}</td><td class="numeric">${c?`${number(c.a.value)} → ${number(c.b.value)}`:'—'}</td><td class="numeric">${deltaHtml(c?.delta??null)}</td></tr>`;}).join('')}</tbody></table></div>`;}
  function renderOverview(){
    const gs=state.config.games,validCount=validRows(null,'demo_ccu').length,growthCount=gs.reduce((n,g)=>n+intervals(g.id,'demo_ccu',true).length,0),events=periodEvents();
    return `<div class="kpi-grid" id="overview-kpis">${[['추적 게임',gs.length,'개','공식 데모 관측 대상'],['유효 동접 관측',validCount,'회',periodLabel()],['동접 증가 구간',growthCount,'건','연속된 관측 사이의 양의 증가'],['공개 사건',events.length,'건',state.range==='all'?'확보한 전체 사건 이력':periodLabel()]].map(([l,n,u,d])=>`<article class="kpi-card"><div class="kpi-top">${l}<span class="kpi-indicator"></span></div><p class="kpi-value">${number(n)}<span>${u}</span></p><p class="kpi-foot">${esc(d)}</p></article>`).join('')}</div>
      <section class="card"><div class="card-header"><h2>게임별 현황 <span>${esc(periodLabel())}</span></h2><a href="${esc(routeHref('compare'))}">비교 보기 →</a></div><div class="table-scroll"><table class="table" id="games-summary-table"><thead><tr><th>게임</th><th class="numeric">최근 동접 (명)</th><th class="numeric">관측 최고 (명)</th><th class="numeric">유효 관측</th><th>팔로워</th><th>수집 상태</th><th></th></tr></thead><tbody>${gs.map(g=>{const s=validRows(g.id,'demo_ccu'),last=s.at(-1),f=validRows(g.id,'followers').at(-1),status=sampleState(g.id,'demo_ccu');return `<tr><td>${gameCell(g)}</td><td class="numeric">${valueCell(last)}</td><td class="numeric mono">${s.length?number(Math.max(...s.map(x=>x.value))):'—'}</td><td class="numeric mono">${number(s.length)}회</td><td>${f?number(f.value)+'명':badge('미확보')}</td><td>${badge(status.text,status.cls)}</td><td><a class="table-action" href="${esc(routeHref('analysis',{game:g.id}))}">분석 →</a></td></tr>`;}).join('')}</tbody></table></div><p class="table-note">최근 동접은 선택 기간의 마지막 유효 관측입니다. 모든 시각은 KST입니다.</p></section>
      <div class="two-column"><section class="card"><div class="card-header"><h2>최근 동접 변화</h2><span class="text-muted">단위: 명</span></div>${latestTable()}<p class="table-note">마지막 두 관측을 비교합니다. 오류·미확보·긴 공백이 포함되면 계산하지 않습니다.</p></section><section class="card"><div class="card-header"><h2>최근 공개 사건</h2><a href="${esc(routeHref('events'))}">전체 보기 →</a></div>${events.length?`<ul class="event-short-list">${events.slice(0,5).map(e=>`<li><a href="${esc(routeHref('events',{event:e.id}))}"><span class="event-short-title">${esc(e.title)}</span><span class="event-short-meta"><span>${esc(game(e.game_id)?.name||e.game_id)}</span><time>${esc(eventDate(e))}</time>${badge(kinds[e.kind]||'소식')}</span></a></li>`).join('')}</ul>`:'<p class="compact-empty">선택 기간에 확보된 공개 사건이 없습니다.</p>'}</section></div>`;
  }
  function renderCompare(){return `<section class="card"><div class="card-header"><h2>게임별 지표 비교</h2><span class="text-muted">${esc(periodLabel())} · KST</span></div><div class="table-scroll"><table class="table" id="comparison-table"><thead><tr><th>게임</th><th class="numeric">최근 동접</th><th class="numeric">관측 최고</th><th class="numeric">첫 관측 → 마지막</th><th class="numeric">변화</th><th class="numeric">유효 관측</th><th>실제 관측 범위</th><th>본편 팔로워</th></tr></thead><tbody>${state.config.games.map(g=>{const s=validRows(g.id,'demo_ccu'),first=s[0],last=s.at(-1),f=validRows(g.id,'followers').at(-1);return `<tr><td>${gameCell(g)}</td><td class="numeric">${valueCell(last)}</td><td class="numeric mono">${s.length?number(Math.max(...s.map(x=>x.value)))+'명':'—'}</td><td class="numeric mono">${s.length>1?`${number(first.value)} → ${number(last.value)}`:'계산 불가'}</td><td class="numeric">${deltaHtml(s.length>1?last.value-first.value:null)}</td><td class="numeric mono">${number(s.length)}회</td><td class="mono">${first?`${date(first.observed_at)}<span class="subline">→ ${date(last.observed_at)}</span>`:'미확보'}</td><td>${f?`${number(f.value)}명`:`${badge('미확보')}<span class="subline">검증된 수집원 없음</span>`}</td></tr>`;}).join('')}</tbody></table></div><p class="table-note">동접 단위: 명. 첫 관측 → 마지막 변화는 기간 전체의 차이이며 중간 공백을 포함할 수 있습니다.</p></section><section class="card chart-card"><div class="card-header"><h2>데모 동시접속자 추이</h2><span class="text-muted">공통 시간축 · 공통 눈금</span></div><div class="chart-legend">${state.config.games.map((g,i)=>`<span><i class="legend-dot" style="background:${i?'#01a88d':'#528df8'}"></i>${esc(g.name)}</span>`).join('')}</div><div id="comparison-chart" class="chart-container"></div><p class="chart-help">단일 관측은 점으로 표시합니다. 관측 공백과 수집 실패 구간은 연결하지 않습니다.</p></section>`;}
  function gameOptions(selected,all=false){return `${all?'<option value="all">모든 게임</option>':''}${state.config.games.map(g=>`<option value="${esc(g.id)}" ${selected===g.id?'selected':''}>${esc(g.name)}</option>`).join('')}`;}
  function renderAnalysis(){
    const g=game(state.game),definition=metric(state.game,state.metric),s=validRows(state.game,state.metric),last=s.at(-1),allIntervals=intervals(state.game,state.metric,true).sort((a,b)=>b.delta-a.delta||time(b.b.observed_at)-time(a.b.observed_at));
    if(!allIntervals.some(i=>i.id===state.interval))state.interval=allIntervals[0]?.id||null;
    const toolbar=`<div class="analysis-toolbar"><div class="field"><label for="game-select">게임</label><select id="game-select">${gameOptions(state.game)}</select></div><div class="field"><label for="metric-select">지표</label><select id="metric-select"><option value="demo_ccu" ${state.metric==='demo_ccu'?'selected':''}>데모 동시접속자</option><option value="followers" ${state.metric==='followers'?'selected':''}>본편 팔로워${metric(state.game,'followers').availability==='unavailable'?' · 미확보':''}</option></select></div><div class="toolbar-links">${link(g.demo_url,'데모 상점')}${link(definition.source_url,'지표 출처')}</div></div>`;
    if(state.metric==='followers'&&!allRows(state.game,'followers').some(valid))return toolbar+`<section class="card" id="metric-unavailable"><div class="metric-unavailable">${badge('미확보')}<div><h2>본편 팔로워 데이터를 확보하지 못했습니다.</h2><p>${esc(definition.unavailable_reason||'팔로워로 검증된 공개 수집원이 없습니다.')}</p><a href="${esc(routeHref('collection'))}">수집 상태와 범위 확인 →</a></div></div></section>`+rawTable();
    const status=sampleState(state.game,state.metric);
    return toolbar+`<div class="analysis-layout"><div class="analysis-main"><section class="card chart-card"><div class="card-header"><div><h2>${esc(metricNames[state.metric])}</h2><p>${esc(g.name)} · ${esc(periodLabel())}</p></div>${badge(status.text,status.cls)}</div><div class="chart-stats"><div class="chart-stat"><span>마지막 유효 관측</span><strong>${last?number(last.value):'—'}<small>${last?'명':'미확보'}</small></strong></div><div class="chart-stat"><span>관측 최고</span><strong>${s.length?number(Math.max(...s.map(x=>x.value))):'—'}<small>명</small></strong></div><div class="chart-stat"><span>유효 관측</span><strong>${number(s.length)}<small>회</small></strong></div><div class="chart-stat note">${last?`관측 ${date(last.observed_at)} KST`:'선택 기간에 관측 없음'}<br>${s.length===1?'기준선 수집 중 · 추세 판단 불가':'단위: 명 · 시간: KST'}</div></div><div id="analysis-chart" class="chart-container"></div><p class="chart-help">${s.length===1?'단일 관측은 점으로 표시합니다. 다음 관측이 확보되면 변화를 비교합니다.':`오류·미확보 및 ${number(gapLimit()/60000)}분 초과 공백은 선을 잇지 않습니다.`}</p></section><section class="card" id="intervals-panel"><div class="card-header"><h2>관측 증가 구간 <span>${number(allIntervals.length)}건</span></h2><span class="text-muted">증가량 순</span></div><div class="table-scroll"><table class="table" id="intervals-table"><thead><tr><th>구간 (KST)</th><th class="numeric">시작 → 끝</th><th class="numeric">증가 (명)</th><th class="numeric">증가율</th><th class="numeric">간격</th></tr></thead><tbody>${allIntervals.length?allIntervals.map(i=>`<tr class="${i.id===state.interval?'selected-row':''}"><td><button class="row-button mono" type="button" data-interval-id="${esc(i.id)}" aria-pressed="${i.id===state.interval}">${date(i.a.observed_at)}<span class="subline">→ ${date(i.b.observed_at)}</span></button></td><td class="numeric">${number(i.a.value)} → ${number(i.b.value)}</td><td class="numeric text-positive">+${number(i.delta)}</td><td class="numeric">${i.percent===null?'—':'+'+number(i.percent)+'%'}</td><td class="numeric">${number(i.elapsed/60000)}분</td></tr>`).join(''):`<tr><td colspan="5" class="table-empty">${s.length<2?'비교 가능한 관측이 부족합니다. 증가 구간을 계산할 수 없습니다.':'연속된 유효 관측 사이에서 양의 증가가 확인되지 않았습니다.'}</td></tr>`}</tbody></table></div><p class="table-note">행을 선택하면 차트의 해당 구간과 전후 공개 사건을 확인할 수 있습니다. 기준값이 0이면 증가율은 계산하지 않습니다.</p></section></div><aside id="interval-detail" class="side-panel" aria-live="polite">${intervalDetail(allIntervals.find(i=>i.id===state.interval))}</aside></div>${rawTable()}`;
  }
  function intervalDetail(interval){
    if(!interval)return `<div class="card-header"><h2>구간 상세</h2></div><div class="card-body"><p class="detail-empty">증가 구간이 확보되면 행을 선택해 관련 소식과 검토 근거를 확인할 수 있습니다.</p><p class="detail-footer">사건의 시간적 근접성만으로 증가 원인을 확정하지 않습니다.</p></div>`;
    const a=time(interval.a.observed_at),b=time(interval.b.observed_at);
    const events=state.data.events.filter(e=>e.game_id===state.game&&exactEvent(e)&&eventTime(e)!==null&&eventTime(e)>=a-6*3600000&&eventTime(e)<=b+3600000).sort((x,y)=>Math.abs(eventTime(x)-b)-Math.abs(eventTime(y)-b)).slice(0,3);
    const reviews=state.data.analyses.filter(r=>r.game_id===state.game&&time(r.from)!==null&&time(r.to)!==null&&time(r.from)<=a&&time(r.to)>=b&&time(r.reviewed_at)>=b);
    const selected=state.data.events.find(e=>e.id===state.chartEvent&&events.some(x=>x.id===e.id));
    return `<div class="card-header"><h2>선택 구간 상세</h2>${badge('인과 미확인')}</div><div class="card-body"><p class="small-heading">${esc(metricNames[interval.metric])}</p><p class="detail-value">+${number(interval.delta)}<small>명 · ${interval.percent===null?'증가율 —':'+'+number(interval.percent)+'%'}</small></p><p class="detail-period">${date(interval.a.observed_at)}<br>→ ${date(interval.b.observed_at)} KST</p><p class="detail-copy">${number(interval.a.value)}명 → ${number(interval.b.value)}명 · ${number(interval.elapsed/60000)}분 간격</p><section class="detail-section"><h4>구간 전후 공개 소식</h4><p class="detail-empty">구간 시작 6시간 전 ~ 종료 1시간 후</p>${events.length?events.map(e=>{const relation=eventTime(e)<a?'선행':eventTime(e)>b?'후행':'구간 내';return `<button type="button" class="related-event" data-related-event="${esc(e.id)}" aria-pressed="${state.chartEvent===e.id}"><span>${date(iso(eventTime(e)))} · ${relation}</span>${esc(e.title)}</button>`;}).join(''):'<p class="detail-copy">수집한 자료에서 인접 소식 미확인</p>'}<p class="detail-footer">세부 시각이 확인된 사건만 표시합니다. 후행 사건은 구간 증가의 선행 원인으로 해석하지 않습니다.</p></section>${selected?`<section class="detail-section"><h4>${esc(selected.title)}</h4><p class="detail-copy">${esc(selected.summary||'원문을 확인해 주세요.')}</p><p class="detail-footer">${eventTime(selected)<bounds()[0]?'차트 시간 범위 이전의 사건입니다.':eventTime(selected)>bounds()[1]?'차트 시간 범위 이후의 사건입니다.':'차트의 점선은 선택한 사건의 시점입니다.'}</p>${link(selected.source_url,'원문 확인','button source-button')}<a class="button source-button" href="${esc(routeHref('events',{event:selected.id}))}">이벤트 상세</a></section>`:''}<section class="detail-section"><h4>검토 근거</h4>${reviews.length?reviews.map(reviewHtml).join(''):'<p class="detail-empty">이 구간을 포함하는 검토 기록이 없습니다. 공개 소식은 설명 후보이며 원인이 확인된 것은 아닙니다.</p>'}</section></div>`;
  }
  function rawTable(){const data=rows(state.game,state.metric).slice().reverse();return `<section class="card raw-table"><div class="card-header"><h2>관측 원자료 <span>${number(data.length)}건</span></h2><button id="download-csv" type="button" class="button" ${data.length?'':'disabled'}>CSV 내려받기 ↓</button></div><div class="table-scroll"><table class="table" id="samples-table"><thead><tr><th>관측 시각 (KST)</th><th>지표</th><th class="numeric">값 (명)</th><th>상태</th><th>출처</th></tr></thead><tbody>${data.length?data.map(s=>`<tr><td class="mono">${date(s.observed_at,true)}</td><td>${esc(metricNames[s.metric]||s.metric)}</td><td class="numeric">${valid(s)?number(s.value):'—'}</td><td>${badge(valid(s)?'확보':s.status==='error'?'수집 오류':'미확보',valid(s)?'ok':s.status==='error'?'error':'')}</td><td>${link(s.source_url,'출처')}</td></tr>`).join(''):'<tr><td colspan="5" class="table-empty">선택 기간에 수집된 기록이 없습니다.</td></tr>'}</tbody></table></div></section>`;}
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
    const outside=selected&&!events.some(e=>e.id===selected.id);
    return `<div class="filter-bar"><div class="field"><label for="events-game">게임</label><select id="events-game">${gameOptions(state.eventGame,true)}</select></div><div class="field"><label for="events-kind">종류</label><select id="events-kind"><option value="all">모든 종류</option>${Object.entries(kinds).map(([k,l])=>`<option value="${k}" ${state.kind===k?'selected':''}>${l}</option>`).join('')}</select></div><div class="field"><label for="events-search">검색</label><input id="events-search" type="search" placeholder="제목 또는 내용 검색" value="${esc(state.search)}"></div><div class="field"><label for="events-from">시작</label><input id="events-from" type="date" value="${esc(state.from)}" aria-label="시작 날짜 KST"></div><div class="field"><label for="events-to">종료</label><input id="events-to" type="date" value="${esc(state.to)}" aria-label="종료 날짜 KST"></div></div>${outside?'<p id="events-pinned-notice" class="inline-alert info">직접 선택한 사건이 현재 목록 필터 범위 밖에 있습니다. 해당 사건의 상세를 표시하며 기간과 필터는 유지합니다.</p>':''}<div class="events-layout"><section class="card events-table"><div class="card-header"><h2>공개 사건 <span id="events-count">${number(events.length)}건</span></h2><span class="text-muted">최신순 · KST</span></div><div class="table-scroll"><table class="table" id="events-table"><thead><tr><th>시각 (KST)</th><th>종류</th><th>게임 / 제목</th></tr></thead><tbody>${events.length?events.map(e=>`<tr class="${e.id===state.event?'selected-row':''}"><td class="mono">${esc(eventDate(e))}<span class="subline">${e.occurred_at?'발생 시각':'공개 시각'}</span></td><td>${badge(kinds[e.kind]||'소식')}</td><td class="event-title-cell"><button type="button" class="row-button" data-event-id="${esc(e.id)}" aria-pressed="${e.id===state.event}">${esc(e.title)}</button><span class="subline">${esc(game(e.game_id)?.name||e.game_id)}</span></td></tr>`).join(''):'<tr><td colspan="3" class="table-empty">조건에 맞는 공개 사건이 없습니다. 기록이 없다는 것은 활동이 없었다는 뜻이 아닙니다.</td></tr>'}</tbody></table></div></section><aside id="event-detail" class="side-panel event-detail-panel" aria-live="polite">${eventDetail(selected)}</aside></div>`;
  }
  function eventDetail(e){
    if(!e)return '<div class="card-header"><h2>이벤트 상세</h2></div><div class="card-body"><p class="detail-empty">목록에서 사건을 선택하면 내용과 원문 출처를 확인할 수 있습니다.</p></div>';
    const reviews=state.data.analyses.filter(r=>r.game_id===e.game_id&&(r.evidence_event_ids||[]).includes(e.id));
    const observed=allRows(e.game_id).map(s=>time(s.observed_at)).filter(t=>t!==null),before=eventTime(e)!==null&&observed.length&&eventTime(e)<Math.min(...observed);
    const news=newsState(e.game_id);
    return `<div class="card-header"><h2>이벤트 상세</h2></div><div class="card-body"><div class="detail-meta">${badge(kinds[e.kind]||'소식')}${badge(game(e.game_id)?.name||e.game_id,'info')}</div><h3>${esc(e.title)}</h3><p class="detail-date">${e.occurred_at?'발생':'공개'} ${esc(eventDate(e))}${exactEvent(e)?' KST':''}${e.time_precision==='hour'?' · 시간 단위 근거':''}</p><p class="detail-copy">${esc(e.summary||'요약이 없습니다. 원문에서 확인할 수 있습니다.')}</p>${link(e.source_url,'원문 확인','button primary source-button')}<p class="detail-footer">출처 확인 ${date(e.verified_at,true)} KST<br>${before?'최초 관측 이전의 사건입니다. 해당 시점의 지표는 확보되지 않았습니다.':!exactEvent(e)?'세부 시각이 확인되지 않아 선후 관계를 확정할 수 없습니다.':'시간적 근접성이 인과관계를 의미하지 않습니다.'}</p>${reviews.length?`<section class="detail-section"><h4>관련 관측 검토</h4>${reviews.map(reviewHtml).join('')}</section>`:''}<section class="detail-section"><p class="detail-footer">${esc(game(e.game_id)?.name||e.game_id)} 공지 확인<br>${news.at?date(news.at,true)+' KST':'기록 없음'} · ${esc(news.text)}</p></section></div>`;
  }
  function newsState(id){const n=state.data.news_status?.[id]||{},at=n.last_attempt_at||(typeof state.data.news_last_attempt_at==='string'?state.data.news_last_attempt_at:state.data.news_last_attempt_at?.[id]),delay=at&&!archived()&&Date.now()-time(at)>((state.config.collection.news_interval_minutes||180)*2+30)*60000;return {at,text:n.status==='error'?'수집 오류':delay?'확인 지연':n.status==='ok'?'확인 완료':'상태 미확인',cls:n.status==='error'?'error':delay?'warn':n.status==='ok'?'ok':'',errors:n.error_codes||[]};}
  function renderCollection(){
    const c=state.config.collection,e=state.config.event;
    return `<section class="card"><div class="card-header"><h2>지표 수집 상태</h2>${badge(archived()?'수집 종료':'수집 진행',archived()?'':'ok')}</div><div class="table-scroll"><table class="table" id="collection-table"><thead><tr><th>게임 / 지표</th><th>상태</th><th>마지막 정상 관측 (KST)</th><th class="numeric">값</th><th>마지막 시도 (KST)</th><th>오류 / 미확보 사유</th><th>출처</th></tr></thead><tbody>${state.config.games.flatMap(g=>['demo_ccu','followers'].map(key=>{const s=sampleState(g.id,key),m=metric(g.id,key);return `<tr><td>${esc(g.name)}<span class="subline">${metricNames[key]}</span></td><td>${badge(s.text,s.cls)}</td><td class="mono">${s.lastOk?date(s.lastOk.observed_at,true):'없음'}</td><td class="numeric">${s.lastOk?number(s.lastOk.value)+'명':'—'}</td><td class="mono">${s.last?date(s.last.observed_at,true):state.data.last_attempt_at?date(state.data.last_attempt_at,true):'없음'}</td><td><span>${esc(s.last?.error_code||'—')}</span>${m.unavailable_reason?`<span class="subline" style="white-space:normal;min-width:220px;max-width:380px">${esc(m.unavailable_reason)}</span>`:''}</td><td>${link(m.source_url||s.last?.source_url,'출처')}</td></tr>`;})).join('')}</tbody></table></div><p class="table-note">관측 지연: 마지막 정상값 이후 ${number(gapLimit()/60000)}분 초과. 종료된 수집은 지연으로 분류하지 않습니다.</p></section><section class="card"><div class="card-header"><h2>공식 공지 확인 상태</h2><span class="text-muted">게임별 확인</span></div><div class="table-scroll"><table class="table" id="news-status-table"><thead><tr><th>게임</th><th>상태</th><th>최근 시도 (KST)</th><th>오류</th></tr></thead><tbody>${state.config.games.map(g=>{const n=newsState(g.id);return `<tr><td>${esc(g.name)}</td><td>${badge(n.text,n.cls)}</td><td class="mono">${n.at?date(n.at,true):'없음'}</td><td>${esc(n.errors.join(', ')||'—')}</td></tr>`;}).join('')}</tbody></table></div><p class="table-note">공지 지연 기준: ${(c.news_interval_minutes||180)*2+30}분. 수집에 실패해도 이전 사건 기록은 유지됩니다.</p></section><div class="settings-grid"><section class="card"><div class="card-header"><h2>수집 설정</h2></div><div class="card-body"><dl class="definition-list"><div><dt>행사 기간</dt><dd class="mono">${date(e.starts_at,true)}<br>~ ${date(e.ends_at,true)} KST</dd></div><div><dt>공식 일정</dt><dd>${link(e.verification_url,'Steam 일정 확인')}</dd></div><div><dt>지표 목표 주기</dt><dd>${c.interval_minutes}분</dd></div><div><dt>공지 목표 주기</dt><dd>${c.news_interval_minutes}분</dd></div><div><dt>수집 종료</dt><dd class="mono">${date(c.stops_at,true)} KST</dd></div><div><dt>기록 파일 갱신</dt><dd class="mono">${date(state.data.generated_at,true)} KST</dd></div><div><dt>화면 새로고침</dt><dd>5분마다 JSON 재조회<br>수집 작업을 새로 실행하지 않습니다.</dd></div></dl><p class="detail-footer">GitHub Actions 예약은 지연될 수 있으며 실제 관측 시각을 기준으로 표시합니다.</p></div></section><section class="card"><div class="card-header"><h2>데이터 범위와 해석</h2></div><div class="card-body"><ul class="principles"><li><h3>플레이와 관심은 다른 지표입니다</h3><p>데모 동접은 해당 시점에 데모를 실행 중인 플레이어 수입니다. 본편 팔로워·위시리스트·구매 수로 환산하지 않습니다.</p></li><li><h3>첫 관측 이전의 과거값은 없습니다</h3><p>최고 동접은 확보된 관측 중 최고입니다. 관측 사이의 실제 최고값은 더 높을 수 있습니다. 장르·규모가 다른 게임의 성패를 점수로 판정하지 않습니다.</p></li><li><h3>미확보와 0은 구분합니다</h3><p>정상 응답의 0은 실제 순간 관측값입니다. 오류·미확보는 값 없음으로 표시하며, 그 지점을 가로질러 선이나 인접 증가를 계산하지 않습니다.</p></li><li><h3>공개 사건은 인과관계의 증명이 아닙니다</h3><p>관련 소식은 구간 시작 6시간 전~종료 1시간 후에서 찾습니다. 날짜만 알려진 사건은 시각 비교에서 제외하고, 검토는 표시된 시점의 자료에만 적용합니다.</p></li></ul>${state.data.notices?.length?`<ul class="notice-list">${state.data.notices.map(n=>typeof n==='string'?n:n.message||n.text||'').filter(Boolean).map(n=>`<li>${esc(n)}</li>`).join('')}</ul>`:''}</div></section></div><section class="card"><div class="card-header"><h2>게임 선정 및 행사 참가 근거</h2></div><div class="card-body evidence-grid">${state.config.games.map(g=>`<article><h3>${esc(g.name)}</h3><p>${esc(g.selection_reason||'선정 근거 확인 중')}</p>${g.participation?.evidence_excerpt?`<blockquote>${esc(g.participation.evidence_excerpt)}</blockquote>`:''}${link(g.participation?.source_url,'참가 근거')}<p class="detail-footer">확인 ${date(g.participation?.verified_at,true)} KST</p></article>`).join('')}</div></section>`;
  }
  function drawChart(container,series,selected=null,selectedEvent=null){
    if(!container)return;
    const width=Math.max(280,Math.round(container.clientWidth-((innerWidth<=720)?16:32))),height=innerWidth<=720?240:290;
    const L=48,R=16,T=26,B=43,[start,end]=bounds();
    const all=series.flatMap(s=>s.data.filter(valid));
    if(!all.length){container.innerHTML='<div class="empty-chart">선택 기간에 유효한 관측값이 없습니다.</div>';return;}
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
        if(segment.length&&time(sample.observed_at)-time(segment.at(-1).observed_at)>gapLimit()){segments.push(segment);segment=[];}
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
    if(state.page==='compare')drawChart($('#comparison-chart'),state.config.games.map((g,i)=>({label:g.name,color:i?'#01a88d':'#528df8',data:rows(g.id,'demo_ccu')})));
    if(state.page==='analysis'&&$('#analysis-chart'))drawChart($('#analysis-chart'),[{label:game(state.game).name,color:'#528df8',data:rows(state.game,state.metric)}],intervals(state.game,state.metric,true).find(i=>i.id===state.interval),state.data.events.find(e=>e.id===state.chartEvent));
  }
  function preserveFocus(fn){
    const active=document.activeElement,id=active?.id,interval=active?.dataset?.intervalId,event=active?.dataset?.eventId,related=active?.dataset?.relatedEvent,range=active?.dataset?.range;
    const start=active instanceof HTMLInputElement&&['search','text'].includes(active.type)?active.selectionStart:null;
    const end=start!==null?active.selectionEnd:null;
    fn();
    const target=id?document.getElementById(id):interval?document.querySelector(`[data-interval-id="${CSS.escape(interval)}"]`):event?document.querySelector(`[data-event-id="${CSS.escape(event)}"]`):related?document.querySelector(`[data-related-event="${CSS.escape(related)}"]`):range?document.querySelector(`[data-range="${CSS.escape(range)}"]`):null;
    if(target){target.focus({preventScroll:true});if(start!==null&&target instanceof HTMLInputElement)target.setSelectionRange(start,end);}
  }
  function csvDownload(){
    const data=rows(state.game,state.metric),cell=value=>`"${String(value??'').replace(/"/g,'""')}"`;
    const matrix=[['game_id','metric','observed_at_utc','observed_at_kst','value','status','source_url','error_code'],...data.map(s=>[s.game_id,s.metric,s.observed_at,date(s.observed_at,true)+' KST',valid(s)?s.value:'',s.status,s.source_url,s.error_code])];
    const blob=new Blob(['\uFEFF'+matrix.map(r=>r.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8;'}),address=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=address;a.download=`nextfest-${state.game}-${state.metric}-${state.range}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(address),1000);
  }
  function bindPage(){
    $('#game-select')?.addEventListener('change',e=>{state.game=e.target.value;state.interval=null;state.chartEvent=null;syncQuery();preserveFocus(render);});
    $('#metric-select')?.addEventListener('change',e=>{state.metric=e.target.value;state.interval=null;state.chartEvent=null;syncQuery();preserveFocus(render);});
    $('#download-csv')?.addEventListener('click',csvDownload);
    $$('[data-interval-id]').forEach(b=>b.addEventListener('click',()=>{state.interval=b.dataset.intervalId;state.chartEvent=null;preserveFocus(render);if(innerWidth<980)$('#interval-detail').scrollIntoView({block:'start',behavior:'smooth'});}));
    $$('[data-related-event]').forEach(b=>b.addEventListener('click',()=>{state.chartEvent=b.dataset.relatedEvent;preserveFocus(render);}));
    $$('[data-event-id]').forEach(b=>b.addEventListener('click',()=>{state.event=b.dataset.eventId;state.eventPinned=false;syncQuery();preserveFocus(render);if(innerWidth<980)$('#event-detail').scrollIntoView({block:'start',behavior:'smooth'});}));
    [['events-game','eventGame'],['events-kind','kind'],['events-from','from'],['events-to','to']].forEach(([id,key])=>$('#'+id)?.addEventListener('change',e=>{state[key]=e.target.value;state.event=null;state.eventPinned=false;preserveFocus(render);}));
    $('#events-search')?.addEventListener('input',e=>{state.search=e.target.value;state.event=null;state.eventPinned=false;preserveFocus(render);});
  }
  function render(){
    if(!state.config)return;
    renderChrome();
    const renderers={overview:renderOverview,compare:renderCompare,analysis:renderAnalysis,events:renderEvents,collection:renderCollection};
    $('#route-view').dataset.page=state.page;
    $('#route-view').innerHTML=renderers[state.page]();
    bindPage();renderCharts();
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
  async function loadData(cacheBust=false){
    const suffix=cacheBust?`?v=${Date.now()}`:'';
    const responses=await Promise.all([fetch('./data/config.json'+suffix,{cache:'no-cache'}),fetch('./data/observations.json'+suffix,{cache:'no-cache'})]);
    if(responses.some(r=>!r.ok))throw new Error('unavailable');
    const [config,data]=await Promise.all(responses.map(r=>r.json()));
    if(!Array.isArray(config.games)||!config.games.length||!config.collection||!config.event||!Array.isArray(data.samples))throw new Error('invalid schema');
    data.events=Array.isArray(data.events)?data.events:[];data.analyses=Array.isArray(data.analyses)?data.analyses:[];
    state.config=config;state.data=data;state.refreshError=false;state.loadedAt=new Date().toISOString();
    if(!config.games.some(g=>g.id===state.game))state.game=config.games[0].id;
  }
  async function refresh(){
    if(state.refreshing)return;
    const hadData=!!state.config;
    state.refreshing=true;if(state.config)renderChrome();else $('#refresh-data').disabled=true;
    try{await loadData(true);if(!hadData)parseRoute();preserveFocus(render);}
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
    $('#refresh-data').addEventListener('click',refresh);
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
    try{await loadData();parseRoute();render();}
    catch{showLoadError();}
    setInterval(()=>{if(state.config)preserveFocus(render);},60000);
    setInterval(refresh,300000);
  }
  init();
})();

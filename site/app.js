'use strict';
(() => {
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const time = value => {const n=Date.parse(value);return Number.isFinite(n)?n:null;};
  const number = n => new Intl.NumberFormat('ko-KR',{maximumFractionDigits:1}).format(n);
  const duration=minutes=>typeof minutes==='number'&&Number.isFinite(minutes)&&minutes>=0?(minutes>=60?`${Math.floor(minutes/60)}시간${minutes%60?' '+number(minutes%60)+'분':''}`:number(minutes)+'분'):'미확보';
  const signed = n => `${n>0?'+':''}${number(n)}`;
  const safeUrl = (value,relative=false) => {try{const u=relative?new URL(value,location.href):new URL(value);return /^https?:$/.test(u.protocol)?u.href:'';}catch{return '';}};
  const link = (href,label,cls='') => safeUrl(href)?`<a href="${esc(safeUrl(href))}" target="_blank" rel="noopener noreferrer" class="${esc(cls)}">${esc(label)} ↗</a>`:'';
  const date = (value,full=false) => {
    if(time(value)===null)return '시각 미확인';
    const p=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value)).map(x=>[x.type,x.value]));
    return `${full?p.year+'.':''}${p.month}.${p.day} ${p.hour}:${p.minute}`;
  };
  const observationDate=value=>`${date(value,true)}:${String(new Date(value).getUTCSeconds()).padStart(2,'0')}`;
  const dateOnly=value=>date(value,true).split(' ')[0];
  const iso=t=>new Date(t).toISOString();
  const metricNames={demo_ccu:'데모 동시접속자',followers:'본편 팔로워',review_count:'Steam 상점 리뷰',review_positive_percent:'상점 리뷰 긍정률',price_final:'본편 가격',wishlists:'위시리스트(찜) · 공개 근거'};
  const kinds={announcement:'발표',update:'업데이트',video:'영상',livestream:'라이브 방송',demo_release:'데모 공개'};
  const routes={overview:['게임 통계','위시리스트(찜) 발표, 동접 변화와 최근 소식을 확인합니다.'],compare:['게임','전체 참가작의 위시리스트(찜) 발표·동접 변화·공식 소식을 비교합니다.'],analysis:['게임 분석','위시리스트(찜)와 실제 관측 지표·공식 소식을 함께 확인합니다.'],events:['소식','공개 발표·업데이트·영상의 시점과 원문을 확인합니다.'],collection:['수집','데이터 갱신 상태와 수집 범위를 확인합니다.']};
  const state={config:null,data:null,page:'overview',game:null,range:'all',metric:'wishlists',interval:null,event:null,eventPinned:false,chartEvent:null,eventGame:'all',kind:'all',search:'',from:'',to:'',refreshError:false,refreshing:false,loadedAt:null,catalog:null,summary:null,gameMap:new Map(),summaryMap:new Map(),seedGames:new Map(),gameContext:new Map(),details:new Map(),detailLoading:new Map(),detailErrors:new Map(),catalogQuery:'',catalogStatus:'all',catalogTag:'all',catalogSort:'current',catalogDir:'desc',catalogPage:1,pageSize:25,compare:[],favorites:new Set(),favoritesOnly:false,eventPage:1,samplePage:1,intervalPage:1,collectionPage:1,collectionQuery:'',collectionStatus:'all',tags:[],generation:0,focusTo:null,compareView:'wishlists',wishFilter:'all',expandedGame:null,ledgerSort:'reviewed',ledgerDir:'desc',eventNavigation:null,intervalNavigation:null};
  const profileKeys=['followers','review_count','review_positive_percent','price_final'];
  const profileSpecs={followers:{label:'본편 팔로워',unit:'명'},review_count:{label:'Steam 상점 리뷰',unit:'건'},review_positive_percent:{label:'상점 리뷰 긍정률',unit:'%'},price_final:{label:'본편 가격',unit:'통화'}};
  const profileSummary=(id,key)=>summaryGame(id).metrics?.[key]||{};
  const profileGap=(id,key)=>(profileSummary(id,key).target_interval_minutes>0?(profileSummary(id,key).target_interval_minutes*2+30)*60000:0);
  const profileScope=(key,context={})=>JSON.stringify(['app_id','app_scope','country','language','review_scope','currency','divisor','package_id'].map(field=>context[field]??null));
  const profileValid=(sample,key)=>valid(sample)&&(key!=='price_final'||(/^[A-Z]{3}$/.test(sample.context?.currency||'')&&Number.isFinite(sample.context?.divisor)&&sample.context.divisor>0))&&(key!=='review_positive_percent'||sample.value<=100);
  function profileLatest(id,key){const s=profileSummary(id,key);return typeof s.current==='number'&&s.last_ok_at?{value:s.current,observed_at:s.last_ok_at,context:s.context||{},status:'ok',source_url:s.source_url}:null;}
  function profileValue(key,value,context={}){
    if(typeof value!=='number'||!Number.isFinite(value)||value<0)return '미확보';
    if(key==='price_final'){
      if(!/^[A-Z]{3}$/.test(context.currency||'')||!Number.isFinite(context.divisor)||context.divisor<=0)return '통화 정보 미확보';
      const formatted=new Intl.NumberFormat('ko-KR',{style:'currency',currency:context.currency}).format(value/context.divisor);
      return context.is_free===true&&value===0?'무료 ('+formatted+')':formatted;
    }
    return number(value)+(profileSpecs[key]?.unit||'');
  }
  function profileState(id,key){
    const s=profileSummary(id,key),latest=profileLatest(id,key),reason={price_not_announced:'가격 미발표',price_not_offered:'판매 가격 미제공',single_game_price_unverified:'단일 게임 가격 미확인',price_currency_unverified:'통화 미확인',store_item_unavailable:'상점 자료 미제공',review_summary_missing:'상점 리뷰 미제공',verified_source_unavailable:'검증 출처 미확보'}[s.last_error_code];
    if(s.status==='error')return '수집 오류'+(latest?' · 이전 정상값':'');
    if(s.status==='conflict')return '출처 불일치';
    if(s.last_error_code==='no_reviews')return '리뷰 없음 · 비율 미계산';
    if(s.status==='unavailable'||(key==='followers'&&!Object.keys(s).length))return latest?(reason||'현재 미제공')+' · 이전 관측':reason||(key==='followers'?'검증 출처 미확보':'미확보');
    if(s.status==='pending'&&latest)return '조회 대기 · 이전 관측';
    if(!latest)return '첫 관측 대기';
    if(!archived()&&profileGap(id,key)>0&&Date.now()-time(latest.observed_at)>profileGap(id,key))return '관측 지연';
    return archived()?'기록 보관':'관측 확보';
  }
  function profileScopeLabel(key,context={}){
    const app=context.app_id?'본편 App '+context.app_id:'본편';
    if(key==='price_final')return `${app} · ${context.country==='KR'?'한국 상점':context.country||'지역 미확인'} · ${context.currency||'통화 미확인'}${context.purchase_option_name?' · '+context.purchase_option_name:''}`;
    if(key.startsWith('review_'))return `${app} · ${context.review_scope==='store_summary_filtered'?'Steam 상점 집계':'집계 범위 미확인'}`;
    return app+' · 위시리스트(찜)와 다른 지표';
  }
  function profileData(id,key){
    const data=rows(id,key),last=data.filter(s=>profileValid(s,key)).at(-1),scope=last?profileScope(key,last.context):null;
    return {data:data.map(s=>profileValid(s,key)&&profileScope(key,s.context)===scope?s:{...s,status:'unavailable',value:null}),last,scope};
  }
  function profileBounds(data){
    if(state.range!=='all')return [rangeEnd()-Number(state.range)*3600000,rangeEnd()];
    const times=data.filter(s=>time(s.observed_at)!==null).map(s=>time(s.observed_at));
    if(!times.length)return [rangeEnd()-3600000,rangeEnd()];
    const first=Math.min(...times),last=Math.max(...times),padding=first===last?3600000:Math.max((last-first)*.02,60000);return [first-padding,last+padding];
  }
  function profilePanel(id,key,detail=false){
    const s=profileSummary(id,key),{data,last}=profileData(id,key),good=data.filter(valid),latest=last||profileLatest(id,key),context=latest?.context||s.context||{},loaded=!!gameHistory(id);
    if(!detail&&loaded&&!good.length)return `<section class="card profile-panel profile-empty profile-compact" id="profile-panel-${key}"><div class="card-header"><h2>${profileSpecs[key].label}</h2></div><div class="profile-value"><strong>미확보</strong></div><p class="profile-caption">${esc(profileState(id,key))}${profileLatest(id,key)?'<br>선택 기간 밖 · 마지막 정상 관측 '+date(profileLatest(id,key).observed_at,true)+' KST':''}${state.detailErrors.has(id)?' · 상세 갱신 실패':''}</p><div class="profile-actions"><a class="button" href="${esc(routeHref('analysis',{game:id,metric:key}))}">지표 상세 →</a>${s.target_interval_minutes?'<span>목표 '+duration(s.target_interval_minutes)+'</span>':''}</div></section>`;
    return `<section class="card profile-panel${good.length?' has-observations':' profile-empty'}" id="profile-panel-${key}"><div class="card-header"><h2>${profileSpecs[key].label}</h2>${badge(profileState(id,key),s.status==='error'?'warn':'')}</div><div class="profile-value"><strong>${loaded?esc(profileValue(key,last?.value,last?.context)):state.detailErrors.has(id)?'조회 실패':'확인 중'}</strong><span>${last?(s.status==='ok'?'관측 ':'이전 정상 관측 ')+date(last.observed_at,true)+' KST':loaded?'선택 기간의 정상 관측 없음':state.detailErrors.has(id)?'상세 조회 실패':'기록 불러오는 중'}</span></div>${good.length?`<div class="chart-container profile-chart" id="profile-chart-${key}" data-profile-chart="${key}"></div><p class="profile-caption">${number(good.length)}회 관측${good.length===1?' · 단일 관측':''} · ${esc(periodLabel())}${rows(id,key).filter(sample=>profileValid(sample,key)).length>good.length?' · 다른 통화·집계 기준은 원자료에서 확인':''}</p>`:`<p class="compact-empty">${key==='followers'?'검증된 공개 수집원 미확보':s.last_error_code==='no_reviews'?'리뷰가 없어 긍정률을 계산하지 않습니다.':state.detailErrors.has(id)?'상세 기록을 불러오지 못했습니다.':!loaded?'상세 기록을 확인 중입니다.':'표시할 관측값이 없습니다.'}${!last&&profileLatest(id,key)?' 마지막 정상 관측 '+date(profileLatest(id,key).observed_at,true)+' KST':''}</p>`}<p class="profile-caption">${esc(profileScopeLabel(key,context))}${state.detailErrors.has(id)?' · 상세 갱신 실패 · 불러온 기록 표시':''}${key==='review_count'||key==='review_positive_percent'?' · 전체 구매유형 합계와 다를 수 있음':''}</p><div class="profile-actions">${detail?'':`<a class="button" href="${esc(routeHref('analysis',{game:id,metric:key}))}">원자료 · 추이 →</a>`}${link(last?.source_url||game(id).store_url,last?.source_url?'관측 출처':'본편 상점')}${s.target_interval_minutes?' <span>목표 '+duration(s.target_interval_minutes)+'</span>':''}</div></section>`;
  }

  function metricOptions(selected){return [['wishlists','종합 통계'],['demo_ccu','데모 동시접속자'],...profileKeys.map(key=>[key,profileSpecs[key].label])].map(([key,label])=>`<option value="${key}" ${key===selected?'selected':''}>${label}</option>`).join('');}
  function renderProfileAnalysis(){
    const id=state.game,key=state.metric;
    return `<div class="analysis-toolbar"><div class="field"><label for="game-select">게임</label>${gamePicker('game-select',id)}</div><div class="field"><label for="metric-select">지표</label><select id="metric-select">${metricOptions(key)}</select></div></div>`+analysisTabs()+`<p class="profile-window">${state.range==='all'?'전체 관측 기록':`조회 기간 ${date(iso(rangeEnd()-Number(state.range)*3600000),true)} → ${date(iso(rangeEnd()),true)} KST`}</p>`+profilePanel(id,key,true)+rawTable(key);
  }

  const valid=s=>s.status==='ok'&&typeof s.value==='number'&&Number.isFinite(s.value)&&s.value>=0&&time(s.observed_at)!==null;
  const sortSamples=rows=>rows.slice().sort((a,b)=>(time(a.observed_at)||0)-(time(b.observed_at)||0));
  const game=id=>state.gameMap.get(id);
  const summaryGame=id=>state.summaryMap.get(id)||{};
  const rangeSummary=id=>summaryGame(id).ranges?.[state.range]||{valid_count:0,first:null,last:null,peak:null,latest_adjacent:null,max_increase:null,positive_intervals:0};
  const settings=()=>({...state.config.collection,...state.summary.collection});
  const rangeEnd=()=>time(state.summary.window_end)||Date.now();
  const gameHistory=id=>state.details.get(id)?.data||null;
  const metric=(id,key)=>state.seedGames.get(id)?.metrics?.find(m=>m.key===key)||(key==='demo_ccu'?{key,definition:'데모 앱을 실행 중인 Steam 연결 플레이어 수',source_url:game(id)?.demo_app_id?`https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=${game(id).demo_app_id}`:'',availability:game(id)?.demo_app_id?'available':'unavailable',unavailable_reason:'확인된 데모 AppID가 없습니다.'}:{key,definition:'본편의 팔로워 수. 위시리스트(찜)·커뮤니티 회원 수와 구분합니다.',availability:'unavailable',unavailable_reason:'팔로워로 검증된 공개 수집원을 확보하지 못했습니다.',source_url:'https://partner.steamgames.com/doc/marketing/followers'});
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
    if(ccuStopped(id)&&lastOk)return {text:s.status==='error'?'보관 · 최근 수집 오류':'보관',cls:s.status==='error'?'warn':'',last,lastOk};
    if(s.status==='error')return {text:'수집 오류',cls:'error',last,lastOk};
    if(s.status==='unavailable')return {text:'데모 미확보',cls:'',last,lastOk};
    if(s.status==='pending'||!lastOk)return {text:'첫 관측 대기',cls:'',last,lastOk};
    if(isStale(lastOk,id))return {text:'관측 지연',cls:'warn',last,lastOk};
    return {text:archived()?'보관':'정상',cls:archived()?'':'ok',last,lastOk};
  }
  function routeHref(page,extra={}){const p=new URLSearchParams({game:state.game||'',range:state.range,...extra});if(page==='analysis'&&!p.has('metric'))p.set('metric','wishlists');if(page==='compare'&&state.compare.length)p.set('compare',state.compare.join(','));if(page==='compare'&&!p.has('view'))p.set('view','wishlists');if(page==='compare'&&!p.has('sort'))p.set('sort',state.catalogSort);if(page==='compare'&&!p.has('evidence_dir'))p.set('evidence_dir',state.ledgerDir);if(page==='compare'&&!p.has('evidence_sort'))p.set('evidence_sort',state.ledgerSort);if(page==='compare'&&!p.has('evidence'))p.set('evidence',state.wishFilter);return `#/${page}?${p.toString()}`;}
  function syncQuery(){state.intervalNavigation=null;const params=new URLSearchParams({game:state.game,range:state.range});if(state.page==='analysis')params.set('metric',state.metric);if(state.page==='compare'&&state.compare.length)params.set('compare',state.compare.join(','));if(state.page==='compare'){params.set('sort',state.catalogSort);params.set('view',state.compareView);params.set('evidence',state.wishFilter);params.set('evidence_sort',state.ledgerSort);params.set('evidence_dir',state.ledgerDir);}if(state.page==='events'&&state.event)params.set('event',state.event);history.replaceState(null,'',`#/${state.page}?${params.toString()}`);}
  function parseRoute(){
    const [path,query='']=location.hash.replace(/^#\/?/,'').split('?');
    state.page=Object.hasOwn(routes,path)?path:'overview';
    const params=new URLSearchParams(query);
    state.compareView=params.get('view')==='ccu'?'ccu':'wishlists';
    if(['all','reviewed','candidate','missing'].includes(params.get('evidence')))state.wishFilter=params.get('evidence');
    state.metric=['demo_ccu','wishlists',...profileKeys].includes(params.get('metric'))?params.get('metric'):params.has('at')?'demo_ccu':'wishlists';
    if(['reviewed','news','peak','max_increase','name'].includes(params.get('evidence_sort')))state.ledgerSort=params.get('evidence_sort');
    if(['asc','desc'].includes(params.get('evidence_dir')))state.ledgerDir=params.get('evidence_dir');
    state.eventNavigation=null;state.intervalNavigation=null;
    state.eventPinned=false;
    state.focusTo=params.get('at')||null;
    if(params.has('game')&&game(params.get('game')))state.game=params.get('game');
    if(['all','6','24'].includes(params.get('range')))state.range=params.get('range');
    if(['demo_ccu','wishlists',...profileKeys].includes(params.get('metric')))state.metric=params.get('metric');
    if(['current','delta','max_increase','percent','peak','samples','last','name'].includes(params.get('sort')))state.catalogSort=params.get('sort');
    if(params.has('compare'))state.compare=[...new Set(params.get('compare').split(',').filter(id=>game(id)))].slice(0,4);
    if(params.has('event_game')&&(params.get('event_game')==='all'||game(params.get('event_game'))))state.eventGame=params.get('event_game');
    if(params.has('event')&&state.data.events.some(e=>e.id===params.get('event'))){state.event=params.get('event');state.eventPinned=true;state.eventNavigation={id:state.event};}
    if(state.page==='analysis'&&state.metric==='demo_ccu'&&time(state.focusTo)!==null)state.intervalNavigation={game:state.game,at:state.focusTo,range:state.range};
  }
  function renderChrome(){
    const now=Date.now(),ev=state.config.event;
    const ended=time(ev.ends_at)!==null&&now>=time(ev.ends_at),upcoming=time(ev.starts_at)!==null&&now<time(ev.starts_at);
    const status=$('#festival-status');status.textContent=ended?'행사 종료':upcoming?'행사 시작 전':'행사 진행 중';status.className=`badge ${ended?'':upcoming?'info':'ok'}`;
    const lastTime=state.summary.games.reduce((latest,s)=>time(s.last_ok_at)>time(latest)?s.last_ok_at:latest,null);
    const last=lastTime?{observed_at:lastTime}:null;
    $('#header-freshness').textContent=`자료 갱신 ${date(state.summary.generated_at)+' KST'}`;
    $('#sidebar-collection').textContent=archived()?'수집 종료 · 기록 보관':state.data.collection_status==='pending'?'지표·공지 수집 대기':'지표·공식 공지 수집';
    $('#sidebar-collection').classList.toggle('archived',archived());
    $('#sidebar-interval').textContent='공개 발표 검토 · 현재 잔액 미확보';
    $('#footer-updated').textContent=`데이터 갱신 ${date(state.data.generated_at,true)} KST`;
    $('#refresh-data').disabled=state.refreshing;
    $('#refresh-data').setAttribute('aria-busy',String(state.refreshing));
    $$('[data-route]').forEach(a=>{a.href=routeHref(a.dataset.route);if(a.dataset.route===state.page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
    $('#page-title').textContent=routes[state.page][0];$('#page-description').textContent=routes[state.page][1];
    document.title=`${routes[state.page][0]} · Next Fest Monitor`;
    const refresh=$('#refresh-status');
    refresh.hidden=!state.refreshError;
    refresh.textContent=state.refreshError?'최신 데이터를 가져오지 못했습니다. 마지막으로 불러온 기록을 유지합니다. 새로고침으로 다시 시도할 수 있습니다.':'';
    $('#page-actions').innerHTML=['collection','overview'].includes(state.page)||(state.page==='analysis'&&state.metric==='wishlists')||(state.page==='compare'&&state.compareView==='wishlists')?'':`<div class="period-control" role="group" aria-label="관측 기간">${[['6','6시간'],['24','24시간'],['all','전체 기록']].map(([v,l])=>`<button type="button" data-range="${v}" aria-pressed="${state.range===v}">${l}</button>`).join('')}</div>`;
    $$('[data-range]').forEach(b=>b.addEventListener('click',()=>{state.range=b.dataset.range;state.interval=null;state.samplePage=1;state.intervalPage=1;state.catalogPage=1;state.eventPage=1;syncQuery();render();}));
  }
  const gameCell=g=>`<div class="game-cell">${g.header_image&&safeUrl(g.header_image,true)?`<img class="game-thumb" src="${esc(safeUrl(g.header_image,true))}" alt="" loading="lazy">`:''}<div><a class="game-name" title="${esc(g.name)}" href="${esc(routeHref('analysis',{metric:'wishlists',game:g.id,range:'all'}))}">${esc(g.name)}</a><p class="game-app">${g.demo_app_id?'데모 '+esc(g.demo_app_id):'데모 매핑 미확보'}</p></div></div>`;
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
    const latest=c?`${deltaHtml(c.delta)}<span class="subline">${c.percent===null?'증가율 —':signed(c.percent)+'%'} · <span class="nowrap">${number(c.elapsed_minutes)}분</span></span>`:'<span class="text-muted">계산 대기</span>';
    const maxLink=includeMax&&max?.delta>0?`<a class="max-increase-link" data-max-increase="${esc(id)}" href="${esc(routeHref('analysis',{metric:'demo_ccu',game:id,at:max.to}))}" title="기간 최대 증가 구간의 관측과 근거 확인">최대 +${number(max.delta)}명</a><span class="subline max-increase-period">${date(max.from)} → ${date(max.to)}</span>`:'';
    return latest+maxLink;
  }
  function renderOverview(){return wishlistOverview();}
  function renderCompare(){
    if(state.compareView==='wishlists')return wishlistCompare();
    const filtered=catalogMatches(),pagination=pager('catalog',filtered.length,state.pageSize),page=filtered.slice((state.catalogPage-1)*state.pageSize,state.catalogPage*state.pageSize);
    return compareTabs()+ccuPeriodContext(state.compare.length?state.compare:state.config.games.map(g=>g.id),'compare')+`<div class="catalog-filters"><div class="field catalog-search"><label for="catalog-search">검색</label><input id="catalog-search" type="search" value="${esc(state.catalogQuery)}" placeholder="게임 이름 또는 AppID"></div><div class="field"><label for="catalog-status">관측</label><select id="catalog-status">${[['all','전체 상태'],['ready','최근 인접 비교 가능'],['ok','정상 관측'],['pending','첫 관측 대기'],['stale','관측 지연'],['error','수집 오류'],['unavailable','데모 미확보']].map(([v,l])=>`<option value="${v}" ${state.catalogStatus===v?'selected':''}>${l}</option>`).join('')}</select></div><div class="field"><label for="catalog-tag">태그</label><select id="catalog-tag"><option value="all">전체 태그</option>${state.tags.map(t=>`<option value="${esc(t)}" ${state.catalogTag===t?'selected':''}>${esc(t)}</option>`).join('')}</select></div><label class="check-label"><input id="favorites-only" type="checkbox" ${state.favoritesOnly?'checked':''}>관심 게임만</label><div class="field"><label for="catalog-page-size">표시</label><select id="catalog-page-size"><option value="25" ${state.pageSize===25?'selected':''}>25개</option><option value="50" ${state.pageSize===50?'selected':''}>50개</option></select></div></div>
    ${state.compare.length?`<div class="selection-summary"><span>비교 선택 <strong>${state.compare.length} / 4개</strong></span><span class="selection-names">${state.compare.map(id=>esc(game(id).name)).join(' · ')}</span><button type="button" class="button" id="jump-to-comparison">비교 차트 보기 ↓</button></div>`:''}<section class="card catalog-table"><div class="card-header"><h2>참가 게임 <span>${number(filtered.length)} / ${number(state.config.games.length)}개</span></h2><div class="field"><label for="catalog-sort">정렬</label><select id="catalog-sort">${[['current','마지막 관측 동접'],['delta','최근 증가량'],['max_increase','기간 최대 증가'],['percent','최근 증가율'],['peak','관측 최고'],['samples','관측 횟수'],['last','최신 관측'],['name','게임 이름']].map(([v,l])=>`<option value="${v}" ${state.catalogSort===v?'selected':''}>${l}</option>`).join('')}</select><button id="catalog-direction" type="button" class="button" aria-label="정렬 방향">${state.catalogDir==='asc'?'오름차순 ↑':'내림차순 ↓'}</button></div></div><div class="table-scroll"><table class="table" id="comparison-table"><thead><tr><th>관심</th><th>비교</th><th>게임</th><th class="numeric">마지막 관측 동접</th><th class="numeric">최근 변화</th><th class="numeric">관측 최고 (명)</th><th class="numeric">유효 관측</th><th>상태 / 목표 주기</th></tr></thead><tbody>${page.length?page.map(g=>{const r=rangeSummary(g.id),status=sampleState(g.id),selected=state.compare.includes(g.id);return `<tr><td><button class="favorite-button" type="button" data-favorite="${esc(g.id)}" aria-pressed="${state.favorites.has(g.id)}" aria-label="${esc(g.name)} 관심 게임">${state.favorites.has(g.id)?'★':'☆'}</button></td><td><input class="compare-check" type="checkbox" data-compare-game="${esc(g.id)}" aria-label="${esc(g.name)} 비교 선택" ${selected?'checked':''} ${!selected&&state.compare.length>=4?'disabled':''}></td><td>${gameCell(g)}</td><td class="numeric">${r.last?`<span class="number-main mono">${number(r.last.value)}</span><small class="metric-unit">명</small><span class="subline">${date(r.last.observed_at)} KST</span>`:'<span class="text-muted">—</span>'}</td><td class="numeric">${summaryChange(g.id,true)}</td><td class="numeric mono">${r.peak===null||r.peak===undefined?'—':number(r.peak)}</td><td class="numeric mono">${number(r.valid_count||0)}</td><td>${badge(status.text,status.cls)}<span class="subline">목표 ${duration(summaryGame(g.id).target_interval_minutes||settings().target_cycle_minutes)}</span></td></tr>`;}).join(''):'<tr><td colspan="8" class="table-empty">조건에 맞는 게임이 없습니다.</td></tr>'}</tbody></table></div>${pagination}<p class="table-note">기간 기준 ${date(state.summary.window_end,true)} KST. 미확보는 정렬 방향과 관계없이 뒤에 표시합니다. 별표는 이 브라우저의 관심 목록에 저장됩니다.</p></section>
    <section class="card chart-card" id="selected-comparison"><div class="card-header"><h2>선택 게임 비교 <span>${state.compare.length} / 4개</span></h2>${state.compare.length?'<button class="button" id="clear-compare" type="button">선택 해제</button>':''}</div><div class="compare-tray">${state.compare.length?state.compare.map((id,i)=>`<span class="compare-chip"><i class="legend-dot" style="background:${['#528df8','#01a88d','#8b5cf6','#e38d20'][i]}"></i>${esc(game(id).name)}<button type="button" data-remove-compare="${esc(id)}" aria-label="${esc(game(id).name)} 비교 해제">×</button></span>`).join(''):'<p class="text-muted">목록에서 비교할 게임을 선택하세요. 최대 4개.</p>'}</div>${state.compare.length?`<div class="table-scroll"><table class="table" id="selected-comparison-table"><thead><tr><th>게임</th><th class="numeric">첫 관측 → 마지막 (명)</th><th class="numeric">기간 변화 (명)</th><th>실제 관측 범위 (KST)</th><th>기록</th></tr></thead><tbody>${state.compare.map(id=>{const r=rangeSummary(id);return `<tr><td>${esc(game(id).name)}</td><td class="numeric mono">${r.valid_count>=2?`${number(r.first.value)} → ${number(r.last.value)}`:'계산 대기'}</td><td class="numeric">${deltaHtml(r.valid_count>=2?r.last.value-r.first.value:null)}</td><td class="mono">${r.first?`${date(r.first.observed_at)}<span class="subline">→ ${date(r.last.observed_at)}</span>`:'미확보'}</td><td>${historyStatus(id)}</td></tr>`;}).join('')}</tbody></table></div><div id="comparison-chart" class="chart-container"></div><p class="chart-help">선택 게임만 공통 시간축·공통 눈금으로 비교합니다. 대상별 목표 주기를 기준으로 공백을 판단합니다.</p>`:''}</section>`;
  }
  function historyStatus(id){if(!game(id)?.demo_app_id)return badge('데모 미확보');return state.detailLoading.has(id)?badge('기록 로딩 중','info'):state.detailErrors.has(id)?`<button type="button" class="table-action" data-retry-history="${esc(id)}">다시 불러오기</button>`:gameHistory(id)?(gameHistory(id).samples.length?badge('원자료 로드','ok'):badge('첫 관측 대기')):badge('기록 대기');}
  function gamePicker(id,selected,allowAll=false){return `<div class="game-picker"><input id="${id}" type="search" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="${id}-results" autocomplete="off" placeholder="게임 이름 또는 AppID 검색" value="${esc(selected==='all'?'모든 게임':game(selected)?.name||'')}"><div id="${id}-results" class="game-results" role="listbox" hidden></div>${allowAll?'<span class="sr-only">빈 검색어로 모든 게임 선택 가능</span>':''}</div>`;}
  function renderAnalysis(){
    if(state.metric==='wishlists')return wishlistAnalysis();
    if(profileKeys.includes(state.metric))return renderProfileAnalysis();
    const g=game(state.game),definition=metric(state.game,state.metric),s=validRows(state.game,state.metric),last=s.at(-1),allIntervals=intervals(state.game,state.metric,true).sort((a,b)=>b.delta-a.delta||time(b.b.observed_at)-time(a.b.observed_at));
    if(state.focusTo){const focus=allIntervals.find(i=>i.b.observed_at===state.focusTo);if(focus)state.interval=focus.id;}
    if(!allIntervals.some(i=>i.id===state.interval))state.interval=allIntervals[0]?.id||null;
    const toolbar=`<div class="analysis-toolbar"><div class="field"><label for="game-select">게임</label>${gamePicker('game-select',state.game)}</div><div class="field"><label for="metric-select">지표</label><select id="metric-select">${metricOptions(state.metric)}</select></div><div class="toolbar-links">${link(g.demo_url,'데모 상점')}${link(definition.source_url,'지표 출처')}</div></div>`;
    if(state.metric==='demo_ccu'&&!g.demo_app_id)return toolbar+analysisTabs()+`<section class="card" id="metric-unavailable"><div class="metric-unavailable">${badge('데모 미확보')}<div><h2>수집할 데모 AppID를 확인하지 못했습니다.</h2><p>공식 행사 참가 목록에는 포함되어 있으나 데모 연결 정보가 확보되지 않았습니다. 동접을 0명으로 표시하지 않습니다.</p>${link(g.store_url,'본편 상점에서 확인')}<a href="${esc(routeHref('collection'))}">수집 범위 확인 →</a></div></div></section>`;
    if(!gameHistory(state.game)&&state.metric!=='followers')return toolbar+analysisTabs()+`<section class="card"><div class="card-body"><h2 class="loading-title">${esc(g.name)} 관측 기록</h2><p class="detail-footer">${state.detailErrors.has(state.game)?'상세 기록을 불러오지 못했습니다. 요약 데이터는 유지됩니다.':'선택한 게임의 상세 기록을 불러오고 있습니다.'}</p>${historyStatus(state.game)}</div></section>`;
    if(state.metric==='followers'&&!allRows(state.game,'followers').some(valid))return toolbar+analysisTabs()+`<section class="card" id="metric-unavailable"><div class="metric-unavailable">${badge('미확보')}<div><h2>본편 팔로워 데이터를 확보하지 못했습니다.</h2><p>${esc(definition.unavailable_reason||'팔로워로 검증된 공개 수집원이 없습니다.')}</p><a href="${esc(routeHref('collection'))}">수집 상태와 범위 확인 →</a></div></div></section>`+rawTable();
    const status=sampleState(state.game,state.metric);
    const intervalPageSize=mobile()?5:25,intervalPagination=pager('intervals',allIntervals.length,intervalPageSize),intervalPage=allIntervals.slice((state.intervalPage-1)*intervalPageSize,state.intervalPage*intervalPageSize);
    return toolbar+analysisTabs()+(state.detailErrors.has(state.game)?'<p class="inline-alert">상세 기록 갱신에 실패해 이전에 불러온 기록을 표시합니다.</p>':'')+`<div class="analysis-layout"><div class="analysis-main"><section class="card chart-card"><div class="card-header"><div><h2>${esc(metricNames[state.metric])}</h2><p>${esc(g.name)} · ${esc(periodLabel())}</p></div>${badge(status.text,status.cls)}</div><div class="chart-stats"><div class="chart-stat"><span>${state.metric==='demo_ccu'?'마지막 관측 동접':'마지막 관측 팔로워'}</span><strong>${last?number(last.value):'—'}<small>${last?'명':'미확보'}</small></strong></div><div class="chart-stat"><span>관측 최고</span><strong>${s.length?number(Math.max(...s.map(x=>x.value))):'—'}<small>명</small></strong></div><div class="chart-stat"><span>선택 기간 관측</span><strong>${number(s.length)}<small>회</small></strong></div><div class="chart-stat note">${last?`관측 ${date(last.observed_at)} KST`:'선택 기간에 관측 없음'}<br>${s.length===1?'기준선 수집 중 · 추세 판단 불가':'데모 실행 중 · 단위 명 · KST'}</div></div>${state.metric==='demo_ccu'?ccuPeriodContext():''}<div id="analysis-chart" class="chart-container"></div>${state.metric==='demo_ccu'?observationHistoryStrip(state.game,true):''}<p class="chart-help">각 점 = 해당 시각 데모 실행 인원 · ${s.length===1?'단일 관측은 점으로 표시합니다. 다음 관측이 확보되면 변화를 비교합니다.':`오류·미확보 및 ${number(gapLimit()/60000)}분 초과 공백은 선을 잇지 않습니다.`}</p></section><section class="card" id="intervals-panel"><div class="card-header"><h2>관측 증가 구간 <span>${number(allIntervals.length)}건</span></h2><span class="text-muted">증가량 순</span></div><div class="table-scroll"><table class="table" id="intervals-table"><thead><tr><th>구간 (KST)</th><th class="numeric">시작 → 끝 (명)</th><th class="numeric">증가 (명)</th><th class="numeric">증가율</th><th class="numeric">간격</th></tr></thead><tbody>${allIntervals.length?intervalPage.map(i=>`<tr class="${i.id===state.interval?'selected-row':''}"><td><button class="row-button mono" type="button" data-interval-id="${esc(i.id)}" aria-pressed="${i.id===state.interval}">${date(i.a.observed_at)}<span class="subline">→ ${date(i.b.observed_at)}</span></button></td><td class="numeric">${number(i.a.value)} → ${number(i.b.value)}</td><td class="numeric text-positive">+${number(i.delta)}</td><td class="numeric">${i.percent===null?'—':'+'+number(i.percent)+'%'}</td><td class="numeric">${number(i.elapsed/60000)}분</td></tr>`).join(''):`<tr><td colspan="5" class="table-empty">${s.length<2?'비교 가능한 관측이 부족합니다. 증가 구간을 계산할 수 없습니다.':'연속된 유효 관측 사이에서 양의 증가가 확인되지 않았습니다.'}</td></tr>`}</tbody></table></div>${intervalPagination}<p class="table-note">행을 선택하면 차트의 해당 구간과 전후 공식 소식을 확인할 수 있습니다. 기준값이 0이면 증가율은 계산하지 않습니다.</p></section></div><aside id="interval-detail" tabindex="-1" class="side-panel" aria-live="polite">${intervalDetail(allIntervals.find(i=>i.id===state.interval))}</aside></div>${rawTable()}`;
  }
  function intervalDetail(interval){
    if(!interval)return `<div class="card-header"><h2>구간 상세</h2></div><div class="card-body"><p class="detail-empty">증가 구간이 확보되면 행을 선택해 관련 소식과 검토 근거를 확인할 수 있습니다.</p><p class="detail-footer">게시 시점이 가깝다는 이유만으로 증가 원인을 확정하지 않습니다.</p></div>`;
    const a=time(interval.a.observed_at),b=time(interval.b.observed_at);
    const events=state.data.events.filter(e=>e.game_id===state.game&&exactEvent(e)&&eventTime(e)!==null&&eventTime(e)>=a-6*3600000&&eventTime(e)<=b+3600000).sort((x,y)=>Math.abs(eventTime(x)-b)-Math.abs(eventTime(y)-b)).slice(0,3);
    const reviews=(gameHistory(state.game)?.analyses||[]).filter(r=>r.game_id===state.game&&time(r.from)!==null&&time(r.to)!==null&&time(r.from)<=a&&time(r.to)>=b&&time(r.reviewed_at)>=b);
    const selected=state.data.events.find(e=>e.id===state.chartEvent&&events.some(x=>x.id===e.id));
    return `<div class="card-header"><h2>선택 구간 상세</h2>${badge('원인 미확인')}</div><div class="card-body"><p class="small-heading">${esc(metricNames[interval.metric])}</p><p class="detail-value">+${number(interval.delta)}<small>명 · ${interval.percent===null?'증가율 —':'+'+number(interval.percent)+'%'}</small></p><p class="detail-period">${date(interval.a.observed_at)}<br>→ ${date(interval.b.observed_at)} KST</p><p class="detail-copy">${number(interval.a.value)}명 → ${number(interval.b.value)}명 · ${number(interval.elapsed/60000)}분 간격</p><section class="detail-section"><h4>구간 전후 공개 소식</h4><p class="detail-empty">구간 시작 6시간 전 ~ 종료 1시간 후</p>${events.length?events.map(e=>{const relation=eventTime(e)<a?'구간 이전':eventTime(e)>b?'구간 이후':'구간 내';return `<button type="button" class="related-event" data-related-event="${esc(e.id)}" aria-pressed="${state.chartEvent===e.id}"><span>${date(iso(eventTime(e)))} · ${relation}</span>${esc(e.title)}</button>`;}).join(''):'<p class="detail-copy">수집한 자료에서 인접 소식 미확인</p>'}<p class="detail-footer">정확한 시각이 있는 소식만 표시 · 원인 미확인</p></section>${selected?`<section class="detail-section"><h4>${esc(selected.title)}</h4><p class="detail-copy">${esc(selected.summary||'원문을 확인해 주세요.')}</p><p class="detail-footer">${eventTime(selected)<bounds()[0]?'차트 시간 범위 이전의 소식입니다.':eventTime(selected)>bounds()[1]?'차트 시간 범위 이후의 소식입니다.':'차트의 점선은 선택한 소식의 시점입니다.'}</p>${link(selected.source_url,'원문 확인','button source-button')}<a class="button source-button" href="${esc(routeHref('events',{event:selected.id}))}">소식 상세</a></section>`:''}<section class="detail-section"><h4>검토 근거</h4>${reviews.length?reviews.map(reviewHtml).join(''):'<p class="detail-empty">검토 기록 없음 · 증가 원인 미확인</p>'}</section></div>`;
  }
  function rawTable(metricKey=state.metric){const data=rows(state.game,metricKey).slice().reverse(),pagination=pager('samples',data.length),page=data.slice((state.samplePage-1)*25,state.samplePage*25);return `<section class="card raw-table"><div class="card-header"><h2>관측 원자료 <span>${number(data.length)}건</span></h2><button id="download-csv" data-export-metric="${esc(metricKey)}" type="button" class="button" ${data.length?'':'disabled'}>CSV 내려받기 ↓</button></div><div class="table-scroll"><table class="table" id="samples-table"><thead><tr><th>관측 시각 (KST)</th><th>지표</th><th class="numeric">${profileKeys.includes(metricKey)?'값':'값 (명)'}</th><th>상태</th><th>출처</th></tr></thead><tbody>${data.length?page.map(s=>`<tr><td class="mono">${date(s.observed_at,true)}</td><td>${esc(metricNames[s.metric]||s.metric)}</td><td class="numeric">${valid(s)?esc(profileKeys.includes(metricKey)?profileValue(metricKey,s.value,s.context):number(s.value)):'—'}</td><td>${badge(valid(s)?'확보':s.status==='error'?'수집 오류':'미확보',valid(s)?'ok':s.status==='error'?'error':'')}</td><td>${link(s.source_url,'출처')}</td></tr>`).join(''):'<tr><td colspan="5" class="table-empty">선택 기간에 수집된 기록이 없습니다.</td></tr>'}</tbody></table></div>${pagination}</section>`;}
  function reviewHtml(r){
    const label={direct_evidence:'직접 근거 확인',temporal_association:'시간적 연관성 · 원인 미확인',insufficient:'근거 부족'};
    const evidence=(r.evidence_event_ids||[]).map(id=>(gameHistory(r.game_id)?.events||[]).find(e=>e.id===id)||state.data.events.find(e=>e.id===id)).filter(Boolean);
    const samples=(r.evidence_sample_times||[]).map(at=>({at,sample:allRows(r.game_id,'demo_ccu').find(s=>s.observed_at===at&&valid(s))}));
    return `<div class="review-record">${badge(label[r.assessment]||'검토 기록',r.assessment==='insufficient'?'':'info')}<dl class="review-facts"><dt>관측 사실</dt><dd>${esc(r.observation)}</dd><dt>가능한 설명</dt><dd>${esc(r.hypothesis||'확인된 설명이 없습니다.')}</dd><dt>다른 가능한 설명</dt><dd>${(r.alternative_explanations||[]).length?r.alternative_explanations.map(esc).join('<br>'):'별도 검토 기록이 없습니다.'}</dd><dt>검토 대상 기간 (KST)</dt><dd class="mono">${date(r.from,true)}<br>→ ${date(r.to,true)}</dd></dl>${evidence.length?`<div class="review-sources"><h4>대조한 공식 소식</h4>${evidence.map(e=>`<p><a href="${esc(routeHref('events',{game:r.game_id,event:e.id,range:'all'}))}">${esc(e.title)}</a><span>${esc(eventDate(e))}</span>${link(e.source_url,'원문')}</p>`).join('')}</div>`:''}${samples.length?`<div class="review-sources"><h4>근거 관측</h4>${samples.map(({at,sample})=>`<p>${date(at,true)} KST${sample?' · 데모 동접 '+number(sample.value)+'명 · '+link(sample.source_url,'관측 출처'):''}</p>`).join('')}</div>`:''}<p class="detail-footer">검토 ${date(r.reviewed_at,true)} KST<br>표시된 기간에 한한 검토입니다.</p></div>`;
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
    return `<div class="filter-bar"><div class="field"><label for="events-game">게임</label>${gamePicker('events-game',state.eventGame,true)}</div><div class="field"><label for="events-kind">종류</label><select id="events-kind"><option value="all">모든 종류</option>${Object.entries(kinds).map(([k,l])=>`<option value="${k}" ${state.kind===k?'selected':''}>${l}</option>`).join('')}</select></div><div class="field"><label for="events-search">검색</label><input id="events-search" type="search" placeholder="제목 또는 게임 이름 검색" value="${esc(state.search)}"></div><div class="field"><label for="events-from">시작</label><input id="events-from" type="date" value="${esc(state.from)}" aria-label="시작 날짜 KST"></div><div class="field"><label for="events-to">종료</label><input id="events-to" type="date" value="${esc(state.to)}" aria-label="종료 날짜 KST"></div></div>${outside?'<p id="events-pinned-notice" class="inline-alert info">필터 밖에서 선택한 소식의 상세입니다.</p>':''}<div class="events-layout"><section class="card events-table"><div class="card-header"><h2>공식 소식 <span id="events-count">${number(events.length)}건</span></h2><span class="text-muted">최신순 · KST</span></div><div class="table-scroll"><table class="table" id="events-table"><thead><tr><th>시각 (KST)</th><th>종류</th><th>게임 / 제목</th></tr></thead><tbody>${events.length?page.map(e=>`<tr class="${e.id===state.event?'selected-row':''}"><td class="mono">${esc(eventDate(e))}<span class="subline">${e.occurred_at?'발생 시각':'공개 시각'}</span></td><td>${badge(kinds[e.kind]||'소식')}</td><td class="event-title-cell"><button type="button" class="row-button" data-event-id="${esc(e.id)}" aria-pressed="${e.id===state.event}">${esc(e.title)}</button><span class="subline">${esc(game(e.game_id)?.name||e.game_id)}</span></td></tr>`).join(''):'<tr><td colspan="3" class="table-empty">조건에 맞는 공식 소식이 없습니다.</td></tr>'}</tbody></table></div>${pagination}</section><aside id="event-detail" tabindex="-1" class="side-panel event-detail-panel" aria-live="polite">${eventDetail(selected)}</aside></div>`;
  }
  function eventDetail(e){
    if(!e)return '<div class="card-header"><h2>소식 상세</h2></div><div class="card-body"><p class="detail-empty">목록에서 소식을 선택하면 내용과 원문 출처를 확인할 수 있습니다.</p></div>';
    const full=gameHistory(e.game_id)?.events?.find(x=>x.id===e.id);if(full)e=full;
    const reviews=(gameHistory(e.game_id)?.analyses||[]).filter(r=>r.game_id===e.game_id&&(r.evidence_event_ids||[]).includes(e.id));
    const observed=allRows(e.game_id).map(s=>time(s.observed_at)).filter(t=>t!==null),before=eventTime(e)!==null&&observed.length&&eventTime(e)<Math.min(...observed);
    const news=newsState(e.game_id);
    return `<div class="card-header"><h2>소식 상세</h2></div><div class="card-body"><div class="detail-meta">${badge(kinds[e.kind]||'소식')}${badge(game(e.game_id)?.name||e.game_id,'info')}</div><h3>${esc(e.title)}</h3><p class="detail-date">${e.occurred_at?'발생':'공개'} ${esc(eventDate(e))}${exactEvent(e)?' KST':''}${e.time_precision==='hour'?' · 시간 단위 근거':''}</p><p class="detail-copy">${esc(e.summary||(state.detailErrors.has(e.game_id)?'소식 상세를 불러오지 못했습니다. 원문 링크에서 확인할 수 있습니다.':!gameHistory(e.game_id)?'선택한 소식의 본문과 검토 기록을 불러오는 중입니다.':'요약이 없습니다. 원문에서 확인할 수 있습니다.'))}</p>${link(e.source_url,'원문 확인','button primary source-button')}${state.detailErrors.has(e.game_id)?`<button type="button" class="button source-button" data-retry-history="${esc(e.game_id)}">상세 다시 불러오기</button>`:''}<p class="detail-footer">출처 확인 ${date(e.verified_at,true)} KST<br>${before?'최초 관측 이전의 소식입니다. 해당 시점의 지표는 확보되지 않았습니다.':!exactEvent(e)?'세부 시각이 확인되지 않아 선후 관계를 확정할 수 없습니다.':'게시 시점이 가깝다는 이유만으로 증가 원인을 확정할 수 없습니다.'}</p>${reviews.length?`<section class="detail-section"><h4>관련 관측 검토</h4>${reviews.map(reviewHtml).join('')}</section>`:''}<section class="detail-section"><p class="detail-footer">${esc(game(e.game_id)?.name||e.game_id)} 공지 확인<br>${news.at?date(news.at,true)+' KST':'기록 없음'} · ${esc(news.text)}</p></section></div>`;
  }
  function newsState(id){const s=summaryGame(id),at=s.last_news_attempt_at,checkedAt=Object.hasOwn(s,'news_all_checked_at')?s.news_all_checked_at:at,delay=checkedAt&&!archived()&&Date.now()-time(checkedAt)>((settings().news_target_cycle_minutes||800)*2+30)*60000;return {at,checkedAt,text:s.news_status==='pending'?'공지 조회 대기':s.news_status==='error'?'수집 오류':s.news_status==='partial'?'일부 출처 확인':delay?'확인 지연':s.news_status==='ok'?'확인 완료':'상태 미확인',cls:s.news_status==='error'?'error':s.news_status==='partial'||delay?'warn':s.news_status==='ok'?'ok':'',errors:s.news_error_codes||[]};}
  function lastRunPanel(){
    const run=state.summary.last_run;
    if(!run)return '<section class="card last-run-panel" id="last-run-status"><div class="card-header"><h2>마지막 수집 실행</h2></div><p class="compact-empty">현재 요약에 마지막 실행 기록이 없습니다.</p></section>';
    const reasons={request_budget:'요청 예산 소진',daily_budget:'일일 예산 소진',runtime_budget:'실행 시간 제한',source_backoff:'요청 오류 보호',utc_day_boundary:'날짜 경계',event_closed:'행사 종료',interrupted:'중단'};
    const reason=run.pause_reason?(reasons[run.pause_reason]||String(run.pause_reason)):(run.finished_at?'완료':'종료 기록 없음');
    const count=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0?number(value)+'회':'미확보';
    return `<section class="card last-run-panel" id="last-run-status"><div class="card-header"><h2>마지막 수집 실행</h2>${badge(reason,run.pause_reason?'warn':run.finished_at?'ok':'')}</div><div class="run-summary"><span>시작 <strong class="mono">${date(run.started_at,true)}</strong></span><span>종료 <strong class="mono">${run.finished_at?date(run.finished_at,true):'기록 없음'}</strong> KST</span><span>실제 요청 <strong class="mono">${count(run.request_count)}</strong></span><span>CCU <strong class="mono">${count(run.ccu_requests)}</strong></span><span>공지 <strong class="mono">${count(run.news_requests)}</strong></span><span>상점 자료 <strong class="mono">${count(run.metadata_requests)}</strong></span><span>예약량 <strong class="mono">${count(run.reserved_requests)}</strong></span></div><p class="table-note">예약량은 마지막 실행에 할당한 요청 예산입니다. 실제 요청량이나 일일 누적 예약량이 아닙니다.</p></section>`;
  }

  function observationHistory(id,preferLoaded=false){
    const summary=summaryGame(id),range=summary.ranges?.all||{},h=summary.observation_history;
    if(preferLoaded&&gameHistory(id)){
      const samples=allRows(id,'demo_ccu').filter(s=>time(s.observed_at)!==null&&time(s.observed_at)<=rangeEnd()),good=samples.filter(valid);
      return {attempts:samples.length,valid:good.length,errors:samples.filter(s=>s.status==='error').length,first:good[0]?.observed_at,last:good.at(-1)?.observed_at,firstAttempt:samples[0]?.observed_at};
    }
    return {attempts:h?.attempt_count??null,valid:h?.valid_count??range.valid_count??0,errors:h?.error_count??null,first:h?.first_valid_at||range.first?.observed_at,last:summary.last_ok_at||range.last?.observed_at,firstAttempt:h?.first_attempt_at||range.first?.observed_at};
  }
  function observationHistoryStrip(id,preferLoaded=false){
    const h=observationHistory(id,preferLoaded);
    return `<div class="observation-history" ${preferLoaded?'id="analysis-history"':''}><div><strong>전체 누적 기록</strong><span>${h.attempts!==null?number(h.attempts)+'건 저장 · ':''}정상 관측 ${number(h.valid)}회${h.errors?' · 오류 '+number(h.errors)+'건':''}</span></div><div class="history-dates"><span>첫 관측 <time>${h.first?date(h.first,true)+' KST':'없음'}</time></span><span>마지막 <time>${h.last?date(h.last,true)+' KST':'없음'}</time></span></div><p>동접은 순간 인원이며 누적 이용자 수가 아닙니다.</p></div>`;
  }
  function collectionSelectedCard(showPicker=true){
    const g=game(state.game),s=summaryGame(g.id),status=sampleState(g.id),history=s.observation_history;
    return `<section class="card selected-game-history" id="selected-game-history"><div class="card-header"><h2>선택 게임 관측 기록</h2>${badge(status.text,status.cls)}</div><div class="card-body">${showPicker?`<div class="field"><label for="collection-game">게임</label>${gamePicker('collection-game',state.game)}</div>`:''}<div class="last-observation"><div><span>마지막 관측 동접</span><p>${typeof s.current==='number'?`<strong>${number(s.current)}</strong><small>명</small>`:'<strong>미확보</strong>'}</p><span>데모 실행 중인 인원</span></div><div class="last-observation-time"><span>정상 관측 시각</span><time>${s.last_ok_at?date(s.last_ok_at,true)+' KST':'기록 없음'}</time>${s.status==='error'?'<span class="text-negative">최근 수집 실패 · 이전 정상값</span>':''}</div></div>${observationHistoryStrip(g.id)}${history?.median_attempt_interval_minutes!==null&&history?.median_attempt_interval_minutes!==undefined?`<p class="observed-cadence">실제 수집 시도 간격 중앙값 <strong>${duration(history.median_attempt_interval_minutes)}</strong></p>`:''}<div class="history-actions"><a class="button primary" id="open-full-history" href="${esc(routeHref('analysis',{game:g.id,metric:'demo_ccu',range:'all'}))}">전체 기록 추이 →</a><a class="button" href="${esc(wishLink(g.id))}">위시리스트(찜) 공개 발표</a><button class="button" id="open-game-evidence" type="button">참가 근거</button></div></div></section>`;
  }
  function collectionCadence(){
    const c=settings(),s=summaryGame(state.game),interval=s.target_interval_minutes||c.target_cycle_minutes;
    return `<section class="card collection-cadence" id="collection-cadence"><div class="card-header"><h2>갱신 주기</h2><span class="text-muted">목표 주기 · 지연 가능</span></div><dl><div><dt>화면 새로고침</dt><dd>5분<span>저장된 자료를 다시 표시</span></dd></div><div><dt>수집 배치 실행</dt><dd>${duration(c.scheduled_interval_minutes||c.interval_minutes)}<span>매번 전체 게임의 일부 처리</span></dd></div><div><dt>이 게임 동접 관측</dt><dd>약 ${duration(interval)}<span>게임별 순환 수집</span></dd></div><div><dt>위시리스트(찜) 수치 정기 수집</dt><dd>없음<span>공개 발표를 검토한 뒤 추가</span></dd></div></dl><p class="cadence-note">공지 출처 순환 목표 ${duration(c.news_target_cycle_minutes)} · 위시리스트(찜) 잔액 수집 주기가 아닙니다.</p></section>`;
  }
  function renderCollection(){return wishlistOperations();}
  const chartReadings=new Map();
  function drawChart(container,series,selected=null,selectedEvent=null,options={}){
    if(!container)return;
    const width=Math.max(280,Math.round(container.clientWidth-((innerWidth<=900)?16:32))),height=options.height||(innerWidth<=900?240:290);
    const L=options.left||48,R=16,T=26,B=43,[start,end]=options.bounds||bounds(series.map(s=>s.id));
    const all=series.flatMap(s=>s.data.filter(valid)),unit=options.unit||'명',formatValue=options.formatValue||(value=>number(value)+unit);
    if(!all.length){chartReadings.delete(container.id);const loading=series.some(s=>state.detailLoading.has(s.id)),failed=series.some(s=>state.detailErrors.has(s.id));container.innerHTML=`<div class="empty-chart">${loading?'선택한 게임의 상세 관측 기록을 불러오는 중입니다.':failed?'일부 상세 기록을 불러오지 못했습니다. 위 표에서 다시 불러올 수 있습니다.':'선택 기간에 유효한 관측값이 없습니다.'}</div>`;return;}
    const max=Math.max(...all.map(s=>s.value));
    let top=max===0?1:max*1.16;
    const power=Math.pow(10,Math.floor(Math.log10(top))),factor=top/power;
    top=(factor<=1?1:factor<=2?2:factor<=2.5?2.5:factor<=5?5:10)*power;
    if(max===0)top=1;
    if(Number.isFinite(options.maxY))top=options.maxY;
    const x=t=>L+(t-start)/(end-start)*(width-L-R),y=v=>T+(1-v/top)*(height-T-B);
    const points=[],scope=JSON.stringify([state.generation,state.range,series.map(s=>s.id),options.bounds||null,options.context||null]);let out='';
    if(chartReadings.get(container.id)?.scope!==scope)chartReadings.delete(container.id);
    if(selected){const x1=x(time(selected.a.observed_at)),x2=x(time(selected.b.observed_at));out+=`<rect data-selected-interval="true" x="${x1}" y="${T}" width="${Math.max(x2-x1,2)}" height="${height-T-B}" fill="#528df818"/><line x1="${x1}" x2="${x1}" y1="${T}" y2="${height-B}" stroke="#528df850"/><line x1="${x2}" x2="${x2}" y1="${T}" y2="${height-B}" stroke="#528df850"/>`;}
    for(let i=0;i<3;i++){const v=top*i/2,yy=y(v);out+=`<line class="grid" x1="${L}" x2="${width-R}" y1="${yy}" y2="${yy}"/><text x="${L-9}" y="${yy+4}" text-anchor="end">${esc(options.axisFormat?options.axisFormat(v):number(v))}</text>`;}
    out+=`<line class="axis" x1="${L}" x2="${width-R}" y1="${height-B}" y2="${height-B}"/>`;
    const ticks=width<500?2:3;
    for(let i=0;i<ticks;i++){const t=start+(end-start)*i/(ticks-1),xx=x(t);out+=`<text x="${xx}" y="${height-14}" text-anchor="${i===0?'start':i===ticks-1?'end':'middle'}">${date(iso(t))}</text>`;}
    if(selectedEvent&&exactEvent(selectedEvent)&&eventTime(selectedEvent)>=start&&eventTime(selectedEvent)<=end){const xx=x(eventTime(selectedEvent));out+=`<line class="event-line" x1="${xx}" x2="${xx}" y1="${T-5}" y2="${height-B}"/><text x="${Math.min(width-R-10,Math.max(L+30,xx))}" y="${T-12}" text-anchor="middle">선택 소식</text>`;}
    series.forEach(s=>{
      let segment=[],segments=[];
      for(const sample of s.data){
        if(!valid(sample)){if(segment.length)segments.push(segment);segment=[];continue;}
        if(segment.length&&time(sample.observed_at)-time(segment.at(-1).observed_at)>(s.gapLimit??gapLimit(s.id))){segments.push(segment);segment=[];}
        if(segment.length&&options.sampleCompatible&&!options.sampleCompatible(segment.at(-1),sample)){segments.push(segment);segment=[];}
        segment.push(sample);
      }
      if(segment.length)segments.push(segment);
      for(const segment of segments){
        if(segment.length>1)out+=`<polyline class="series" stroke="${s.color}" points="${segment.map(p=>`${x(time(p.observed_at))},${y(p.value)}`).join(' ')}"/>`;
        for(const p of segment){const pointIndex=points.length;points.push({sample:p,label:s.label,x:x(time(p.observed_at)),y:y(p.value)});out+=`<circle data-observation-point="${pointIndex}" cx="${x(time(p.observed_at))}" cy="${y(p.value)}" r="${segment.length===1?4:3}" fill="${s.color}" stroke="white" stroke-width="1.5"><title>${esc(s.label)} · ${observationDate(p.observed_at)} KST · ${esc(formatValue(p.value,p))}</title></circle>`;}
      }
    });
    container.innerHTML=`<svg id="${esc(container.id)}-plot" tabindex="0" class="chart-svg" viewBox="0 0 ${width} ${height}" role="group" aria-label="좌우 방향키로 관측값 확인. ${esc(series.map(s=>s.label).join(', '))} 추이. 유효 관측 ${all.length}회. 단위 ${esc(unit)}, KST. 원자료 표에서 정확한 값을 확인할 수 있습니다."><title>실제 관측값의 변화</title>${out}</svg><output class="chart-reading" aria-live="polite">점을 누르거나 방향키로 관측값 확인</output>`;
    const svg=container.querySelector('svg'),reading=container.querySelector('.chart-reading'),ordered=points.map((p,i)=>i).sort((a,b)=>time(points[a].sample.observed_at)-time(points[b].sample.observed_at)||a-b);
    const show=index=>{const p=points[index];if(!p)return;chartReadings.set(container.id,{scope,index});reading.textContent=`${p.label} · ${observationDate(p.sample.observed_at)} KST · ${formatValue(p.sample.value,p.sample)}`;container.querySelectorAll('[data-observation-point]').forEach(c=>c.classList.toggle('reading-point',Number(c.dataset.observationPoint)===index));};
    const saved=chartReadings.get(container.id);if(saved)show(saved.index);
    svg.addEventListener('click',e=>{const point=svg.createSVGPoint();point.x=e.clientX;point.y=e.clientY;const local=point.matrixTransform(svg.getScreenCTM().inverse());let best=0,distance=Infinity;points.forEach((p,i)=>{const d=(p.x-local.x)**2+(p.y-local.y)**2;if(d<distance){distance=d;best=i;}});show(best);});
    svg.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const current=ordered.indexOf(chartReadings.get(container.id)?.index),position=e.key==='Home'?0:e.key==='End'?ordered.length-1:current<0?(e.key==='ArrowLeft'?ordered.length-1:0):Math.max(0,Math.min(ordered.length-1,current+(e.key==='ArrowRight'?1:-1)));show(ordered[position]);});
  }
  const publicationDay=value=>/^\d{4}-\d{2}-\d{2}$/.test(value||'')?value:time(value)!==null?dateOnly(value).replaceAll('.','-'):null;
  const dayNumber=day=>Date.parse(day+'T00:00:00Z')/86400000;
  function drawPublicationChart(container,records){
    if(!container)return;
    const groups=new Map();for(const d of records){const day=publicationDay(d.published_at);if(!day)continue;if(!groups.has(day))groups.set(day,[]);groups.get(day).push(d);}
    const days=[...groups.keys()].sort();
    if(!days.length){container.innerHTML='<p class="compact-empty">발표 날짜를 확인한 수치 기록이 없습니다.</p>';return;}
    let selected=wish.selectedDays.get(state.game);if(!groups.has(selected))selected=days.at(-1);wish.selectedDays.set(state.game,selected);
    const width=Math.max(270,Math.round(container.clientWidth-28)),left=24,right=24,first=dayNumber(days[0]),last=dayNumber(days.at(-1)),x=day=>first===last?width/2:left+(dayNumber(day)-first)/(last-first)*(width-left-right);
    const choose=day=>{wish.selectedDays.set(state.game,day);drawPublicationChart(container,records);container.querySelector('[data-publication-day]')?.focus({preventScroll:true});};
    container.innerHTML=`<svg class="publication-svg" viewBox="0 0 ${width} 108" role="img" aria-label="위시리스트(찜) 수치 기록 ${records.length}건의 발표 날짜. 같은 날짜는 한 표식으로 묶습니다. 위시리스트(찜) 잔액 추이가 아닙니다."><line x1="${left}" x2="${width-right}" y1="53" y2="53" stroke="#dfe6ef"/>${days.map(day=>`<g tabindex="0" role="button" data-publication-point="${esc(day)}" aria-label="${esc(day)} 수치 기록 ${groups.get(day).length}건 선택"><rect x="${x(day)-22}" y="25" width="44" height="50" fill="transparent"/><circle cx="${x(day)}" cy="53" r="${day===selected?7:5}" fill="${day===selected?'#245db7':'#528df8'}" stroke="white" stroke-width="2"/>${groups.get(day).length>1?`<text x="${x(day)}" y="30" text-anchor="middle">${groups.get(day).length}건</text>`:''}<title>${esc(day)} · 수치 기록 ${groups.get(day).length}건</title></g>`).join('')}<text x="${left}" y="92">${esc(days[0].replaceAll('-','.'))}</text>${days.length>1?`<text x="${width-right}" y="92" text-anchor="end">${esc(days.at(-1).replaceAll('-','.'))}</text>`:''}</svg><div class="publication-picker"><label for="publication-day">발표일</label><select id="publication-day" data-publication-day>${days.map(day=>`<option value="${esc(day)}" ${day===selected?'selected':''}>${esc(day.replaceAll('-','.'))} · 수치 기록 ${groups.get(day).length}건</option>`).join('')}</select></div><ul class="publication-selection">${groups.get(selected).map(d=>`<li>${records.length===1?'':`<strong>${esc(wishClaim(d))}</strong><p>${esc(wishMeaning(d))}</p>`}<span>${esc(wishScope(d))} · ${wishDate(d.published_at)}${d.as_of?` · 수치 기준 ${wishDate(d.as_of)}`:''}</span>${link(d.source_url,'원문')}</li>`).join('')}</ul>`;
    container.querySelector('[data-publication-day]').addEventListener('change',e=>choose(e.target.value));
    container.querySelectorAll('[data-publication-point]').forEach(node=>{node.addEventListener('click',()=>choose(node.dataset.publicationPoint));node.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(node.dataset.publicationPoint);}});});
  }
  function drawNewsChart(container,events){
    if(!container)return;
    const groups=new Map();let unknown=0;
    for(const e of events){const day=publicationDay(e.published_at);if(!day){unknown++;continue;}if(!groups.has(day))groups.set(day,{news:0,video:0});groups.get(day)[['video','livestream'].includes(e.kind)?'video':'news']++;}
    const days=[...groups.keys()].sort();if(!days.length){container.innerHTML='<p class="compact-empty">게시일을 확인한 소식이 없습니다.</p>';return;}
    const width=Math.max(270,Math.round(container.clientWidth-28)),L=28,R=14,T=18,B=34,H=155,first=dayNumber(days[0]),last=dayNumber(days.at(-1)),span=Math.max(1,last-first+1),max=Math.max(...[...groups.values()].map(g=>g.news+g.video)),area=H-T-B,bar=Math.max(1,Math.min(30,(width-L-R)/span*.7)),x=day=>L+(dayNumber(day)-first+.5)/span*(width-L-R),height=n=>n/max*area;
    container.innerHTML=`<svg class="news-svg" viewBox="0 0 ${width} ${H}" role="img" aria-label="보유 공식 소식의 게시일별 건수. 게시일 확인 ${events.length-unknown}건. 전체 활동량이 아닙니다."><text x="${L-7}" y="${T+4}" text-anchor="end">${max}</text><text x="${L-7}" y="${H-B+4}" text-anchor="end">0</text><line x1="${L}" x2="${width-R}" y1="${H-B}" y2="${H-B}" stroke="#dfe6ef"/>${days.map(day=>{const g=groups.get(day),xx=x(day)-bar/2;return `<g data-news-day="${esc(day)}"><title>${esc(day)} · 소식 ${g.news}건 · 영상·방송 ${g.video}건</title>${g.news?`<rect x="${xx}" y="${H-B-height(g.news)}" width="${bar}" height="${height(g.news)}" fill="#528df8"/>`:''}${g.video?`<rect x="${xx}" y="${H-B-height(g.news+g.video)}" width="${bar}" height="${height(g.video)}" fill="#01a88d"/>`:''}</g>`;}).join('')}<text x="${L}" y="${H-9}">${esc(days[0].replaceAll('-','.'))}</text>${days.length>1?`<text x="${width-R}" y="${H-9}" text-anchor="end">${esc(days.at(-1).replaceAll('-','.'))}</text>`:''}</svg><p class="mini-chart-legend"><span>소식 ${events.filter(e=>!['video','livestream'].includes(e.kind)).length}건</span><span>영상·방송 ${events.filter(e=>['video','livestream'].includes(e.kind)).length}건</span>${unknown?`<span>게시일 미확인 ${unknown}건</span>`:''}</p>`;
  }
  function renderCharts(){
    $$('[data-profile-chart]').forEach(container=>{const key=container.dataset.profileChart,{data,last,scope}=profileData(state.game,key),context=last?.context||{};drawChart(container,[{id:state.game,label:profileSpecs[key].label,color:'#456e88',data,gapLimit:profileGap(state.game,key)}],null,null,{height:220,left:key==='price_final'?78:48,bounds:profileBounds(data),unit:key==='price_final'?context.currency:profileSpecs[key].unit,maxY:key==='review_positive_percent'?100:null,context:key+'|'+scope,formatValue:(value,sample)=>profileValue(key,value,sample?.context||context),axisFormat:key==='price_final'?value=>number(value/context.divisor):null,sampleCompatible:(a,b)=>profileScope(key,a.context)===profileScope(key,b.context)});});
    const preview=$('#catalog-preview-chart');if(preview){const id=preview.dataset.previewGame,data=allRows(id,'demo_ccu').filter(s=>time(s.observed_at)!==null&&time(s.observed_at)<=rangeEnd()),times=data.map(s=>time(s.observed_at)),first=times.length?Math.min(...times):rangeEnd()-3600000,last=times.length?Math.max(...times):rangeEnd(),pad=Math.max((last-first)*.02,first===last?3600000:60000);drawChart(preview,[{id,label:game(id).name+' 데모 동접',color:'#456e88',data}],null,null,{height:210,bounds:[first-pad,last+pad]});}

    if(state.page==='compare'&&state.compare.length)drawChart($('#comparison-chart'),state.compare.map((id,i)=>({id,label:game(id).name,color:['#528df8','#01a88d','#8b5cf6','#e38d20'][i],data:rows(id,'demo_ccu')})));
    if(state.page==='analysis'&&$('#analysis-chart'))drawChart($('#analysis-chart'),[{id:state.game,label:game(state.game).name,color:'#528df8',data:rows(state.game,state.metric)}],intervals(state.game,state.metric,true).find(i=>i.id===state.interval),state.data.events.find(e=>e.id===state.chartEvent));
    if(state.page==='analysis'&&state.metric==='wishlists'){
      drawChart($('#game-ccu-chart'),[{id:state.game,label:game(state.game).name+' 데모 동접',color:'#528df8',data:rows(state.game,'demo_ccu')}]);
      drawPublicationChart($('#game-publication-chart'),wishRows('disclosures',state.game));
      drawNewsChart($('#game-news-chart'),gameNews());
    }
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
  function csvDownload(metricKey=state.metric){
    const data=rows(state.game,metricKey),cell=value=>`"${String(value??'').replace(/"/g,'""')}"`;
    const matrix=[['game_id','metric','observed_at_utc','observed_at_kst','value','status','source_url','error_code','context_json'],...data.map(s=>[s.game_id,s.metric,s.observed_at,date(s.observed_at,true)+' KST',valid(s)?s.value:'',s.status,s.source_url,s.error_code,s.context?JSON.stringify(s.context):''])];
    const blob=new Blob(['\uFEFF'+matrix.map(r=>r.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8;'}),address=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=address;a.download=`nextfest-${state.game}-${metricKey}-${state.range}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(address),1000);
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
    $$('[data-overview-section]').forEach(button=>button.addEventListener('click',()=>document.getElementById(button.dataset.overviewSection)?.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'})));
    bindWishlist();bindPicker('game-select');bindPicker('events-game',true);bindPicker('collection-game');
    $('#metric-select')?.addEventListener('change',e=>{state.metric=e.target.value;state.interval=null;state.chartEvent=null;state.samplePage=1;syncQuery();preserveFocus(render);});
    $('#download-csv')?.addEventListener('click',e=>csvDownload(e.currentTarget.dataset.exportMetric||state.metric));
    $('#download-overview-csv')?.addEventListener('click',()=>csvDownload('demo_ccu'));
    $$('[data-game-range]').forEach(b=>b.addEventListener('click',()=>{state.range=b.dataset.gameRange;state.samplePage=1;syncQuery();preserveFocus(render);}));
    $$('[data-interval-id]').forEach(b=>b.addEventListener('click',()=>{state.interval=b.dataset.intervalId;state.focusTo=null;state.intervalNavigation=null;state.chartEvent=null;preserveFocus(render);if(innerWidth<980)$('#interval-detail').scrollIntoView({block:'start',behavior:'smooth'});}));
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
    $('#open-game-evidence')?.addEventListener('click',()=>{const href=safeUrl(game(state.game)?.participation?.source_url);if(href)window.open(href,'_blank','noopener,noreferrer');});
    $('#collection-status')?.addEventListener('change',e=>{state.collectionStatus=e.target.value;state.collectionPage=1;preserveFocus(render);});
    $$('[data-show-evidence]').forEach(b=>b.addEventListener('click',()=>{state.game=b.dataset.showEvidence;syncQuery();render();$('#selected-game-history').scrollIntoView({block:'start',behavior:'smooth'});}));
    $$('[data-game-section]').forEach(button=>button.addEventListener('click',()=>document.getElementById(button.dataset.gameSection)?.scrollIntoView({block:'start',behavior:'smooth'})));
    $$('[data-retry-history]').forEach(b=>b.addEventListener('click',()=>loadHistory(b.dataset.retryHistory,true)));
  }
  function activeHistoryIds(){
    if(state.page==='analysis'&&state.metric==='wishlists')return [state.game];
    if(state.page==='compare'&&state.compareView==='wishlists')return state.expandedGame?[state.expandedGame]:[];
    if(state.page==='analysis')return [state.game];
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

  const wish={data:null,loading:false,error:false,attemptedAt:-Infinity,inputs:new Map(),open:new Set(),selectedDays:new Map()};
  const wishlistActive=()=>['overview','collection'].includes(state.page)||(state.page==='analysis'&&state.metric==='wishlists')||(state.page==='compare'&&state.compareView==='wishlists');
  const wishLink=id=>routeHref('analysis',{game:id,metric:'wishlists',range:'all'});
  const wishRows=(key,id=null)=>(wish.data?.[key]||[]).filter(r=>!id||r.game_id===id);
  const wishNumber=n=>Number.isSafeInteger(n)&&n>=0;
  const wishDate=value=>/^\d{4}-\d{2}-\d{2}$/.test(value||'')?String(value).replaceAll('-','.')+' · 시각 미확인':date(value,true)+' KST';
  function wishValue(d){if(!wishNumber(d.value))return '수치 미확보';const v=number(d.value)+'건';return d.operator==='gt'?v+' 초과':d.operator==='gte'?v+' 이상':d.operator==='approx'?'약 '+v:v;}
  const disclosureKind=d=>d.kind==='period_additions'?'기간 추가':d.stock_definition==='balance'?'위시리스트(찜) 잔액 발표':d.stock_definition==='lifetime_adds'?'누적 추가 발표':d.kind==='milestone_lower_bound'?'달성 발표':'공개 발표';
  const dayWishClaim=d=>d.stock_definition==='unspecified'&&d.period_text==='1일'&&/in (?:just )?a day/i.test(d.quote||'');
  function wishClaim(d){
    const value=wishValue(d);
    if(d.kind==='period_additions'||d.stock_definition==='period_adds')return `위시리스트(찜) ${value} 추가`;
    if(d.stock_definition==='balance')return `위시리스트(찜) 잔액 ${value}`;
    if(d.stock_definition==='lifetime_adds')return `누적 위시리스트(찜) 추가 ${value}`;
    if(dayWishClaim(d))return `하루 만에 위시리스트(찜) ${value}`;
    return `위시리스트(찜) ${value}${d.kind==='milestone_lower_bound'?' 달성':' 발표'}`;
  }
  function wishMeaning(d){
    if(d.kind==='period_additions'||d.stock_definition==='period_adds')return '개발사 발표 · 기간 중 추가량';
    if(d.stock_definition==='balance')return '개발사 발표 · 발표된 기준일의 잔액';
    if(d.stock_definition==='lifetime_adds')return '개발사 발표 · 누적 추가량';
    return `개발사 발표 · ${dayWishClaim(d)?'총량/하루 추가':d.period_text?'총량/기간 추가':'누적 추가/잔액'} 구분 미기재`;
  }
  const wishScope=d=>d.platform_scope==='steam'?'Steam 집계':'집계 범위 미기재';
  function wishSource(d){try{const h=new URL(d.source_url).hostname;return /(^|\.)(steamcommunity\.com|steampowered\.com)$/.test(h)||h==='steamstore-a.akamaihd.net'?'Steam 공식 공지':'공식 출처';}catch{return '출처';}}
  function wishClaimBody(d){return `<strong class="wish-claim">${esc(wishClaim(d))}</strong><p class="wish-meaning">${esc(wishMeaning(d))}</p>${d.period_text&&!dayWishClaim(d)?`<p class="wish-period">기간 표현: ${esc(d.period_text)}</p>`:''}`;}
  function wishClaimMeta(d,full=false){return `<div class="wish-claim-meta"><span>${wishDate(d.published_at)} 발표</span><span>${esc(wishScope(d))}</span>${d.as_of?`<span>수치 기준 ${wishDate(d.as_of)}</span>`:full?'<span>집계 기준시점 미기재</span>':''}${link(d.source_url,wishSource(d))}</div>`;}
  const wishReadState=()=>wish.loading||!wish.error?'위시리스트(찜) 자료 확인 중':'위시리스트(찜) 자료 조회 실패';
  const wishEmpty=()=>`<p class="compact-empty">${!wish.data?(wish.error&&!wish.loading?'위시리스트(찜) 자료를 불러오지 못했습니다.':'위시리스트(찜) 자료를 확인 중입니다.'):'검토한 공개 위시리스트(찜) 수치 없음'}</p>`;
  const wishNotice=()=>!wish.data?`<div id="wish-load-status" class="inline-alert ${wish.error&&!wish.loading?'':'info'}" role="status">${wish.error&&!wish.loading?'위시리스트(찜) 자료를 불러오지 못했습니다. 기록이 없는 상태와 다릅니다.':'위시리스트(찜) 자료를 확인하고 있습니다.'}${wish.error&&!wish.loading?'<button class="button" type="button" data-wish-retry>다시 불러오기</button>':''}</div>`:wish.error?'<div id="wish-load-status" class="inline-alert" role="status">위시리스트(찜) 자료 갱신 실패 · 이전 기록 표시 <button class="button" type="button" data-wish-retry>다시 불러오기</button></div>':'';
  function compareTabs(){return `<div class="metric-tabs" role="group" aria-label="게임 통계 보기"><button type="button" data-compare-view="wishlists" aria-pressed="${state.compareView==='wishlists'}">전체 게임</button><button type="button" data-compare-view="ccu" aria-pressed="${state.compareView==='ccu'}">동접 비교</button></div>`;}
  function wishDetails(key,label,content){return `<details class="compact-disclosure wish-disclosure" data-wish-disclosure="${esc(key)}" ${wish.open.has(key)?'open':''}><summary>${label}</summary><div class="disclosure-body">${content}</div></details>`;}
  let newsIndexSource=null,newsIndexCache=new Map();
  function catalogNewsIndex(){
    if(newsIndexSource===state.data.events)return newsIndexCache;
    newsIndexSource=state.data.events;newsIndexCache=new Map();
    for(const e of state.data.events){if(!newsIndexCache.has(e.game_id))newsIndexCache.set(e.game_id,[]);newsIndexCache.get(e.game_id).push(e);}
    for(const events of newsIndexCache.values())events.sort((a,b)=>(time(b.published_at)??-Infinity)-(time(a.published_at)??-Infinity)||a.id.localeCompare(b.id));
    return newsIndexCache;
  }
  function catalogPreview(g,records,events){
    const id=g.id,history=gameHistory(id),samples=allRows(id,'demo_ccu').filter(s=>time(s.observed_at)!==null&&time(s.observed_at)<=rangeEnd()),good=samples.filter(valid);
    return `<div class="ledger-preview" id="preview-${esc(id)}" role="region" aria-label="${esc(g.name)} 자료"><section><div class="preview-heading"><h3>동접 추이</h3><span>${history?number(good.length)+'회 관측':state.detailErrors.has(id)?'불러오기 실패':'불러오는 중'}</span></div><div class="chart-container ledger-chart" id="catalog-preview-chart" data-preview-game="${esc(id)}"></div>${good.length?`<p class="ledger-meta">${date(good[0].observed_at,true)} → ${date(good.at(-1).observed_at,true)} KST · 전체 기록</p>`:''}${state.detailErrors.has(id)?`<p>기록 갱신 실패 <button class="button" data-retry-history="${esc(id)}">다시 불러오기</button></p>`:''}<a class="button" href="${esc(routeHref('analysis',{game:id,metric:'demo_ccu',range:'all'}))}">증가 구간 · 원자료 · CSV →</a></section><section><h3>최근 공식 소식</h3><ul class="preview-news">${events.slice(0,3).map(e=>`<li><a href="${esc(routeHref('events',{game:id,event:e.id,event_game:id,range:'all'}))}">${esc(e.title)}</a><span>${wishDate(e.published_at)} · ${esc(kinds[e.kind]||'소식')}</span></li>`).join('')||'<li>확보한 소식 없음</li>'}</ul><h3>위시리스트(찜) 발표 기록</h3>${records.length?`<ul class="preview-claims">${records.slice().sort(newestDisclosure).slice(0,3).map(d=>`<li>${wishClaimBody(d)}<span>${esc(wishScope(d))}</span><span>${wishDate(d.published_at)}${d.as_of?` · 수치 기준 ${wishDate(d.as_of)}`:''} · ${link(d.source_url,'원문')}</span></li>`).join('')}</ul>`:'<p class="ledger-meta">검토한 공개 수치 미확보</p>'}<p class="ledger-meta">${history?`영상·방송 ${history.events.filter(e=>['video','livestream'].includes(e.kind)).length}건 · 저장된 검토 ${history.analyses.length}건`:state.detailErrors.has(id)?'상세 조회 실패':'상세 자료 확인 중'}</p><div class="preview-sources"><a class="button" href="${esc(wishLink(id))}">게임 정보 · 영상 · 검토 →</a>${link(g.store_url,'상점')}${link(g.demo_url,'데모')}${link(g.participation?.source_url,'참가 출처')}</div></section></div>`;
  }
  function ledgerDirectionLabel(key=state.ledgerSort,dir=state.ledgerDir){return ['reviewed','news'].includes(key)?(dir==='desc'?'최신순':'오래된순'):key==='name'?(dir==='asc'?'가나다순':'역순'):(dir==='desc'?'높은순':'낮은순');}
  function changeLedgerSort(key,toggle=false){state.ledgerDir=toggle&&state.ledgerSort===key?(state.ledgerDir==='desc'?'asc':'desc'):key==='name'?'asc':'desc';state.ledgerSort=key;state.catalogPage=1;syncQuery();preserveFocus(render);}
  function wishlistCompare(){
    const reviewed=groupWish('disclosures'),candidates=groupWish('candidates'),news=catalogNewsIndex(),q=state.catalogQuery.trim().toLocaleLowerCase();
    const games=state.config.games.filter(g=>(!q||g._search.includes(q))&&(!state.favoritesOnly||state.favorites.has(g.id))&&(state.catalogTag==='all'||g.tags?.includes(state.catalogTag))&&(state.wishFilter==='all'||state.wishFilter==='reviewed'&&reviewed.has(g.id)||state.wishFilter==='candidate'&&candidates.has(g.id)||state.wishFilter==='missing'&&!reviewed.has(g.id)));
    const latestReviewed=new Map([...reviewed].map(([id,records])=>[id,selectedWishlistRecords(records,id).latest]));
    const score=g=>{const r=summaryGame(g.id).ranges?.all;if(state.ledgerSort==='news')return time(news.get(g.id)?.[0]?.published_at);if(state.ledgerSort==='peak')return r?.peak??null;if(state.ledgerSort==='max_increase')return r?.max_increase?.delta??null;return time(latestReviewed.get(g.id)?.published_at);};
    games.sort((a,b)=>{const tie=a.name.localeCompare(b.name)||a.id.localeCompare(b.id),direction=state.ledgerDir==='asc'?1:-1;if(state.ledgerSort==='name')return direction*tie;const av=score(a),bv=score(b);return av===null&&bv!==null?1:av!==null&&bv===null?-1:av!==bv?direction*((av??0)-(bv??0)):tie;});
    const pagination=pager('catalog',games.length,25),page=games.slice((state.catalogPage-1)*25,state.catalogPage*25);
    if(state.expandedGame&&!page.some(g=>g.id===state.expandedGame))state.expandedGame=null;
    return wishNotice()+compareTabs()+`<div class="catalog-filters ledger-filters"><div class="field catalog-search"><label for="catalog-search">검색</label><input id="catalog-search" type="search" value="${esc(state.catalogQuery)}" placeholder="게임 이름 또는 AppID"></div><div class="field"><label for="ledger-sort">정렬</label><select id="ledger-sort">${[['reviewed','최근 위시리스트(찜) 발표일'],['news','최근 소식 게시일'],['peak','동접 최고'],['max_increase','최대 증가'],['name','게임 이름']].map(([v,l])=>`<option value="${v}" ${state.ledgerSort===v?'selected':''}>${l}</option>`).join('')}</select><button class="button ledger-direction" id="ledger-direction" type="button" aria-label="${esc({reviewed:'위시리스트(찜) 발표일',news:'소식 게시일',peak:'동접 최고',max_increase:'최대 증가',name:'게임 이름'}[state.ledgerSort])} 현재 ${esc(ledgerDirectionLabel())}. ${esc(ledgerDirectionLabel(state.ledgerSort,state.ledgerDir==='desc'?'asc':'desc'))}으로 정렬">${esc(ledgerDirectionLabel())} ${state.ledgerDir==='desc'?'↓':'↑'}</button></div>${wishDetails('ledger-filters','필터',`<div class="ledger-extra-filters"><div class="field"><label for="wish-evidence-filter">위시리스트(찜) 근거</label><select id="wish-evidence-filter">${[['all','전체 게임'],['reviewed','검토 발표 있음'],['candidate','수치 후보 있음'],['missing','검토 발표 미확보']].map(([v,l])=>`<option value="${v}" ${state.wishFilter===v?'selected':''}>${l}</option>`).join('')}</select></div><div class="field"><label for="catalog-tag">태그</label><select id="catalog-tag"><option value="all">전체 태그</option>${state.tags.map(t=>`<option value="${esc(t)}" ${state.catalogTag===t?'selected':''}>${esc(t)}</option>`).join('')}</select></div><label class="check-label"><input id="favorites-only" type="checkbox" ${state.favoritesOnly?'checked':''}>관심 게임만</label></div>`)}</div>${state.compare.length?`<div class="selection-summary"><span>비교 선택 <strong>${state.compare.length} / 4개</strong></span><a class="button" href="${esc(routeHref('compare',{view:'ccu',range:'all'}))}">선택 게임 동접 비교 →</a><button class="button" id="clear-compare" type="button">선택 해제</button></div>`:''}<section class="card game-ledger" id="wishlist-catalog"><div class="ledger-heading"><h2>게임 <span>${wish.data||state.wishFilter==='all'?number(games.length):'—'} / ${number(state.config.games.length)}</span></h2><p>동접: 전체 누적 기록 · ${esc(ccuCollectionText())}</p></div>${pagination.replace('id="catalog-pagination"','id="catalog-pagination-top"').replace('class="pagination"','class="pagination ledger-pagination-top"')}<div class="ledger-columns"><span>게임 / 관심 · 비교</span><button id="ledger-header-reviewed" type="button" data-ledger-sort="reviewed" aria-label="최근 위시리스트(찜) 발표일 ${state.ledgerSort==='reviewed'?ledgerDirectionLabel():'정렬'} · ${state.ledgerSort==='reviewed'&&state.ledgerDir==='desc'?'오래된순':'최신순'}으로 정렬">최근 위시리스트(찜) 발표 <span aria-hidden="true">${state.ledgerSort==='reviewed'?(state.ledgerDir==='desc'?'↓':'↑'):'↕'}</span></button><span>동접 기록</span><span>가장 많이 늘어난 구간</span><span>공식 소식</span></div><ul class="ledger-rows">${page.map(g=>{const records=reviewed.get(g.id)||[],d=selectedWishlistRecords(records,g.id).latest,pending=candidates.get(g.id)||[],s=summaryGame(g.id),r=s.ranges?.all||{},inc=r.max_increase,events=news.get(g.id)||[],latest=events[0],image=safeUrl(g.header_image,true);return `<li class="ledger-entry" data-ledger-game="${esc(g.id)}"><div class="ledger-row"><div class="ledger-game"><div class="ledger-identity">${image?`<img src="${esc(image)}" alt="" loading="lazy" width="64" height="36">`:''}<a class="game-name" href="${esc(wishLink(g.id))}">${esc(g.name)}</a></div><p class="ledger-tags">${(g.tags||[]).slice(0,2).map(esc).join(' · ')}</p><div class="ledger-choice"><button type="button" class="favorite-button" data-favorite="${esc(g.id)}" aria-pressed="${state.favorites.has(g.id)}" aria-label="${esc(g.name)} 관심 게임">${state.favorites.has(g.id)?'★':'☆'}</button><label class="check-label"><input type="checkbox" data-compare-game="${esc(g.id)}" ${state.compare.includes(g.id)?'checked':''} ${!state.compare.includes(g.id)&&state.compare.length>=4?'disabled':''}>비교</label><button class="ledger-expand" id="expand-${esc(g.id)}" data-expand-game="${esc(g.id)}" aria-expanded="${state.expandedGame===g.id}" aria-controls="preview-${esc(g.id)}">${state.expandedGame===g.id?'접기 −':'자료 +'}<span class="sr-only"> ${esc(g.name)}</span></button></div></div><div class="ledger-wish wish-list-value">${d?wishClaimBody(d):`<strong>${wish.data?'위시리스트(찜) 발표 미확보':wishReadState()}</strong>${pending.length?`<p class="wish-meaning">미검토 수치 후보 ${pending.length}건</p>`:''}`}${d?`<p class="ledger-meta">${wishDate(d.published_at)} 발표<br>${esc(wishScope(d))}${d.as_of?` · 수치 기준 ${wishDate(d.as_of)}`:''} · ${link(d.source_url,wishSource(d))}</p>`:''}</div><div class="ledger-stats"><div class="ledger-ccu"><div><span>마지막 정상 관측</span><strong>${r.last?number(r.last.value)+'명':'미확보'}</strong></div><div><span>관측 최고</span><strong>${typeof r.peak==='number'?number(r.peak)+'명':'미확보'}</strong></div><time>${s.last_ok_at?date(s.last_ok_at,true)+' KST':''}</time>${s.status==='error'?'<span>최근 시도 오류</span>':''}</div><div class="ledger-increase"><span>최대 증가</span>${inc?`<a href="${esc(routeHref('analysis',{game:g.id,metric:'demo_ccu',range:'all',at:inc.to}))}"><strong>+${number(inc.delta)}명</strong></a><p><span>${number(inc.start_value)} → ${number(inc.end_value)}명</span> <span>· ${duration(inc.elapsed_minutes)} 간격</span></p><time>${date(inc.from)} → ${date(inc.to)} KST</time>`:`<strong>—</strong><p>${(r.valid_count||0)<2?'비교 관측 부족':'유효 증가 구간 없음'}</p>`}</div></div><div class="ledger-news"><span>공식 소식 ${number(events.length)}건 확보</span>${latest?`<a href="${esc(routeHref('events',{game:g.id,event:latest.id,event_game:g.id,range:'all'}))}">${esc(latest.title)}</a><time>${wishDate(latest.published_at)}</time>`:'<p>확보한 소식 없음</p>'}</div></div>${state.expandedGame===g.id?catalogPreview(g,records,events):''}</li>`;}).join('')||`<li class="compact-empty">${!wish.data?wishReadState():'조건에 맞는 게임이 없습니다.'}</li>`}</ul>${pagination}</section>`;
  }

  const ccuStopped=id=>summaryGame(id).ccu_collection_enabled===false||settings().ccu_collection?.enabled===false||state.config.collection.ccu_enabled===false;
  const ccuCollectionText=(id=state.game)=>archived()?'수집 종료 · 기록 보관':ccuStopped(id)?'자동 수집 중단 · 기록 보관':'자동 수집 · 관측 시각 기준';
  const newestDisclosure=(a,b)=>(time(b.published_at)||0)-(time(a.published_at)||0)||(a.id>b.id?-1:a.id<b.id?1:0);
  const platformBadge=d=>badge(wishScope(d));
  function groupWish(key){const result=new Map();for(const record of wishRows(key)){const rows=result.get(record.game_id)||[];rows.push(record);result.set(record.game_id,rows);}return result;}
  function promotionalMentions(id){const excluded=new Set([...wishRows('disclosures'),...wishRows('candidates')].map(r=>r.event_id).filter(Boolean));return wishRows('mentions',id).filter(m=>!excluded.has(m.event_id));}
  function archivedCcuLink(id=state.game){return wishDetails('ccu-archive-'+id,'동접 기록',`<p class="wish-date">${ccuStopped(id)?'자동 수집 중단 · 기존 관측 보존':'기존 동접 관측 기록'}</p><a class="button" href="${esc(routeHref('analysis',{game:id,metric:'demo_ccu',range:'all'}))}">전체 동접 기록 →</a><a class="button" href="${esc(routeHref('compare',{view:'ccu'}))}">동접 기록 비교</a>`);}
  function compactCcu(id){
    const s=summaryGame(id),r=s.ranges?.all,has=typeof s.current==='number'&&Number.isFinite(s.current)&&s.last_ok_at;
    return `<div class="compact-ccu"><span>전체 동접 기록 ${has?`마지막 <b>${number(s.current)}명</b>`:'미확보'}${typeof r?.peak==='number'?` · 관측 최고 <b>${number(r.peak)}명</b>`:''}</span>${has?`<time>${date(s.last_ok_at,true)} KST 관측</time>`:''}${r?.max_increase?.delta>0?`<a class="ccu-interval-link" href="${esc(routeHref('analysis',{game:id,metric:'demo_ccu',range:'all',at:r.max_increase.to}))}">전체 기록 최대 +${number(r.max_increase.delta)}명 →</a>`:''}</div>`;
  }
  function overviewCcu(ids){
    const unique=[...new Set(ids)].filter(id=>game(id)).slice(0,3);
    if(!unique.length&&game(state.game))unique.push(state.game);
    return `<section class="card overview-ccu" id="overview-ccu"><div class="card-header"><h2>데모 동접 기록</h2>${badge(ccuCollectionText())}</div><p class="wishlist-caption">전체 누적 관측 기록</p><ul>${unique.map(id=>`<li><a class="game-name" href="${esc(routeHref('analysis',{game:id,metric:'demo_ccu',range:'all'}))}">${esc(game(id).name)}</a>${compactCcu(id)}<p class="ccu-history-meta">유효 관측 ${number(summaryGame(id).observation_history?.valid_count??summaryGame(id).ranges?.all?.valid_count??0)}회${summaryGame(id).ranges?.all?.first?` · ${date(summaryGame(id).ranges.all.first.observed_at)} → ${date(summaryGame(id).ranges.all.last.observed_at)} KST`:''}</p><a class="ccu-chart-link" href="${esc(routeHref('analysis',{game:id,metric:'demo_ccu',range:'all'}))}">동접 추이 →</a></li>`).join('')}</ul><a class="button ccu-compare-button" href="${esc(routeHref('compare',{view:'ccu',range:'all'}))}">게임별 동접 기록 비교 →</a></section>`;
  }
  function ccuSignals(){
    const entries=state.summary.games.filter(s=>game(s.game_id)&&s.ranges?.all?.max_increase?.delta>0).sort((a,b)=>b.ranges.all.max_increase.delta-a.ranges.all.max_increase.delta).slice(0,3);
    return `<section class="card overview-ccu" id="overview-ccu-signals"><div class="card-header"><h2>동접이 가장 많이 늘어난 구간</h2><a href="${esc(routeHref('compare',{view:'ccu',sort:'max_increase',range:'all'}))}">전체 비교 →</a></div><p class="wishlist-caption">전체 누적 기록의 최대 증가 · ${esc(ccuCollectionText())}</p><ul>${entries.map(s=>{const r=s.ranges.all,m=r.max_increase;return `<li><a class="game-name" href="${esc(routeHref('analysis',{game:s.game_id,metric:'demo_ccu',range:'all',at:m.to}))}">${esc(game(s.game_id).name)}</a><p class="signal-values"><strong>+${number(m.delta)}명</strong><span>${number(m.start_value)} → ${number(m.end_value)}명</span></p><p class="wish-date">${date(m.from,true)} → ${date(m.to,true)} KST<br>간격 ${duration(m.elapsed_minutes)} · 관측 최고 ${number(r.peak)}명</p><a class="ccu-chart-link" href="${esc(routeHref('analysis',{game:s.game_id,metric:'demo_ccu',range:'all',at:m.to}))}">추이·구간 근거 →</a></li>`;}).join('')||'<li class="text-muted">비교 가능한 증가 구간이 없습니다.</li>'}</ul></section>`;
  }
  function overviewNews(){
    const events=state.data.events.filter(e=>eventTime(e)!==null).slice().sort((a,b)=>eventTime(b)-eventTime(a)).slice(0,5);
    return `<section class="card" id="overview-news"><div class="card-header"><h2>최근 공식 소식</h2><a href="${esc(routeHref('events',{event_game:'all'}))}">전체 소식 →</a></div><ul class="event-short-list">${events.map(e=>`<li><a href="${esc(routeHref('events',{event:e.id}))}"><span class="event-short-title">${esc(e.title)}</span><span class="event-short-meta">${esc(game(e.game_id)?.name||e.game_id)} · ${esc(eventDate(e))} · ${esc(kinds[e.kind]||'소식')}</span></a></li>`).join('')||'<li class="compact-empty">수집된 공식 소식 없음</li>'}</ul></section>`;
  }
  function analysisTabs(){return `<nav class="analysis-sections" aria-label="게임 분석 보기"><a class="${state.metric==='wishlists'?'active':''}" href="${esc(wishLink(state.game))}">종합 통계</a><a class="${state.metric==='demo_ccu'?'active':''}" href="${esc(routeHref('analysis',{game:state.game,metric:'demo_ccu'}))}">동접 추이·증가 구간</a><a href="${esc(routeHref('events',{game:state.game,event_game:state.game}))}">공식 소식</a></nav>`;}
  function wishlistCoverage(){
    const c=wish.data?.coverage;
    return `<div class="wishlist-coverage" id="wishlist-overview-kpis"><span>위시리스트(찜) 수치 기록 <strong>${c?number(c.disclosures):'—'}건</strong> · ${c?number(c.disclosure_games):'—'} / ${number(state.config.games.length)}게임</span><a href="${esc(routeHref('collection'))}">확보 범위</a></div>`;
  }
  function wishlistOverview(){
    const records=wishRows('disclosures').slice().sort(newestDisclosure).slice(0,3);
    return wishNotice()+wishlistCoverage()+`<nav class="overview-shortcuts" aria-label="개요 통계 이동"><button class="button" type="button" data-overview-section="wishlist-latest-reviews">위시리스트(찜) 발표</button><button class="button" type="button" data-overview-section="overview-ccu-signals">동접 변화</button><button class="button" type="button" data-overview-section="overview-news">최근 소식</button></nav><div class="overview-evidence-grid"><section class="card" id="wishlist-latest-reviews"><div class="card-header"><h2>최근 위시리스트(찜) 발표</h2><a href="${esc(routeHref('compare',{view:'wishlists',evidence:'reviewed'}))}">더 보기 →</a></div>${records.length?`<ul class="wish-game-list semantic-wish-list">${records.map(d=>`<li><div class="wish-game-main"><a class="game-name" href="${esc(wishLink(d.game_id))}">${esc(game(d.game_id)?.name||d.game_id)}</a><div class="wish-list-value">${wishClaimBody(d)}</div>${wishClaimMeta(d)}</div></li>`).join('')}</ul>`:wishEmpty()}</section>${ccuSignals()}</div>${overviewNews()}<section class="card wishlist-tools">${wishDetails('overview-candidates','미검토 수치 후보 '+(wish.data?.coverage?.candidates??'—')+'건',wishlistCandidatePanel(null,5))}</section>`;
  }
  function wishlistCandidatePanel(id=null,limit=25){
    const rows=wishRows('candidates',id).slice().sort((a,b)=>(time(b.published_at)||0)-(time(a.published_at)||0));
    return `<section class="card wishlist-candidates" id="wishlist-candidates"><div class="card-header"><h2>수치 후보 <span>${wish.data&&Array.isArray(wish.data.candidates)?number(rows.length)+'건':wishReadState()}</span></h2>${id?badge('미검토','warn'):`<a href="${esc(routeHref('compare',{view:'wishlists',evidence:'candidate'}))}">후보 게임 →</a>`}</div><p class="wishlist-caption">수량 언급 · 미검토 · 목표 등 미확인 문구 포함</p>${rows.length?`<ul class="wish-candidate-list">${rows.slice(0,limit).map(r=>`<li><a class="game-name" href="${esc(wishLink(r.game_id))}">${esc(game(r.game_id)?.name||r.game_id)}</a><p>${esc(r.title)}</p><p class="wish-date">${wishDate(r.published_at)}</p>${wishDetails('candidate-'+r.id,'문구 · 원문',`<blockquote>${esc(r.quote)}</blockquote>${link(r.source_url,'원문','button')}`)}</li>`).join('')}</ul>`:`<p class="compact-empty">${wish.error&&!wish.data?'위시리스트(찜) 근거 파일을 불러오지 못했습니다.':!Array.isArray(wish.data?.candidates)?'수치 후보 자료 확인 중…':'확인된 미검토 수치 후보가 없습니다.'}</p>`}</section>`;
  }
  function selectedWishlistRecords(records,id=state.game){
    const comparison=wishRows('comparisons',id)[0];
    const latest=records.find(d=>d.id===comparison?.latest_disclosure_id)||records.slice().sort(newestDisclosure)[0];
    const previous=records.find(d=>d.id===comparison?.previous_disclosure_id);
    return {latest,previous,comparison};
  }
  function latestWishlistPanel(records){
    if(wish.data&&!wish.error&&!wish.loading&&!records.length)return `<section class="card wishlist-current game-headline" id="wishlist-current"><p class="compact-empty">검토된 공개 위시리스트(찜) 수치 없음</p></section>`;
    const {latest,previous,comparison}=selectedWishlistRecords(records);
    const precise=d=>d&&d.platform_scope==='steam'&&d.stock_definition==='balance'&&d.operator==='eq'&&d.as_of&&/T\d/.test(d.as_of)&&time(d.as_of)!==null;
    const comparable=comparison?.status==='reported_balance_difference'&&Number.isFinite(comparison.delta)&&precise(latest)&&precise(previous)&&time(previous.as_of)<time(latest.as_of)&&comparison.latest_disclosure_id===latest.id&&comparison.previous_disclosure_id===previous.id;
    return `<section class="card wishlist-current game-headline" id="wishlist-current"><div class="card-body"><div class="game-headline-top"><span>최근 위시리스트(찜) 발표</span>${latest?`<span>${wishDate(latest.published_at)} 발표</span>`:''}</div>${latest?`<div class="wish-record-heading">${wishClaimBody(latest)}</div><div class="game-headline-source"><span>${esc(wishScope(latest))}${latest.as_of?` · 수치 기준 ${wishDate(latest.as_of)}`:''}</span>${link(latest.source_url,wishSource(latest))}</div>${previous?`<div class="wish-previous"><span>이전 발표</span><strong>${esc(wishClaim(previous))}</strong><time>${wishDate(previous.published_at)}</time></div>`:''}${comparison?.publication_order_ambiguous?'<p class="wish-date">같은 날짜 발표 · 선후 미확인</p>':''}`:wish.data?'<p class="compact-empty">검토된 공개 위시리스트(찜) 수치 없음</p>':wishEmpty()}<p class="wish-change" id="wishlist-change">${comparable?`공개 위시리스트(찜) 잔액 차이 ${signed(comparison.delta)}건${!Number.isFinite(comparison.percent)?'':` · ${signed(comparison.percent)}%`}`:'실제 위시리스트(찜) 증가량 미확인 · 비교 가능한 잔액 없음'}</p></div></section>`;
  }
  function nearbyWishlistEvidence(disclosure){
    if(!disclosure)return '';
    const published=time(disclosure.published_at);if(published===null)return '';
    const dayOnly=/^\d{4}-\d{2}-\d{2}$/.test(disclosure.published_at),span=3*86400000;
    const dayStart=dayOnly?time(disclosure.published_at+'T00:00:00+09:00'):published,center=dayOnly?dayStart+43200000:published;
    const start=dayStart-span,end=dayStart+span+(dayOnly?86400000-1:0);
    const events=state.data.events.filter(e=>e.game_id===state.game&&e.id!==disclosure.event_id&&eventTime(e)!==null&&eventTime(e)>=start&&eventTime(e)<=end).sort((a,b)=>Math.abs(eventTime(a)-center)-Math.abs(eventTime(b)-center)).slice(0,6);
    return `<section class="card" id="wishlist-context"><div class="card-header"><h2>발표 전후 공식 소식</h2>${badge('원인 미확인')}</div><p class="wishlist-caption">발표일 전후 3일${dayOnly?' · 발표 시각 미확인':''}</p>${events.length?`<ul class="event-short-list">${events.map(e=>`<li><a href="${esc(routeHref('events',{event:e.id}))}"><span class="event-short-title">${esc(e.title)}</span><span class="event-short-meta">${esc(eventDate(e))} ${badge(kinds[e.kind]||'소식')}</span></a>${link(e.source_url,'원문','context-source')}</li>`).join('')}</ul>`:`<p class="compact-empty">${state.detailLoading.has(state.game)?'게임의 공식 소식을 확인 중입니다.':'수집한 자료에 인접 공식 소식이 없습니다.'}</p>`}</section>`;
  }
  function profileCollection(){
    const id=state.game;
    return `<section class="card" id="metric-collection-status"><div class="card-header"><h2>자동 수집 지표</h2><span>본편 / 데모 구분</span></div><div class="metric-collection-list">${['demo_ccu',...profileKeys].map(key=>{const s=key==='demo_ccu'?summaryGame(id):profileSummary(id,key),label=key==='demo_ccu'?'데모 동접':profileSpecs[key].label,status=key==='demo_ccu'?sampleState(id).text:profileState(id,key);return `<div><strong>${label}</strong><span>${esc(status)}</span><p>정상 관측 ${s.last_ok_at?date(s.last_ok_at,true)+' KST':'없음'}${s.last_attempt_at?' · 최근 시도 '+date(s.last_attempt_at,true)+' KST':''}</p><small>${key==='demo_ccu'&&ccuStopped(id)?'자동 수집 중단':s.target_interval_minutes?'목표 '+duration(s.target_interval_minutes):key==='followers'?'검증된 수집원 미확보':'목표 주기 확인 전'}</small></div>`;}).join('')}</div></section>`;
  }

  function preservedCoverage(){
    const context=state.config.game_context,c=context?.coverage,total=c?.catalog_games||state.config.games.length,count=v=>typeof v==='number'&&Number.isFinite(v)?number(v):'미확보',fraction=v=>count(v)+' / '+number(total)+'게임';
    if(!c)return '';
    return `<section class="card" id="preserved-coverage"><div class="card-header"><h2>저장 자료의 확보 범위</h2><span>전체 ${number(total)}게임 · 정기 수집과 별도</span></div><dl class="preserved-coverage"><div><dt>개발사 / 배급사</dt><dd>개발 ${count(c.developers_games)}게임 · 배급 ${count(c.publishers_games)}게임</dd></div><div><dt>장르 / 출시 정보</dt><dd>장르 ${count(c.genres_games)}게임 · 출시 ${count(c.release_date_games)}게임</dd></div><div><dt>확인한 공식 영상</dt><dd>${count(c.videos)}건 · ${fraction(c.video_games)}</dd></div><div><dt>저장된 검토 기록</dt><dd>${fraction(state.summary.coverage?.reviewed_games)} · 대상 기간·검토일은 각 기록 참고</dd></div></dl><p class="context-meta">기본정보 ${context.source_snapshot_started_at?dateOnly(context.source_snapshot_started_at):'시점 미확인'}${context.source_snapshot_at&&dateOnly(context.source_snapshot_at)!==dateOnly(context.source_snapshot_started_at)?' ~ '+dateOnly(context.source_snapshot_at):''} 당시 자료 · 영상과 검토는 확보된 기록만 제공</p></section>`;
  }
  function wishlistOperations(){
    const s=summaryGame(state.game),n=newsState(state.game),c=settings(),g=game(state.game),reviewed=wishRows('disclosures',g.id).length,candidates=wishRows('candidates',g.id).length;
    return wishNotice()+`<section class="card" id="wishlist-status"><div class="card-header"><h2>위시리스트(찜) 근거 수집</h2>${badge('현재 잔액 미확보')}</div><div class="card-body"><div class="field"><label for="collection-game">게임</label>${gamePicker('collection-game',state.game)}</div><dl class="wishlist-source-status"><div><dt>검토한 수치</dt><dd>${wish.data?number(reviewed)+'건':wishReadState()}</dd></div><div><dt>수치 후보</dt><dd>${wish.data&&Array.isArray(wish.data.candidates)?number(candidates)+'건 · 미검토':wishReadState()}</dd></div><div><dt>공식 공지</dt><dd>${badge(n.text,n.cls)}<span>${n.at?'최근 시도 '+date(n.at,true)+' KST':'조회 기록 없음'}</span></dd></div><div><dt>공개 위시리스트(찜) 잔액</dt><dd>정기 수집 없음</dd></div><div><dt>동접 자동 수집</dt><dd>${ccuStopped(g.id)?'중단 · 이전 기록 보존':archived()?'종료 · 기록 보관':'자동 수집 · 목표 '+duration(s.target_interval_minutes||c.target_cycle_minutes)}</dd></div></dl><a class="button primary" href="${esc(wishLink(g.id))}">게임 위시리스트(찜) 근거 →</a><a class="button" href="${esc(routeHref('compare',{view:'wishlists',evidence:'all'}))}">전체 게임 검색</a></div></section>${profileCollection()}${preservedCoverage()}<section class="card" id="collection-cadence"><div class="card-header"><h2>갱신 주기</h2></div><dl class="wishlist-source-status"><div><dt>화면 갱신</dt><dd>5분<span>저장된 자료 재조회</span></dd></div><div><dt>수집 배치</dt><dd>${duration(c.scheduled_interval_minutes||c.interval_minutes)} 목표</dd></div><div><dt>공지 출처 순환</dt><dd>${duration(c.news_target_cycle_minutes)} 목표<span>예약 실행은 지연될 수 있습니다.</span></dd></div><div><dt>위시리스트(찜) 공개 수치</dt><dd>발표 근거 검토 후 추가<span>현재 위시리스트(찜) 수를 자동 계산하지 않습니다.</span></dd></div></dl></section><section class="card wishlist-tools">${wishDetails('collection-ccu','동접 기록',collectionSelectedCard(false))}${wishDetails('collection-operations','운영 세부',lastRunPanel()+`<p class="wish-date">자료 기준 ${date(state.summary.generated_at,true)} KST · ${number(state.config.games.length)}개 참가작</p>`)}${wishDetails('collection-interpretation','자료 해석 기준','<p>공개 발표·미검토 수치 후보·일반 홍보 언급은 구분합니다. 발표 하한끼리 차감해 실제 증가량을 만들지 않습니다.</p><p>직접 입력한 참고 계산은 이 게임의 자동 추정치가 아니며, 정확도 보정용 실제 잔액은 확보하지 못했습니다.</p>')}</section>`;
  }
  const followerCheckTime=record=>time(record.observed_at||record.verified_at||record.observation_window_utc?.[1])??-Infinity;
  function newestFollowerCheck(a,b){
    const at=followerCheckTime(a),bt=followerCheckTime(b);
    if(at!==bt)return at>bt?-1:1;
    return a.id===b.id?0:a.id>b.id?-1:1;
  }
  function gameProfile(g){return `<div class="game-profile"><div>${(g.tags||[]).slice(0,3).map(t=>badge(t)).join(' ')}</div><div>${link(g.store_url,'본편 상점')}${link(g.demo_url,'데모')}${link(g.participation?.source_url,'참가 출처')}</div></div>`;}
  function gameBackground(g){
    const seed=state.seedGames.get(g.id),p=state.gameContext.get(g.id)?.profile_snapshot,fields=[];
    const names=values=>(values||[]).map(v=>String(v).trim()).filter(Boolean);
    if(names(p?.developers).length)fields.push(['개발',names(p.developers).join(' · ')]);
    if(names(p?.publishers).length)fields.push(['배급',names(p.publishers).join(' · ')]);
    if(p?.genres?.length)fields.push(['장르',p.genres.map(v=>typeof v==='string'?v:v.description).filter(Boolean).join(' · ')]);
    if(p?.release_date?.date)fields.push([p.release_date.coming_soon?'출시 예정 · 확인 당시':'출시일 · 확인 당시',p.release_date.date]);
    const genreProof=p?.provenance?.fields?.genres,releaseProof=p?.provenance?.fields?.release_date;
    const sharedProof=!!p?.genres?.length&&!!p?.release_date?.date&&genreProof?.evidence_collected_at&&!genreProof.observed_at&&!releaseProof?.observed_at&&genreProof.evidence_collected_at===releaseProof?.evidence_collected_at;
    return `<section class="card game-background" id="game-background"><div class="card-header"><h2>게임 정보</h2>${p?.observed_at?`<span>개발·배급 ${date(p.observed_at,true)} KST 확인</span>`:''}</div>${seed?.description_ko?`<p class="context-description">${esc(seed.description_ko)}</p>`:''}${fields.length?`<dl class="game-info-fields">${fields.map(([k,v])=>{const field=k==='장르'?'genres':k.startsWith('출시')?'release_date':k==='개발'?'developers':'publishers',proof=p?.provenance?.fields?.[field];return `<div><dt>${esc(k)}</dt><dd>${esc(v)}${proof?.evidence_collected_at&&!proof?.observed_at&&!sharedProof?`<small>${dateOnly(proof.evidence_collected_at)} 자료 저장</small>${wishDetails('profile-source-'+g.id+'-'+field,'출처 확인',`<p>개별 확인시각 미기재 · 자료 저장 ${date(proof.evidence_collected_at,true)} KST</p>${link(proof.source_url,'출처')}`)}`:''}${proof?.observed_at&&['genres','release_date'].includes(field)?`<small>${date(proof.observed_at,true)} KST 확인</small>`:''}</dd></div>`;}).join('')}</dl>`:''}${sharedProof?`<div class="profile-shared-source"><p>장르·출시 계획 · ${dateOnly(genreProof.evidence_collected_at)} 자료 저장</p>${wishDetails('profile-source-'+g.id,'출처 확인',`<p>장르·출시 계획의 개별 확인시각은 미기재입니다. 자료 저장 ${date(genreProof.evidence_collected_at,true)} KST</p>${link(genreProof.source_url,'장르 출처')}${releaseProof.source_url!==genreProof.source_url?link(releaseProof.source_url,'출시 정보 출처'):''}`)}</div>`:''}<div class="game-context-links">${link(g.store_url,'본편 상점')}${link(g.demo_url,'데모')}${link(g.participation?.source_url,'참가 근거')}${p?.provenance?.fields?.release_date?.source_url?link(p.provenance.fields.release_date.source_url,'장르·출시 정보 출처'):''}</div><p class="context-meta">본편 ${esc(g.app_id)}${g.demo_app_id?' · 데모 '+esc(g.demo_app_id):''}${fields.length?' · 확인 당시 저장된 정보':''}</p>${g.tags?.length?`<p class="context-meta">태그 · ${g.tags.slice(0,6).map(esc).join(' · ')}</p>`:''}</section>`;
  }
  function storedReviews(){
    const records=(gameHistory(state.game)?.analyses||[]).filter(r=>r.game_id===state.game).slice().sort((a,b)=>(time(b.reviewed_at)||0)-(time(a.reviewed_at)||0));
    if(!records.length)return `<p class="context-meta" id="game-reviews">${gameHistory(state.game)?'저장된 검토 기록 없음':state.detailErrors.has(state.game)?'상세 기록 조회 실패':'검토 기록 확인 중'}</p>`;
    return `<section class="card game-reviews" id="game-reviews"><div class="card-header"><h2>저장된 검토 기록</h2><span>${records.length}건</span></div>${records.length?records.map((r,i)=>wishDetails('saved-review-'+state.game+'-'+i,`${date(r.reviewed_at,true)} 검토 · ${{direct_evidence:'직접 근거',temporal_association:'시점 대조',insufficient:'근거 부족'}[r.assessment]||'검토 기록'}`,reviewHtml(r))).join(''):'<p class="context-meta">'+(gameHistory(state.game)?'작성된 검토 기록 없음':state.detailErrors.has(state.game)?'상세 기록 조회 실패':'상세 기록 확인 중')+'</p>'}</section>`;
  }
  function ccuPeriodContext(ids=[state.game],page='analysis'){
    if(state.range==='all')return '';
    const end=rangeEnd(),start=end-Number(state.range)*3600000,last=Math.max(...ids.map(id=>time(summaryGame(id).last_ok_at)).filter(t=>t!==null));
    const stopped=ids.length>0&&ids.every(ccuStopped),empty=ids.every(id=>(summaryGame(id).ranges?.[state.range]?.valid_count||0)===0);
    return `<div class="period-context"><p>조회 기간 ${date(iso(start),true)} → ${date(iso(end),true)} KST</p>${empty&&Number.isFinite(last)&&last<start?`<p>선택 기간에 기록 없음${stopped?' · 동접 수집 중단':''}. 마지막 기록 ${date(iso(last),true)} KST · <a href="${esc(routeHref(page,{range:'all',...(page==='compare'?{view:'ccu'}:{metric:state.metric})}))}">전체 기록 보기</a></p>`:''}</div>`;
  }
  function integratedCcu(){
    const id=state.game,history=gameHistory(id),observed=validRows(id,'demo_ccu'),last=observed.at(-1),max=observed.length?Math.max(...observed.map(s=>s.value)):null,changes=intervals(id,'demo_ccu',true).sort((a,b)=>b.delta-a.delta),available=!!game(id).demo_app_id,status=sampleState(id);
    return `<section class="card integrated-ccu" id="game-ccu-panel"><div class="card-header"><h2>데모 동접 추이</h2>${badge(ccuCollectionText(id))}</div><div class="integrated-period" role="group" aria-label="동접 기록 기간">${[['all','전체 기록'],['24','24시간'],['6','6시간']].map(([v,l])=>`<button class="button" type="button" data-game-range="${v}" aria-pressed="${state.range===v}">${l}</button>`).join('')}<span>${state.range==='all'?'전체 기록':''}</span></div>${ccuPeriodContext()}<div class="integrated-metrics"><div><span>마지막 정상 관측</span><strong>${last?number(last.value)+'명':'—'}</strong><time class="ccu-last-time">${last?observationDate(last.observed_at)+' KST':history?'선택 기간에 관측 없음':'관측 기록 확인 중'}</time>${badge(status.text,status.cls)}</div><div><span>${state.range==='all'?'전체 기록 최고':'선택 기간 최고'}</span><strong>${max===null?'—':number(max)+'명'}</strong></div><div><span>유효 관측</span><strong>${history?number(observed.length)+'회':'—'}</strong></div><div><span>${state.range==='all'?'전체 기록 최대 증가':'선택 기간 최대 증가'}</span><strong>${changes.length?'+'+number(changes[0].delta)+'명':'—'}</strong></div></div>${!available?'<p class="compact-empty">데모 연결 미확보 · 동접 자료 없음</p>':`<div class="chart-container" id="game-ccu-chart"></div>`}<p class="integrated-range">${last?`${date(observed[0].observed_at,true)} → ${date(last.observed_at,true)} KST`:'선택 기간의 정상 관측 없음'}${summaryGame(id).status==='error'?' · 최근 관측 시도 오류':''}${state.detailErrors.has(id)?' · 상세 갱신 실패':''}</p>${state.detailErrors.has(id)?`<button class="button" data-retry-history="${esc(id)}">관측 기록 다시 불러오기</button>`:''}<div class="integrated-chart-actions"><a class="button" href="${esc(routeHref('analysis',{game:id,metric:'demo_ccu'}))}">증가 구간·검토 근거 →</a><button class="button" type="button" id="download-overview-csv" ${rows(id,'demo_ccu').length?'':'disabled'}>동접 CSV ↓</button></div>${changes.length?`<h3 class="context-subheading">가장 많이 늘어난 구간</h3><ul class="integrated-increases">${changes.slice(0,3).map(c=>`<li><a href="${esc(routeHref('analysis',{game:id,metric:'demo_ccu',at:c.b.observed_at}))}"><strong>+${number(c.delta)}명<small>${c.percent===null?'증가율 —':'+'+number(c.percent)+'%'}</small></strong><span>${date(c.a.observed_at)} → ${date(c.b.observed_at)} KST<br>${number(c.a.value)} → ${number(c.b.value)}명 · ${duration(c.elapsed/60000)} 간격</span></a></li>`).join('')}</ul>`:''}<p class="mini-chart-note">관측된 값만 표시 · 오류와 긴 공백은 연결하지 않음</p></section>`;
  }
  function gameNews(){return state.data.events.filter(e=>e.game_id===state.game).slice().sort((a,b)=>(eventTime(b)||0)-(eventTime(a)||0));}
  function integratedNews(){
    const events=gameNews(),videos=events.filter(e=>['video','livestream'].includes(e.kind)),news=events.filter(e=>!['video','livestream'].includes(e.kind)),snapshots=state.gameContext.get(state.game)?.videos_snapshot||[];
    const full=e=>(gameHistory(state.game)?.events||[]).find(v=>v.id===e.id)||e;
    return `<section class="card game-news" id="game-news-panel"><div class="card-header"><h2>공식 소식·영상</h2><span>${events.length}건 확보</span></div>${events.length?'<div class="mini-chart-container" id="game-news-chart"></div>':'<p class="compact-empty">수집된 소식 없음 · 활동이 없다는 뜻은 아닙니다.</p>'}<p class="mini-chart-note">전체 확보 기록의 게시일별 건수 · 빈 날짜는 활동 0을 뜻하지 않음</p><ul class="event-short-list context-news">${news.slice(0,4).map(e=>{const entry=full(e);return `<li><a href="${esc(routeHref('events',{event:e.id}))}"><span class="event-short-title">${esc(e.title)}</span><span class="event-short-meta">${esc(eventDate(e))} · ${esc(kinds[e.kind]||'소식')}</span></a><div class="context-news-actions">${link(e.source_url,'원문')}${entry.summary?wishDetails('news-summary-'+e.id,'요약',`<p class="context-summary">${esc(entry.summary)}</p>`):''}</div></li>`;}).join('')}</ul>${videos.length?`<div class="game-video-list"><h3>공식 영상·방송 ${videos.length}건</h3>${videos.slice(0,3).map(e=>{const v=snapshots.find(v=>(v.source_url||v.url)===e.source_url),entry=full(e);return `<div class="context-video">${link(e.source_url,e.title)}<span>${v?.author_name?(v.author_url?link(v.author_url,v.author_name):esc(v.author_name))+' · ':''}${esc(eventDate(e))}</span>${entry.summary||entry.relationship_source_url?wishDetails('video-context-'+e.id,'영상 설명 · 연결 근거',`<p class="context-summary">${esc(entry.summary||'')}</p>${entry.relationship_source_url?link(entry.relationship_source_url,'개발사 연결 공지'):''}${v?.observed_at?`<p class="context-meta">채널 확인 ${date(v.observed_at,true)} KST</p>`:''}`):''}</div>`;}).join('')}</div>`:''}<a class="button game-news-all" href="${esc(routeHref('events',{game:state.game,event_game:state.game,range:'all'}))}">전체 소식·원문 →</a></section>`;
  }
  function publicationPanel(records){return `<section class="card game-publications" id="game-publications-panel"><div class="card-header"><h2>위시리스트(찜) 발표 시점</h2><span>수치 기록 ${wish.data?records.length+'건':wishReadState()}</span></div>${records.length?'<div class="mini-chart-container" id="game-publication-chart"></div>':wishEmpty()}<p class="mini-chart-note">전체 확보 기록 · 발표일 표식이며 잔액 증가선이 아님</p></section>`;}
  function wishlistAnalysis(){
    const id=state.game,g=game(id),records=wishRows('disclosures',id).slice().sort((a,b)=>(time(a.published_at)||0)-(time(b.published_at)||0)),checks=wishRows('follower_checks',id).slice().sort(newestFollowerCheck),mentions=promotionalMentions(id);
    const toolbar=`<div class="analysis-toolbar integrated-toolbar"><div class="field"><label for="game-select">게임</label>${gamePicker('game-select',id)}</div><div class="field"><label for="metric-select">지표</label><select id="metric-select">${metricOptions(state.metric)}</select></div></div>`;
    const emptyDisclosures=!!wish.data&&!wish.error&&!wish.loading&&!records.length;
    const history=`<section class="card" id="wishlist-disclosures"><div class="card-header"><h2>위시리스트(찜) 수치 기록 <span>${wish.data?records.length+'건':wishReadState()}</span></h2></div><p class="wishlist-caption">발표 시간순 · 실제 잔액 추이와 다름</p>${records.length?`<ol class="wish-disclosures wish-timeline" aria-label="공개 발표 시간순 기록">${records.map(d=>`<li><div class="wish-record-heading">${wishClaimBody(d)}</div>${wishClaimMeta(d)}${wishDetails('disclosure-'+d.id,'원문 · 해석 근거',`<blockquote>${esc(d.quote)}</blockquote>${d.review_scope?`<p class="detail-footer">${esc(d.review_scope)}</p>`:''}<p class="detail-footer">${d.as_of?'수치 기준 '+wishDate(d.as_of):'집계 기준시점 미기재'} · 확인 ${date(d.verified_at,true)} KST</p>${link(d.source_url,'발표 원문','button')}${d.source_context_url?link(d.source_context_url,'관련 출처','button'):''}`)}</li>`).join('')}</ol>`:wish.data?'<p class="compact-empty">검증된 공개 위시리스트(찜) 수치 없음</p>':wishEmpty()}</section>`;

    const followers=`<section class="card" id="wishlist-followers"><div class="card-header"><h2>팔로워 근거</h2>${badge(checks[0]?.status==='conflict'?'출처 불일치':checks[0]?.status==='ok'?'확인 기록':wish.data?'미확보':wishReadState(),checks[0]?.status==='conflict'?'warn':'')}</div><div class="card-body">${checks.length?checks.slice(0,3).map(c=>`<div class="wish-follower-record"><p>${c.status==='ok'&&wishNumber(c.value)?`<strong class="mono">${number(c.value)}</strong>명 · 위시리스트(찜) 수와 다름`:c.status==='conflict'?'경로별 값이 달라 추정에 사용할 수 없습니다.':'검증된 팔로워 수 미확보'}</p><p class="wish-date">${c.observed_at?'관측 '+wishDate(c.observed_at):Array.isArray(c.observation_window_utc)&&c.observation_window_utc.length===2?'관측 범위 '+wishDate(c.observation_window_utc[0])+' ~ '+wishDate(c.observation_window_utc[1]):'관측 시각 미확보'}</p>${wishDetails('follower-'+c.id,'경로 · 출처',`<ul class="wish-source-list">${(c.candidates||[]).map(x=>`<li><code>${esc(x.path)}</code><span>${wishNumber(x.value)?number(x.value):'미확보'}</span></li>`).join('')}</ul><p class="detail-footer">${esc(c.mapping?.group_name||game(c.game_id)?.name||'')} · 본편 AppID ${esc(c.app_id)}<br>${c.mapping?.appid_matches===true&&c.mapping?.apphub_group_id_matches===true?'공식 앱 그룹 연결 확인':'공식 앱 그룹 연결 미확인'}</p>${link(c.source_url,'확인 출처','button')}`)}</div>`).join(''):wish.data?'<p class="text-muted">검증된 팔로워 수 미확보 · 자동 추정하지 않습니다.</p>':wishEmpty()}</div></section>`;
    const mentionPanel=wishDetails('wish-mentions-'+id,`일반 위시리스트(찜) 홍보 언급 ${wish.data?mentions.length+'건':wishReadState()}`,mentions.length?`<ul class="wish-mentions">${mentions.slice(0,25).map(m=>`<li>${link(m.source_url,m.title)}<p class="wish-date">${wishDate(m.published_at)}</p><p>${esc(m.quote)}</p></li>`).join('')}</ul>`:wish.data?'<p class="text-muted">일반 홍보 언급이 없습니다.</p>':wishEmpty());
    return toolbar+wishNotice()+latestWishlistPanel(records)+`<nav class="game-section-nav" aria-label="게임 분석 자료"><button type="button" data-game-section="game-ccu-panel">동접·증가</button><button type="button" data-game-section="game-news-panel">소식·영상</button><button type="button" data-game-section="game-background">정보·검토</button></nav>`+integratedCcu()+`<div class="game-graph-grid${emptyDisclosures?' single-panel':''}">${emptyDisclosures?'':publicationPanel(records)}${integratedNews()}</div>`+gameBackground(g)+storedReviews()+rawTable('demo_ccu')+(emptyDisclosures?'':records.length===1?wishDetails('single-claim-history-'+id,'위시리스트(찜) 수치 원문 · 해석 근거',history):history)+nearbyWishlistEvidence(selectedWishlistRecords(records).latest)+`<section class="card wishlist-tools">${wishDetails('game-candidates','미검토 수치 후보',wishlistCandidatePanel(id))}${mentionPanel}${wishDetails('followers-panel','팔로워 확인 기록',followers)}${wishlistCalculator()}</section>`;
  }
  function wishlistCollection(){const c=wish.data?.coverage;return wishNotice()+`<section class="card wishlist-status" id="wishlist-status"><div class="card-header"><h2>위시리스트(찜) 정보</h2>${badge('현재 잔액 미확보')}</div><div class="card-body"><p>타사 게임의 정확한 현재 위시리스트(찜) 잔액은 공개 자료로 확인되지 않습니다. 공개 발표와 참고 계산을 분리해 제공합니다.</p>${c?`<p class="wish-date">발표 ${number(c.disclosure_games||0)}개 게임 · 팔로워 불일치 ${number(c.followers_conflict||0)}개</p>`:''}<a class="button" href="${esc(wishLink(state.game))}">${esc(game(state.game).name)} 위시리스트(찜) 근거</a><a class="button" href="${esc(routeHref('compare',{view:'wishlists'}))}">발표 게임 찾기</a></div></section>`;}
  function wishInputState(){if(!wish.inputs.has(state.game))wish.inputs.set(state.game,{followers:'',estimate:'',actual:'',estimateDate:'',actualDate:'',scenarioResult:'',errorResult:''});return wish.inputs.get(state.game);}
  function wishMethod(){return wishRows('methods').find(m=>Number.isFinite(m.lower_multiplier)&&Number.isFinite(m.upper_multiplier)&&m.lower_multiplier>0&&m.upper_multiplier>=m.lower_multiplier&&safeUrl(m.source_url));}
  function wishlistCalculator(){
    const m=wishMethod(),v=wishInputState();
    if(!m)return wishDetails('wish-calculator','참고 계산 / 오차 확인','<p class="text-muted">검토된 참고 방법을 불러온 뒤 사용할 수 있습니다.</p>');
    const field=(id,label,value,type='text')=>`<div class="field"><label for="wish-${id}">${label}</label><input id="wish-${id}" data-wish-input="${id}" type="${type}" ${type==='text'?'inputmode="numeric"':''} autocomplete="off" value="${esc(value)}"></div>`;
    return wishDetails('wish-calculator','참고 계산 / 오차 확인',`<p class="wish-warning">정확도 미검증 · 보정용 실측 미확보 · 2023년 표본 참고</p><p class="wish-date">이 탭에서만 사용 · 입력값은 저장하거나 전송하지 않습니다.</p><form id="wish-scenario-form" class="wish-form"><h3>팔로워 입력 시나리오</h3>${field('followers','팔로워 수',v.followers)}<button type="submit" class="button">참고 범위 계산</button><output id="wish-scenario-output" role="status">${esc(v.scenarioResult)}</output></form><p class="wish-method">입력 × ${number(m.lower_multiplier)}–${number(m.upper_multiplier)}배 · 신뢰구간 아님 ${link(m.source_url,'방법 출처')}</p><p class="wish-date">${esc(m.label)} · ${esc(m.source_date)}<br>${esc(m.sample_description)}</p><form id="wish-error-form" class="wish-form"><h3>같은 게임 · 같은 기준일 오차</h3><p class="wish-date">${esc(game(state.game).name)} · 개발사 실제 잔액이 있을 때만</p>${field('estimate','비교할 추정값',v.estimate)}${field('estimateDate','추정 기준일',v.estimateDate,'date')}${field('actual','실제 위시리스트(찜) 잔액',v.actual)}${field('actualDate','잔액 기준일',v.actualDate,'date')}<button type="submit" class="button">오차 계산</button><output id="wish-error-output" role="status">${esc(v.errorResult)}</output></form><p class="wish-date">발표 하한·기간 추가 수는 잔액이 아닙니다. 한 게임의 오차를 전체 게임에 적용할 수 없습니다.</p>`);
  }
  const parseWishInput=value=>typeof value==='string'&&/^\d+$/.test(value.trim())&&Number.isSafeInteger(Number(value.trim()))?Number(value.trim()):null;
  function bindWishlist(){
    $('#ledger-sort')?.addEventListener('change',e=>changeLedgerSort(e.target.value));
    $$('[data-ledger-sort]').forEach(b=>b.addEventListener('click',()=>changeLedgerSort(b.dataset.ledgerSort,true)));
    $('#ledger-direction')?.addEventListener('click',()=>changeLedgerSort(state.ledgerSort,true));
    $$('[data-expand-game]').forEach(b=>b.addEventListener('click',()=>{state.expandedGame=state.expandedGame===b.dataset.expandGame?null:b.dataset.expandGame;preserveFocus(render);}));
    $('#wish-evidence-filter')?.addEventListener('change',e=>{state.wishFilter=e.target.value;state.catalogPage=1;syncQuery();preserveFocus(render);});
    $$('[data-compare-view]').forEach(b=>b.addEventListener('click',()=>{state.compareView=b.dataset.compareView;state.catalogPage=1;syncQuery();render();}));
    $$('[data-wish-retry]').forEach(b=>b.addEventListener('click',()=>loadWishlists()));
    $$('[data-wish-disclosure]').forEach(d=>d.addEventListener('toggle',()=>{if(d.isConnected){d.open?wish.open.add(d.dataset.wishDisclosure):wish.open.delete(d.dataset.wishDisclosure);}}));
    $$('[data-wish-input]').forEach(input=>input.addEventListener('input',()=>{const v=wishInputState();v[input.dataset.wishInput]=input.value;if(input.dataset.wishInput==='followers'){v.scenarioResult='';$('#wish-scenario-output').textContent='';}else{v.errorResult='';$('#wish-error-output').textContent='';}}));
    $('#wish-scenario-form')?.addEventListener('submit',e=>{e.preventDefault();const v=wishInputState(),n=parseWishInput(v.followers),m=wishMethod();let text='0 이상의 정수를 입력하세요.';
      if(n!==null&&m){const lo=n*m.lower_multiplier,hi=n*m.upper_multiplier;if(Number.isSafeInteger(lo)&&Number.isSafeInteger(hi)){const unit=x=>10**Math.max(0,Math.floor(Math.log10(x||1))-1);text=`입력 시나리오: 약 ${number(Math.floor(lo/unit(lo))*unit(lo))}–${number(Math.ceil(hi/unit(hi))*unit(hi))}개 · 이 게임의 추정값 아님`;}else text='계산 가능한 범위를 초과했습니다.';}
      v.scenarioResult=text;$('#wish-scenario-output').textContent=text;
    });
    $('#wish-error-form')?.addEventListener('submit',e=>{e.preventDefault();const v=wishInputState(),estimate=parseWishInput(v.estimate),actual=parseWishInput(v.actual);let text='추정값과 실제 잔액에 0 이상의 정수를 입력하세요.';
      if(estimate!==null&&actual!==null){if(!/^\d{4}-\d{2}-\d{2}$/.test(v.estimateDate)||v.estimateDate!==v.actualDate)text='같은 기준일을 입력하세요.';else{const absolute=Math.abs(estimate-actual);text=`절대 오차 ${number(absolute)}개 · 상대 오차 ${actual===0?'— (실제 잔액 0)':number(absolute/actual*100)+'%'} · 입력값 기준`;}}
      v.errorResult=text;$('#wish-error-output').textContent=text;
    });
  }
  async function loadWishlists(){
    if(wish.loading)return;wish.loading=true;wish.attemptedAt=Date.now();if(state.config&&wishlistActive())preserveFocus(render);
    try{const response=await fetch('./data/wishlists.json?v='+Date.now(),{cache:'no-cache'});if(!response.ok)throw new Error('wishlist data unavailable');const data=await response.json();if(data.schema_version!==1||!['disclosures','follower_checks','methods','mentions'].every(k=>Array.isArray(data[k])))throw new Error('invalid wishlist schema');wish.data=data;wish.error=false;}
    catch{wish.error=true;}finally{wish.loading=false;if(state.config&&wishlistActive())preserveFocus(render);}
  }
  const expandedSections=new Set();
  function disclosure(key,label,nodes,parent,before=null){
    if(!nodes.length)return;
    const details=document.createElement('details');details.className='compact-disclosure';details.dataset.disclosure=key;
    const summary=document.createElement('summary');summary.textContent=label;details.append(summary);
    const body=document.createElement('div');body.className='disclosure-body';details.append(body);
    parent.insertBefore(details,before);nodes.forEach(node=>body.append(node));
    details.open=expandedSections.has(key);
    details.addEventListener('toggle',()=>{if(details.isConnected){details.open?expandedSections.add(key):expandedSections.delete(key);}});
  }
  function simplifyLayout(){
    const root=$('#route-view');
    root.querySelectorAll('table').forEach(table=>{
      table.classList.add('responsive-table');table.setAttribute('role','table');
      const headings=[...table.querySelectorAll('thead th')].map(th=>th.textContent.trim());
      table.querySelectorAll('thead,tbody').forEach(group=>group.setAttribute('role','rowgroup'));
      table.querySelectorAll('tr').forEach(row=>row.setAttribute('role','row'));
      table.querySelectorAll('th').forEach(th=>{th.setAttribute('role','columnheader');th.scope='col';});
      table.querySelectorAll('tbody tr').forEach(row=>[...row.cells].forEach((td,i)=>{td.setAttribute('role','cell');if(td.colSpan===1)td.dataset.label=headings[i]||'';}));
    });
    const compare=$('#comparison-table');
    if(compare)compare.querySelectorAll('tbody tr').forEach(row=>{
      if(row.cells.length!==8)return;
      const checkbox=row.querySelector('[data-compare-game]'),label=document.createElement('label');label.className='compare-choice';
      checkbox.before(label);label.append(checkbox,document.createTextNode('비교'));
      const source=row.querySelector('.game-name'),action=document.createElement('a');action.className='mobile-analysis-link button';action.href=source.href;action.textContent='분석 →';row.cells[7].append(action);const freshness=row.cells[7].querySelector('.badge')?.cloneNode(true);if(freshness){freshness.classList.add('mobile-freshness');row.cells[3].append(freshness);}
    });
    const filters=root.querySelector('.catalog-filters,.filter-bar');
    if(filters&&state.page==='compare'&&state.compareView==='ccu'){
      disclosure('catalog-filters','필터',[...filters.children].slice(1),filters);
    }else if(filters&&state.page==='events'){
      const extra=[...filters.children].filter(el=>!el.querySelector('#events-search'));
      disclosure('event-filters','게임 · 종류 · 날짜 필터',extra,filters);
    }
    // Keep method notes available without filling the working surface.
    root.querySelectorAll('.table-note').forEach((note,i)=>{if(state.page==='collection')disclosure(state.page+'-note-'+i,'기준 보기',[note],note.parentElement,note);else note.remove();});
    if(state.page==='collection'){
      const fleet=$('#fleet-coverage'),run=$('#last-run-status');if(fleet&&run)disclosure('fleet-operation','전체 수집 현황',[fleet,run],root,fleet);
      const settings=root.querySelector('.settings-grid');if(settings)disclosure('collection-method','수집 설정 · 해석 기준',[settings],settings.parentElement,settings);
    }
    if(state.page==='analysis'){
      const raw=root.querySelector('.raw-table');if(raw)disclosure('raw-data','원자료 · CSV',[raw],raw.parentElement,raw);
      const panel=$('#interval-detail');
      panel?.querySelectorAll('.detail-section').forEach((section,i)=>{
        if(section.querySelector('h4')?.textContent==='검토 근거')disclosure('review-evidence','검토 근거',[section],section.parentElement,section);
      });
    }
  }
  function render(){
    if(!state.config)return;
    renderChrome();
    const renderers={overview:renderOverview,compare:renderCompare,analysis:renderAnalysis,events:renderEvents,collection:renderCollection};
    $('#route-view').dataset.page=state.page;$('#route-view').innerHTML=renderers[state.page]();
    simplifyLayout();bindPage();renderCharts();
    const navigation=state.eventNavigation;if(navigation)requestAnimationFrame(()=>{if(state.eventNavigation!==navigation||state.page!=='events'||state.event!==navigation.id)return;state.eventNavigation=null;const panel=$('#event-detail');if(panel&&mobile()){panel.focus({preventScroll:true});panel.scrollIntoView({block:'start',behavior:'instant'});}});
    const intervalNav=state.intervalNavigation;
    if(intervalNav&&state.page==='analysis'&&state.metric==='demo_ccu'&&state.game===intervalNav.game&&state.range===intervalNav.range&&state.details.get(intervalNav.game)?.generation===state.generation){
      const target=intervals(intervalNav.game,'demo_ccu',true).find(i=>i.b.observed_at===intervalNav.at);
      if(!target)state.intervalNavigation=null;
      else if(state.interval===target.id)requestAnimationFrame(()=>{if(state.intervalNavigation!==intervalNav||state.page!=='analysis'||state.metric!=='demo_ccu'||state.game!==intervalNav.game||state.range!==intervalNav.range)return;state.intervalNavigation=null;const panel=$('#interval-detail');if(panel){panel.focus({preventScroll:true});panel.scrollIntoView({block:'start',behavior:'instant'});}});
    }
    for(const id of activeHistoryIds())if(!state.detailLoading.has(id))loadHistory(id);
    if(wishlistActive()&&!wish.loading&&Date.now()-wish.attemptedAt>300000)loadWishlists();
  }
  function mobile(){return matchMedia('(max-width:900px)').matches;}
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
      const appIds=new Map(catalog.games.map(g=>[g.id,g.app_id]));
      state.gameContext=new Map((payload.config.game_context?.games||[]).filter(e=>appIds.get(e.game_id)===e.app_id).map(e=>[e.game_id,e]));
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
    $('#refresh-data').addEventListener('click',()=>{refresh(true);if(wishlistActive())loadWishlists();});
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
    $$('[data-route]').forEach(a=>a.addEventListener('click',()=>setMenu(false)));
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

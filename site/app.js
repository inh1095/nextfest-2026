'use strict';
(() => {
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const url = (s) => { try { const u = new URL(s); return ['https:', 'http:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } };
  const assetUrl = (s) => { try { const u = new URL(s, location.href); return ['https:', 'http:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } };
  const link = (href, label, cls = '') => url(href) ? `<a class="${esc(cls)}" href="${esc(url(href))}" target="_blank" rel="noopener noreferrer">${esc(label)} <span aria-hidden="true">↗</span></a>` : '';
  const stamp = (s) => { const t = Date.parse(s); return Number.isFinite(t) ? t : null; };
  const number = (n) => new Intl.NumberFormat('ko-KR', {maximumFractionDigits:1}).format(n);
  const date = (s, mode = 'full') => {
    if (stamp(s) === null) return '시각 미확인';
    const opts = {timeZone:'Asia/Seoul', month:'2-digit', day:'2-digit', ...(mode !== 'day' ? {hour:'2-digit',minute:'2-digit',hourCycle:'h23'} : {}), ...(mode === 'full' ? {year:'numeric'} : {})};
    return new Intl.DateTimeFormat('ko-KR', opts).format(new Date(s));
  };
  const parts = (s) => new Intl.DateTimeFormat('en-GB', {timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(s));
  const shortDate = (s, withTime = true) => { if (stamp(s) === null) return '미확인'; const p=Object.fromEntries(parts(s).map(x=>[x.type,x.value])); return `${p.month}.${p.day}${withTime ? ` ${p.hour}:${p.minute}` : ''}`; };
  const labels = {demo_ccu:'데모 동시접속자', followers:'본편 팔로워'};
  const kinds = {announcement:'발표',update:'업데이트',video:'영상',livestream:'라이브 방송',demo_release:'데모 공개'};
  const state = {config:null,data:null,game:null,range:'all',event:null,refreshError:false};
  const valid = (s) => s.status === 'ok' && typeof s.value === 'number' && Number.isFinite(s.value) && s.value >= 0 && stamp(s.observed_at) !== null;
  const sorted = (arr) => arr.slice().sort((a,b) => (stamp(a.observed_at)||0) - (stamp(b.observed_at)||0));
  const gameSamples = (id = state.game) => sorted(state.data.samples.filter(s => s.game_id === id));
  const validSamples = (id, metric) => gameSamples(id).filter(s => s.metric === metric && valid(s));
  const metricConfig = (game, metric) => (game.metrics || []).find(m => m.key === metric) || {};
  const gapLimit = () => ((state.config.collection.interval_minutes || 20)*2+30)*60000;
  const isArchived = () => state.data.collection_status === 'archived' || (stamp(state.config.collection.stops_at) !== null && Date.now() >= stamp(state.config.collection.stops_at));
  const stale = (sample) => sample && !isArchived() && Date.now()-stamp(sample.observed_at) > gapLimit();
  const games = () => state.config.games;
  const currentGame = () => games().find(g => g.id === state.game);
  const eventTime = (e) => stamp(e.occurred_at) ?? stamp(e.published_at);
  const rangeBounds = () => {
    const observations = gameSamples().map(s => stamp(s.observed_at)).filter(t => t !== null);
    const last = observations.length ? Math.max(...observations) : Date.now();
    if (state.range !== 'all') {
      const end = isArchived() ? Math.max(last, stamp(state.config.collection.stops_at) || last) : Math.max(last, Date.now());
      return [end-Number(state.range)*3600000,end];
    }
    if (!observations.length) return [Date.now()-6*3600000,Date.now()];
    const first = Math.min(...observations);
    if (first === last) return [first-3600000,last+3600000];
    const pad = Math.max((last-first)*.025, 60000);
    return [first-pad,last+pad];
  };
  const filteredSamples = () => { const [start,end] = rangeBounds(); return gameSamples().filter(s => stamp(s.observed_at) !== null && stamp(s.observed_at)>=start && stamp(s.observed_at)<=end); };
  const currentEvents = () => { const [start,end] = rangeBounds(); return state.data.events.filter(e => e.game_id===state.game && (state.range==='all' || (eventTime(e)!==null && eventTime(e)>=start && eventTime(e)<=end))).sort((a,b)=>(eventTime(b)||0)-(eventTime(a)||0)); };
  const selectedAnalysis = () => {
    const list = state.data.analyses.filter(a => a.game_id===state.game);
    return list.find(a => (a.evidence_event_ids||[]).includes(state.event)) || null;
  };
  function renderHeader() {
    const {event,collection} = state.config;
    const ended = stamp(event.ends_at)!==null && Date.now()>=stamp(event.ends_at);
    const upcoming = stamp(event.starts_at)!==null && Date.now()<stamp(event.starts_at);
    $('#festival-dates').textContent = `${date(event.starts_at,'short')} — ${date(event.ends_at,'short')} KST`;
    $('#event-status').textContent = ended ? '페스티벌 종료' : upcoming ? '페스티벌 시작 전' : '페스티벌 진행 중';
    $('#collection-status').textContent = isArchived() ? '수집 종료 · 기록 보관' : state.data.collection_status==='pending' ? '첫 수집 대기' : '관측 기록 수집 중';
    const source = $('#festival-source');
    if (url(event.verification_url)) { source.href=url(event.verification_url); source.hidden=false; }
    const validAll = state.data.samples.filter(valid);
    const lastValid = sorted(validAll).at(-1);
    $('#freshness').textContent = `마지막 유효 관측 ${lastValid ? date(lastValid.observed_at)+' KST' : '없음'} · 파일 갱신 ${date(state.data.generated_at)} KST`;
    $('#collection-note').textContent = `지표 ${collection.interval_minutes || 20}분 · 소식 ${collection.news_interval_minutes || 180}분 간격 수집 예정 · ${date(collection.stops_at)} KST 수집 종료`;
    const notices = [];
    if(state.refreshError)notices.push('최신 기록을 가져오지 못했습니다. 마지막으로 불러온 자료를 유지합니다. 5분 후 다시 확인합니다.');
    if (isArchived()) notices.push('수집 기간이 끝났습니다. 이 페이지는 보관된 관측 기록을 보여줍니다.');
    if (lastValid && stamp(lastValid.observed_at)>stamp(event.ends_at)) notices.push('첫 수집이 페스티벌 종료 이후 시작됐다면 행사 중 변화는 확인할 수 없습니다. 이 페이지는 실제로 확보한 시점부터 기록합니다.');
    if (state.data.collection_status==='pending' && !validAll.length) notices.push('아직 유효한 관측값이 없습니다. 첫 관측이 확보되면 숫자와 그래프에 반영됩니다.');
    for (const notice of state.data.notices || []) {
      const text = typeof notice === 'string' ? notice : notice.message || notice.text;
      if (text) notices.push(text);
    }
    $('#data-notices').innerHTML = [...new Set(notices)].map(n=>`<p class="notice">${esc(n)}</p>`).join('');
  }
  function renderCards() {
    $('#game-cards').innerHTML=games().map((g,i)=>{
      const ccu=validSamples(g.id,'demo_ccu').at(-1), follower=validSamples(g.id,'followers').at(-1);
      const stat = (sample,metric) => `<div class="game-stat"><span class="stat-label">${labels[metric]}</span><div class="stat-number ${!sample?'small':''}">${sample ? `${number(sample.value)}<span class="unit">명</span>` : '미확보'}</div><span class="stat-context">${sample ? `${shortDate(sample.observed_at)} KST${stale(sample)?' · 관측 지연':''}` : metric==='followers' ? '검증된 공개값 없음' : '유효 관측값 없음'}</span></div>`;
      return `<button type="button" class="game-card" data-game="${esc(g.id)}" aria-pressed="${g.id===state.game}" aria-label="${esc(g.name)} 관측 보기"><div class="game-art">${g.header_image && assetUrl(g.header_image)?`<img src="${esc(assetUrl(g.header_image))}" alt="" loading="eager" referrerpolicy="no-referrer">`:''}<span class="game-index">GAME 0${i+1}</span><span class="game-selected">${g.id===state.game?'선택됨':'자세히 보기'}</span></div><div class="game-body"><div class="game-title-row"><h3>${esc(g.name)}</h3><span aria-hidden="true">↗</span></div><p class="game-tagline">${esc(g.description_ko || '')}</p><div class="game-stats">${stat(ccu,'demo_ccu')}${stat(follower,'followers')}</div></div></button>`;
    }).join('');
    document.querySelectorAll('[data-game]').forEach(button=>button.addEventListener('click',()=>{ state.game=button.dataset.game;state.event=null;renderDetail();renderCards();document.querySelector(`[data-game="${CSS.escape(state.game)}"]`).focus({preventScroll:true}); }));
  }
  function chart(metric, bounds) {
    const game=currentGame(), definition=metricConfig(game,metric);
    const rows=filteredSamples().filter(s=>s.metric===metric), samples=rows.filter(valid);
    const allValid=validSamples(state.game,metric), latest=allValid.at(-1), lastAttempt=gameSamples().filter(s=>s.metric===metric).at(-1);
    const [start,end]=bounds, W=680,H=188,L=48,R=15,T=22,B=43;
    const maxValue=samples.length?Math.max(...samples.map(s=>s.value)):0;
    const maximum=maxValue===0 ? 1 : Math.ceil(maxValue*1.2/Math.pow(10,Math.floor(Math.log10(maxValue))))*Math.pow(10,Math.floor(Math.log10(maxValue)));
    const x=t=>L+(t-start)/(end-start)*(W-L-R), y=v=>T+(1-v/maximum)*(H-T-B);
    const color=metric==='demo_ccu'?'#e9b85e':'#afc9a5';
    const tickCount=3;
    let svg='';
    for(let i=0;i<tickCount;i++){const v=maximum*i/(tickCount-1), yy=y(v);svg+=`<line class="gridline" x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}"/><text x="${L-9}" y="${yy+3}" text-anchor="end">${samples.length?esc(number(v)):'—'}</text>`;}
    svg+=`<line class="axis" x1="${L}" y1="${H-B}" x2="${W-R}" y2="${H-B}"/>`;
    for(let i=0;i<3;i++){const t=start+(end-start)*i/2, xx=x(t);svg+=`<text x="${xx}" y="${H-13}" text-anchor="${i===0?'start':i===2?'end':'middle'}">${esc(shortDate(new Date(t).toISOString()))}</text>`;}
    const selectedEvent=currentEvents().find(e=>e.id===state.event);
    if(selectedEvent && ['minute','hour'].includes(selectedEvent.time_precision) && eventTime(selectedEvent)>=start && eventTime(selectedEvent)<=end){const xx=x(eventTime(selectedEvent));svg+=`<line class="event-marker" x1="${xx}" y1="${T-7}" x2="${xx}" y2="${H-B}"/><text x="${Math.max(L+5,Math.min(W-R-5,xx))}" y="${T-12}" text-anchor="middle">선택한 사건</text>`;}
    let segment=[], segments=[];
    for(const row of rows){
      if(!valid(row)){if(segment.length)segments.push(segment);segment=[];continue;}
      if(segment.length && stamp(row.observed_at)-stamp(segment.at(-1).observed_at)>gapLimit()){segments.push(segment);segment=[];}
      segment.push(row);
    }
    if(segment.length)segments.push(segment);
    for(const points of segments){if(points.length>1){svg+=`<polyline points="${points.map(s=>`${x(stamp(s.observed_at)).toFixed(2)},${y(s.value).toFixed(2)}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;}}
    for(const sample of samples){const xx=x(stamp(sample.observed_at)),yy=y(sample.value);svg+=`<circle cx="${xx}" cy="${yy}" r="${samples.length===1?5:3}" fill="${color}" stroke="#202420" stroke-width="2" tabindex="0" role="img" aria-label="${esc(date(sample.observed_at))} KST ${number(sample.value)}명"><title>${esc(date(sample.observed_at))} KST · ${number(sample.value)}명</title></circle>`;}
    let empty='';
    if(!samples.length){const reason=definition.unavailable_reason || (state.range!=='all' && allValid.length ? '이전 유효 관측은 전체 기간에서 확인할 수 있습니다.' : '아직 확인된 공개 관측값이 없습니다.');empty=`<div class="chart-empty-label"><strong>${metric==='followers'?'팔로워 데이터 미확보':'선택 기간의 유효 관측 없음'}</strong><span>${esc(reason)}</span></div>`;}
    let note = samples.length===1 ? '관측 1회 · 기준선 수집 중. 추세와 증감은 아직 계산하지 않습니다.' : samples.length>1 ? `유효 관측 ${number(samples.length)}회 · ${number(gapLimit()/60000)}분 초과 공백·수집 실패 구간은 연결하지 않습니다.` : '값 없음은 0명이 아닙니다.';
    if(lastAttempt && !valid(lastAttempt) && latest) note+=` 최근 수집 ${lastAttempt.status==='error'?'오류':'미확보'}로 마지막 유효값을 표시합니다.`;
    const latestInRange=latest && stamp(latest.observed_at)>=start && stamp(latest.observed_at)<=end;
    return `<section class="metric-chart ${metric}" aria-label="${labels[metric]} 차트"><div class="metric-topline"><div><h4 class="metric-label"><span class="metric-dot"></span>${labels[metric]}</h4><p class="metric-definition">${esc(definition.definition || (metric==='demo_ccu'?'데모 앱을 실행 중인 플레이어':'본편의 공개 팔로워 수'))}</p></div><div><div class="metric-value">${latest?`${number(latest.value)}<span>명</span>`:'<span class="no-value">— 미확보</span>'}</div><p class="metric-observed">${latest?`${latestInRange?'마지막 관측':'기간 밖 마지막 관측'} ${shortDate(latest.observed_at)}${stale(latest)?' · 지연':''}`:'확인된 값 없음'}</p></div></div><svg class="metric-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${labels[metric]}: 선택 기간에 ${samples.length}회의 유효 관측. ${samples.length===1?'단일 점으로 변화 판단 불가.':''}">${svg}</svg>${empty}<p class="metric-detail-note">${esc(note)}${link(definition.source_url,'지표 출처')}</p></section>`;
  }
  function renderInsights(){
    const rows=filteredSamples().filter(s=>s.metric==='demo_ccu' && valid(s));
    const allMetricRows=filteredSamples().filter(s=>s.metric==='demo_ccu');
    const max=rows.length?Math.max(...rows.map(s=>s.value)):null;
    let best=null;
    for(let i=1;i<allMetricRows.length;i++){
      const before=allMetricRows[i-1],after=allMetricRows[i];
      if(!valid(before)||!valid(after)||stamp(after.observed_at)-stamp(before.observed_at)>gapLimit())continue;
      const increase=after.value-before.value;
      if(increase>0 && (!best||increase>best.increase))best={before,after,increase};
    }
    let growth;
    if(rows.length<2){growth=`<div class="growth-block"><p class="growth-label">관측 증가 구간 · 데모 동시접속자</p><p class="growth-waiting">${rows.length?'기준선 수집 중':'관측값 대기 중'}</p><p class="growth-copy">${rows.length?'아직 한 번의 관측만 있습니다. 다음 관측이 확보되면 언제, 얼마나 변했는지 비교합니다.':'유효한 관측이 확보되면 변화 구간을 계산합니다.'}</p></div>`;}
    else if(best){
      const percent=best.before.value===0?'—':`+${number(best.increase/best.before.value*100)}%`;
      const nearby=state.data.events.filter(e=>e.game_id===state.game && ['minute','hour'].includes(e.time_precision) && eventTime(e)!==null && eventTime(e)>=stamp(best.before.observed_at)-6*3600000 && eventTime(e)<=stamp(best.after.observed_at)+3600000).sort((a,b)=>Math.abs(eventTime(a)-stamp(best.after.observed_at))-Math.abs(eventTime(b)-stamp(best.after.observed_at))).slice(0,3);
      const nearbyHtml=`<div class="nearby-events"><p class="nearby-label">구간 전후 공개 소식 · 원인 미확인</p>${nearby.length?nearby.map(e=>`<button type="button" data-nearby-event="${esc(e.id)}"><span>${esc(shortDate(new Date(eventTime(e)).toISOString()))} KST</span>${esc(e.title)} <span aria-hidden="true">↗</span></button>`).join(''):'<p class="nearby-empty">수집한 자료에서 인접 소식 미확인</p>'}<p class="nearby-window">구간 시작 6시간 전부터 종료 1시간 후까지 · 정확한 시각이 확인된 사건만</p></div>`;
      growth=`<div class="growth-block"><p class="growth-label">관측 증가 구간 · 가장 큰 인접 증가</p><p class="growth-value">+${number(best.increase)}<span>명 / ${percent}</span></p><p class="growth-period">${esc(shortDate(best.before.observed_at))} → ${esc(shortDate(best.after.observed_at))} KST</p><p class="growth-copy">데모 동시접속자 ${number(best.before.value)}명 → ${number(best.after.value)}명.${best.before.value===0?' 기준값이 0이어서 증가율은 계산하지 않습니다.':''}</p><p class="growth-copy">확보한 인접 관측 중 최대 증가입니다. 급증의 원인이나 행사 전체 성과를 의미하지 않습니다.</p>${nearbyHtml}</div>`;
    }else growth=`<div class="growth-block"><p class="growth-label">관측 증가 구간 · 데모 동시접속자</p><p class="growth-waiting">확인된 증가 없음</p><p class="growth-copy">연속된 유효 관측 사이에서 양의 증가가 확인되지 않았습니다. 관측 공백은 비교에서 제외합니다.</p></div>`;
    const first=rows[0],last=rows.at(-1);
    const difference=rows.length>=2?last.value-first.value:null;
    const review=state.data.analyses.filter(a=>a.game_id===state.game).sort((a,b)=>(stamp(b.reviewed_at)||0)-(stamp(a.reviewed_at)||0))[0];
    const reviewText=review?`마지막 검토 ${date(review.reviewed_at)} KST. 이후 관측은 이 검토에 포함되지 않을 수 있습니다.`:'사건과의 연관성에 대한 검토가 아직 없습니다.';
    $('#growth-insights').innerHTML=growth+`<div class="growth-block"><p class="growth-label">선택 기간의 관측 요약</p><dl class="insight-mini"><div><dt>관측 최고 동접</dt><dd>${max===null?'—':number(max)}<span>${max===null?'':'명'}</span></dd></div><div><dt>유효 관측</dt><dd>${number(rows.length)}<span>회</span></dd></div></dl><p class="growth-copy">처음 → 마지막 변화 <strong>${difference===null?'판단 대기':`${difference>0?'+':''}${number(difference)}명`}</strong></p><p class="growth-period">${first?`${esc(shortDate(first.observed_at))}${rows.length>1?` → ${esc(shortDate(last.observed_at))}`:''} KST`:'첫 관측 미확보'}</p><p class="growth-copy">${esc(reviewText)}</p></div>`;
    document.querySelectorAll('[data-nearby-event]').forEach(button=>button.addEventListener('click',()=>{
      const eventId=button.dataset.nearbyEvent;
      if(!currentEvents().some(e=>e.id===eventId))state.range='all';
      state.event=eventId;renderDetail();
      $('#event-detail').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
      $('#event-detail').setAttribute('tabindex','-1');$('#event-detail').focus({preventScroll:true});
    }));
  }
  function renderEvents(){
    const events=currentEvents();
    const news = state.data.news_status?.[state.game] || {};
    const newsAttempt = news.last_attempt_at || (typeof state.data.news_last_attempt_at === 'string' ? state.data.news_last_attempt_at : state.data.news_last_attempt_at?.[state.game]);
    const newsDelay = !isArchived() && stamp(newsAttempt)!==null && Date.now()-stamp(newsAttempt)>((state.config.collection.news_interval_minutes||180)*2+30)*60000;
    $('#news-freshness').textContent=`공식 공지 최근 확인 ${newsAttempt ? date(newsAttempt)+' KST' : '기록 없음'} · ${news.status==='error'?'수집 오류 · 이전 사건 기록 유지':newsDelay?'확인 지연':news.status==='ok'?'확인 완료':'상태 미확인'}${isArchived()?' · 수집 종료':''}`;
    if(!events.some(e=>e.id===state.event))state.event=events[0]?.id||null;
    $('#event-list').innerHTML=events.length?events.map(e=>{
      const time=eventTime(e), exact=['minute','hour'].includes(e.time_precision);
      let day='날짜 미확인',hours='';
      if(time!==null){day=shortDate(new Date(time).toISOString(),false);hours=exact?shortDate(new Date(time).toISOString()).split(' ')[1]:'시각 미확인';}
      return `<button type="button" class="event-button" data-event="${esc(e.id)}" aria-pressed="${e.id===state.event}"><span class="event-time">${esc(day)}<small>${esc(hours)}</small></span><span><span class="event-kind">${esc(kinds[e.kind]||'공개 소식')}</span><span class="event-title">${esc(e.title)}</span></span><span class="event-arrow" aria-hidden="true">↗</span></button>`;
    }).join(''):'<p class="empty-events">선택 기간에 확인된 사건이 없습니다.<br>공개 근거를 확보한 소식만 기록합니다.</p>';
    document.querySelectorAll('[data-event]').forEach(button=>button.addEventListener('click',()=>{state.event=button.dataset.event;renderEvents();renderCharts();document.querySelector(`[data-event="${CSS.escape(state.event)}"]`)?.focus({preventScroll:true});}));
    const e=events.find(e=>e.id===state.event);
    if(!e){$('#event-detail').innerHTML='<p class="eyebrow">EVENT CONTEXT</p><h3>확인된 기록을 기다립니다.</h3><p class="no-event-detail">공개 발표나 업데이트를 확인하면 출처와 시점을 함께 표시합니다. 소식이 없다는 것은 활동이 없었다는 뜻이 아닙니다.</p>';return;}
    const exact=['minute','hour'].includes(e.time_precision),time=eventTime(e);
    const analysis=selectedAnalysis();
    const [chartStart,chartEnd]=rangeBounds();
    const markerVisible=exact && time!==null && time>=chartStart && time<=chartEnd;
    const observationTimes=gameSamples().map(s=>stamp(s.observed_at)).filter(t=>t!==null);
    const beforeObservations=time!==null && observationTimes.length && time<Math.min(...observationTimes);
    const markerNote=markerVisible?' 그래프의 세로 점선은 선택한 사건의 시점입니다.':!exact?' 세부 시각이 확인되지 않아 그래프에 특정 시점으로 표시하지 않습니다.':beforeObservations?' 최초 관측 이전의 사건입니다. 해당 시점의 지표값은 확보되지 않았습니다.':' 선택한 차트 시간 범위 밖의 사건입니다.';
    let review='';
    if(analysis){
      const assessments={direct_evidence:'직접 근거 확인',temporal_association:'시간적 연관성 · 인과 미확인',insufficient:'근거 부족'};
      review=`<section class="reviewed-analysis"><h4>${esc(assessments[analysis.assessment]||'검토 기록')}</h4><dl><dt>관측 사실</dt><dd>${esc(analysis.observation)}</dd><dt>가능한 설명</dt><dd>${esc(analysis.hypothesis||'확인된 설명이 없습니다.')}</dd><dt>다른 가능한 설명</dt><dd>${(analysis.alternative_explanations||[]).length?analysis.alternative_explanations.map(esc).join('<br>'):'별도 검토 기록이 없습니다.'}</dd><dt>검토 대상 기간</dt><dd>${esc(date(analysis.from))} → ${esc(date(analysis.to))} KST</dd></dl><p class="review-date">검토 시각 ${esc(date(analysis.reviewed_at))} KST · 이후 자료는 미반영될 수 있음</p></section>`;
    }
    $('#event-detail').innerHTML=`<p class="eyebrow">SELECTED EVENT / ${esc(kinds[e.kind]||'공개 소식')}</p><h3>${esc(e.title)}</h3><p class="event-meta">${e.occurred_at?'발생':'공개'} ${time!==null?esc(date(new Date(time).toISOString(),exact?'full':'day')):'시점 미확인'}${exact?' KST': ' · 세부 시각 미확인'}${e.time_precision==='hour'?' · 시간 단위 근거':''}</p><p class="event-summary">${esc(e.summary||'요약이 없습니다. 원문 출처에서 내용을 확인할 수 있습니다.')}</p><div class="event-source">${link(e.source_url,'원문에서 확인')}</div><p class="evidence-note">${analysis?'관련 관측에 대한 검토 기록이 아래에 있습니다.':'이 사건과 지표 변화의 인과관계는 확인되지 않았습니다.'}${esc(markerNote)}<br>출처 확인 ${esc(date(e.verified_at))} KST</p>${review}`;
  }
  function renderCharts(){
    const bounds=rangeBounds();
    $('#charts').innerHTML=['demo_ccu','followers'].map(metric=>chart(metric,bounds)).join('');
    const samples=filteredSamples();
    const times=samples.map(s=>stamp(s.observed_at)).filter(t=>t!==null);
    $('#chart-period').textContent=times.length?`${shortDate(new Date(Math.min(...times)).toISOString())} — ${shortDate(new Date(Math.max(...times)).toISOString())} KST`:'선택 기간에 확보된 관측이 없습니다.';
    $('#download-csv').disabled=!samples.length;
    $('#sample-count').textContent=`${number(samples.length)}건`;
    $('#sample-rows').innerHTML=samples.slice().reverse().map(s=>`<tr><td>${esc(date(s.observed_at))}</td><td>${esc(labels[s.metric]||s.metric)}</td><td>${valid(s)?esc(number(s.value)):'—'}</td><td>${s.status==='ok'&&valid(s)?'확보':s.status==='error'?'수집 오류':'미확보'}</td><td>${link(s.source_url,'출처')}</td></tr>`).join('')||'<tr><td colspan="5">확보된 관측 기록이 없습니다.</td></tr>';
  }
  function renderDetail(){
    const game=currentGame();
    $('#detail-title').textContent=game.name;
    $('#detail-description').textContent=`데모 App ${game.demo_app_id || '미확인'} · 본편 App ${game.app_id || '미확인'} · 최초 관측 이전의 과거값은 포함하지 않습니다.`;
    $('#detail-links').innerHTML=link(game.store_url,'본편 상점')+link(game.demo_url,'데모 상점');
    $('#selection-evidence').innerHTML=`<p>${esc(game.selection_reason||'선정 이유 확인 중')}</p>${game.participation?.evidence_excerpt?`<blockquote>${esc(game.participation.evidence_excerpt)}</blockquote>`:''}${link(game.participation?.source_url,'Next Fest 참가 근거')}<p>${game.participation?.verified_at?`확인 ${esc(date(game.participation.verified_at))} KST`:''}</p>`;
    renderEvents();renderCharts();renderInsights();
    document.querySelectorAll('[data-range]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.range===state.range)));
  }
  function csvDownload(){
    const samples=filteredSamples();
    const cell=(s)=>`"${String(s??'').replace(/"/g,'""')}"`;
    const rows=[['game_id','metric','observed_at_utc','observed_at_kst','value','status','source_url','error_code'],...samples.map(s=>[s.game_id,s.metric,s.observed_at,date(s.observed_at)+' KST',valid(s)?s.value:'',s.status,s.source_url,s.error_code])];
    const blob=new Blob(['\uFEFF'+rows.map(r=>r.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8;'});
    const address=URL.createObjectURL(blob),a=document.createElement('a');a.href=address;a.download=`nextfest-${state.game}-${state.range}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(address),1000);
  }
  function preserveFocus(render){
    const active=document.activeElement;
    const game=active?.dataset?.game,event=active?.dataset?.event;
    render();
    if(game)document.querySelector(`[data-game="${CSS.escape(game)}"]`)?.focus({preventScroll:true});
    if(event)document.querySelector(`[data-event="${CSS.escape(event)}"]`)?.focus({preventScroll:true});
  }
  async function loadData(refresh=false){
    const suffix=refresh?`?v=${Date.now()}`:'';
    const responses=await Promise.all([fetch('./data/config.json'+suffix,{cache:'no-cache'}),fetch('./data/observations.json'+suffix,{cache:'no-cache'})]);
    if(responses.some(r=>!r.ok))throw new Error('data unavailable');
    const [config,data]=await Promise.all(responses.map(r=>r.json()));
    if(!Array.isArray(config.games)||!config.games.length||!config.event||!config.collection||!Array.isArray(data.samples))throw new Error('invalid schema');
    data.events=Array.isArray(data.events)?data.events:[];
    data.analyses=Array.isArray(data.analyses)?data.analyses:[];
    state.config=config;state.data=data;state.refreshError=false;
    if(!config.games.some(g=>g.id===state.game))state.game=config.games[0].id;
  }
  async function init(){
    try{
      await loadData();
      renderHeader();renderCards();renderDetail();
      $('#loading-state').hidden=true;$('#detail-panel').hidden=false;
      document.querySelectorAll('[data-range]').forEach(button=>button.addEventListener('click',()=>{state.range=button.dataset.range;renderDetail();}));
      $('#download-csv').addEventListener('click',csvDownload);
      setInterval(()=>preserveFocus(()=>{renderHeader();renderCards();renderDetail();}),60000);
      setInterval(async()=>{
        try{await loadData(true);preserveFocus(()=>{renderHeader();renderCards();renderDetail();});}
        catch{state.refreshError=true;renderHeader();}
      },300000);
    }catch(error){
      $('#loading-state').textContent='관측 기록을 불러오지 못했습니다. 잠시 후 새로고침해 주세요. 확보되지 않은 수치는 표시하지 않습니다.';
      $('#freshness').textContent='데이터를 불러오지 못해 갱신 시각을 확인할 수 없습니다.';
      $('#collection-status').textContent='기록 불러오기 실패';
      console.error('Observation data could not be loaded.');
    }
  }
  init();
})();

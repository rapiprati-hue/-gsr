/* oriori_gsr v2 — 빌드 없는 순수 JS 프론트엔드.
   /            운영자(노트북, localhost)   : 대시보드 · 진행(대본) · 결과 · 데이터 · 가이드 · 설정
   /tablet      참가자(태블릿)              : 동의 · 응답 · 결과 · 평가
   /result/<id> 영수증(브라우저 인쇄/PDF)                                                     */
(() => {
  'use strict';
  const root = document.getElementById('root');
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const LABELS = { O: '개방성', C: '성실성', E: '외향성', A: '우호성', N: '정서 민감성' };
  const SCALE = ['전혀 아니다', '아닌 편이다', '보통이다', '그런 편이다', '매우 그렇다'];
  const STATUS = { waiting: ['동의 대기', ''], consented: ['동의 완료 · 시작 대기', 'warn'], running: ['진행 중', 'accent'], completed: ['완료', 'ok'], stopped: ['중단', 'bad'] };
  const CAT = { big5: 'Big5 문항', gaze_direct: '눈맞춤 (직접)', gaze_averted: '시선 회피', question_neutral: '중립 질문', question_self: '자기 참조 질문', question_social: '사회적 평가 질문', interview_lack: '결핍', interview_filled: '충만', interview_meaning: '의미' };

  let toastTimer;
  function toast(msg, error) {
    $$('.toast').forEach(t => t.remove());
    const el = document.createElement('div');
    el.className = 'toast' + (error ? ' error' : '');
    el.textContent = msg;
    document.body.appendChild(el);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.remove(), error ? 5000 : 2600);
  }
  async function api(url, method = 'GET', body) {
    const r = await fetch(url, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    let data = {};
    try { data = await r.json(); } catch { /* empty */ }
    if (!r.ok) { const e = new Error(data.error || `요청 실패 (${r.status})`); e.status = r.status; throw e; }
    return data;
  }
  const patch = (sid, body) => api(`/api/sessions/${sid}`, 'PATCH', body);
  const fmtTime = iso => iso ? new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) : '—';
  const mmss = ms => { const s = Math.max(0, Math.floor(ms / 1000)); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
  const word = z => z == null ? '기록 없음' : z >= 1.5 ? '뚜렷하게 올라감' : z >= .5 ? '조금 올라감' : z <= -.5 ? '오히려 가라앉음' : '큰 변화 없음';

  let audio;
  function beep(freq = 880, ms = 120) {
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      const o = audio.createOscillator(), g = audio.createGain();
      o.frequency.value = freq; o.connect(g); g.connect(audio.destination);
      g.gain.setValueAtTime(.12, audio.currentTime); g.gain.exponentialRampToValueAtTime(.0001, audio.currentTime + ms / 1000);
      o.start(); o.stop(audio.currentTime + ms / 1000);
    } catch { /* 오디오 없어도 진행 */ }
  }

  function drawSignal(canvas, samples, marks = []) {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth || 300, h = canvas.clientHeight || 120;
    if (canvas.width !== w * dpr) { canvas.width = w * dpr; canvas.height = h * dpr; }
    const ctx = canvas.getContext && canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!samples || samples.length < 2) { ctx.fillStyle = '#999'; ctx.font = '12px sans-serif'; ctx.fillText('신호 없음', 10, 20); return; }
    const vals = samples.map(s => s.adc);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (hi - lo < 400) { const m = (hi + lo) / 2; lo = m - 200; hi = m + 200; }
    ctx.strokeStyle = '#bd6a48'; ctx.lineWidth = 1.6; ctx.beginPath();
    samples.forEach((s, i) => { const x = i / (samples.length - 1) * w, y = h - 8 - (s.adc - lo) / (hi - lo) * (h - 16); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke();
    ctx.fillStyle = '#888'; ctx.font = '11px sans-serif';
    ctx.fillText(String(hi), 6, 12); ctx.fillText(String(lo), 6, h - 4);
    ctx.fillText(`${vals[vals.length - 1]}`, w - 52, 12);
  }
  function bars(scores) {
    return Object.keys(LABELS).map(k => { const v = scores?.[k]; return `<div class="bar"><span>${LABELS[k]}</span><div class="t"><i style="width:${v ?? 0}%"></i></div><span class="right">${v ?? '—'}</span></div>`; }).join('');
  }
  function reportHtml(s, forTablet) {
    const r = s.report || {};
    if (s.reportPending) return `<div class="report"><p class="muted">Claude 가 오늘의 기록을 문장으로 옮기고 있어요… (운영 화면에서 생성 중)</p></div>`;
    return `<div class="report">${r.title ? `<div class="title">${esc(r.title)}</div>` : ''}<p>${esc(r.character)}</p>${r.lackMeaning ? `<p>${esc(r.lackMeaning)}</p>` : ''}${r.oneLine ? `<p class="one">“${esc(r.oneLine)}”</p>` : ''}
      ${forTablet ? '' : `<p class="tiny muted">출처: ${r.source === 'claude' ? 'Claude · ' + esc(r.model) : r.source === 'rules-fallback' ? '규칙 문장 (Claude 실패: ' + esc(r.error || '') + ')' : '규칙 문장'}</p>`}</div>`;
  }

  // ======================================================================= 운영자
  function operatorApp() {
    const state = { ws: null, view: 'dash', timers: [] };
    const nav = [['dash', '대시보드'], ['data', '데이터'], ['guide', '준비 가이드'], ['settings', '설정']];
    function route() {
      const h = location.hash.replace('#', '') || 'dash';
      const [view, id] = h.split('/');
      state.view = view; state.id = id;
      state.timers.forEach(clearInterval); state.timers = [];
      document.onkeydown = null;
      render();
    }
    window.addEventListener('hashchange', route);
    async function loadWs() {
      try { state.ws = await api('/api/workspace'); state.denied = false; }
      catch (e) { state.denied = e.status === 403 ? e.message : null; if (!state.denied) toast(e.message, true); }
    }
    function shell(inner, title, sub) {
      const ws = state.ws;
      root.innerHTML = `<div class="shell"><aside class="side"><div class="brand">oriori_gsr<small>LIVE SOCIAL · GSR BOOTH</small></div>
        <nav class="nav">${nav.map(([k, n]) => `<a href="#${k}" class="${state.view === k ? 'on' : ''}">${n}</a>`).join('')}</nav>
        <div class="foot">${ws ? `<div><span class="dot ${ws.devices.pico ? 'on' : 'bad'}"></span>Pico ${ws.settings.demo ? '데모(합성)' : ws.devices.pico ? '연결됨' : '미연결'}</div><div><span class="dot ${ws.llmAvailable ? 'on' : ''}"></span>Claude ${ws.llmAvailable ? 'ON' : 'OFF'}</div><div class="tiny" style="margin-top:6px">v${ws.version} · ${ws.settings.demo ? 'demo' : 'hardware'} 모드</div>` : ''}</div></aside>
        <main class="main">${title ? `<div class="page-title">${title}</div><div class="page-sub">${sub || ''}</div>` : ''}${inner}</main></div>`;
    }
    async function render() {
      if (!state.ws) await loadWs();
      if (state.denied) { root.innerHTML = `<div class="tablet"><div class="tcard"><h1>운영 화면은 노트북에서만</h1><p class="lead">${esc(state.denied)}</p></div></div>`; return; }
      if (!state.ws) { root.innerHTML = '<div class="main">서버에 연결할 수 없어요. 앱 창이 켜져 있는지 확인하세요.</div>'; return; }
      ({ dash, run, result, data, guide, settings }[state.view] || dash)();
    }

    // ------------------------------------------------------------- 대시보드
    async function dash() {
      await loadWs();
      const ws = state.ws, today = new Date().toDateString();
      const done = ws.sessions.filter(s => s.status === 'completed' && new Date(s.createdAt).toDateString() === today);
      const revenue = done.reduce((a, s) => a + (s.price || 0), 0);
      shell(`
        <div class="grid3">
          <div class="card stat"><div class="v">${done.length}</div><div class="k">오늘 완료한 검사</div></div>
          <div class="card stat"><div class="v">${revenue.toLocaleString()}원</div><div class="k">완료 코스 가격 합계 (${ws.settings.demo ? '데모' : '결제 확인은 직접'})</div></div>
          <div class="card stat"><div class="v"><span class="dot ${ws.devices.pico ? 'on' : 'bad'}"></span>${ws.settings.demo ? '데모' : ws.devices.pico ? '수신 중' : '끊김'}</div><div class="k">센서 · <canvas class="live" id="mini" style="height:44px;margin-top:6px"></canvas></div></div>
        </div>
        <div class="card" style="margin-top:14px"><div class="row between"><div><h2>검사 세션</h2><div class="small muted">새 검사 → 태블릿 QR → 동의 → 진행 화면에서 대본대로.</div></div><button class="btn primary big" id="new">＋ 새 검사 시작</button></div>
          <table style="margin-top:14px"><thead><tr><th>ID</th><th>코스</th><th>상태</th><th>시간</th><th>Claude 동의</th><th>평가</th><th></th></tr></thead><tbody>
          ${ws.sessions.length ? ws.sessions.map(s => `<tr class="clickable" data-id="${s.id}" data-status="${s.status}"><td class="mono">${s.code}</td><td>${esc(s.courseName)}</td><td><span class="badge ${STATUS[s.status]?.[1]}">${STATUS[s.status]?.[0] || s.status}</span></td><td>${fmtTime(s.createdAt)}</td><td>${s.aiConsent ? '예' : '—'}</td><td>${s.feedback ? s.feedback.accuracy + '/5' : '—'}</td><td class="right"><button class="btn small go">${s.status === 'completed' ? '결과' : s.status === 'stopped' ? '보기' : '진행 화면'}</button></td></tr>`).join('') : '<tr><td colspan="7" class="muted">아직 세션이 없어요. 새 검사를 시작하세요.</td></tr>'}
          </tbody></table></div>`, '운영 대시보드', `태블릿 주소 <span class="mono">${ws.tabletBase}/tablet</span> · 노트북과 태블릿은 같은 핫스팟`);
      $('#new').onclick = newSessionModal;
      $$('tr.clickable .go').forEach(b => b.onclick = e => { const tr = e.target.closest('tr'); location.hash = (tr.dataset.status === 'completed' || tr.dataset.status === 'stopped' ? 'result/' : 'run/') + tr.dataset.id; });
      const mini = $('#mini');
      const tick = async () => { try { const s = await api('/api/sensor'); drawSignal(mini, s.samples.slice(-200)); } catch { /* ignore */ } };
      tick(); state.timers.push(setInterval(tick, 500), setInterval(async () => { await loadWs(); if (state.view === 'dash') { /* 표만 갱신 */ dash(); } }, 8000));
    }
    function newSessionModal() {
      const ws = state.ws; let course = 'social', created = null;
      const bg = document.createElement('div'); bg.className = 'modal-bg';
      const draw = () => {
        bg.innerHTML = `<div class="modal">${created ? `
          <h2 style="font-size:20px">세션 ${created.code} 준비 완료</h2><p class="muted small">태블릿에서 QR 을 찍으면 동의 화면이 열립니다. 동의가 끝나면 진행 화면에서 '측정 시작'.</p>
          <div class="row" style="margin-top:16px;gap:24px;align-items:flex-start"><div class="qr"><img src="/api/qr?text=${encodeURIComponent(created.tabletUrl)}" width="180" height="180" alt="QR"></div>
          <div class="grow"><label class="field">참가자(태블릿) 주소</label><input type="text" readonly value="${esc(created.tabletUrl)}" onclick="this.select()"><div class="row" style="margin-top:12px"><a class="btn" href="${esc(created.tabletUrl)}" target="_blank">이 기기에서 태블릿 화면 열기 (테스트용)</a><button class="btn primary" id="gorun">진행 화면으로 →</button></div></div></div>` : `
          <h2 style="font-size:20px">어떤 코스로 진행할까요?</h2><p class="muted small">${ws.settings.demo ? '데모 모드: 합성 신호, 짧은 타이머.' : '실제 측정: 센서 연결과 참가자 동의를 먼저 확인.'}</p>
          <div class="grid3" style="margin-top:16px">${Object.entries(ws.courses).map(([k, c]) => `<div class="course ${course === k ? 'sel' : ''}" data-k="${k}"><div class="row between"><span class="n">${esc(c.name)}</span><span class="p">${(ws.settings.prices[k] || 0).toLocaleString()}원</span></div><div class="small muted">약 ${c.minutes}분</div><ul>${c.includes.map(i => `<li>${esc(i)}</li>`).join('')}</ul></div>`).join('')}</div>
          <div class="row between" style="margin-top:18px"><button class="btn ghost" id="close">닫기</button><button class="btn primary big" id="create">세션 만들기</button></div>`}</div>`;
        $$('.course', bg).forEach(c => c.onclick = () => { course = c.dataset.k; draw(); });
        const close = $('#close', bg); if (close) close.onclick = () => bg.remove();
        const cr = $('#create', bg); if (cr) cr.onclick = async () => { cr.disabled = true; try { const s = await api('/api/sessions', 'POST', { course }); created = { ...s, tabletUrl: `${ws.tabletBase}/tablet?session=${s.id}` }; draw(); } catch (e) { toast(e.message, true); cr.disabled = false; } };
        const go = $('#gorun', bg); if (go) go.onclick = () => { bg.remove(); location.hash = 'run/' + created.id; };
      };
      draw(); document.body.appendChild(bg);
    }

    // ------------------------------------------------------------- 진행(대본) 화면
    async function run() {
      const sid = state.id; let s, script, lastStep = null, stepLocal = 0, timerDone = false, advancing = false;
      try { s = await api(`/api/sessions/${sid}?script=1`); script = s.script; } catch (e) { toast(e.message, true); location.hash = 'dash'; return; }
      if (s.status === 'completed' || s.status === 'stopped') { location.hash = 'result/' + sid; return; }
      const tabletUrl = `${state.ws.tabletBase}/tablet?session=${sid}`;
      shell(`<div class="row between" style="margin-bottom:14px"><div><div class="page-title" style="margin:0">${s.code} · ${esc(s.courseName)}</div><div class="muted small">${s.demo ? '데모(합성 신호)' : '실제 측정'} · 총 ${script.length}단계 · <span id="elapsed">00:00</span></div></div>
        <div class="row"><span class="badge" id="pstatus"></span><button class="btn danger" id="stop">중단</button></div></div>
        <div class="runner"><div><div class="card step-card" id="step"></div></div>
        <div><div class="card"><h3>실시간 신호 <span class="tiny muted" id="sig"></span></h3><canvas class="live" id="live"></canvas><div class="tiny muted" style="margin-top:6px">기준선 대비 상대 변화만 봅니다. 값 자체는 보정 전 ADC.</div></div>
        <div class="card"><h3>참가자 태블릿</h3><div id="tab" class="small"></div><details style="margin-top:8px"><summary class="small muted">QR / 주소</summary><div class="qr" style="margin-top:8px"><img src="/api/qr?text=${encodeURIComponent(tabletUrl)}" width="140" height="140"></div><div class="tiny mono" style="word-break:break-all">${esc(tabletUrl)}</div></details></div>
        <div class="card"><h3>단계</h3><div class="steps-list" id="list"></div></div>
        <div class="card small"><b>단축키</b><br><span class="kbd">Enter</span> 다음 &nbsp; <span class="kbd">Space</span> 질문끝/답변시작/답변끝 &nbsp; <span class="kbd">1</span>~<span class="kbd">5</span> 응답 대신 입력</div></div></div>`);
      const stepEl = $('#step'), live = $('#live');
      const refresh = async () => { try { const n = await api(`/api/sessions/${sid}`); s = { ...n, script }; } catch { /* keep */ } };
      const syncLocal = () => { stepLocal = performance.now() - Math.max(0, (s.hostMs || 0) - (s.stepStartedMs || 0)); timerDone = false; };
      const setStep = async index => {
        if (advancing || index < 0 || index >= script.length) return; advancing = true;
        try { s = { ...(await patch(sid, { action: 'step', index })), script }; stepLocal = performance.now(); timerDone = false; drawStep(true); }
        catch (e) { toast(e.message, true); } finally { advancing = false; }
      };
      const next = () => { const st = script[s.step]; if (st.kind === 'end') return complete(); if (st.kind === 'big5' && s.answers[st.id] == null && !confirm('아직 응답이 없어요. 결측으로 두고 넘어갈까요?')) return; setStep(s.step + 1); };
      const complete = async () => { if (advancing) return; advancing = true; try { await patch(sid, { action: 'complete' }); toast('측정 완료. 결과를 계산했어요.'); location.hash = 'result/' + sid; } catch (e) { toast(e.message, true); advancing = false; } };
      const mark = async () => {
        const st = script[s.step]; if (!st || !['question', 'interview'].includes(st.kind)) return;
        const m = s.marks?.[st.id] || {}; const kind = !m.asked_end ? 'asked_end' : !m.answer_start ? 'answer_start' : !m.answer_end ? 'answer_end' : null;
        if (!kind) return; try { s = { ...(await patch(sid, { action: 'mark', kind, questionId: st.id })), script }; beep(kind === 'asked_end' ? 660 : 520, 60); updateDynamic(); } catch (e) { toast(e.message, true); }
      };
      const answer = async v => { const st = script[s.step]; if (!st || st.kind !== 'big5') return; try { s = { ...(await patch(sid, { action: 'answer', itemId: st.id, value: v, source: 'operator' })), script }; drawStep(); } catch (e) { toast(e.message, true); } };
      let noteTimer;
      const saveNote = (qid, text) => { clearTimeout(noteTimer); noteTimer = setTimeout(() => patch(sid, { action: 'note', questionId: qid, text }).then(n => { s.notes = n.notes; }).catch(e => toast(e.message, true)), 400); };

      function drawStep(force) {
        $('#pstatus').textContent = STATUS[s.status]?.[0] || s.status;
        const idx = s.step, st = script[idx];
        $('#tab').innerHTML = s.status === 'waiting' ? '<span class="badge warn">동의 대기</span> 태블릿에서 QR 을 열어 동의를 받아 주세요.' : `<span class="badge ok">동의 완료</span> Claude 전송 동의: <b>${s.aiConsent ? '예' : '아니오'}</b>${st?.kind === 'big5' ? ` · 이 문항 응답: <b>${s.answers?.[st.id] ?? '없음'}</b>` : ''}`;
        $('#list').innerHTML = script.map((x, i) => `<div class="${i === idx ? 'now' : ''}" data-i="${i}">${i + 1}. ${esc(x.title)}</div>`).join('');
        $$('#list div').forEach(d => d.onclick = () => { if (s.status === 'running' && confirm(`${+d.dataset.i + 1}번 단계로 이동할까요? (이벤트에 기록됩니다)`)) setStep(+d.dataset.i); });
        const nowEl = $('#list .now'); if (nowEl) nowEl.scrollIntoView({ block: 'nearest' });
        if (s.status !== 'running') {
          stepEl.innerHTML = `<div class="step-title">시작 전</div><div class="say">${s.status === 'waiting' ? '참가자가 태블릿에서 동의 항목을 확인하고 있어요.' : '동의가 끝났어요. 센서 밴드를 준비하고 측정을 시작하세요.'}</div>
            <div class="tip">시작을 누르는 순간부터 원시 신호가 저장됩니다. 첫 단계는 인사 대본이에요. 그동안 센서 밴드를 감으면 됩니다.</div>
            <div class="controls"><button class="btn primary big" id="start" ${s.status !== 'consented' ? 'disabled' : ''}>측정 시작 →</button><a class="btn" target="_blank" href="${esc(tabletUrl)}">태블릿 화면 열기</a></div>`;
          const b = $('#start'); if (b) b.onclick = async () => { b.disabled = true; try { s = { ...(await patch(sid, { action: 'start' })), script }; stepLocal = performance.now(); drawStep(true); } catch (e) { toast(e.message, true); b.disabled = false; } };
          lastStep = null; return;
        }
        if (!force && lastStep === idx) return updateDynamic();
        lastStep = idx;
        let controls = '';
        if (st.kind === 'big5') {
          const v = s.answers?.[st.id];
          controls = `<div class="scale">${SCALE.map((t, i) => `<button data-v="${i + 1}" class="${v === i + 1 ? 'sel' : ''}">${i + 1}<small>${t}</small></button>`).join('')}</div><div class="row between" style="width:100%"><span class="small muted">${v ? '응답 기록됨' : '응답 대기 (태블릿 또는 1~5 키)'}</span><button class="btn primary" id="next">다음 <span class="kbd">Enter</span></button></div>`;
        } else if (st.kind === 'timer') {
          controls = `<div class="timer" id="timer">${mmss(st.duration * 1000)}</div><button class="btn primary" id="next">다음 <span class="kbd">Enter</span></button>${st.auto ? '<span class="small muted">자동으로 넘어갑니다</span>' : ''}`;
        } else if (st.kind === 'gaze') {
          controls = `<div class="gaze-flag ${st.direction}">${st.direction === 'direct' ? '👁 지금 눈을 맞추세요' : '↘ 지금 화면을 보세요'}</div><div class="timer" id="timer">00:05</div><span class="small muted">5초 후 자동으로 휴식 단계로 넘어갑니다</span>`;
        } else if (st.kind === 'question' || st.kind === 'interview') {
          const m = s.marks?.[st.id] || {};
          const lat = m.asked_end && m.answer_start ? `${((m.answer_start - m.asked_end) / 1000).toFixed(1)}초 뜸` : '';
          controls = `<div class="marks"><span class="m ${m.asked_end ? 'done' : ''}">① 질문 끝</span><span class="m ${m.answer_start ? 'done' : ''}">② 답변 시작 ${lat ? '· ' + lat : ''}</span><span class="m ${m.answer_end ? 'done' : ''}">③ 답변 끝</span><button class="btn" id="mark">표시 <span class="kbd">Space</span></button></div>
            ${st.kind === 'interview' ? `<div style="width:100%"><label class="field">참가자 답변 메모 (키워드 · 참가자 표현 그대로 · 이름/학교 금지)</label><textarea id="note" placeholder="예: 시간이 부족 / 혼자 있는 시간 / 그림 그릴 때">${esc(s.notes?.[st.id] || '')}</textarea></div>` : ''}
            <button class="btn primary" id="next" style="margin-left:auto">다음 <span class="kbd">Enter</span></button>`;
        } else if (st.kind === 'end') {
          controls = `<button class="btn green big" id="done">측정 완료 · 결과 계산</button>`;
        } else {
          controls = `<button class="btn primary" id="next">다음 <span class="kbd">Enter</span></button>`;
        }
        stepEl.innerHTML = `<div class="row between"><div class="step-title">${idx + 1} / ${script.length} · ${esc(st.title)}</div>${st.category ? `<span class="badge">${CAT[st.category] || st.category}</span>` : ''}</div>
          <div class="say ${st.kind === 'big5' ? 'item' : ''}">${esc(st.say)}</div><div class="tip">${esc(st.tip)}</div><div class="controls">${controls}</div>
          <div class="progress">${script.map((_, i) => `<i class="${i < idx ? 'done' : i === idx ? 'now' : ''}"></i>`).join('')}</div>
          <div class="row" style="margin-top:10px"><button class="btn ghost small" id="prev" ${idx === 0 ? 'disabled' : ''}>← 이전 단계</button></div>`;
        const n = $('#next'); if (n) n.onclick = next;
        const d = $('#done'); if (d) d.onclick = complete;
        const p = $('#prev'); if (p) p.onclick = () => setStep(idx - 1);
        const mk = $('#mark'); if (mk) mk.onclick = mark;
        $$('.scale button', stepEl).forEach(b => b.onclick = () => answer(+b.dataset.v));
        const note = $('#note'); if (note) note.oninput = () => saveNote(st.id, note.value);
        if (st.kind === 'gaze') beep(880, 150);
        updateDynamic();
      }
      function updateDynamic() {
        const st = script[s.step]; if (!st) return;
        if (st.duration) {
          const remain = st.duration * 1000 - (performance.now() - stepLocal), t = $('#timer');
          if (t) { t.textContent = mmss(remain); if (remain <= 0) t.classList.add('done'); }
          if (remain <= 0 && !timerDone) { timerDone = true; if (st.kind === 'gaze') beep(440, 200); if (st.auto) setStep(s.step + 1); }
        }
        if (st.kind === 'question' || st.kind === 'interview') {
          const m = s.marks?.[st.id] || {}, els = $$('.marks .m', stepEl);
          if (els.length === 3) { els[0].classList.toggle('done', !!m.asked_end); els[1].classList.toggle('done', !!m.answer_start); els[2].classList.toggle('done', !!m.answer_end); els[1].textContent = '② 답변 시작' + (m.asked_end && m.answer_start ? ` · ${((m.answer_start - m.asked_end) / 1000).toFixed(1)}초 뜸` : ''); }
        }
        if (st.kind === 'big5') { const v = s.answers?.[st.id]; $$('.scale button', stepEl).forEach(b => b.classList.toggle('sel', +b.dataset.v === v)); const m = $('.controls .muted', stepEl); if (m) m.textContent = v ? '응답 기록됨' : '응답 대기 (태블릿 또는 1~5 키)'; }
      }
      document.onkeydown = e => {
        if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); next(); } return; }
        if (s.status !== 'running') return;
        if (e.key === 'Enter') { e.preventDefault(); next(); }
        else if (e.key === ' ') { e.preventDefault(); mark(); }
        else if (/^[1-5]$/.test(e.key)) answer(+e.key);
      };
      $('#stop').onclick = async () => { if (!confirm('측정을 중단할까요? 지금까지의 원시 데이터는 보존됩니다.')) return; try { await patch(sid, { action: 'stop' }); location.hash = 'result/' + sid; } catch (e) { toast(e.message, true); } };
      if (s.status === 'running') syncLocal();
      drawStep(true);
      state.timers.push(setInterval(async () => {
        const prevStep = s.step, prevStatus = s.status, prevAns = JSON.stringify(s.answers);
        await refresh();
        if (s.status === 'stopped') { toast('참가자가 중단했어요.'); location.hash = 'result/' + sid; return; }
        if (s.status === 'completed') { location.hash = 'result/' + sid; return; }
        if (s.status !== prevStatus || s.step !== prevStep) { if (s.step !== prevStep || s.status === 'running') syncLocal(); drawStep(true); }
        else if (JSON.stringify(s.answers) !== prevAns) drawStep(true);
        if (s.hostMs != null) $('#elapsed').textContent = mmss(s.hostMs);
      }, 1000), setInterval(async () => { try { const x = await api('/api/sensor'); drawSignal(live, x.samples); $('#sig').textContent = x.connected ? '수신 중' : (x.error || '신호 없음'); } catch { /* ignore */ } }, 250), setInterval(updateDynamic, 200));
    }

    // ------------------------------------------------------------- 결과
    async function result() {
      const sid = state.id; let s;
      try { s = await api(`/api/sessions/${sid}`); } catch (e) { toast(e.message, true); location.hash = 'dash'; return; }
      const ws = state.ws, m = s.metrics || {}, cz = m.categoryZ || {};
      const canClaude = s.course === 'deep' && s.aiConsent && ws.llmAvailable && s.status === 'completed';
      shell(`<div class="row between" style="margin-bottom:14px"><div><div class="page-title" style="margin:0">${s.code} · ${esc(s.courseName)} <span class="badge ${STATUS[s.status]?.[1]}">${STATUS[s.status]?.[0]}</span></div><div class="muted small">${s.demo ? '데모 · 합성 데이터' : '실제 측정'} · ${fmtTime(s.createdAt)} 시작 · Claude 동의 ${s.aiConsent ? '예' : '아니오'}</div></div>
        <div class="row"><a class="btn" href="/result/${sid}" target="_blank">영수증 열기 · 브라우저 인쇄/PDF</a>${ws.settings.printer !== 'browser' ? '<button class="btn" id="print">프린터로 전송</button>' : ''}<button class="btn danger" id="del">삭제</button></div></div>
        ${s.status !== 'completed' ? `<div class="card"><h2>${s.status === 'stopped' ? '중단된 세션' : '아직 완료되지 않은 세션'}</h2><p class="muted">원시 데이터는 보존되어 있습니다. ${s.status === 'stopped' ? '' : '<a href="#run/' + sid + '">진행 화면으로</a>'}</p></div>` : `
        <div class="grid2"><div class="card"><h2>Big5 자기보고 <span class="tiny muted">Mini-IPIP 20 · 0–100 환산 · 백분위 아님</span></h2>${bars(s.scores)}<div class="small muted" style="margin-top:8px">4글자 참고 표기 <b>${s.referenceType || '—'}</b> (공식 MBTI 아님) · 결측 ${Object.values(s.scoreMissing || {}).reduce((a, b) => a + b, 0)}문항 · 문항 응답 중앙 지연 ${m.big5LatencyMedianMs ?? '—'} ms</div></div>
        <div class="card"><h2>몸의 반응 <span class="tiny muted">기준선 SD 단위 z · 이벤트 후 1–6초 최대 편차</span></h2>
          <table><thead><tr><th>상황</th><th>z</th><th>말로</th></tr></thead><tbody>${Object.keys(CAT).filter(k => cz[k] != null).map(k => `<tr><td>${CAT[k]}</td><td class="mono">${cz[k]}</td><td>${word(cz[k])}</td></tr>`).join('') || '<tr><td colspan="3" class="muted">이벤트 없음</td></tr>'}</tbody></table>
          <div class="small muted" style="margin-top:8px">대비: ${Object.entries(m.contrasts || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || '—'}<br>기준선 ${m.baseline} ± ${m.baselineSd} · 품질 ${m.quality}% · ${m.observedHz} Hz · 누락 seq ${m.missingSequenceCount} · 극성 ${m.polarity}</div></div></div>
        <div class="grid2" style="margin-top:14px"><div class="card"><h2>질문별 반응시간 · 메모</h2><table><thead><tr><th>질문</th><th>뜸(ms)</th><th>z</th><th>메모</th></tr></thead><tbody>${(s.responses || []).filter(r => !r.category.startsWith('big5')).map(r => `<tr><td>${CAT[r.category] || r.category}</td><td class="mono">${r.latencyMs ?? '—'}</td><td class="mono">${r.z ?? '—'}</td><td class="small">${esc(r.note || '')}</td></tr>`).join('') || '<tr><td colspan="4" class="muted">기본 코스에는 질문 과제가 없어요</td></tr>'}</tbody></table></div>
        <div class="card"><div class="row between"><h2>결과 문장</h2>${canClaude ? `<button class="btn primary" id="gen">${s.report?.source === 'claude' ? 'Claude 로 다시 생성' : 'Claude 로 서사 생성'}</button>` : ''}</div><div id="rep">${reportHtml(s)}</div>
          ${s.feedback ? `<div class="small" style="margin-top:12px;padding-top:10px;border-top:1px solid var(--line)">참가자 평가 <b>${s.feedback.accuracy}/5</b>${s.feedback.resonant ? ` · 와닿은 문장: “${esc(s.feedback.resonant)}”` : ''}</div>` : '<div class="tiny muted" style="margin-top:10px">참가자 평가는 태블릿 결과 화면에서 입력됩니다.</div>'}
          ${!canClaude && s.course === 'deep' ? `<div class="tiny muted" style="margin-top:8px">${!s.aiConsent ? '참가자가 Claude 전송에 동의하지 않아 규칙 문장을 사용합니다.' : !ws.llmAvailable ? '.env 에 ANTHROPIC_API_KEY 가 없어 규칙 문장을 사용합니다.' : ''}</div>` : ''}</div></div>
        <div class="card" style="margin-top:14px"><div class="row" style="gap:8px"><b class="small">이 세션 내보내기</b><a class="btn small" href="/api/export?kind=sessions&id=${sid}">요약 CSV</a><a class="btn small" href="/api/export?kind=responses&id=${sid}">이벤트별 반응 CSV</a><a class="btn small" href="/api/export?kind=raw&id=${sid}">원시 신호 CSV</a><a class="btn small" href="/api/export?kind=events&id=${sid}">이벤트 CSV</a><a class="btn small" href="/api/export?format=json&id=${sid}">전체 JSON</a></div></div>`}`,
      );
      const gen = async () => { const b = $('#gen'); if (b) { b.disabled = true; b.textContent = 'Claude 생성 중…'; } try { const r = await api(`/api/sessions/${sid}/report`, 'POST', {}); s.report = r.report; s.reportPending = false; $('#rep').innerHTML = reportHtml(s); toast(r.report.source === 'claude' ? 'Claude 서사를 생성했어요. 내용을 확인하고 인쇄하세요.' : '규칙 문장으로 대체했어요: ' + (r.report.error || ''), r.report.source !== 'claude'); } catch (e) { toast(e.message, true); } finally { if (b) { b.disabled = false; b.textContent = 'Claude 로 다시 생성'; } } };
      const g = $('#gen'); if (g) g.onclick = gen;
      if (s.reportPending && canClaude) gen();
      const p = $('#print'); if (p) p.onclick = async () => { try { const r = await api(`/api/sessions/${sid}/print`, 'POST', { paperWidth: ws.settings.paperWidth }); toast(r.browser ? '브라우저 인쇄 모드입니다. 영수증 열기를 사용하세요.' : '프린터로 전송했어요.'); } catch (e) { toast(e.message, true); } };
      $('#del').onclick = async () => { if (!confirm(`${s.code} 의 응답·원시 신호·이벤트를 영구 삭제할까요?`)) return; try { await api(`/api/sessions/${sid}`, 'DELETE'); toast('삭제했어요.'); location.hash = 'dash'; } catch (e) { toast(e.message, true); } };
      state.timers.push(setInterval(async () => { try { const n = await api(`/api/sessions/${sid}`); if (JSON.stringify(n.feedback) !== JSON.stringify(s.feedback)) { s = n; result(); } } catch { /* ignore */ } }, 4000));
    }

    // ------------------------------------------------------------- 데이터
    function data() {
      const n = state.ws.sessions.length, done = state.ws.sessions.filter(s => s.status === 'completed').length;
      shell(`<div class="card"><h2>내보내기 <span class="tiny muted">CSV = 엑셀에서 더블클릭으로 바로 열리는 표 (UTF-8 BOM 포함, 한글 깨짐 없음)</span></h2>
        <table><tbody>
        <tr><td><b>요약 CSV</b><div class="small muted">세션 1행: 코스, Big5 5점수, 4글자, 문항 20개 응답, 상황별 z, 반응시간 중앙값, 서사 출처, 참가자 평가</div></td><td class="right"><a class="btn" href="/api/export?kind=sessions">내려받기</a></td></tr>
        <tr><td><b>이벤트별 반응 CSV</b> ← 논문용 핵심 표<div class="small muted">자극 1행: 세션, 범주(눈맞춤 직접/회피, 질문 유형…), 반응 진폭, z, 뜸(ms), 응답, 메모 → 범주 간 비교/혼합모형에 바로 사용</div></td><td class="right"><a class="btn" href="/api/export?kind=responses">내려받기</a></td></tr>
        <tr><td><b>원시 신호 CSV</b><div class="small muted">20Hz ADC 전부 (세션당 수천 행). 재분석·SCR 분해용</div></td><td class="right"><a class="btn" href="/api/export?kind=raw">내려받기</a></td></tr>
        <tr><td><b>이벤트 CSV</b><div class="small muted">단계 시작, 질문끝/답변시작/답변끝, 응답, 동의, 중단, 서사 생성 로그. 원시와 같은 시계(hostElapsedMs)</div></td><td class="right"><a class="btn" href="/api/export?kind=events">내려받기</a></td></tr>
        <tr><td><b>전체 JSON</b><div class="small muted">위 전부 + 서사 원문·프롬프트 버전·모델명. 백업용</div></td><td class="right"><a class="btn" href="/api/export?format=json">내려받기</a></td></tr></tbody></table>
        <p class="small muted" style="margin-top:12px">보관 중 ${n}건 (완료 ${done}) · 파일은 <span class="mono">data/&lt;세션ID&gt;/</span> 에 세션별로 저장 · 30일 후 자동 삭제 · 데모(demo=true) 는 분석에서 제외</p></div>
        <div class="card"><h2>분석에서 쓰는 변수 한 줄 요약</h2><ul class="small" style="padding-left:18px;line-height:1.9">
        <li><b>z_baseline</b>: (이벤트 후 1–6초 최대 ADC − 이벤트 직전 1초 평균) ÷ 기준선 60초 표준편차. 참가자 내 표준화라 개인 간 피부 차이를 상쇄.</li>
        <li><b>latency_ms</b>: 운영자가 '질문 끝'을 누른 시각 → '답변 시작'을 누른 시각. 같은 서버 시계. 운영자 반응 지연이 포함되므로 조건 간 비교(within-subject)에만 쓰기.</li>
        <li><b>가설 예시</b>: 눈맞춤(직접) z &gt; 회피 z · 자기/사회평가 질문 z &gt; 중립 z · 사회평가 질문 latency &gt; 중립 · N 높을수록 사회평가 z 큼 · Claude 서사 정확도 평가 vs 규칙 문장 평가.</li></ul></div>`, '데이터', 'raw → events → responses 순으로 재현 가능. 데이터를 보기 전에 가설과 제외 기준을 적어 두세요.');
    }

    // ------------------------------------------------------------- 가이드
    function guide() {
      shell(`<div class="card guide"><h2>당일 순서 (총 90분 여유)</h2><ol>
        <li><b>데모 한 바퀴 (10분)</b> — 지금 이 상태에서 새 검사 → 사회 코스 → 태블릿 화면 열기 → 동의 → 진행 화면에서 Enter/Space 로 끝까지. 결과·영수증·CSV 가 나오면 소프트웨어는 끝.</li>
        <li><b>배선 (전원 뺀 상태, 20분)</b><table class="wire" style="margin:8px 0"><tr><th>모듈</th><th>선</th><th>Pico</th><th>물리 핀</th></tr><tr><td>GSR 모듈</td><td>SIG (아날로그 출력)</td><td>GP26 / ADC0</td><td>31</td></tr><tr><td>GSR 모듈</td><td>VCC</td><td>3V3 OUT (모듈이 3.3V 지원 시)</td><td>36</td></tr><tr><td>GSR 모듈</td><td>GND</td><td>GND</td><td>38</td></tr><tr><td>버튼 KS0029 (선택)</td><td>S</td><td>GP14</td><td>19</td></tr></table>
          <span class="small muted">온습도(DHT11)·사운드는 제외했습니다. GSR 출력이 3.3V 를 넘지 않는지 데이터시트 확인. 5V 신호 직결 금지.</span></li>
        <li><b>Thonny → Pico (10분)</b> — BOOTSEL 누른 채 USB 연결 → MicroPython 펌웨어 설치 → Thonny 에서 <code>pico/main.py</code> 열고 'Raspberry Pi Pico 에 저장' 이름 <code>main.py</code> → 셸에 <code>{"seq":..,"adc":..}</code> 줄이 흐르면 성공 → <b>Thonny 완전 종료</b>.</li>
        <li><b>앱을 하드웨어 모드로 (5분)</b> — 설정 화면에서 포트 선택(COM3 / /dev/tty.usbmodem…) → <code>config.json</code> 의 <code>"mode": "hardware"</code> 로 수정 → 앱 재시작 → 대시보드 센서 그래프가 실제로 움직이는지 확인. USB 를 뽑으면 '끊김'으로 바뀌어야 정상.</li>
        <li><b>극성 확인 (3분, 중요)</b> — 밴드를 내 손가락에 끼우고 그래프를 보며 <b>깊게 숨을 들이쉬고 참기</b>. 몇 초 뒤 그래프가 <b>올라가면</b> 설정의 '각성 시 ADC 상승' 을 켠 채로, <b>내려가면</b> 끄기. (모듈마다 방향이 반대라서 이걸 안 하면 반응 부호가 뒤집힙니다.)</li>
        <li><b>핫스팟 + 태블릿 (5분)</b> — 노트북 개인 핫스팟 켜기 → 태블릿 연결 → 대시보드 상단의 태블릿 주소 열림 확인. 학교 와이파이는 기기 간 통신을 막는 경우가 많음.</li>
        <li><b>Claude (5분)</b> — 폴더의 <code>.env.example</code> 을 <code>.env</code> 로 복사 → <code>ANTHROPIC_API_KEY=sk-ant-…</code> 입력 → 앱 재시작 → 사이드바 'Claude ON'. 키 없어도 규칙 문장으로 전부 진행됩니다. 참가자가 동의한 심층 코스에만 전송.</li>
        <li><b>프린터 (10분)</b> — 제조사 드라이버 설치 → OS 테스트 페이지 → 결과 화면 '영수증 열기' → 브라우저 인쇄에서 프린터 선택, 여백 최소, 머리글/바닥글 끄기. 자동 커터가 꼭 필요할 때만 <code>config.json</code> 의 printer 를 win32/usb 로.</li>
        <li><b>파일럿 2회 (15분)</b> — 친구에게 사회 코스 1회, 심층 코스 1회. 대본을 소리 내어 읽고 Space 타이밍 연습. 밴드 소독. 학교 승인·보호자 동의 확인 후 <code>schoolApprovalConfirmed: true</code>.</li></ol></div>
        <div class="card guide"><h2>운영 중 말버릇 3개</h2><ol><li>"정답은 없어요. 처음 떠오르는 대로요." (Big5 문항마다 고민 길어질 때)</li><li>"괜찮아요, 천천히요." (인터뷰 침묵 — 침묵도 데이터, 재촉 금지)</li><li>"이건 오늘의 기록이지 당신을 정하는 게 아니에요." (결과 보여줄 때)</li></ol></div>
        <div class="card guide"><h2>안 될 때</h2><ol><li>센서 '끊김': Thonny 가 켜져 있음 / 포트 이름 오타 / 케이블이 충전 전용.</li><li>태블릿에서 안 열림: 주소가 localhost 면 안 됨 → 대시보드의 IP 주소 사용 / 핫스팟 다른지 확인 / 방화벽에서 Python 허용.</li><li>Claude 실패: 결과 화면에 사유가 표시되고 규칙 문장으로 진행. 키·잔액·모델명(.env 의 ANTHROPIC_MODEL) 확인.</li><li>진행 중 화면을 새로고침해도 서버가 단계를 기억하므로 이어서 진행됩니다.</li></ol></div>`, '준비 가이드', '이 순서대로 하면 됩니다. 소프트웨어 → 배선 → 펌웨어 → 모드 전환 → 극성 → 네트워크 → Claude → 프린터 → 파일럿.');
    }

    // ------------------------------------------------------------- 설정
    async function settings() {
      await loadWs();
      const st = state.ws.settings; let ports = [];
      try { ports = (await api('/api/ports')).ports; } catch { /* serial 미설치 등 */ }
      shell(`<div class="grid2"><div class="card"><h2>Pico 시리얼</h2><p class="small muted">${st.demo ? '지금은 데모 모드. 실제 센서는 config.json 의 mode 를 hardware 로 바꾼 뒤 재시작.' : '하드웨어 모드.'}</p>
        <label class="field">포트</label><select id="port"><option value="">선택…</option>${ports.map(p => `<option value="${esc(p.device)}" ${p.device === st.serialPort ? 'selected' : ''}>${esc(p.device)} — ${esc(p.description)}</option>`).join('')}${st.serialPort && !ports.some(p => p.device === st.serialPort) ? `<option value="${esc(st.serialPort)}" selected>${esc(st.serialPort)} (현재 설정)</option>` : ''}</select>
        <label class="field">직접 입력</label><input type="text" id="portText" value="${esc(st.serialPort)}" placeholder="COM3 또는 /dev/tty.usbmodem1101">
        <label class="field" style="margin-top:16px"><input type="checkbox" id="pol" ${st.adcRisesWithArousal ? 'checked' : ''}> 각성 시 ADC 상승 (극성) — 가이드 5번으로 확인</label>
        <div class="small muted">학교 승인 확인: <b>${st.schoolApprovalConfirmed ? '완료' : '미완료 (config.json 의 schoolApprovalConfirmed)'}</b></div></div>
        <div class="card"><h2>영수증 프린터</h2><label class="field">출력 방식</label><select id="printer">${[['browser', '브라우저 인쇄 / PDF (기본)'], ['win32', 'Windows RAW ESC/POS'], ['usb', 'USB ESC/POS (VID/PID 는 config.json)'], ['network', '네트워크 ESC/POS (printerHost)']].map(([v, n]) => `<option value="${v}" ${st.printer === v ? 'selected' : ''}>${n}</option>`).join('')}</select>
        <label class="field">감열지 너비</label><select id="paper"><option value="80" ${st.paperWidth == 80 ? 'selected' : ''}>80mm</option><option value="58" ${st.paperWidth == 58 ? 'selected' : ''}>58mm</option></select>
        <h3 style="margin-top:18px">Claude</h3><div class="small">${state.ws.llmAvailable ? `<span class="badge ok">ON</span> 모델 <span class="mono">${esc(state.ws.llmModel)}</span>` : '<span class="badge">OFF</span> .env 에 ANTHROPIC_API_KEY 를 넣고 재시작'}</div><div class="tiny muted" style="margin-top:6px">전송 내용: Big5 점수, 상황별 반응(말로 요약), 질문별 뜸, 운영자 메모. 이름·원음성·원시 신호는 전송하지 않음. 심층 코스 + 참가자 선택 동의 시에만.</div>
        <div class="controls"><button class="btn primary" id="save">설정 저장</button></div></div></div>`, '설정', '측정 중에는 저장이 막힙니다.');
      $('#port').onchange = e => { $('#portText').value = e.target.value; };
      $('#save').onclick = async () => { try { await api('/api/settings', 'PATCH', { serialPort: $('#portText').value.trim(), printer: $('#printer').value, paperWidth: $('#paper').value, adcRisesWithArousal: $('#pol').checked }); toast('저장했어요. 포트 변경은 앱 재시작 후 적용됩니다.'); await loadWs(); } catch (e) { toast(e.message, true); } };
    }
    route();
  }

  // ======================================================================= 참가자(태블릿)
  function tabletApp() {
    const sid = new URLSearchParams(location.search).get('session');
    let s = null, script = null, local = { ai: false, agree: false, fb: null, resonant: null, sent: false }, lastKey = '';
    const card = html => { root.innerHTML = `<div class="tablet"><div class="tcard">${html}</div></div>`; };
    if (!sid) { card('<h1>oriori_gsr</h1><p class="lead">운영자가 보여주는 QR 을 찍으면 이 화면이 열려요.</p>'); return; }
    document.addEventListener('visibilitychange', () => { if (s && s.status === 'running') api(`/api/sessions/${sid}/events`, 'POST', { type: 'visibility', payload: { hidden: document.hidden } }).catch(() => {}); });
    async function poll() {
      try {
        const n = await api(`/api/sessions/${sid}${script ? '' : '?script=1'}`);
        if (n.script) script = n.script;
        s = n; draw();
      } catch (e) { card(`<h1>연결을 확인해 주세요</h1><p class="lead">${esc(e.message)}</p>`); }
    }
    function draw() {
      const st = script?.[s.step];
      const key = JSON.stringify([s.status, s.step, s.answers?.[st?.id], s.reportPending, !!s.report, local]);
      if (key === lastKey) return; lastKey = key;
      if (s.status === 'waiting') {
        card(`<h1>시작하기 전에,<br>약속 몇 가지만 확인해요.</h1><p class="lead">이 체험은 당신을 어떤 유형에 가두는 검사가 아니에요.</p>
          <div class="consent"><div class="item"><div><b>이름 대신 익명 ID 만</b><br>문항 응답, 손가락 피부 전도 신호, 버튼·질문 시각, 운영자가 적는 답변 키워드를 기록해요. 음성은 녹음하지 않아요.</div></div>
          <div class="item"><div><b>정답도 진단도 없어요</b><br>센서는 감정이나 거짓말을 판독하지 않아요. 결과는 오늘의 기록일 뿐이에요.</div></div>
          <div class="item"><div><b>그만하고 싶으면 언제든</b><br>중단할 수 있고, 운영자에게 ID 를 말하면 삭제해 드려요. 보관 30일, 연구 활용은 비활성화.</div></div>
          <label class="item"><input type="checkbox" id="agree" ${local.agree ? 'checked' : ''}><div><b>[필수]</b> 안내를 이해했고 체험과 데이터 저장에 동의해요.</div></label>
          <label class="item"><input type="checkbox" id="ai" ${local.ai ? 'checked' : ''}><div><b>[선택]</b> 요약 점수와 운영자가 적은 답변 키워드를 <b>Anthropic Claude API</b> 로 보내 나만의 결과 문장을 만들어도 좋아요. (이름·음성·원시 신호는 보내지 않아요. API 입력은 기본적으로 모델 학습에 쓰이지 않아요. 심층 코스에서만 사용.)</div></label></div>
          <div class="tiny muted" style="margin:14px 0">미성년자 참여는 학교 승인 및 필요한 보호자 동의를 운영자가 먼저 확인합니다.</div>
          <button class="btn primary big" id="go" ${local.agree ? '' : 'disabled'}>나를 만나러 가기</button>`);
        $('#agree').onchange = e => { local.agree = e.target.checked; lastKey = ''; draw(); };
        $('#ai').onchange = e => { local.ai = e.target.checked; };
        $('#go').onclick = async () => { try { s = await patch(sid, { action: 'consent', aiConsent: local.ai }); lastKey = ''; draw(); } catch (e) { alert(e.message); } };
      } else if (s.status === 'consented') {
        card('<h1>고마워요.</h1><p class="lead">이제 운영자가 손가락에 센서 밴드를 감아 드릴 거예요. 손은 무릎 위에 편하게.</p><div class="fix"></div>');
      } else if (s.status === 'running' && st) {
        const v = st.tablet.view;
        let html = '';
        if (v === 'fixation') html = `<p class="lead">${esc(st.tablet.text)}</p><div class="fix"></div>`;
        else if (v === 'gaze') html = `<p class="lead" style="font-size:22px;margin-top:40px">${esc(st.tablet.text)}</p>`;
        else if (v === 'item') { const a = s.answers?.[st.id]; html = `<div class="small muted">${esc(st.title)}</div><div class="q">${esc(st.tablet.text)}</div><div class="tscale">${SCALE.map((t, i) => `<button data-v="${i + 1}" class="${a === i + 1 ? 'sel' : ''}">${i + 1}<small>${t}</small></button>`).join('')}</div><p class="small muted" style="margin-top:14px">${a ? '기록했어요. 바꾸고 싶으면 다시 눌러도 돼요.' : '평소의 나와 얼마나 비슷한가요?'}</p>`; }
        else if (v === 'question') html = `<div class="small muted">${esc(st.title)}</div><div class="q">${esc(st.tablet.text)}</div><p class="lead">떠오르는 대로, 편하게 말씀해 주세요.</p>`;
        else html = `<p class="lead" style="font-size:20px">${esc(st.tablet.text)}</p>`;
        card(html + `<div class="stopbar no-print"><button class="btn ghost small muted" id="stop">잠깐 멈추고 싶어요</button></div>`);
        $$('.tscale button').forEach(b => b.onclick = async () => { try { s = await patch(sid, { action: 'answer', itemId: st.id, value: +b.dataset.v, source: 'tablet' }); lastKey = ''; draw(); } catch (e) { alert(e.message); } });
        $('#stop').onclick = async () => { if (confirm('검사를 중단할까요? 저장된 데이터는 운영자에게 삭제를 요청할 수 있어요.')) { try { s = await patch(sid, { action: 'stop' }); lastKey = ''; draw(); } catch (e) { alert(e.message); } } };
      } else if (s.status === 'running') {
        card('<p class="lead">준비 중…</p>');
      } else if (s.status === 'completed') {
        const sentences = [s.report?.character, s.report?.lackMeaning].filter(Boolean).join(' ').split(/(?<=[.!?。])\s+/).map(x => x.trim()).filter(x => x.length > 6).slice(0, 8);
        card(`<h1>오늘의 나,<br>잘 만나고 왔나요?</h1>
          <div style="text-align:left;margin:18px 0">${reportHtml(s, true)}</div>
          <div style="text-align:left">${bars(s.scores)}<div class="tiny muted">0–100 은 응답 범위 환산값이에요 (인구 백분위 아님). 4글자 참고 표기 ${s.referenceType || '—'} 는 공식 MBTI 가 아니에요. 센서로 성격이나 감정을 판정하지 않아요.</div></div>
          ${s.feedback || local.sent ? `<div class="thanks">고마워요. 오늘의 기록은 ${s.code} 로 남아요.</div><p class="small muted">삭제를 원하면 운영자에게 이 ID 를 말해 주세요.</p>` : s.reportPending ? '<p class="small muted" style="margin-top:16px">문장이 준비되면 평가를 부탁드릴게요.</p>' : `
          <hr style="border:0;border-top:1px solid var(--line);margin:22px 0"><div style="text-align:left"><b>이 문장들이 오늘의 나와 얼마나 맞나요?</b><div class="tscale" style="margin-top:10px">${['전혀', '조금', '보통', '꽤', '매우'].map((t, i) => `<button data-v="${i + 1}" class="${local.fb === i + 1 ? 'sel' : ''}">${i + 1}<small>${t}</small></button>`).join('')}</div>
          ${sentences.length ? `<div style="margin-top:16px"><b>가장 와닿는 문장 하나 (선택)</b><div class="pick">${sentences.map(x => `<button data-s="${esc(x)}" class="${local.resonant === x ? 'sel' : ''}">${esc(x)}</button>`).join('')}</div></div>` : ''}
          <div class="row" style="margin-top:16px;justify-content:flex-end"><button class="btn primary big" id="send" ${local.fb ? '' : 'disabled'}>보내기</button></div></div>`}`);
        $$('.tscale button').forEach(b => b.onclick = () => { local.fb = +b.dataset.v; lastKey = ''; draw(); });
        $$('.pick button').forEach(b => b.onclick = () => { local.resonant = local.resonant === b.dataset.s ? null : b.dataset.s; lastKey = ''; draw(); });
        const send = $('#send'); if (send) send.onclick = async () => { try { s = await patch(sid, { action: 'feedback', accuracy: local.fb, resonant: local.resonant }); local.sent = true; lastKey = ''; draw(); } catch (e) { alert(e.message); } };
      } else if (s.status === 'stopped') {
        card(`<h1>여기서 쉬어가도 괜찮아요.</h1><p class="lead">측정을 안전하게 중단했어요. 기록 삭제를 원하면 운영자에게 <b>${s.code}</b> 를 알려 주세요.</p>`);
      }
    }
    poll(); setInterval(poll, 500);
  }

  // ======================================================================= 영수증(/result/<id>)
  async function resultApp(sid) {
    let s;
    try { s = await api(`/api/sessions/${sid}`); } catch (e) { root.innerHTML = `<div class="tablet"><div class="tcard"><h1>결과를 찾을 수 없어요</h1><p class="lead">${esc(e.message)}</p></div></div>`; return; }
    const w = new URLSearchParams(location.search).get('w') || s.paperWidth || '80';
    const r = s.report || {}, sm = s.summary || { reactivity: {}, latency: {} };
    root.innerHTML = `<div class="receipt-wrap"><div class="row no-print"><button class="btn primary" onclick="window.print()">인쇄 / PDF 저장</button><a class="btn" href="/result/${sid}?w=${w == 80 ? 58 : 80}">${w == 80 ? '58mm' : '80mm'} 로 보기</a><a class="btn ghost" href="/#result/${sid}">운영 화면</a></div>
      <div class="receipt ${w == 58 ? 'w58' : ''}"><div class="c h">oriori_gsr</div><div class="c tiny">A LITTLE RECORD OF YOU</div><hr>
      <div class="c">${s.code} / ${esc(s.courseName)}</div><div class="c tiny">${s.demo ? 'DEMO / 합성 데이터' : '탐색적 체험 기록'} · ${new Date(s.createdAt).toLocaleDateString('ko-KR')}</div>
      ${r.title ? `<div class="c tiny" style="margin-top:8px">오늘의 나의 캐릭터</div><div class="c rt">${esc(r.title)}</div>` : ''}<hr>
      ${bars(s.scores)}<div class="c tiny">4글자 참고 ${s.referenceType || '—'} · 공식 MBTI 아님 · 0–100 은 응답 환산값</div><hr>
      ${Object.entries(sm.reactivity).map(([k, v]) => `<div>${esc(k)}: <b>${esc(v)}</b></div>`).join('')}${Object.entries(sm.latency).map(([k, v]) => `<div>${esc(k)}: ${esc(v)} 답함</div>`).join('')}
      ${Object.keys(sm.reactivity).length ? '<hr>' : ''}<p>${esc(r.character || '')}</p>${r.lackMeaning ? `<p>${esc(r.lackMeaning)}</p>` : ''}${r.oneLine ? `<p class="c"><b>“${esc(r.oneLine)}”</b></p>` : ''}
      <hr><div class="c tiny">의료·성격 진단이 아닌 탐색용 기록<br>센서값으로 감정을 판독하지 않아요.</div>
      <img src="/api/qr?text=${encodeURIComponent(s.resultUrl)}&public=1" width="110" height="110" alt="QR"><div class="c tiny">YOU ARE MORE THAN A TYPE.</div></div></div>`;
  }

  const p = location.pathname;
  if (p.startsWith('/tablet')) tabletApp(); else if (p.startsWith('/result/')) resultApp(p.split('/')[2]); else operatorApp();
})();

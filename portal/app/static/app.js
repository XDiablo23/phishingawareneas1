/* Awareness & Remediation Portal - single-page app (vanilla JS). */
const App = (() => {
  const K = { emp: 'portal_emp_token', adm: 'portal_admin_token', admMeta: 'portal_admin_meta' };
  const state = { mode: null, empToken: null, adminToken: null, empUser: null, admin: null };
  const $ = (id) => document.getElementById(id);
  const view = () => $('view');

  function esc(s){ return (s==null?'':String(s)).replace(/[&<>"']/g,c=>(
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

  function toast(msg, ms=2600){
    const t=$('toast'); t.textContent=msg; t.classList.remove('hidden');
    clearTimeout(t._h); t._h=setTimeout(()=>t.classList.add('hidden'),ms);
  }

  async function api(path, {method='GET', body=null, token=null, form=null}={}){
    const opt={ method, headers:{} };
    if(token){ opt.headers['Authorization']='Bearer '+token; }
    if(form){ opt.body=form; }
    else if(body!=null){ opt.headers['Content-Type']='application/json'; opt.body=JSON.stringify(body); }
    const r=await fetch(path,opt);
    const txt=await r.text();
    let data; try{ data=txt?JSON.parse(txt):{}; }catch(e){ data={detail:txt}; }
    if(!r.ok){ const msg=(data&&data.detail)?(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail)):('HTTP '+r.status); throw new Error(msg); }
    return data;
  }

  function setChrome(){
    $('modeLabel').textContent = state.mode==='employee' ? '- Employee'
      : state.mode==='admin' ? '- Administrator' : '';
    const signedIn = (state.mode==='employee'&&state.empToken)||(state.mode==='admin'&&state.adminToken);
    $('logoutBtn').classList.toggle('hidden', !signedIn);
    $('who').textContent = state.mode==='employee'&&state.empUser ? state.empUser.email
      : state.mode==='admin'&&state.admin ? state.admin.email : '';
  }

  function logout(){
    if(state.mode==='employee'){ localStorage.removeItem(K.emp); state.empToken=null; state.empUser=null; }
    else if(state.mode==='admin'){ localStorage.removeItem(K.adm); localStorage.removeItem(K.admMeta); state.adminToken=null; state.admin=null; }
    state.mode=null; setChrome(); landing();
  }

  function landing(){
    state.mode=null; setChrome();
    view().innerHTML = `
      <div class="choose">
        <div class="card" onclick="App.enter('employee')">
          <h2>I'm an employee</h2>
          <p class="muted">Do your training, take exams, and acknowledge policies.</p>
        </div>
        <div class="card" onclick="App.enter('admin')">
          <h2>I'm an administrator</h2>
          <p class="muted">Manage training, policies, results and escalations.</p>
        </div>
      </div>`;
  }

  function enter(mode){
    state.mode=mode; setChrome();
    if(mode==='employee'){
      state.empToken=localStorage.getItem(K.emp);
      if(state.empToken){ Emp.dashboard(); } else { Emp.authScreen(); }
    } else {
      state.adminToken=localStorage.getItem(K.adm);
      const meta=localStorage.getItem(K.admMeta);
      if(state.adminToken){ state.admin=meta?JSON.parse(meta):{email:''}; Adm.home(); }
      else { Adm.authScreen(); }
    }
  }

  function boot(){ landing(); }

  return { state, api, esc, toast, view, setChrome, logout, landing, enter, boot, K };
})();


/* ---------------- Employee ---------------- */
const Emp = (() => {
  const api=(p,o={})=>App.api(p,{...o,token:App.state.empToken});

  function authScreen(tab='login'){
    App.view().innerHTML = `
      <div class="card" style="max-width:440px;margin:6vh auto">
        <div class="tabs">
          <div class="tab ${tab==='login'?'active':''}" onclick="Emp.authScreen('login')">Sign in</div>
          <div class="tab ${tab==='register'?'active':''}" onclick="Emp.authScreen('register')">Create account</div>
        </div>
        ${tab==='login'?loginForm():registerForm()}
        <p class="small muted center" style="margin-top:14px"><a onclick="App.landing()"><- back</a></p>
      </div>`;
  }
  const loginForm=()=>`
    <label>Work email</label><input id="le" type="email" placeholder="you@company.com">
    <label>Password</label><input id="lp" type="password">
    <div class="spacer"></div>
    <button class="primary" style="width:100%" onclick="Emp.doLogin()">Sign in</button>`;
  const registerForm=()=>`
    <label>Full name</label><input id="rn" placeholder="Jane Doe">
    <label>Work email</label><input id="re" type="email" placeholder="you@company.com">
    <div class="formgrid">
      <div><label>Department</label><input id="rd" placeholder="Finance"></div>
      <div><label>Job title</label><input id="rj" placeholder="Analyst"></div>
    </div>
    <label>Password (min 6)</label><input id="rp" type="password">
    <div class="spacer"></div>
    <button class="primary" style="width:100%" onclick="Emp.doRegister()">Create account &amp; start training</button>`;

  async function doLogin(){
    try{
      const d=await App.api('/api/portal/auth/login',{method:'POST',body:{email:$id('le').value.trim(),password:$id('lp').value}});
      finishAuth(d);
    }catch(e){ App.toast(e.message); }
  }
  async function doRegister(){
    try{
      const d=await App.api('/api/portal/auth/register',{method:'POST',body:{
        full_name:$id('rn').value.trim(), email:$id('re').value.trim(),
        department:$id('rd').value.trim()||'Unassigned', job_title:$id('rj').value.trim()||'Employee',
        password:$id('rp').value}});
      finishAuth(d); App.toast('Welcome! Start with your onboarding training.');
    }catch(e){ App.toast(e.message); }
  }
  function finishAuth(d){
    App.state.empToken=d.access_token; App.state.empUser=d.user;
    localStorage.setItem(App.K.emp,d.access_token); App.setChrome(); dashboard();
  }
  const $id=(i)=>document.getElementById(i);


  let cache={me:null,assignments:[],policies:[]};

  async function dashboard(tab='training'){
    try{
      const [me,assignments,policies]=await Promise.all([
        api('/api/portal/me'), api('/api/portal/assignments'), api('/api/portal/policies')]);
      App.state.empUser=me; App.setChrome();
      cache={me,assignments,policies};
    }catch(e){ App.toast(e.message); if(String(e.message).includes('token')) App.logout(); return; }
    render(tab);
  }

  function statusBanner(me){
    const s=me.status;
    const outstanding=me.outstanding_count, unacked=me.unacked_policies;
    if(me.needs_inperson) return `<div class="banner bad"><b>In-person awareness required.</b> Your risk has stayed elevated, so a ticket was raised for a face-to-face session. Keep completing training below.</div>`;
    if(s==='onboarding') return `<div class="banner info"><b>Welcome - finish your onboarding.</b> Complete the mandatory module below to activate your access baseline.</div>`;
    if(s==='remediation'||outstanding>0||unacked>0) return `<div class="banner warn"><b>Action needed.</b> You have ${outstanding} training item(s)${unacked?` and ${unacked} policy(ies) to acknowledge`:''}.</div>`;
    return `<div class="banner ok"><b>You're in good standing.</b> No outstanding training. Thanks for staying sharp.</div>`;
  }

  function render(tab){
    const me=cache.me;
    App.view().innerHTML = `
      ${statusBanner(me)}
      <div class="row" style="gap:14px;margin-bottom:8px">
        <div class="stat grow"><div class="l">Status</div><div class="n" style="font-size:1.2rem"><span class="badge status ${me.status}">${me.status}</span></div></div>
        <div class="stat grow"><div class="l">Current risk (PhishAwareness)</div><div class="n" style="font-size:1.2rem"><span class="badge ${me.risk.band}">${me.risk.band}</span> <span class="muted small">HRS ${me.risk.hrs}</span></div></div>
        <div class="stat grow"><div class="l">Outstanding</div><div class="n">${me.outstanding_count}</div></div>
      </div>
      <div class="tabs">
        <div class="tab ${tab==='training'?'active':''}" onclick="Emp.render('training')">My training</div>
        <div class="tab ${tab==='policies'?'active':''}" onclick="Emp.render('policies')">Policies ${me.unacked_policies?`<span class="pill">${me.unacked_policies}</span>`:''}</div>
        <div class="tab ${tab==='history'?'active':''}" onclick="Emp.showHistory()">History</div>
      </div>
      <div id="empbody"></div>`;
    if(tab==='training') renderTraining();
    else if(tab==='policies') renderPolicies();
  }

  function renderTraining(){
    const items=cache.assignments;
    const body=document.getElementById('empbody');
    if(!items.length){ body.innerHTML=`<div class="card muted">No training assigned. </div>`; return; }
    const order={assigned:0,in_progress:1,completed:2};
    items.sort((a,b)=>(order[a.status]-order[b.status]));
    body.innerHTML = items.map(a=>{
      const m=a.module||{}; const done=a.status==='completed';
      const reason={onboarding:'Onboarding',phishing_failure:'After a phishing failure',new_policy:'New policy',escalation:'Escalation',manual:'Assigned'}[a.reason]||a.reason;
      return `<div class="card tight row between">
        <div>
          <div><b>${App.esc(m.title)}</b> <span class="pill">${m.kind}${m.level>1?' - L'+m.level:''}</span></div>
          <div class="small muted">${App.esc(m.description||'')}</div>
          <div class="small muted">Reason: ${reason} - ${done?('Completed - best '+Math.round(a.best_score*100)+'%'):(a.status==='in_progress'?'In progress':'Not started')}</div>
        </div>
        <div>${done?'<span class="badge Low">Done</span>':`<button class="primary" onclick="Emp.openModule('${a.id}')">${a.status==='in_progress'?'Continue':'Start'}</button>`}</div>
      </div>`;
    }).join('');
  }


  let _timer=null;
  function stopTimer(){ if(_timer){ clearInterval(_timer); _timer=null; } }

  async function openModule(aid){
    stopTimer();
    let d;
    try{ d=await api('/api/portal/assignments/'+aid); }catch(e){ App.toast(e.message); return; }
    const m=d.module;
    const embed = m.video_embed_url ? `<div class="videowrap"><iframe src="${App.esc(m.video_embed_url)}" allowfullscreen></iframe></div>` : '';
    const resource = m.resource_url ? `<p><a href="${App.esc(m.resource_url)}" target="_blank" rel="noopener">↗ Open the official resource (opens in a new tab)</a></p>` : '';
    App.view().innerHTML = `
      <p><a onclick="Emp.dashboard('training')"><- Back to my training</a></p>
      <div class="card">
        <h2>${App.esc(m.title)} <span class="pill">${m.kind}${m.level>1?' - L'+m.level:''}</span></h2>
        ${embed}
        <div class="lesson">${m.lesson_html||''}</div>
        ${resource}
        <div class="row between">
          <div class="grow"><div class="progress"><i id="dwellbar"></i></div></div>
          <div class="small muted" id="dwelltxt"></div>
        </div>
        <p class="small muted">The exam unlocks after you've spent enough time on the lesson (this can't be skipped).</p>
      </div>
      <div id="examcard" class="card ${d.unlocked?'':'hidden'}"><h3>Knowledge check</h3>
        <div id="exam">${examHtml(d.questions)}</div>
        <div class="spacer"></div>
        <button class="primary" onclick="Emp.submitExam('${aid}',${d.questions.length})">Submit answers</button>
        <div id="examresult"></div>
      </div>`;
    runDwell(aid, d.module.min_seconds, d.watched_seconds);
  }

  function examHtml(qs){
    return qs.map((q,i)=>`<div class="card tight" data-q="${i}">
      <div><b>${i+1}.</b> ${App.esc(q.text)}</div>
      ${q.choices.map((c,ci)=>`<label class="choice"><input type="radio" name="q${i}" value="${ci}"> <span>${App.esc(c)}</span></label>`).join('')}
    </div>`).join('');
  }

  function runDwell(aid,min,watched){
    const bar=document.getElementById('dwellbar'), txt=document.getElementById('dwelltxt');
    const paint=(w)=>{ const pct=Math.min(100,Math.round(w/min*100)); bar.style.width=pct+'%';
      txt.textContent = w>=min ? 'Lesson complete ✓' : `${w}/${min}s`;
      if(w>=min){ document.getElementById('examcard').classList.remove('hidden'); } };
    paint(watched);
    if(watched>=min){ return; }
    _timer=setInterval(async()=>{
      try{
        const r=await api('/api/portal/assignments/'+aid+'/heartbeat',{method:'POST',body:{seconds:3}});
        paint(r.watched_seconds);
        if(r.unlocked) stopTimer();
      }catch(e){ stopTimer(); }
    },3000);
  }

  async function submitExam(aid,n){
    const answers=[];
    for(let i=0;i<n;i++){ const sel=document.querySelector(`input[name="q${i}"]:checked`); answers.push(sel?parseInt(sel.value):-1); }
    if(answers.includes(-1)){ App.toast('Please answer every question.'); return; }
    let r; try{ r=await api('/api/portal/assignments/'+aid+'/exam',{method:'POST',body:{answers}}); }
    catch(e){ App.toast(e.message); return; }
    r.results.forEach((res,i)=>{
      const block=document.querySelector(`[data-q="${i}"]`);
      block.querySelectorAll('.choice').forEach((ch,ci)=>{
        if(ci===res.correct_index) ch.classList.add('correct');
        const chosen=ch.querySelector('input').checked;
        if(chosen && ci!==res.correct_index) ch.classList.add('wrong');
      });
      if(res.explanation){ const p=document.createElement('div'); p.className='small muted'; p.style.marginTop='6px'; p.textContent='i '+res.explanation; block.appendChild(p); }
    });
    const rd=document.getElementById('examresult');
    rd.innerHTML = `<div class="banner ${r.passed?'ok':'bad'}" style="margin-top:14px">
      ${r.passed?'✓ Passed':'✗ Not passed'} - ${r.correct}/${r.total} (${Math.round(r.score*100)}%, need ${Math.round(r.pass_threshold*100)}%).
      ${r.passed?'Nice work.':'Review the highlights above and try again.'}</div>`;
    if(r.passed){ App.toast('Module completed!'); setTimeout(()=>dashboard('training'),1400); }
  }


  function renderPolicies(){
    const body=document.getElementById('empbody');
    const pols=cache.policies;
    if(!pols.length){ body.innerHTML=`<div class="card muted">No policies published.</div>`; return; }
    body.innerHTML = pols.map(p=>`<div class="card">
      <div class="row between">
        <div><b>${App.esc(p.title)}</b> <span class="pill">v${App.esc(p.version)}</span></div>
        <div>${p.acknowledged?'<span class="badge Low">Acknowledged</span>':'<span class="badge High">Action needed</span>'}</div>
      </div>
      <div class="lesson">${p.body_html||''}${p.file_name?`<p class="muted small">Document: ${App.esc(p.file_name)}</p>`:''}</div>
      ${p.acknowledged?`<div class="small muted">Acknowledged ${new Date(p.acknowledged_at).toLocaleString()}</div>`
        :`<button class="primary" onclick="Emp.ackPolicy('${p.id}')">I have read and agree</button>`}
    </div>`).join('');
  }

  async function ackPolicy(pid){
    try{ await api('/api/portal/policies/'+pid+'/ack',{method:'POST'}); App.toast('Policy acknowledged.'); dashboard('policies'); }
    catch(e){ App.toast(e.message); }
  }

  async function showHistory(){
    render('history');
    const body=document.getElementById('empbody');
    body.innerHTML=`<div class="card muted">Loading...</div>`;
    try{
      const rows=await api('/api/portal/history');
      body.innerHTML = rows.length? `<div class="card"><table><thead><tr><th>Module</th><th>Score</th><th>Result</th><th>When</th></tr></thead><tbody>
        ${rows.map(h=>`<tr><td>${App.esc(h.module)}</td><td>${Math.round(h.score*100)}%</td>
        <td>${h.passed?'<span class="badge Low">Pass</span>':'<span class="badge High">Fail</span>'}</td>
        <td class="small muted">${new Date(h.attempted_at).toLocaleString()}</td></tr>`).join('')}
        </tbody></table></div>` : `<div class="card muted">No attempts yet.</div>`;
    }catch(e){ App.toast(e.message); }
  }

  return { authScreen, doLogin, doRegister, dashboard, render, openModule,
           submitExam, ackPolicy, showHistory };
})();


/* ---------------- Admin ---------------- */
const Adm = (() => {
  const api=(p,o={})=>App.api(p,{...o,token:App.state.adminToken});
  const $id=(i)=>document.getElementById(i);

  function authScreen(){
    App.view().innerHTML = `
      <div class="card" style="max-width:460px;margin:6vh auto">
        <h2>Administrator sign in</h2>
        <p class="muted small">Use your <b>PhishAwareness</b> operator/admin credentials - the portal verifies them against PhishAwareness.</p>
        <label>PhishAwareness URL</label><input id="ab" value="http://127.0.0.1:8000">
        <label>Email</label><input id="ae" type="email" placeholder="operator@company.com">
        <label>Password</label><input id="ap" type="password">
        <div class="spacer"></div>
        <button class="primary" style="width:100%" onclick="Adm.doLogin()">Sign in</button>
        <p class="small muted center" style="margin-top:14px"><a onclick="App.landing()"><- back</a></p>
      </div>`;
  }

  async function doLogin(){
    try{
      const d=await App.api('/api/portal/admin/auth/login',{method:'POST',body:{
        email:$id('ae').value.trim(), password:$id('ap').value, base_url:$id('ab').value.trim()}});
      App.state.adminToken=d.access_token; App.state.admin=d.admin;
      localStorage.setItem(App.K.adm,d.access_token);
      localStorage.setItem(App.K.admMeta,JSON.stringify(d.admin));
      App.setChrome(); home();
    }catch(e){ App.toast(e.message); }
  }

  const TABS=[['overview','Overview'],['employees','Employees'],['policies','Policies'],
              ['modules','Modules'],['ticketing','Ticketing'],['settings','Settings']];

  function home(tab='overview'){
    App.view().innerHTML = `
      <div class="tabs">${TABS.map(([k,l])=>`<div class="tab ${tab===k?'active':''}" onclick="Adm.home('${k}')">${l}</div>`).join('')}</div>
      <div id="admbody"><div class="card muted">Loading...</div></div>`;
    ({overview,employees,policies,modules,ticketing,settings}[tab])();
  }


  async function overview(){
    let o; try{ o=await api('/api/portal/admin/overview'); }
    catch(e){ App.toast(e.message); if(String(e.message).includes('token')||String(e.message).includes('auth')) App.logout(); return; }
    const bs=o.by_status||{};
    const body=$id('admbody');
    body.innerHTML = `
      <div class="row between">
        <h2>Overview</h2>
        <button class="primary" onclick="Adm.sync()">↻ Run sync &amp; escalation now</button>
      </div>
      <div class="grid">
        <div class="stat"><div class="l">Employees</div><div class="n">${o.employees}</div></div>
        <div class="stat"><div class="l">Onboarding</div><div class="n">${bs.onboarding||0}</div></div>
        <div class="stat"><div class="l">Active</div><div class="n">${bs.active||0}</div></div>
        <div class="stat"><div class="l">In remediation</div><div class="n">${bs.remediation||0}</div></div>
        <div class="stat"><div class="l">Flagged (in-person)</div><div class="n" style="color:var(--critical)">${bs.flagged||0}</div></div>
        <div class="stat"><div class="l">Active modules</div><div class="n">${o.modules}</div></div>
      </div>
      <div class="card">
        <h3>Flagged for in-person awareness</h3>
        ${(o.flagged||[]).length? `<table><thead><tr><th>Name</th><th>Email</th><th>Band</th><th>Since</th></tr></thead><tbody>
          ${o.flagged.map(f=>`<tr><td>${App.esc(f.full_name)}</td><td>${App.esc(f.email)}</td><td><span class="badge ${f.band}">${f.band}</span></td><td class="small muted">${f.elevated_since?new Date(f.elevated_since).toLocaleDateString():'-'}</td></tr>`).join('')}
          </tbody></table>` : `<p class="muted">None - no one is stuck elevated. </p>`}
      </div>
      <div class="card">
        <h3>Recent tickets raised</h3>
        ${(o.recent_tickets||[]).length? `<table><thead><tr><th>Event</th><th>Employee</th><th>Result</th><th>When</th></tr></thead><tbody>
          ${o.recent_tickets.map(t=>`<tr><td>${App.esc(t.event)}</td><td>${App.esc(t.user_email||'-')}</td><td>${t.ok?'<span class="badge Low">sent</span>':'<span class="badge Critical">failed</span>'}${t.status_code?` <span class="small muted">${t.status_code}</span>`:''}</td><td class="small muted">${t.created_at?new Date(t.created_at).toLocaleString():''}</td></tr>`).join('')}
          </tbody></table>` : `<p class="muted">No tickets raised yet.</p>`}
        <p class="small muted">Last sync: ${o.last_sync_at?new Date(o.last_sync_at).toLocaleString():'never'}</p>
      </div>`;
  }

  async function sync(){
    App.toast('Syncing with PhishAwareness...');
    try{ const r=await api('/api/portal/admin/sync',{method:'POST'});
      App.toast(`Synced ${r.synced} employees, ${r.changed} change(s).`); overview();
    }catch(e){ App.toast(e.message); }
  }


  async function employees(){
    let rows; try{ rows=await api('/api/portal/admin/employees'); }catch(e){ App.toast(e.message); return; }
    const body=$id('admbody');
    body.innerHTML = `<div class="card">
      <h2>Employees</h2>
      ${rows.length? `<table><thead><tr><th>Name</th><th>Status</th><th>Risk</th><th>Outstanding</th><th>In-person</th><th></th></tr></thead><tbody>
        ${rows.map(u=>`<tr>
          <td><b>${App.esc(u.full_name)}</b><div class="small muted">${App.esc(u.email)} - ${App.esc(u.department)}</div></td>
          <td><span class="badge status ${u.status}">${u.status}</span></td>
          <td><span class="badge ${u.band}">${u.band}</span> <span class="small muted">${u.hrs}</span></td>
          <td>${u.outstanding}</td>
          <td>${u.needs_inperson?'<span class="badge Critical">yes</span>':'<span class="muted">-</span>'}</td>
          <td><button class="ghost" onclick="Adm.employeeDetail('${u.id}')">View</button></td>
        </tr>`).join('')}
        </tbody></table>` : `<p class="muted">No employees have signed up yet.</p>`}
    </div>`;
  }

  async function employeeDetail(id){
    let u, mods; try{ [u,mods]=await Promise.all([api('/api/portal/admin/employees/'+id), api('/api/portal/admin/modules')]); }
    catch(e){ App.toast(e.message); return; }
    const body=$id('admbody');
    body.innerHTML = `
      <p><a onclick="Adm.employees()"><- All employees</a></p>
      <div class="card">
        <div class="row between"><h2>${App.esc(u.full_name)}</h2><span class="badge status ${u.status}">${u.status}</span></div>
        <p class="muted">${App.esc(u.email)} - ${App.esc(u.job_title)} - ${App.esc(u.department)}</p>
        <div class="row">
          <div class="stat grow"><div class="l">Risk</div><div class="n" style="font-size:1.1rem"><span class="badge ${u.band}">${u.band}</span> ${u.hrs}</div></div>
          <div class="stat grow"><div class="l">Campaigns scored</div><div class="n">${u.campaigns_scored}</div></div>
          <div class="stat grow"><div class="l">Onboarded</div><div class="n" style="font-size:1.1rem">${u.onboarded?'Yes':'No'}</div></div>
          <div class="stat grow"><div class="l">In-person flag</div><div class="n" style="font-size:1.1rem">${u.needs_inperson?'<span style="color:var(--critical)">Raised</span>':'-'}</div></div>
        </div>
      </div>
      <div class="card">
        <h3>Assign a module</h3>
        <div class="row"><select id="asgMod" class="grow">${mods.filter(m=>m.active).map(m=>`<option value="${m.key}">${App.esc(m.title)} (${m.kind}${m.level>1?' L'+m.level:''})</option>`).join('')}</select>
        <button class="primary" onclick="Adm.assign('${id}')">Assign</button></div>
      </div>
      <div class="card">
        <h3>Training record</h3>
        ${(u.assignments||[]).length? `<table><thead><tr><th>Module</th><th>Reason</th><th>Status</th><th>Best</th></tr></thead><tbody>
          ${u.assignments.map(a=>`<tr><td>${App.esc(a.module)}</td><td class="small muted">${a.reason}</td><td>${a.status}</td><td>${Math.round(a.best_score*100)}%</td></tr>`).join('')}
          </tbody></table>` : `<p class="muted">No assignments.</p>`}
      </div>`;
  }

  async function assign(id){
    const key=$id('asgMod').value;
    try{ await api('/api/portal/admin/employees/'+id+'/assign',{method:'POST',body:{module_key:key,reason:'manual'}});
      App.toast('Module assigned.'); employeeDetail(id);
    }catch(e){ App.toast(e.message); }
  }


  async function policies(){
    let pols, mods; try{ [pols,mods]=await Promise.all([api('/api/portal/admin/policies'),api('/api/portal/admin/modules')]); }
    catch(e){ App.toast(e.message); return; }
    const modOpts=mods.filter(m=>m.active).map(m=>`<option value="${m.key}">${App.esc(m.title)}</option>`).join('');
    const body=$id('admbody');
    body.innerHTML = `
      <div class="card">
        <h2>Policies</h2>
        ${pols.length? `<table><thead><tr><th>Title</th><th>Ver</th><th>Ack'd</th><th>Remediation</th><th>Active</th><th></th></tr></thead><tbody>
          ${pols.map(p=>`<tr><td>${App.esc(p.title)}${p.file_name?` <span class="pill">file</span>`:''}</td><td>${App.esc(p.version)}</td>
            <td>${p.acks}/${p.of_users}</td><td>${p.triggers_remediation?'yes':'no'}</td>
            <td>${p.active?'yes':'<span class="muted">no</span>'}</td>
            <td>${p.active?`<button class="danger ghost" onclick="Adm.deactivatePolicy('${p.id}')">Retire</button>`:''}</td></tr>`).join('')}
          </tbody></table>` : `<p class="muted">No policies yet.</p>`}
      </div>
      <div class="row">
        <div class="card grow">
          <h3>Publish a policy (text)</h3>
          <label>Title</label><input id="pcTitle" placeholder="Acceptable Use Policy">
          <div class="formgrid"><div><label>Version</label><input id="pcVer" value="1.0"></div>
          <div><label>Remediation module</label><select id="pcMod"><option value="">- none -</option>${modOpts}</select></div></div>
          <label>Body (HTML allowed)</label><textarea id="pcBody" placeholder="<p>Policy text...</p>"></textarea>
          <label class="row" style="align-items:center;gap:8px"><input type="checkbox" id="pcRem" checked style="width:auto"> Assign remediation to everyone on publish</label>
          <div class="spacer"></div>
          <button class="primary" onclick="Adm.createPolicy()">Publish policy</button>
        </div>
        <div class="card grow">
          <h3>Upload a policy document</h3>
          <label>Title</label><input id="puTitle" placeholder="Data Handling Standard">
          <div class="formgrid"><div><label>Version</label><input id="puVer" value="1.0"></div>
          <div><label>Remediation module</label><select id="puMod"><option value="">- none -</option>${modOpts}</select></div></div>
          <label>File (PDF/DOCX/...) </label><input type="file" id="puFile">
          <label class="row" style="align-items:center;gap:8px"><input type="checkbox" id="puRem" checked style="width:auto"> Assign remediation on upload</label>
          <div class="spacer"></div>
          <button class="primary" onclick="Adm.uploadPolicy()">Upload &amp; publish</button>
        </div>
      </div>`;
  }

  async function createPolicy(){
    const body={ title:$id('pcTitle').value.trim(), version:$id('pcVer').value.trim()||'1.0',
      body_html:$id('pcBody').value, triggers_remediation:$id('pcRem').checked,
      remediation_module_key:$id('pcMod').value||null };
    if(!body.title){ App.toast('Title required.'); return; }
    try{ const r=await api('/api/portal/admin/policies',{method:'POST',body});
      App.toast(`Published. Remediation assigned to ${r.assigned_remediation_to||0}.`); policies();
    }catch(e){ App.toast(e.message); }
  }

  async function uploadPolicy(){
    const f=$id('puFile').files[0];
    if(!$id('puTitle').value.trim()||!f){ App.toast('Title and file required.'); return; }
    const fd=new FormData();
    fd.append('file',f); fd.append('title',$id('puTitle').value.trim());
    fd.append('version',$id('puVer').value.trim()||'1.0');
    fd.append('triggers_remediation',$id('puRem').checked?'true':'false');
    if($id('puMod').value) fd.append('remediation_module_key',$id('puMod').value);
    try{ const r=await api('/api/portal/admin/policies/upload',{method:'POST',form:fd});
      App.toast(`Uploaded. Remediation assigned to ${r.assigned_remediation_to||0}.`); policies();
    }catch(e){ App.toast(e.message); }
  }

  async function deactivatePolicy(id){
    try{ await api('/api/portal/admin/policies/'+id,{method:'DELETE'}); App.toast('Policy retired.'); policies(); }
    catch(e){ App.toast(e.message); }
  }


  async function modules(){
    let mods; try{ mods=await api('/api/portal/admin/modules'); }catch(e){ App.toast(e.message); return; }
    const body=$id('admbody');
    const qExample='[{"text":"Question?","choices":["A","B","C"],"correct_index":1,"explanation":"why"}]';
    body.innerHTML = `
      <div class="card">
        <h2>Training modules</h2>
        <table><thead><tr><th>Title</th><th>Kind</th><th>Level</th><th>Q's</th><th>Min&nbsp;s</th><th>Active</th><th></th></tr></thead><tbody>
          ${mods.map(m=>`<tr><td><b>${App.esc(m.title)}</b><div class="small muted">${App.esc(m.key)}</div></td>
            <td>${m.kind}</td><td>${m.level}</td><td>${m.questions}</td><td>${m.min_seconds}</td>
            <td>${m.active?'yes':'<span class="muted">no</span>'}</td>
            <td>${m.active?`<button class="danger ghost" onclick="Adm.deactivateModule('${m.id}')">Retire</button>`:''}</td></tr>`).join('')}
        </tbody></table>
      </div>
      <div class="card">
        <h3>Create a module</h3>
        <div class="formgrid">
          <div><label>Key (unique)</label><input id="mKey" placeholder="remediation-usb-safety"></div>
          <div><label>Title</label><input id="mTitle" placeholder="USB &amp; Removable Media"></div>
          <div><label>Kind</label><select id="mKind"><option value="remediation">remediation</option><option value="onboarding">onboarding</option><option value="policy">policy</option></select></div>
          <div><label>Level (remediation ladder)</label><input id="mLevel" type="number" value="1"></div>
          <div><label>Min seconds (dwell)</label><input id="mMin" type="number" value="60"></div>
          <div><label>Pass threshold (0-1)</label><input id="mPass" type="number" step="0.05" value="0.7"></div>
        </div>
        <label>Resource URL (optional)</label><input id="mRes" placeholder="https://www.cisa.gov/...">
        <label>Video embed URL (optional, e.g. YouTube /embed/...)</label><input id="mVid" placeholder="">
        <label>Description</label><input id="mDesc">
        <label>Lesson (HTML allowed)</label><textarea id="mLesson"></textarea>
        <label>Questions (JSON array)</label><textarea id="mQ" placeholder='${qExample}'></textarea>
        <div class="spacer"></div>
        <button class="primary" onclick="Adm.createModule()">Create module</button>
      </div>`;
  }

  async function createModule(){
    let questions=[];
    const raw=$id('mQ').value.trim();
    if(raw){ try{ questions=JSON.parse(raw); if(!Array.isArray(questions)) throw 0; }
      catch(e){ App.toast('Questions must be a valid JSON array.'); return; } }
    const body={ key:$id('mKey').value.trim(), title:$id('mTitle').value.trim(),
      kind:$id('mKind').value, level:parseInt($id('mLevel').value)||1,
      min_seconds:parseInt($id('mMin').value)||60, pass_threshold:parseFloat($id('mPass').value)||0.7,
      resource_url:$id('mRes').value.trim()||null, video_embed_url:$id('mVid').value.trim()||null,
      description:$id('mDesc').value.trim(), lesson_html:$id('mLesson').value, questions };
    if(!body.key||!body.title){ App.toast('Key and title required.'); return; }
    try{ await api('/api/portal/admin/modules',{method:'POST',body}); App.toast('Module created.'); modules(); }
    catch(e){ App.toast(e.message); }
  }

  async function deactivateModule(id){
    try{ await api('/api/portal/admin/modules/'+id,{method:'DELETE'}); App.toast('Module retired.'); modules(); }
    catch(e){ App.toast(e.message); }
  }


  async function ticketing(){
    let cfg, logs; try{ [cfg,logs]=await Promise.all([api('/api/portal/admin/ticket-config'),api('/api/portal/admin/tickets')]); }
    catch(e){ App.toast(e.message); return; }
    const body=$id('admbody');
    body.innerHTML = `
      <div class="card">
        <h2>Ticketing integration</h2>
        <p class="muted small">When someone is stuck High/Critical too long, the portal sends a JSON envelope to this webhook (e.g. a Jira automation inbound webhook). The portal only sends the information - your team decides what the ticket does.</p>
        <label class="row" style="align-items:center;gap:8px"><input type="checkbox" id="tEnabled" ${cfg.enabled?'checked':''} style="width:auto"> Enabled</label>
        <label>Webhook URL</label><input id="tUrl" value="${App.esc(cfg.webhook_url||'')}" placeholder="https://your-org.atlassian.net/.../hooks/...">
        <div class="formgrid">
          <div><label>Auth header name (optional)</label><input id="tHName" value="${App.esc(cfg.auth_header_name||'')}" placeholder="Authorization"></div>
          <div><label>Auth header value ${cfg.auth_header_set?'(set - leave blank to keep)':''}</label><input id="tHVal" type="password" placeholder="${cfg.auth_header_set?'------':'Bearer ...'}"></div>
        </div>
        <label>System label</label><input id="tLabel" value="${App.esc(cfg.system_label||'Jira')}">
        <div class="spacer"></div>
        <div class="row"><button class="primary" onclick="Adm.saveTicketConfig()">Save</button>
        <button onclick="Adm.testTicket()">Send test ticket</button></div>
      </div>
      <div class="card">
        <h3>Ticket log</h3>
        ${logs.length? `<table><thead><tr><th>Event</th><th>Employee</th><th>Result</th><th>Response</th><th>When</th></tr></thead><tbody>
          ${logs.map(t=>`<tr><td>${App.esc(t.event)}</td><td>${App.esc(t.user_email||'-')}</td>
            <td>${t.ok?'<span class="badge Low">sent</span>':'<span class="badge Critical">failed</span>'}${t.status_code?` <span class="small muted">${t.status_code}</span>`:''}</td>
            <td class="small muted">${App.esc((t.response_snippet||'').slice(0,60))}</td>
            <td class="small muted">${t.created_at?new Date(t.created_at).toLocaleString():''}</td></tr>`).join('')}
          </tbody></table>` : `<p class="muted">No tickets sent yet.</p>`}
      </div>`;
  }

  async function saveTicketConfig(){
    const body={ enabled:$id('tEnabled').checked, webhook_url:$id('tUrl').value.trim(),
      auth_header_name:$id('tHName').value.trim(), system_label:$id('tLabel').value.trim()||'Jira' };
    const v=$id('tHVal').value; if(v) body.auth_header_value=v;
    try{ await api('/api/portal/admin/ticket-config',{method:'PUT',body}); App.toast('Ticketing saved.'); ticketing(); }
    catch(e){ App.toast(e.message); }
  }
  async function testTicket(){
    try{ const r=await api('/api/portal/admin/ticket-config/test',{method:'POST'});
      App.toast(r.ok?'Test ticket sent ✓':('Test failed: '+(r.reason||r.response||r.status_code||'error'))); ticketing();
    }catch(e){ App.toast(e.message); }
  }


  async function settings(){
    let s; try{ s=await api('/api/portal/admin/settings'); }catch(e){ App.toast(e.message); return; }
    const body=$id('admbody');
    body.innerHTML = `
      <div class="card">
        <h2>PhishAwareness connection</h2>
        <p class="muted small">The portal URL/tenant were set from your admin sign-in. The service token below authenticates the portal's own background automation - generate it in PhishAwareness under Manage &rarr; Integration (rotate "Portal service token") and paste it here.</p>
        <div class="formgrid">
          <div><label>PhishAwareness URL</label><input id="sUrl" value="${App.esc(s.pa_base_url||'')}"></div>
          <div><label>Tenant ID</label><input id="sTid" value="${App.esc(s.pa_tenant_id||'')}"></div>
          <div><label>Service token ${s.pa_service_token_set?'(set - blank keeps it)':''}</label><input id="sToken" type="password" placeholder="${s.pa_service_token_set?'------':'paste the generated token'}"></div>
        </div>
        <div class="spacer"></div>
        <div class="row"><button class="primary" onclick="Adm.saveSettings()">Save connection</button>
        <button onclick="Adm.testSettings()">Test connection</button></div>
      </div>
      <div class="card">
        <h2>Escalation policy</h2>
        <div class="formgrid">
          <div><label>Onboarding baseline HRS (Moderate ~ 25-49)</label><input id="sFloor" type="number" value="${s.onboarding_floor}"></div>
          <div><label>Days elevated before in-person + ticket</label><input id="sDays" type="number" value="${s.inperson_after_days}"></div>
        </div>
        <div class="spacer"></div>
        <button class="primary" onclick="Adm.saveSettings()">Save policy</button>
      </div>`;
  }

  async function saveSettings(){
    const body={ pa_base_url:$id('sUrl').value.trim(), pa_tenant_id:$id('sTid').value.trim(),
      onboarding_floor:parseFloat($id('sFloor').value), inperson_after_days:parseInt($id('sDays').value) };
    const t=$id('sToken').value; if(t) body.pa_service_token=t;
    try{ await api('/api/portal/admin/settings',{method:'PUT',body}); App.toast('Settings saved.'); settings(); }
    catch(e){ App.toast(e.message); }
  }
  async function testSettings(){
    try{ const r=await api('/api/portal/admin/settings/test',{method:'POST'});
      App.toast(r.ok?`Connected ✓ (${r.employees} employees)`:('Failed: '+(r.error||'error')));
    }catch(e){ App.toast(e.message); }
  }

  return { authScreen, doLogin, home, overview, sync, employees, employeeDetail,
           assign, policies, createPolicy, uploadPolicy, deactivatePolicy,
           modules, createModule, deactivateModule, ticketing, saveTicketConfig,
           testTicket, settings, saveSettings, testSettings };
})();

document.addEventListener('DOMContentLoaded', App.boot);

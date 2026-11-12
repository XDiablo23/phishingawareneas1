import React, { useEffect, useState } from "react";
import {
  getIntegration, rotateSecret, getIntegrationStatus,
  getGoPhishStatus, setGoPhishConfig, listGoPhishCampaigns, syncGoPhish,
  getEntraStatus, setEntraConfig, previewEntra, syncEntra,
  getLdapStatus, setLdapConfig, previewLdap, syncLdap,
  gpTemplates, gpPages, gpSmtp, gpGroups, gpGroupFromRoster, gpLaunch,
  gpComplete, gpDelete,
} from "../api.js";

function timeAgo(iso) {
  if (!iso) return "never";
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return "just now";
  const mins = secs / 60;
  if (mins < 60) return `${Math.floor(mins)} min ago`;
  const hrs = mins / 60;
  if (hrs < 24) return `${Math.floor(hrs)} h ago`;
  return `${Math.floor(hrs / 24)} d ago`;
}

function StatusPanel({ tenantId }) {
  const [st, setSt] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    setBusy(true);
    getIntegrationStatus(tenantId)
      .then((s) => { setSt(s); setErr(""); })
      .catch((e) => setErr(e.message))
      .finally(() => setBusy(false));
  };
  useEffect(load, [tenantId]);

  const anyTraffic = st && st.sources.some((s) => s.total_events > 0);

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Connection status</h2>
        <div className="section-actions">
          <button className="btn btn-xs" onClick={load} disabled={busy}>
            {busy ? "..." : "↻ Refresh"}
          </button>
        </div>
      </div>
      <div className="panel-body">
        {err && <div className="banner banner-error">{err}</div>}
        {!st ? (
          <div className="center-msg"><span className="spinner" />Checking...</div>
        ) : (
          <>
            <p className="faint int-intro">
              {anyTraffic
                ? "Live view of simulation event metadata reaching the scoring pipeline."
                : "No simulation events have arrived yet. Once GoPhish or the landing beacon posts here, traffic shows up below."}
            </p>
            <div className="status-grid">
              {st.sources.map((s) => (
                <div key={s.source} className={`status-card ${s.total_events ? "live" : "idle"}`}>
                  <div className="status-head">
                    <span className={`dot ${s.total_events ? "on" : "off"}`} />
                    <span className="status-name">{s.source === "gophish" ? "GoPhish webhook" : "Landing beacon"}</span>
                  </div>
                  <div className="status-big">{s.total_events}</div>
                  <div className="faint status-sub">events total - {s.events_24h} in last 24h</div>
                  <div className="faint status-sub">last: {timeAgo(s.last_event_at)}</div>
                  {!!Object.keys(s.event_types || {}).length && (
                    <div className="status-types">
                      {Object.entries(s.event_types).map(([t, n]) => (
                        <span key={t} className="chip">{t.replace(/_/g, " ")} {n}</span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="faint status-foot">
              {st.linked_campaigns} of {st.total_campaigns} campaigns linked to a GoPhish id.
              {st.total_campaigns > 0 && st.linked_campaigns === 0 &&
                " Link a campaign under Campaigns so inbound events can be matched."}
              {st.other_events > 0 &&
                ` - ${st.other_events} seeded/demo events (not from an integration) are also scored.`}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function GoPhishSyncPanel({ tenantId, role }) {
  const isAdmin = role === "org_admin" || role === "super_admin";
  const [st, setSt] = useState(null);
  const [camps, setCamps] = useState(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [verifyTls, setVerifyTls] = useState(null); // null = inherit server default
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");

  const loadStatus = () => {
    getGoPhishStatus(tenantId)
      .then((s) => {
        setSt(s);
        if (s.base_url) setBaseUrl(s.base_url);
        setVerifyTls(s.verify_tls_override ?? null);
      })
      .catch((e) => setErr(e.message));
  };
  useEffect(loadStatus, [tenantId]);

  const gpBase = st && st.base_url ? st.base_url.replace(/\/$/, "") : "";

  const saveConfig = async () => {
    setBusy("save"); setErr(""); setMsg("");
    try {
      const body = { base_url: baseUrl, verify_tls: verifyTls };
      if (apiKey) body.api_key = apiKey;
      const s = await setGoPhishConfig(tenantId, body);
      setSt(s); setApiKey(""); setVerifyTls(s.verify_tls_override ?? null);
      setMsg(s.reachable
        ? `Connected - ${s.campaign_count} campaign(s) visible.`
        : (s.error || "Saved, but GoPhish isn't reachable."));
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const test = async () => {
    setBusy("test"); setErr(""); setMsg("");
    try { const s = await getGoPhishStatus(tenantId); setSt(s);
      setMsg(s.reachable ? `Reachable - ${s.campaign_count} campaign(s).` : (s.error || "Not reachable."));
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const loadCampaigns = async () => {
    setBusy("camps"); setErr("");
    try { setCamps(await listGoPhishCampaigns(tenantId)); }
    catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const doSync = async () => {
    setBusy("sync"); setErr(""); setMsg("");
    try {
      const r = await syncGoPhish(tenantId);
      setMsg(`Synced ${r.campaigns_synced} campaign(s): ${r.events_ingested} new event(s) ingested, ${r.skipped_existing} already known.`);
      loadCampaigns();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const doComplete = async (id) => {
    if (!window.confirm(`Mark GoPhish campaign #${id} complete?`)) return;
    setBusy("c" + id); setErr(""); setMsg("");
    try { await gpComplete(tenantId, id); setMsg(`Campaign #${id} completed.`); loadCampaigns(); }
    catch (e) { setErr(e.message); } finally { setBusy(""); }
  };
  const doDelete = async (id) => {
    if (!window.confirm(`Delete GoPhish campaign #${id}? This removes it in GoPhish too.`)) return;
    setBusy("d" + id); setErr(""); setMsg("");
    try { await gpDelete(tenantId, id); setMsg(`Campaign #${id} deleted.`); loadCampaigns(); }
    catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>GoPhish sync</h2>
        <div className="section-actions">
          <button className="btn btn-xs" onClick={test} disabled={!!busy}>{busy === "test" ? "..." : "Test"}</button>
          <button className="btn btn-xs" onClick={loadCampaigns} disabled={!!busy}>{busy === "camps" ? "..." : "Campaigns"}</button>
          {isAdmin && <button className="btn btn-xs" onClick={doSync} disabled={!!busy}>{busy === "sync" ? "..." : "↻ Sync now"}</button>}
        </div>
      </div>
      <div className="panel-body">
        <p className="faint int-intro">
          Pulls GoPhish campaigns and results into this console so you monitor and score everything
          in one place. To build groups and launch campaigns, use <strong>GoPhish campaign
          control</strong> below - the email templates and landing pages themselves stay authored
          in GoPhish (this console selects and uses them).
        </p>
        {err && <div className="banner banner-error">{err}</div>}
        {msg && <div className="banner">{msg}</div>}
        {st && (
          <div className={`int-status ${st.reachable ? "ok" : "off"}`} style={{ marginBottom: 12 }}>
            {st.reachable
              ? `● connected to ${st.base_url} - ${st.campaign_count} campaign(s)`
              : st.configured ? `○ configured but not reachable${st.error ? ": " + st.error : ""}` : "○ not configured"}
            {" - TLS "}{st.verify_tls ? "verified" : "not verified"}
            {st.verify_tls_override === null || st.verify_tls_override === undefined
              ? " (server default)" : " (tenant override)"}
          </div>
        )}
        {isAdmin && (
          <div className="gp-config">
            <label className="int-label">GoPhish admin URL</label>
            <input className="input" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://127.0.0.1:3333" />
            <label className="int-label">API key {st && st.api_key_set && <span className="faint">(set - leave blank to keep)</span>}</label>
            <input className="input" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                   placeholder={st && st.api_key_set ? "-------- (unchanged)" : "paste GoPhish API key"} />
            <label className="int-label">TLS certificate verification</label>
            <select className="input" value={verifyTls === null ? "" : String(verifyTls)}
                    onChange={(e) => setVerifyTls(e.target.value === "" ? null : e.target.value === "true")}>
              <option value="">Use server default</option>
              <option value="true">Verify (recommended for production)</option>
              <option value="false">Skip verification (self-signed cert)</option>
            </select>
            <div style={{ marginTop: 8 }}>
              <button className="btn-primary btn-sm" onClick={saveConfig} disabled={!!busy}>{busy === "save" ? "..." : "Save & connect"}</button>
            </div>
            <div className="faint" style={{ marginTop: 6 }}>
              API key stored write-only, never shown again. Find it in GoPhish -> Settings -> API key.
              GoPhish ships a self-signed admin cert by default - only skip verification if you know
              this tenant's GoPhish server uses one; verify against a real certificate in production.
            </div>
          </div>
        )}
        {camps && (
          <div style={{ marginTop: 14, overflowX: "auto" }}>
            {camps.length === 0 ? <div className="faint">No GoPhish campaigns found.</div> : (
              <table className="table">
                <thead>
                  <tr><th>#</th><th>Campaign</th><th>Status</th><th>Opened</th><th>Clicked</th><th>Submitted</th><th>Linked</th><th></th></tr>
                </thead>
                <tbody>
                  {camps.map((c) => (
                    <tr key={c.id}>
                      <td>{c.id}</td><td>{c.name}</td><td>{c.status}</td>
                      <td>{(c.stats && c.stats.opened) || 0}</td>
                      <td>{(c.stats && c.stats.clicked) || 0}</td>
                      <td>{(c.stats && c.stats.submitted) || 0}</td>
                      <td>{c.linked ? <span className="chip">linked</span> : <span className="faint">-</span>}</td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {gpBase && <a className="btn-ghost btn-sm" href={`${gpBase}/campaigns/${c.id}`} target="_blank" rel="noreferrer">Open ↗</a>}
                        {isAdmin && <button className="btn-ghost btn-sm" disabled={!!busy} onClick={() => doComplete(c.id)}>Complete</button>}
                        {isAdmin && <button className="btn-ghost btn-sm" disabled={!!busy} onClick={() => doDelete(c.id)}>Delete</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function DirectoryPanel({ tenantId, role }) {
  const isAdmin = role === "org_admin" || role === "super_admin";
  const [source, setSource] = useState("entra");
  const [st, setSt] = useState(null);
  const [tenant, setTenant] = useState("");
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [uri, setUri] = useState("");
  const [bindDn, setBindDn] = useState("");
  const [bindPw, setBindPw] = useState("");
  const [baseDn, setBaseDn] = useState("");
  const [filter, setFilter] = useState("");
  const [preview, setPreview] = useState(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");

  const load = (src) => {
    setErr(""); setMsg(""); setPreview(null);
    const getter = src === "ldap" ? getLdapStatus : getEntraStatus;
    getter(tenantId).then((s) => {
      setSt(s);
      if (src === "entra" && s.entra_tenant_id) setTenant(s.entra_tenant_id);
      if (src === "ldap") {
        if (s.ldap_uri) setUri(s.ldap_uri);
        if (s.ldap_base_dn) setBaseDn(s.ldap_base_dn);
        if (s.ldap_bind_dn) setBindDn(s.ldap_bind_dn);
        if (s.ldap_user_filter) setFilter(s.ldap_user_filter);
      }
    }).catch((e) => setErr(e.message));
  };
  useEffect(() => load(source), [tenantId, source]);

  const save = async () => {
    setBusy("save"); setErr(""); setMsg("");
    try {
      if (source === "entra") {
        const body = {};
        if (tenant) body.tenant_id = tenant;
        if (clientId) body.client_id = clientId;
        if (secret) body.client_secret = secret;
        await setEntraConfig(tenantId, body);
        setSecret(""); setClientId("");
        const s = await getEntraStatus(tenantId); setSt(s);
        setMsg(s.ok ? "Connected to Microsoft Graph ✓" : (s.error || "Saved, but not reachable yet."));
      } else {
        const body = {};
        if (uri) body.uri = uri;
        if (bindDn) body.bind_dn = bindDn;
        if (bindPw) body.bind_password = bindPw;
        if (baseDn) body.base_dn = baseDn;
        if (filter) body.user_filter = filter;
        await setLdapConfig(tenantId, body);
        setBindPw("");
        const s = await getLdapStatus(tenantId); setSt(s);
        setMsg(s.ok ? "Bound to Active Directory ✓" : (s.error || "Saved, but not reachable yet."));
      }
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const doPreview = async () => {
    setBusy("prev"); setErr(""); setMsg("");
    try {
      const r = source === "ldap" ? await previewLdap(tenantId) : await previewEntra(tenantId);
      setPreview(r.users);
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const doSync = async () => {
    if (!window.confirm("Import directory users into the employee roster now?")) return;
    setBusy("sync"); setErr(""); setMsg("");
    try {
      const r = source === "ldap" ? await syncLdap(tenantId) : await syncEntra(tenantId);
      setMsg(`Imported: ${r.created} new, ${r.updated} updated, ${r.skipped} skipped (of ${r.total}). Recompute to score new hires.`);
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Directory sync</h2>
        <div className="section-actions">
          <button className="btn btn-xs" onClick={doPreview} disabled={!!busy}>{busy === "prev" ? "..." : "Preview"}</button>
          {isAdmin && <button className="btn btn-xs" onClick={doSync} disabled={!!busy}>{busy === "sync" ? "..." : "↓ Import users"}</button>}
        </div>
      </div>
      <div className="panel-body">
        <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
          <button className={`btn btn-xs ${source === "entra" ? "btn-primary" : ""}`} onClick={() => setSource("entra")}>Azure AD (Entra)</button>
          <button className={`btn btn-xs ${source === "ldap" ? "btn-primary" : ""}`} onClick={() => setSource("ldap")}>On-prem AD (LDAP)</button>
        </div>
        <p className="faint int-intro">
          Pulls your people into the employee roster - name, email, department, title, office, and a
          seniority guess from job title. Reads directory <strong>metadata only</strong>; it never
          reads anyone's password.
        </p>
        {err && <div className="banner banner-error">{err}</div>}
        {msg && <div className="banner">{msg}</div>}
        {st && (
          <div className={`int-status ${st.ok ? "ok" : "off"}`} style={{ marginBottom: 12 }}>
            {st.ok ? (source === "ldap" ? "● bound - directory reachable" : "● connected - directory reachable")
              : st.configured ? `○ configured but not reachable${st.error ? ": " + st.error : ""}`
              : "○ not configured"}
          </div>
        )}
        {isAdmin && source === "entra" && (
          <div className="gp-config">
            <label className="int-label">Directory (tenant) ID or domain</label>
            <input className="input" value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="contoso.onmicrosoft.com" />
            <label className="int-label">Application (client) ID</label>
            <input className="input" value={clientId} onChange={(e) => setClientId(e.target.value)}
                   placeholder={st && st.client_id_set ? "---- (set - blank keeps)" : "app registration client id"} />
            <label className="int-label">Client secret {st && st.client_secret_set && <span className="faint">(set - leave blank to keep)</span>}</label>
            <input className="input" type="password" value={secret} onChange={(e) => setSecret(e.target.value)}
                   placeholder={st && st.client_secret_set ? "-------- (unchanged)" : "client secret value"} />
            <div style={{ marginTop: 8 }}>
              <button className="btn-primary btn-sm" onClick={save} disabled={!!busy}>{busy === "save" ? "..." : "Save & test"}</button>
            </div>
            <div className="faint" style={{ marginTop: 6 }}>
              Needs an Entra app registration with the <code>User.Read.All</code> (or{" "}
              <code>Directory.Read.All</code>) application permission, admin-consented. Stored write-only.
            </div>
          </div>
        )}
        {isAdmin && source === "ldap" && (
          <div className="gp-config">
            <label className="int-label">LDAP server URI</label>
            <input className="input" value={uri} onChange={(e) => setUri(e.target.value)} placeholder="ldap://dc.corp.local:389  (or ldaps://...:636)" />
            <label className="int-label">Bind DN (read-only service account)</label>
            <input className="input" value={bindDn} onChange={(e) => setBindDn(e.target.value)} placeholder="svc-directory@corp.local  or  CN=svc,OU=...,DC=corp,DC=local" />
            <label className="int-label">Bind password {st && st.bind_password_set && <span className="faint">(set - leave blank to keep)</span>}</label>
            <input className="input" type="password" value={bindPw} onChange={(e) => setBindPw(e.target.value)}
                   placeholder={st && st.bind_password_set ? "-------- (unchanged)" : "service account password"} />
            <label className="int-label">Search base DN</label>
            <input className="input" value={baseDn} onChange={(e) => setBaseDn(e.target.value)} placeholder="DC=corp,DC=local" />
            <label className="int-label">User filter <span className="faint">(optional)</span></label>
            <input className="input" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="(&(objectClass=user)(objectCategory=person))" />
            <div style={{ marginTop: 8 }}>
              <button className="btn-primary btn-sm" onClick={save} disabled={!!busy}>{busy === "save" ? "..." : "Save & test"}</button>
            </div>
            <div className="faint" style={{ marginTop: 6 }}>
              Use a read-only service account, and prefer <code>ldaps://</code> in production. Reads
              directory metadata only; the bind password is stored write-only.
            </div>
          </div>
        )}
        {preview && (
          <div style={{ marginTop: 14, overflowX: "auto" }}>
            <div className="int-label">Preview (first {preview.length})</div>
            {preview.length === 0 ? <div className="faint">No users returned.</div> : (
              <table className="table">
                <thead><tr><th>Name</th><th>Email</th><th>Dept</th><th>Title</th><th>Seniority</th></tr></thead>
                <tbody>
                  {preview.map((u) => (
                    <tr key={u.email}><td>{u.full_name}</td><td>{u.email}</td><td>{u.department}</td>
                      <td>{u.job_title}</td><td><span className="chip">{u.seniority_level}</span></td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function GoPhishControlPanel({ tenantId, role }) {
  const canControl = role === "org_admin" || role === "super_admin" || role === "operator";
  const [tpls, setTpls] = useState(null);
  const [pages, setPages] = useState(null);
  const [smtps, setSmtps] = useState(null);
  const [groups, setGroups] = useState(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");
  const [groupName, setGroupName] = useState("All Staff");
  const [dept, setDept] = useState("");
  const [f, setF] = useState({
    name: "", template: "", page: "", smtp: "", group: "", url: "",
    tier: 2, attack_vector: "credential_harvest", launch_date: "", authorized: false,
  });
  const upd = (k, v) => setF((s) => ({ ...s, [k]: v }));

  const loadAll = async () => {
    setBusy("load"); setErr(""); setMsg("");
    try {
      const [t, p, s, g] = await Promise.all([
        gpTemplates(tenantId), gpPages(tenantId), gpSmtp(tenantId), gpGroups(tenantId)]);
      setTpls(t); setPages(p); setSmtps(s); setGroups(g);
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const pushGroup = async () => {
    setBusy("group"); setErr(""); setMsg("");
    try {
      const r = await gpGroupFromRoster(tenantId, { name: groupName, department: dept || null });
      setMsg(`Group "${r.name}" pushed with ${r.targets} target(s).`);
      setGroups(await gpGroups(tenantId));
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const chosenPage = pages && pages.find((p) => p.name === f.page);
  const pwCapture = chosenPage && chosenPage.capture_passwords;

  const launch = async () => {
    if (!f.name || !f.template || !f.page || !f.smtp || !f.group || !f.url) {
      setErr("Fill name, template, landing page, sending profile, group and URL."); return;
    }
    if (!f.authorized) { setErr("Confirm this simulation is authorized before launching."); return; }
    setBusy("launch"); setErr(""); setMsg("");
    try {
      const body = { ...f };
      if (!body.launch_date) delete body.launch_date;
      const r = await gpLaunch(tenantId, body);
      setMsg(`Launched - GoPhish #${r.gophish_id}, linked to scoring.${r.warning ? " Warning: " + r.warning : ""}`);
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  if (!canControl) return null;
  const grid = { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 12px" };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>GoPhish campaign control</h2>
        <div className="section-actions">
          <button className="btn btn-xs" onClick={loadAll} disabled={!!busy}>{busy === "load" ? "..." : "Load content"}</button>
        </div>
      </div>
      <div className="panel-body">
        <p className="faint int-intro">
          Run the whole campaign lifecycle from here: build target groups from your roster and
          launch or schedule campaigns. The email templates and landing pages are the ones you
          authored <strong>in GoPhish</strong> - this console selects and uses them, it doesn't
          create or clone them. Launches are authorization-gated and audit-logged.
        </p>
        {err && <div className="banner banner-error">{err}</div>}
        {msg && <div className="banner">{msg}</div>}

        <div className="gp-config" style={{ marginBottom: 16 }}>
          <div className="int-label">Build a target group from the roster</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
            <input className="input" style={{ flex: "1 1 160px" }} value={groupName}
                   onChange={(e) => setGroupName(e.target.value)} placeholder="Group name" />
            <input className="input" style={{ flex: "1 1 160px" }} value={dept}
                   onChange={(e) => setDept(e.target.value)} placeholder="Department (blank = everyone)" />
            <button className="btn-primary btn-sm" onClick={pushGroup} disabled={!!busy}>{busy === "group" ? "..." : "Push group"}</button>
          </div>
        </div>

        <div className="gp-config">
          <div className="int-label">Launch a campaign</div>
          <input className="input" value={f.name} onChange={(e) => upd("name", e.target.value)} placeholder="Campaign name" />
          <div style={grid}>
            <div>
              <label className="int-label">Email template</label>
              <select className="input" value={f.template} onChange={(e) => upd("template", e.target.value)}>
                <option value="">- choose -</option>
                {(tpls || []).map((t) => <option key={t.id} value={t.name}>{t.name}</option>)}
              </select>
            </div>
            <div>
              <label className="int-label">Landing page</label>
              <select className="input" value={f.page} onChange={(e) => upd("page", e.target.value)}>
                <option value="">- choose -</option>
                {(pages || []).map((p) => <option key={p.id} value={p.name}>{p.name}{p.capture_passwords ? " (captures passwords)" : ""}</option>)}
              </select>
            </div>
            <div>
              <label className="int-label">Sending profile</label>
              <select className="input" value={f.smtp} onChange={(e) => upd("smtp", e.target.value)}>
                <option value="">- choose -</option>
                {(smtps || []).map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
              </select>
            </div>
            <div>
              <label className="int-label">Target group</label>
              <select className="input" value={f.group} onChange={(e) => upd("group", e.target.value)}>
                <option value="">- choose -</option>
                {(groups || []).map((g) => <option key={g.id} value={g.name}>{g.name} ({g.targets})</option>)}
              </select>
            </div>
            <div>
              <label className="int-label">Phishing URL</label>
              <input className="input" value={f.url} onChange={(e) => upd("url", e.target.value)} placeholder="http://sim.yourdomain/..." />
            </div>
            <div>
              <label className="int-label">Difficulty tier (scoring)</label>
              <select className="input" value={f.tier} onChange={(e) => upd("tier", parseInt(e.target.value))}>
                <option value={1}>Tier 1 - low</option><option value={2}>Tier 2 - moderate</option><option value={3}>Tier 3 - targeted</option>
              </select>
            </div>
            <div>
              <label className="int-label">Vector</label>
              <select className="input" value={f.attack_vector} onChange={(e) => upd("attack_vector", e.target.value)}>
                <option value="credential_harvest">credential_harvest</option>
                <option value="link_only">link_only</option>
                <option value="attachment_download">attachment_download</option>
                <option value="chatbot">chatbot</option>
              </select>
            </div>
            <div>
              <label className="int-label">Launch date (blank = now)</label>
              <input className="input" type="datetime-local"
                     onChange={(e) => upd("launch_date", e.target.value ? new Date(e.target.value).toISOString() : "")} />
            </div>
          </div>
          {pwCapture && (
            <div className="banner banner-error" style={{ marginTop: 10 }}>
              Warning: the selected landing page captures <strong>passwords</strong> in GoPhish. Best practice
              for awareness testing is to disable password capture - this platform never receives or
              stores those values.
            </div>
          )}
          <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10 }}>
            <input type="checkbox" checked={f.authorized} onChange={(e) => upd("authorized", e.target.checked)} />
            <span>I confirm this phishing simulation is authorized for these recipients.</span>
          </label>
          <div style={{ marginTop: 10 }}>
            <button className="btn-primary btn-sm" onClick={launch} disabled={!!busy || !f.authorized}>{busy === "launch" ? "..." : "Launch campaign"}</button>
          </div>
          <div className="faint" style={{ marginTop: 6 }}>
            Templates and landing pages come from GoPhish. Use "Load content" to refresh the lists.
          </div>
        </div>
      </div>
    </div>
  );
}

function Copy({ text }) {
  const [done, setDone] = useState(false);
  return (
    <button className="btn-ghost btn-sm" onClick={async () => {
      try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }
      catch { /* clipboard blocked; user can select manually */ }
    }}>{done ? "Copied" : "Copy"}</button>
  );
}

export default function Integration({ tenantId, role }) {
  const isAdmin = role === "org_admin" || role === "super_admin";
  const [cfg, setCfg] = useState(null);
  const [err, setErr] = useState("");
  const [revealed, setRevealed] = useState({}); // field -> value shown once
  const [busy, setBusy] = useState("");

  const load = () => {
    setErr("");
    getIntegration(tenantId).then(setCfg).catch((e) => setErr(e.message));
  };
  useEffect(load, [tenantId]);

  const rotate = async (field) => {
    if (!window.confirm(
      `Rotate ${field.replace("_", " ")}? The old value stops working immediately, ` +
      `and the new value is shown only once.`)) return;
    setBusy(field);
    try {
      const r = await rotateSecret(tenantId, field);
      setRevealed((m) => ({ ...m, [field]: r.value }));
      load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(""); }
  };

  if (err) return <div className="center-msg">Couldn't load integration config: {err}</div>;
  if (!cfg) return <div className="center-msg"><span className="spinner" />Loading...</div>;

  const tokenForSnippet = revealed.ingest_token || "<YOUR_BEACON_INGEST_TOKEN>";
  const snippet =
`<script>
  window.PHISH_BEACON = {
    endpoint:    "${cfg.beacon_url.split("?")[0]}",
    tenantId:    "${cfg.tenant_id}",
    token:       "${tokenForSnippet}",
    campaignRef: "{{.CampaignId}}",
    email:       "{{.Email}}"
  };
</script>
<script src="beacon.js" defer></script>`;

  const Secret = ({ label, field, set }) => (
    <div className="int-row">
      <div>
        <div className="int-label">{label}</div>
        <div className={`int-status ${set ? "ok" : "off"}`}>
          {set ? "● configured" : "○ not set"}
        </div>
        {revealed[field] && (
          <div className="int-reveal">
            <code>{revealed[field]}</code>
            <Copy text={revealed[field]} />
            <span className="faint"> - copy now; not shown again</span>
          </div>
        )}
      </div>
      {isAdmin && (
        <button className="btn-primary btn-sm" disabled={busy === field}
                onClick={() => rotate(field)}>
          {busy === field ? "..." : set ? "Rotate" : "Generate"}
        </button>
      )}
    </div>
  );

  return (
    <div className="fade-in int-wrap">
      <StatusPanel tenantId={tenantId} />
      <DirectoryPanel tenantId={tenantId} role={role} />
      <GoPhishSyncPanel tenantId={tenantId} role={role} />
      <GoPhishControlPanel tenantId={tenantId} role={role} />
      <div className="panel">
        <div className="panel-head"><h2>GoPhish webhook</h2></div>
        <div className="panel-body">
          <p className="faint int-intro">
            Point your GoPhish webhook here to feed real campaign events (opened / clicked /
            submitted / reported) into the scoring pipeline. Set the secret below as the
            webhook's signing key.
          </p>
          <div className="int-url">
            <code>{cfg.webhook_url}</code><Copy text={cfg.webhook_url} />
          </div>
          <Secret label="Webhook signing secret" field="webhook_secret" set={cfg.webhook_secret_set} />
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h2>Landing-page beacon</h2></div>
        <div className="panel-body">
          <p className="faint int-intro">
            The beacon adds the richer signals GoPhish can't see - dwell time, credential-field
            focus, and typing-without-submitting. It sends <strong>metadata only</strong>; it never
            reads or transmits what a person types. Host <code>beacon.js</code> (in the repo under
            <code> instrumentation/</code>) on your landing page and add this snippet:
          </p>
          <div className="int-url">
            <code>{cfg.beacon_url}</code><Copy text={cfg.beacon_url} />
          </div>
          <Secret label="Beacon ingest token" field="ingest_token" set={cfg.ingest_token_set} />
          <div className="int-snippet">
            <div className="int-snippet-head">
              <span className="int-label">Landing-page snippet</span>
              <Copy text={snippet} />
            </div>
            <pre>{snippet}</pre>
            <div className="faint">
              GoPhish substitutes <code>{"{{.Email}}"}</code> and <code>{"{{.CampaignId}}"}</code> per
              recipient. <code>campaignRef</code> must match the campaign's <code>external_ref</code>
              (link it under Manage -> Campaigns).
              {!revealed.ingest_token && cfg.ingest_token_set &&
                " The token isn't shown here for security - paste the value you saved when you generated it."}
            </div>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h2>Awareness &amp; Remediation Portal</h2></div>
        <div className="panel-body">
          <p className="faint int-intro">
            The separate Portal service authenticates its background automation (pulling scores,
            pushing risk floors and in-person marks) with this token instead of an operator login -
            it can reach only the portal signal endpoints, nothing else in Manage. Generate it here,
            then paste it into the Portal's Settings screen.
          </p>
          <Secret label="Portal service token" field="portal_service_token"
                  set={cfg.portal_service_token_set} />
        </div>
      </div>
    </div>
  );
}

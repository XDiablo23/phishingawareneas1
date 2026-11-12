// Thin API client. The session itself lives in an httpOnly cookie set by
// the backend (backend/app/api/security.py) - this file never holds the
// access token, so an XSS payload can't read or exfiltrate it. Every
// request is sent with credentials so the browser attaches that cookie;
// state-changing requests also attach the CSRF cookie's value as a header
// (double-submit pattern - see backend/app/api/csrf.py). Only non-secret
// profile fields (role/tenant/email/department) are mirrored into
// localStorage, purely for UI state between page loads. In dev, URLs are
// relative and proxied to the backend by Vite; set VITE_API_BASE for a
// separate production origin.

const BASE = import.meta.env.VITE_API_BASE || "";

function readCookie(name) {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

export function getSession() {
  try {
    return JSON.parse(localStorage.getItem("phish_session") || "null");
  } catch {
    return null;
  }
}

export function setSession(session) {
  if (session) localStorage.setItem("phish_session", JSON.stringify(session));
  else localStorage.removeItem("phish_session");
}

function csrfHeaders(method) {
  const m = (method || "GET").toUpperCase();
  if (m === "GET" || m === "HEAD") return {};
  const csrf = readCookie("csrf_token");
  return csrf ? { "X-CSRF-Token": csrf } : {};
}

function handleUnauthorized() {
  setSession(null);
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("phish-unauthorized"));
  }
}

async function req(path, opts = {}) {
  const res = await fetch(BASE + path, {
    ...opts,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...csrfHeaders(opts.method),
      ...(opts.headers || {}),
    },
  });
  if (res.status === 401) handleUnauthorized();
  if (!res.ok) {
    let msg = `${res.status}`;
    try {
      const body = await res.json();
      msg = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

// --- auth ---
export async function login(email, password) {
  const body = new URLSearchParams({ username: email, password });
  const res = await fetch(BASE + "/api/v1/auth/login", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) throw new Error("Incorrect email or password");
  const data = await res.json();
  // The httpOnly cookie set on this response is what actually authenticates
  // future requests - never keep access_token in JS-readable storage, or
  // an XSS payload could read it there just as easily as from localStorage.
  const { access_token, token_type, ...profile } = data;
  return profile; // { role, tenant_id, email, department_scope }
}

export async function logout() {
  try {
    await fetch(BASE + "/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
      headers: csrfHeaders("POST"),
    });
  } finally {
    setSession(null);
  }
}

// --- demo bootstrap ---
export const seedDemo = (n_employees = 60, n_campaigns = 8) =>
  req("/api/v1/seed/synthetic", {
    method: "POST",
    body: JSON.stringify({ n_employees, n_campaigns }),
  });

export const recompute = (tid) =>
  req(`/api/v1/tenants/${tid}/recompute`, { method: "POST" });

// --- dashboard reads ---
const d = (tid) => `/api/v1/tenants/${tid}/dashboard`;
export const getSummary = (tid) => req(`${d(tid)}/summary`);
export const getDepartments = (tid) => req(`${d(tid)}/departments`);
export const getCampaigns = (tid) => req(`${d(tid)}/campaigns`);
export const getEmployees = (tid, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return req(`${d(tid)}/employees${q ? "?" + q : ""}`);
};
export const getEmployee = (tid, eid) => req(`${d(tid)}/employees/${eid}`);
export const getOrgTrend = (tid, weeks = 8) =>
  req(`${d(tid)}/trend?weeks=${weeks}`);
export const getEmployeeTrend = (tid, eid, weeks = 8) =>
  req(`${d(tid)}/employees/${eid}/trend?weeks=${weeks}`);

// --- management: campaigns ---
const mg = (tid) => `/api/v1/tenants/${tid}/manage`;
export const listCampaigns = (tid) => req(`${mg(tid)}/campaigns`);
export const createCampaign = (tid, body) =>
  req(`${mg(tid)}/campaigns`, { method: "POST", body: JSON.stringify(body) });
export const updateCampaign = (tid, cid, body) =>
  req(`${mg(tid)}/campaigns/${cid}`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteCampaign = (tid, cid) =>
  req(`${mg(tid)}/campaigns/${cid}`, { method: "DELETE" });

// --- management: roster ---
export const listRoster = (tid) => req(`${mg(tid)}/employees`);
export const createEmployee = (tid, body) =>
  req(`${mg(tid)}/employees`, { method: "POST", body: JSON.stringify(body) });
export const updateEmployee = (tid, eid, body) =>
  req(`${mg(tid)}/employees/${eid}`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteEmployee = (tid, eid) =>
  req(`${mg(tid)}/employees/${eid}`, { method: "DELETE" });
export async function importRoster(tid, file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(BASE + `${mg(tid)}/employees/import`, {
    method: "POST",
    credentials: "include",
    headers: csrfHeaders("POST"), // let the browser set the multipart boundary itself
    body: fd,
  });
  if (res.status === 401) handleUnauthorized();
  if (!res.ok) {
    let msg = `${res.status}`;
    try { const b = await res.json(); msg = b.detail || JSON.stringify(b); } catch { /**/ }
    throw new Error(msg);
  }
  return res.json();
}

// --- management: users ---
export const listUsers = (tid) => req(`${mg(tid)}/users`);
export const createUser = (tid, body) =>
  req(`${mg(tid)}/users`, { method: "POST", body: JSON.stringify(body) });
export const updateUser = (tid, uid, body) =>
  req(`${mg(tid)}/users/${uid}`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteUser = (tid, uid) =>
  req(`${mg(tid)}/users/${uid}`, { method: "DELETE" });
export const resetUserPassword = (tid, uid) =>
  req(`${mg(tid)}/users/${uid}/reset-password`, { method: "POST" });

// --- CSV export (auth'd download via blob) ---
export async function downloadEmployeesCsv(tid) {
  const res = await fetch(BASE + `${mg(tid)}/export/employees.csv`, {
    credentials: "include",
  });
  if (res.status === 401) { handleUnauthorized(); return; }
  if (!res.ok) throw new Error(`export failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "risk_scores.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// --- management: integration (webhook + beacon config, secret rotation) ---
export const getIntegration = (tid) => req(`${mg(tid)}/integration`);
export const rotateSecret = (tid, field) =>
  req(`${mg(tid)}/integration/rotate`, { method: "POST", body: JSON.stringify({ field }) });
// live inbound-event health (proves GoPhish/beacon are actually delivering)
export const getIntegrationStatus = (tid) => req(`${mg(tid)}/integration/status`);

// --- management: scoring settings (aggregation model) ---
export const getSettings = (tid) => req(`${mg(tid)}/settings`);
export const updateSettings = (tid, body) =>
  req(`${mg(tid)}/settings`, { method: "PATCH", body: JSON.stringify(body) });

// --- management: GoPhish sync (single-console, read-only pull) ---
export const getGoPhishStatus = (tid) => req(`${mg(tid)}/integration/gophish/status`);
export const setGoPhishConfig = (tid, body) =>
  req(`${mg(tid)}/integration/gophish/config`, { method: "POST", body: JSON.stringify(body) });
export const listGoPhishCampaigns = (tid) => req(`${mg(tid)}/integration/gophish/campaigns`);
export const syncGoPhish = (tid) =>
  req(`${mg(tid)}/integration/gophish/sync`, { method: "POST" });


// --- management: Entra (Azure AD) directory sync ---
export const setEntraConfig = (tid, body) =>
  req(`${mg(tid)}/integration/entra/config`, { method: "POST", body: JSON.stringify(body) });
export const getEntraStatus = (tid) => req(`${mg(tid)}/integration/entra/status`);
export const previewEntra = (tid) => req(`${mg(tid)}/integration/entra/preview`);
export const syncEntra = (tid) =>
  req(`${mg(tid)}/integration/entra/sync`, { method: "POST" });

// --- management: GoPhish full campaign lifecycle (operator control) ---
export const gpTemplates = (tid) => req(`${mg(tid)}/integration/gophish/templates`);
export const gpPages = (tid) => req(`${mg(tid)}/integration/gophish/pages`);
export const gpSmtp = (tid) => req(`${mg(tid)}/integration/gophish/smtp`);
export const gpGroups = (tid) => req(`${mg(tid)}/integration/gophish/groups`);
export const gpGroupFromRoster = (tid, body) =>
  req(`${mg(tid)}/integration/gophish/groups/from-roster`, { method: "POST", body: JSON.stringify(body) });
export const gpLaunch = (tid, body) =>
  req(`${mg(tid)}/integration/gophish/campaigns/launch`, { method: "POST", body: JSON.stringify(body) });
export const gpComplete = (tid, id) =>
  req(`${mg(tid)}/integration/gophish/campaigns/${id}/complete`, { method: "POST" });
export const gpDelete = (tid, id) =>
  req(`${mg(tid)}/integration/gophish/campaigns/${id}`, { method: "DELETE" });


// --- management: on-prem AD (LDAP) directory sync ---
export const setLdapConfig = (tid, body) =>
  req(`${mg(tid)}/integration/ldap/config`, { method: "POST", body: JSON.stringify(body) });
export const getLdapStatus = (tid) => req(`${mg(tid)}/integration/ldap/status`);
export const previewLdap = (tid) => req(`${mg(tid)}/integration/ldap/preview`);
export const syncLdap = (tid) =>
  req(`${mg(tid)}/integration/ldap/sync`, { method: "POST" });

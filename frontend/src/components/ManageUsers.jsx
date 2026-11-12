import React, { useEffect, useState } from "react";
import { listUsers, createUser, updateUser, deleteUser, resetUserPassword } from "../api.js";

const ROLES = ["org_admin", "operator", "dept_viewer"];
const blank = { email: "", role: "operator", department_scope: "" };

export default function ManageUsers({ tenantId, currentEmail }) {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState(null); // {email, password}

  const load = () => {
    setErr("");
    listUsers(tenantId).then(setRows).catch((e) => setErr(e.message));
  };
  useEffect(load, [tenantId]);

  async function submit() {
    setBusy(true); setErr(""); setIssued(null);
    try {
      const body = { email: form.email, role: form.role };
      if (form.role === "dept_viewer") body.department_scope = form.department_scope;
      const res = await createUser(tenantId, body);
      if (res.initial_password) setIssued({ email: res.email, password: res.initial_password });
      setForm(blank); setShowForm(false); load();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  async function changeRole(uid, role, dept) {
    try {
      const body = { role };
      if (role === "dept_viewer") body.department_scope = dept || "Finance";
      await updateUser(tenantId, uid, body);
      load();
    } catch (e) { setErr(e.message); }
  }
  async function reset(uid, email) {
    if (!window.confirm(`Reset password for ${email}?`)) return;
    try { const r = await resetUserPassword(tenantId, uid); setIssued({ email: r.email, password: r.initial_password }); }
    catch (e) { setErr(e.message); }
  }
  async function remove(uid, email) {
    if (!window.confirm(`Delete user ${email}?`)) return;
    try { await deleteUser(tenantId, uid); load(); } catch (e) { setErr(e.message); }
  }

  return (
    <div className="panel fade-in">
      <div className="panel-head">
        <h2>Console users</h2>
        <div className="section-actions">
          <button className="btn btn-xs" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "+ New user"}
          </button>
        </div>
      </div>

      {showForm && (
        <div className="form-panel">
          <div className="form-grid">
            <div className="form-field"><label>Email</label>
              <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
            <div className="form-field"><label>Role</label>
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {ROLES.map((r) => <option key={r} value={r}>{r.replace("_", " ")}</option>)}
              </select></div>
            {form.role === "dept_viewer" && (
              <div className="form-field"><label>Department scope</label>
                <input value={form.department_scope} onChange={(e) => setForm({ ...form, department_scope: e.target.value })}
                       placeholder="e.g. Finance" /></div>
            )}
          </div>
          <div className="form-actions">
            <button className="btn btn-primary"
                    disabled={busy || !form.email || (form.role === "dept_viewer" && !form.department_scope)}
                    onClick={submit}>
              {busy ? "Creating..." : "Create user"}
            </button>
            <span className="faint" style={{ fontSize: 12 }}>A one-time password is generated and shown once.</span>
          </div>
        </div>
      )}

      {issued && (
        <div className="banner banner-ok">
          Password for <strong>{issued.email}</strong> (copy it now - shown once):
          <div className="pw-box"><span className="val">{issued.password}</span></div>
        </div>
      )}
      {err && <div className="banner banner-error">{err}</div>}

      <div className="panel-body" style={{ padding: 0, overflowX: "auto" }}>
        {!rows ? (
          <div className="center-msg"><span className="spinner" />Loading...</div>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Email</th><th>Role</th><th>Scope</th><th></th></tr>
            </thead>
            <tbody>
              {rows.map((u) => {
                const self = u.email === currentEmail;
                return (
                  <tr key={u.id}>
                    <td className="name">{u.email}{self && <span className="faint" style={{ fontSize: 11 }}> - you</span>}</td>
                    <td>
                      <select className="inline" value={u.role} disabled={self}
                              onChange={(e) => changeRole(u.id, e.target.value, u.department_scope)}>
                        {ROLES.map((r) => <option key={r} value={r}>{r.replace("_", " ")}</option>)}
                      </select>
                    </td>
                    <td className="dim">{u.department_scope || "-"}</td>
                    <td className="actions">
                      <button className="btn btn-xs" onClick={() => reset(u.id, u.email)}>Reset password</button>
                      {!self && <button className="btn btn-xs btn-danger" onClick={() => remove(u.id, u.email)}>Delete</button>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

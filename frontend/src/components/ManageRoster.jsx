import React, { useEffect, useRef, useState } from "react";
import { listRoster, createEmployee, deleteEmployee, importRoster } from "../api.js";

const SENIORITY = ["", "Staff", "Manager", "Director", "Exec"];
const blank = { full_name: "", email: "", department: "", job_title: "", manager_email: "", seniority_level: "" };

export default function ManageRoster({ tenantId }) {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef();

  const load = () => {
    setErr("");
    listRoster(tenantId).then(setRows).catch((e) => setErr(e.message));
  };
  useEffect(load, [tenantId]);

  async function submit() {
    setBusy(true); setErr(""); setOk("");
    try {
      const body = { ...form };
      Object.keys(body).forEach((k) => body[k] === "" && (body[k] = k === "seniority_level" ? null : body[k]));
      await createEmployee(tenantId, { ...body, seniority_level: form.seniority_level || null,
        manager_email: form.manager_email || null });
      setForm(blank); setShowForm(false); setOk("Employee added."); load();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  async function doImport() {
    const file = fileRef.current?.files?.[0];
    if (!file) { setErr("Choose a CSV file first."); return; }
    setBusy(true); setErr(""); setOk("");
    try {
      const res = await importRoster(tenantId, file);
      setOk(`Imported: ${res.created} created, ${res.updated} updated, ${res.skipped} skipped.`
        + (res.errors?.length ? ` First issues: ${res.errors.slice(0, 3).join("; ")}` : ""));
      setShowImport(false); load();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  async function remove(eid, name) {
    if (!window.confirm(`Remove ${name} and all their event history?`)) return;
    try { await deleteEmployee(tenantId, eid); load(); } catch (e) { setErr(e.message); }
  }

  return (
    <div className="panel fade-in">
      <div className="panel-head">
        <h2>Employees {rows ? <span className="faint" style={{ fontWeight: 400 }}>- {rows.length}</span> : null}</h2>
        <div className="section-actions">
          <button className="btn btn-xs" onClick={() => { setShowForm((v) => !v); setShowImport(false); }}>
            {showForm ? "Cancel" : "+ Add employee"}
          </button>
          <button className="btn btn-xs" onClick={() => { setShowImport((v) => !v); setShowForm(false); }}>
            {showImport ? "Cancel" : "⬆ Import CSV"}
          </button>
        </div>
      </div>

      {showForm && (
        <div className="form-panel">
          <div className="form-grid">
            <div className="form-field"><label>Full name</label>
              <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></div>
            <div className="form-field"><label>Email</label>
              <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
            <div className="form-field"><label>Department</label>
              <input value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} /></div>
            <div className="form-field"><label>Job title</label>
              <input value={form.job_title} onChange={(e) => setForm({ ...form, job_title: e.target.value })} /></div>
            <div className="form-field"><label>Manager email (optional)</label>
              <input value={form.manager_email} onChange={(e) => setForm({ ...form, manager_email: e.target.value })} /></div>
            <div className="form-field"><label>Seniority (optional)</label>
              <select value={form.seniority_level} onChange={(e) => setForm({ ...form, seniority_level: e.target.value })}>
                {SENIORITY.map((s) => <option key={s} value={s}>{s || "-"}</option>)}
              </select></div>
          </div>
          <div className="form-actions">
            <button className="btn btn-primary" disabled={busy || !form.full_name || !form.email || !form.department || !form.job_title} onClick={submit}>
              {busy ? "Adding..." : "Add employee"}
            </button>
          </div>
        </div>
      )}

      {showImport && (
        <div className="form-panel">
          <div className="import-hint">
            CSV columns: <code>full_name</code>, <code>email</code>, <code>department</code>, <code>job_title</code>,
            and optionally <code>manager_email</code>, <code>seniority_level</code>. Existing rows (matched by email) are updated.
          </div>
          <div className="file-row">
            <input ref={fileRef} type="file" accept=".csv,text/csv" />
            <button className="btn btn-primary" disabled={busy} onClick={doImport}>
              {busy ? "Importing..." : "Import"}
            </button>
          </div>
        </div>
      )}

      {err && <div className="banner banner-error">{err}</div>}
      {ok && <div className="banner banner-ok">{ok}</div>}

      <div className="panel-body" style={{ padding: 0, overflowX: "auto" }}>
        {!rows ? (
          <div className="center-msg"><span className="spinner" />Loading...</div>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Name</th><th>Email</th><th>Department</th><th>Title</th><th>Seniority</th><th></th></tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id}>
                  <td className="name">{e.full_name}</td>
                  <td className="dim mono" style={{ fontSize: 12 }}>{e.email}</td>
                  <td className="dim">{e.department}</td>
                  <td className="dim">{e.job_title}</td>
                  <td className="dim">{e.seniority_level || "-"}</td>
                  <td className="actions">
                    <button className="btn btn-xs btn-danger" onClick={() => remove(e.id, e.full_name)}>Remove</button>
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr><td colSpan={6} className="faint" style={{ textAlign: "center", padding: 28 }}>
                  No employees yet. Add one or import a CSV.
                </td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

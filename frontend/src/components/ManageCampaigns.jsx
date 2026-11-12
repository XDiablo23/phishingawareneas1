import React, { useEffect, useState } from "react";
import { listCampaigns, createCampaign, updateCampaign, deleteCampaign } from "../api.js";

const VECTORS = ["link_only", "credential_harvest", "attachment_download", "chatbot", "mixed"];
const STATUSES = ["draft", "scheduled", "running", "completed", "halted"];

const blank = { name: "", tier: 1, attack_vector: "credential_harvest", external_ref: "" };

export default function ManageCampaigns({ tenantId }) {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setErr("");
    listCampaigns(tenantId).then(setRows).catch((e) => setErr(e.message));
  };
  useEffect(load, [tenantId]);

  async function submit() {
    setBusy(true);
    setErr("");
    try {
      await createCampaign(tenantId, { ...form, tier: Number(form.tier),
        external_ref: form.external_ref || null });
      setForm(blank);
      setShowForm(false);
      load();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(cid, status) {
    try { await updateCampaign(tenantId, cid, { status }); load(); }
    catch (e) { setErr(e.message); }
  }
  async function remove(cid, name) {
    if (!window.confirm(`Delete campaign "${name}" and its events? Scores refresh on Recompute.`)) return;
    try { await deleteCampaign(tenantId, cid); load(); }
    catch (e) { setErr(e.message); }
  }

  return (
    <div className="panel fade-in">
      <div className="panel-head">
        <h2>Campaigns</h2>
        <div className="section-actions">
          <button className="btn btn-xs" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "+ New campaign"}
          </button>
        </div>
      </div>

      {showForm && (
        <div className="form-panel">
          <div className="form-grid">
            <div className="form-field">
              <label>Name</label>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                     placeholder="e.g. Q1 Finance credential test" />
            </div>
            <div className="form-field">
              <label>Tier</label>
              <select value={form.tier} onChange={(e) => setForm({ ...form, tier: e.target.value })}>
                <option value={1}>Tier 1 - generic</option>
                <option value={2}>Tier 2 - role-based</option>
                <option value={3}>Tier 3 - manager impersonation</option>
              </select>
            </div>
            <div className="form-field">
              <label>Attack vector</label>
              <select value={form.attack_vector} onChange={(e) => setForm({ ...form, attack_vector: e.target.value })}>
                {VECTORS.map((v) => <option key={v} value={v}>{v.replace(/_/g, " ")}</option>)}
              </select>
            </div>
            <div className="form-field">
              <label>GoPhish campaign id (optional)</label>
              <input value={form.external_ref} onChange={(e) => setForm({ ...form, external_ref: e.target.value })}
                     placeholder="link to a GoPhish campaign" />
            </div>
          </div>
          <div className="form-actions">
            <button className="btn btn-primary" disabled={busy || !form.name} onClick={submit}>
              {busy ? "Creating..." : "Create campaign"}
            </button>
          </div>
        </div>
      )}

      {err && <div className="banner banner-error">{err}</div>}

      <div className="panel-body" style={{ padding: 0, overflowX: "auto" }}>
        {!rows ? (
          <div className="center-msg"><span className="spinner" />Loading...</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th><th>Tier</th><th>Vector</th><th>Status</th>
                <th style={{ textAlign: "right" }}>Targets</th>
                <th style={{ textAlign: "right" }}>Events</th>
                <th>GoPhish</th><th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td className="name">{c.name}</td>
                  <td className="mono">T{c.tier}</td>
                  <td className="dim">{c.attack_vector.replace(/_/g, " ")}</td>
                  <td>
                    <select className="inline" value={c.status} onChange={(e) => setStatus(c.id, e.target.value)}>
                      {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </td>
                  <td className="num dim">{c.targets}</td>
                  <td className="num dim">{c.events}</td>
                  <td className="dim mono" style={{ fontSize: 12 }}>{c.external_ref || "-"}</td>
                  <td className="actions">
                    <button className="btn btn-xs btn-danger" onClick={() => remove(c.id, c.name)}>Delete</button>
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr><td colSpan={8} className="faint" style={{ textAlign: "center", padding: 28 }}>
                  No campaigns yet. Create one, then link it to a GoPhish campaign to receive events.
                </td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

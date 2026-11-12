import React, { useEffect, useState } from "react";
import { getSettings, updateSettings, recompute } from "../api.js";

const MODES = [
  { key: "average", label: "Average",
    desc: "Decayed mean of all campaign residuals. Steady; one lapse fades over time." },
  { key: "peak", label: "Peak",
    desc: "Worst decayed residual only. Unforgiving; a single deep compromise dominates." },
  { key: "blend", label: "Blend",
    desc: "alpha-peak + (1-alpha)-average. Balances the worst event against the overall pattern." },
];

export default function ManageSettings({ tenantId, role }) {
  const isAdmin = role === "org_admin" || role === "super_admin";
  const [cfg, setCfg] = useState(null);
  const [mode, setMode] = useState("blend");
  const [alpha, setAlpha] = useState(0.5);
  const [overrideAgg, setOverrideAgg] = useState(true);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [savedMsg, setSavedMsg] = useState("");
  const [recomputing, setRecomputing] = useState(false);
  const [recomputed, setRecomputed] = useState(false);

  const load = () => {
    setErr("");
    getSettings(tenantId).then((c) => {
      setCfg(c);
      setMode(c.aggregation);
      setAlpha(c.blend_alpha);
      setOverrideAgg(c.aggregation_source === "tenant");
      setDirty(false);
    }).catch((e) => setErr(e.message));
  };
  useEffect(load, [tenantId]);

  const change = (fn) => { fn(); setDirty(true); setSavedMsg(""); setRecomputed(false); };

  async function save() {
    setSaving(true);
    setErr("");
    try {
      // If "use server default" is chosen, send null to clear the override.
      const body = overrideAgg
        ? { aggregation: mode, blend_alpha: mode === "blend" ? Number(alpha) : cfg.blend_alpha }
        : { aggregation: null, blend_alpha: null };
      const c = await updateSettings(tenantId, body);
      setCfg(c);
      setMode(c.aggregation);
      setAlpha(c.blend_alpha);
      setOverrideAgg(c.aggregation_source === "tenant");
      setDirty(false);
      setSavedMsg("Saved. Recompute to apply the change to stored scores.");
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  async function doRecompute() {
    setRecomputing(true);
    try { await recompute(tenantId); setRecomputed(true); setSavedMsg(""); }
    catch (e) { setErr(e.message); }
    finally { setRecomputing(false); }
  }

  if (err && !cfg) return <div className="center-msg">Couldn't load settings: {err}</div>;
  if (!cfg) return <div className="center-msg"><span className="spinner" />Loading...</div>;

  return (
    <div className="fade-in int-wrap">
      <div className="panel">
        <div className="panel-head"><h2>Scoring model</h2></div>
        <div className="panel-body">
          <p className="faint int-intro">
            How each person's campaign residuals combine into their headline Human Risk
            Score. This is a defensible, org-level choice - pick one and keep it consistent
            so trends stay comparable. Changes apply on the next <strong>Recompute</strong>.
          </p>

          <div className="set-effective">
            <span className="faint">Currently scoring with</span>{" "}
            <span className="pill">{cfg.aggregation}{cfg.aggregation === "blend" ? ` - alpha=${cfg.blend_alpha}` : ""}</span>{" "}
            <span className={`int-status ${cfg.aggregation_source === "tenant" ? "ok" : "off"}`}>
              {cfg.aggregation_source === "tenant" ? "● org override" : "○ server default"}
            </span>
          </div>

          {isAdmin ? (
            <>
              <label className="set-toggle">
                <input type="checkbox" checked={overrideAgg}
                       onChange={(e) => change(() => setOverrideAgg(e.target.checked))} />
                <span>Override the server default (<code>{cfg.default_aggregation}
                  {cfg.default_aggregation === "blend" ? ` - alpha=${cfg.default_blend_alpha}` : ""}</code>) for this organization</span>
              </label>

              <div className={`set-modes ${overrideAgg ? "" : "disabled"}`}>
                {MODES.map((m) => (
                  <label key={m.key} className={`set-mode ${mode === m.key ? "sel" : ""}`}>
                    <input type="radio" name="agg" value={m.key} disabled={!overrideAgg}
                           checked={mode === m.key}
                           onChange={() => change(() => setMode(m.key))} />
                    <div>
                      <div className="set-mode-label">{m.label}</div>
                      <div className="faint set-mode-desc">{m.desc}</div>
                    </div>
                  </label>
                ))}
              </div>

              {overrideAgg && mode === "blend" && (
                <div className="set-alpha">
                  <label>Blend alpha (peak weight): <strong>{Number(alpha).toFixed(2)}</strong></label>
                  <input type="range" min="0" max="1" step="0.05" value={alpha}
                         onChange={(e) => change(() => setAlpha(e.target.value))} />
                  <div className="faint set-alpha-scale">
                    <span>0 = all average</span><span>1 = all peak</span>
                  </div>
                </div>
              )}

              {err && <div className="banner banner-error" style={{ marginTop: 12 }}>{err}</div>}
              {savedMsg && <div className="banner banner-ok" style={{ marginTop: 12 }}>{savedMsg}</div>}
              {recomputed && <div className="banner banner-ok" style={{ marginTop: 12 }}>Recompute complete - scores now reflect this model.</div>}

              <div className="form-actions" style={{ marginTop: 14 }}>
                <button className="btn btn-primary" disabled={saving || !dirty} onClick={save}>
                  {saving ? "Saving..." : "Save"}
                </button>
                <button className="btn" disabled={recomputing} onClick={doRecompute}>
                  {recomputing ? <><span className="spinner" />Recomputing...</> : "↻ Recompute now"}
                </button>
              </div>
            </>
          ) : (
            <p className="faint">Only an administrator can change the scoring model.</p>
          )}
        </div>
      </div>
    </div>
  );
}

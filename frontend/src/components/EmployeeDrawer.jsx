import React, { useEffect, useState } from "react";
import { getEmployee, getEmployeeTrend } from "../api.js";
import { BandChip, Meter, DepthLadder, TrendSparkline } from "./shared.jsx";

export default function EmployeeDrawer({ tenantId, employeeId, onClose }) {
  const [emp, setEmp] = useState(null);
  const [err, setErr] = useState("");
  const [trend, setTrend] = useState(null);

  useEffect(() => {
    let live = true;
    setEmp(null);
    setTrend(null);
    getEmployee(tenantId, employeeId)
      .then((e) => live && setEmp(e))
      .catch((e) => setErr(e.message));
    getEmployeeTrend(tenantId, employeeId, 8)
      .then((t) => live && setTrend(t.points))
      .catch(() => {});
    return () => { live = false; };
  }, [tenantId, employeeId]);

  useEffect(() => {
    const onEsc = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [onClose]);

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true">
        {err && <div className="drawer-body center-msg">Couldn't load: {err}</div>}
        {!emp && !err && <div className="drawer-body center-msg"><span className="spinner" />Loading...</div>}
        {emp && (
          <>
            <div className="drawer-head">
              <div className="top">
                <div>
                  <h2>{emp.full_name}</h2>
                  <div className="sub">{emp.job_title} - {emp.department}</div>
                </div>
                <button className="x-btn" onClick={onClose} aria-label="Close">✕</button>
              </div>

              <div className="score-head">
                <div>
                  <div className="big" style={{ color: "var(--text)" }}>{emp.hrs}</div>
                </div>
                <div style={{ paddingBottom: 6 }}>
                  <span className="of">/ 100 HRS</span>{" "}
                  <BandChip band={emp.hrs_band} />
                </div>
              </div>
              <div style={{ marginTop: 10 }}><Meter value={emp.hrs} /></div>

              <div className="metric-row">
                <div className="m">
                  <div className="k">Susceptibility</div>
                  <div className="v">{emp.susceptibility_index}</div>
                </div>
                <div className="m">
                  <div className="k">Org-risk</div>
                  <div className="v">{emp.org_risk}</div>
                </div>
                <div className="m">
                  <div className="k">Campaigns</div>
                  <div className="v">{emp.campaigns.length}</div>
                </div>
              </div>
            </div>

            <div className="drawer-body">
              {emp.summary && <div className="summary-line">{emp.summary}</div>}

              {trend && trend.length >= 2 && (
                <div className="trend-block">
                  <div className="section-label">HRS trend - last {trend.length} weeks</div>
                  <TrendSparkline points={trend} field="hrs" label="Human Risk Score" />
                </div>
              )}

              <div className="section-label">Compromise depth by campaign</div>
              {emp.campaigns.map((c) => (
                <div className="camp-item" key={c.campaign_id}>
                  <div className="row1">
                    <span className="tier">T{c.tier}</span>
                    <span className="t">{c.campaign_name || c.vector.replace(/_/g, " ")}</span>
                    {c.reported && <span className="tag reported">reported</span>}
                    {c.breached && <span className="tag breached">breached pwd</span>}
                    <span className="risk-num">risk {c.campaign_risk_severity}</span>
                  </div>
                  <DepthLadder
                    vector={c.vector}
                    reasons={c.reasons}
                    depth={c.compromise_depth}
                    reported={c.reported}
                  />
                  <div className="ladder-caption">
                    <span className="faint">{c.vector.replace(/_/g, " ")}</span>
                    <span className="mono dim">
                      depth {c.compromise_depth} - reached {Math.round((c.penetration_ratio || 0) * 100)}%
                    </span>
                  </div>
                </div>
              ))}
              {!emp.campaigns.length && <div className="faint">No campaign activity recorded.</div>}
            </div>
          </>
        )}
      </aside>
    </>
  );
}

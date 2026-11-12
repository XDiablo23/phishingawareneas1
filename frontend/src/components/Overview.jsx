import React, { useEffect, useState } from "react";
import { getSummary, getDepartments, getCampaigns, getOrgTrend } from "../api.js";
import { BandChip, BAND_COLOR, bandOf, TrendSparkline } from "./shared.jsx";

function Stat({ label, value, sub }) {
  return (
    <div className="panel stat fade-in">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

function Distribution({ dist, total }) {
  return (
    <div>
      {["Low", "Moderate", "High", "Critical"].map((b) => {
        const n = dist?.[b] || 0;
        const pct = total ? (n / total) * 100 : 0;
        return (
          <div className="dist-row" key={b}>
            <BandChip band={b} />
            <div className="dist-track">
              <div className="dist-fill" style={{ width: `${pct}%`, background: BAND_COLOR[b] }} />
            </div>
            <div className="mono dim" style={{ textAlign: "right" }}>{n}</div>
          </div>
        );
      })}
    </div>
  );
}

function Heatmap({ depts }) {
  if (!depts?.length) return <div className="faint">No department data.</div>;
  return (
    <div className="heat">
      {depts.map((d) => (
        <div className="heat-cell" key={d.department}>
          <div className="glow" style={{ background: BAND_COLOR[d.band] }} />
          <div className="dept">{d.department}</div>
          <div className="meta">{d.employees} people - worst {d.worst_hrs}</div>
          <div className="score" style={{ color: BAND_COLOR[d.band] }}>{d.mean_hrs}</div>
        </div>
      ))}
    </div>
  );
}

function CampaignRow({ c }) {
  return (
    <div className="camp">
      <span className="tier">T{c.tier}</span>
      <div className="cname">
        <div className="t">{c.name}</div>
        <div className="v">{c.vector.replace(/_/g, " ")} - {c.targets} targeted - avg depth {c.mean_depth}</div>
      </div>
      <div className="funnel">
        <span className="seg">{c.opened} open</span>
        <span className="arrow">></span>
        <span className="seg">{c.clicked} click</span>
        <span className="arrow">></span>
        <span className="seg">{c.submitted} submit</span>
        {c.reported > 0 && <span className="seg" style={{ color: "var(--low)" }}>{c.reported} report</span>}
      </div>
    </div>
  );
}

export default function Overview({ tenantId, refreshKey }) {
  const [summary, setSummary] = useState(null);
  const [depts, setDepts] = useState(null);
  const [camps, setCamps] = useState(null);
  const [trend, setTrend] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let live = true;
    setErr("");
    setSummary(null);
    setTrend(null);
    Promise.all([getSummary(tenantId), getDepartments(tenantId), getCampaigns(tenantId)])
      .then(([s, d, c]) => {
        if (!live) return;
        setSummary(s);
        setDepts(d);
        setCamps(c);
      })
      .catch((e) => setErr(e.message));
    getOrgTrend(tenantId, 8)
      .then((t) => live && setTrend(t.points))
      .catch(() => {});
    return () => { live = false; };
  }, [tenantId, refreshKey]);

  if (err) return <div className="center-msg">Couldn't load overview: {err}</div>;
  if (!summary) return <div className="center-msg"><span className="spinner" />Loading overview...</div>;

  const total = summary.scored || 0;
  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="grid cols-4">
        <Stat label="Mean HRS" value={summary.mean_hrs} sub={`peak ${summary.max_hrs}`} />
        <Stat label="Employees scored" value={total} sub={`${summary.campaigns} campaigns`} />
        <Stat label="Mean susceptibility" value={summary.mean_susceptibility} sub="how easily fooled" />
        <Stat label="Breached submissions" value={summary.employees_with_breached_submission} sub="reused a breached password" />
      </div>

      <div className="grid cols-2">
        <div className="panel fade-in">
          <div className="panel-head">
            <h2>Risk band distribution</h2>
            <span className="eyebrow">{summary.scope?.department ? summary.scope.department : "whole org"}</span>
          </div>
          <div className="panel-body"><Distribution dist={summary.band_distribution} total={total} /></div>
        </div>

        <div className="panel fade-in">
          <div className="panel-head">
            <h2>Department heatmap</h2>
            <span className="eyebrow">mean HRS</span>
          </div>
          <div className="panel-body"><Heatmap depts={depts} /></div>
        </div>
      </div>

      {trend && trend.length >= 2 && (
        <div className="panel fade-in">
          <div className="panel-head">
            <h2>Org HRS trend</h2>
            <span className="eyebrow">mean - last {trend.length} weeks</span>
          </div>
          <div className="panel-body">
            <TrendSparkline
              points={trend.map((p) => ({ hrs: p.mean_hrs }))}
              field="hrs"
              height={90}
              label="Mean Human Risk Score"
            />
            <div className="trend-foot faint">
              {trend[trend.length - 1].high_or_critical} employee(s) currently High/Critical
            </div>
          </div>
        </div>
      )}

      <div className="panel fade-in">
        <div className="panel-head">
          <h2>Campaigns</h2>
          <span className="eyebrow">most recent first</span>
        </div>
        <div className="panel-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
          {camps?.length ? camps.map((c) => <CampaignRow key={c.campaign_id} c={c} />)
            : <div className="faint">No campaigns.</div>}
        </div>
      </div>
    </div>
  );
}

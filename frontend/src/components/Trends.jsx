import React, { useEffect, useState } from "react";
import { getOrgTrend } from "../api.js";
import { BAND_COLOR, bandOf } from "./shared.jsx";

// Org-level HRS trend. The backend re-scores the tenant at several past dates
// (decay makes older failures weigh less at each point), so this shows whether
// the population is improving without any historical-snapshot table.
export default function Trends({ tenantId, refreshKey }) {
  const [weeks, setWeeks] = useState(8);
  const [points, setPoints] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let live = true;
    setErr("");
    setPoints(null);
    getOrgTrend(tenantId, weeks)
      .then((r) => live && setPoints(r.points || []))
      .catch((e) => setErr(e.message));
    return () => { live = false; };
  }, [tenantId, weeks, refreshKey]);

  if (err) return <div className="center-msg">Couldn't load trend: {err}</div>;
  if (!points) return <div className="center-msg"><span className="spinner" />Computing trend...</div>;
  if (points.length < 2) return <div className="center-msg">Not enough history to plot a trend yet.</div>;

  const W = 320, H = 150, padL = 8, padR = 8, padT = 10, padB = 22;
  const iw = W - padL - padR, ih = H - padT - padB;
  const n = points.length;
  const means = points.map((p) => Math.max(0, Math.min(100, p.mean_hrs || 0)));
  const counts = points.map((p) => p.high_or_critical || 0);
  const maxCount = Math.max(1, ...counts);

  const x = (i) => padL + (n === 1 ? iw / 2 : (i / (n - 1)) * iw);
  const yHrs = (v) => padT + (1 - v / 100) * ih;
  const yCount = (c) => padT + (1 - c / maxCount) * ih;

  const line = means.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${yHrs(v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(n - 1).toFixed(1)},${padT + ih} L${x(0).toFixed(1)},${padT + ih} Z`;
  const last = means[n - 1], first = means[0];
  const col = BAND_COLOR[bandOf(last)];
  const delta = Math.round((last - first) * 10) / 10;
  const barW = Math.max(2, (iw / n) * 0.4);

  const showEvery = Math.ceil(n / 6);

  return (
    <div className="panel fade-in">
      <div className="panel-head">
        <h2>Risk trend - organisation</h2>
        <div className="filters">
          {[8, 12, 26].map((w) => (
            <button
              key={w}
              className={`btn-chip ${weeks === w ? "active" : ""}`}
              onClick={() => setWeeks(w)}
            >{w}w</button>
          ))}
        </div>
      </div>
      <div className="panel-body">
        <div className="trend-legend" style={{ marginBottom: 8 }}>
          <span><span className="dot" style={{ background: col }} /> Mean HRS</span>
          <span className="mono" style={{ color: col }}>
            {last.toFixed(0)}{" "}
            <span className="faint">({delta > 0 ? "▲ +" : delta < 0 ? "▼ " : "- "}{Math.abs(delta) || 0} over {n - 1} steps)</span>
          </span>
        </div>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
             aria-label={`Organisation mean HRS trend, latest ${last.toFixed(0)}`}>
          {/* band guides at 25/50/75 */}
          {[25, 50, 75].map((g) => (
            <line key={g} x1={padL} x2={W - padR} y1={yHrs(g)} y2={yHrs(g)} className="trend-guide" />
          ))}
          {/* High/Critical headcount bars (secondary axis) */}
          {counts.map((c, i) => (
            c > 0 && (
              <rect key={i} x={x(i) - barW / 2} y={yCount(c)} width={barW}
                    height={padT + ih - yCount(c)} rx="1"
                    fill="var(--danger, #e5484d)" opacity="0.28" />
            )
          ))}
          {/* mean-HRS line + fill */}
          <path d={area} fill={col} opacity="0.12" />
          <path d={line} fill="none" stroke={col} strokeWidth="1.8"
                vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
          <circle cx={x(n - 1)} cy={yHrs(last)} r="2.4" fill={col}
                  vectorEffect="non-scaling-stroke" />
          {/* x labels */}
          {points.map((p, i) => (
            (i % showEvery === 0 || i === n - 1) && (
              <text key={i} x={x(i)} y={H - 6} className="trend-xlabel"
                    textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}>
                {p.date.slice(5)}
              </text>
            )
          ))}
        </svg>
        <div className="trend-note faint">
          Bars = employees at <strong>High or Critical</strong> (peak {maxCount}). Line = decay-weighted mean HRS.
          A downward line means the population is improving.
        </div>
      </div>
    </div>
  );
}

import React from "react";

export const BANDS = ["Low", "Moderate", "High", "Critical"];
export const BAND_COLOR = {
  Low: "var(--low)",
  Moderate: "var(--moderate)",
  High: "var(--high)",
  Critical: "var(--critical)",
};

export function bandOf(hrs) {
  if (hrs <= 24) return "Low";
  if (hrs <= 49) return "Moderate";
  if (hrs <= 74) return "High";
  return "Critical";
}

export function BandChip({ band }) {
  return (
    <span className={`chip band-${band}`}>
      <span className="dot" />
      {band}
    </span>
  );
}

// Calibrated HRS meter with band zones and a needle at the score.
export function Meter({ value }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="meter" title={`HRS ${value}`}>
      <div className="needle" style={{ left: `calc(${pct}% - 1px)` }} />
    </div>
  );
}

// ---- compromise-depth ladder (the signature element) ----
const RUNGS = {
  opened: { short: "Open", match: "opened the email" },
  clicked: { short: "Click", match: "clicked the link" },
  dwell: { short: "Dwell", match: "dwelled" },
  field_focus: { short: "Focus", match: "focused a credential" },
  typed: { short: "Type", match: "typed credentials" },
  submitted: { short: "Submit", match: "submitted the fake" },
  download: { short: "Download", match: "downloaded the lure" },
  chatbot: { short: "Chatbot", match: "engaged the chatbot" },
  disclosure: { short: "Disclose", match: "disclosed a secret" },
};

const VECTOR_RUNGS = {
  link_only: ["opened", "clicked"],
  credential_harvest: ["opened", "clicked", "dwell", "field_focus", "typed", "submitted"],
  attachment_download: ["opened", "clicked", "download"],
  chatbot: ["opened", "clicked", "chatbot", "disclosure"],
  mixed: ["opened", "clicked", "dwell", "field_focus", "typed", "submitted", "download", "chatbot", "disclosure"],
};

function severityClass(depth) {
  if (depth < 20) return "sev-low";
  if (depth < 45) return "sev-mid";
  if (depth < 70) return "sev-hi";
  return "sev-crit";
}

export function DepthLadder({ vector, reasons = [], depth = 0, reported = false }) {
  const keys = VECTOR_RUNGS[vector] || VECTOR_RUNGS.mixed;
  const text = reasons.join(" ").toLowerCase();
  const sev = severityClass(depth);
  // Reached rungs are derived from the reason trail directly. A protective
  // (pre-click) report has no stage keywords, so it lights nothing; an
  // after-click report still shows the stages the person actually reached.
  return (
    <div className="ladder">
      {keys.map((k) => {
        const reached = text.includes(RUNGS[k].match);
        return (
          <div key={k} className={`rung ${reached ? "reached " + sev : ""}`}>
            {RUNGS[k].short}
          </div>
        );
      })}
    </div>
  );
}

// --- TrendSparkline: dependency-free SVG line over 0..100 HRS ---
// Band thresholds (25/50/75) drawn as faint guides; the line and its end-dot
// take the band colour of the latest point. Values are HRS unless `field` set.
export function TrendSparkline({ points = [], field = "hrs", height = 64, label }) {
  if (!points || points.length < 2) {
    return <div className="faint" style={{ fontSize: 12 }}>Not enough history yet.</div>;
  }
  const W = 100, H = 100; // viewBox units; scales to container width
  const vals = points.map((p) => Math.max(0, Math.min(100, p[field] ?? 0)));
  const n = vals.length;
  const x = (i) => (i / (n - 1)) * W;
  const y = (v) => H - (v / 100) * H;
  const line = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${W},${H} L0,${H} Z`;
  const last = vals[n - 1];
  const first = vals[0];
  const col = BAND_COLOR[bandOf(last)];
  const delta = Math.round((last - first) * 10) / 10;
  return (
    <div className="trend-wrap">
      {label && (
        <div className="trend-legend">
          <span>{label}</span>
          <span className="mono" style={{ color: col }}>
            {last.toFixed(0)}{" "}
            <span className="faint">
              ({delta > 0 ? "▲ +" : delta < 0 ? "▼ " : "- "}{Math.abs(delta) || 0})
            </span>
          </span>
        </div>
      )}
      <svg className="trend-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
           style={{ height }} role="img" aria-label={`${label || "trend"}: ${last.toFixed(0)}`}>
        {[25, 50, 75].map((g) => (
          <line key={g} x1="0" x2={W} y1={y(g)} y2={y(g)}
                className="trend-guide" />
        ))}
        <path d={area} fill={col} opacity="0.12" />
        <path d={line} fill="none" stroke={col} strokeWidth="1.6"
              vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        <circle cx={x(n - 1)} cy={y(last)} r="1.8" fill={col}
                vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}

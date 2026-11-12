import React, { useEffect, useMemo, useState } from "react";
import { getEmployees } from "../api.js";
import { BandChip } from "./shared.jsx";

const COLS = [
  { key: "name",           label: "Name",       sortVal: (r) => (r.full_name || "").toLowerCase() },
  { key: "department",     label: "Department", sortVal: (r) => (r.department || "").toLowerCase() },
  { key: "seniority",      label: "Role",       sortVal: (r) => r.seniority_level || "" },
  { key: "hrs",            label: "HRS",        num: true, sortVal: (r) => r.hrs },
  { key: "band",           label: "Band",       sortVal: (r) => r.hrs },
  { key: "susceptibility", label: "Suscept.",   num: true, sortVal: (r) => r.susceptibility_index },
  { key: "org_risk",       label: "Org-risk",   num: true, sortVal: (r) => r.org_risk },
  { key: "campaigns",      label: "Campaigns",  num: true, sortVal: (r) => r.campaigns_scored },
];

export default function People({ tenantId, onSelect, refreshKey }) {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState("");
  const [dept, setDept] = useState("");
  const [band, setBand] = useState("");
  const [seniority, setSeniority] = useState("");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState("hrs");
  const [sortDir, setSortDir] = useState("desc");

  useEffect(() => {
    let live = true;
    setErr("");
    setRows(null);
    getEmployees(tenantId)
      .then((r) => live && setRows(r))
      .catch((e) => setErr(e.message));
    return () => { live = false; };
  }, [tenantId, refreshKey]);

  const departments = useMemo(
    () => (rows ? [...new Set(rows.map((r) => r.department))].sort() : []),
    [rows]
  );
  const seniorities = useMemo(
    () => (rows ? [...new Set(rows.map((r) => r.seniority_level).filter(Boolean))].sort() : []),
    [rows]
  );

  const shown = useMemo(() => {
    if (!rows) return [];
    const q = query.trim().toLowerCase();
    const col = COLS.find((c) => c.key === sortKey) || COLS[3];
    const out = rows.filter(
      (r) =>
        (!dept || r.department === dept) &&
        (!band || r.hrs_band === band) &&
        (!seniority || r.seniority_level === seniority) &&
        (!q ||
          (r.full_name || "").toLowerCase().includes(q) ||
          (r.job_title || "").toLowerCase().includes(q))
    );
    out.sort((a, b) => {
      const va = col.sortVal(a), vb = col.sortVal(b);
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return sortDir === "asc" ? cmp : -cmp;
    });
    return out;
  }, [rows, dept, band, seniority, query, sortKey, sortDir]);

  const clickSort = (key) => {
    if (key === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir(key === "name" || key === "department" || key === "seniority" ? "asc" : "desc");
    }
  };

  if (err) return <div className="center-msg">Couldn't load people: {err}</div>;
  if (!rows) return <div className="center-msg"><span className="spinner" />Loading people...</div>;

  const sortLabel = COLS.find((c) => c.key === sortKey)?.label || "HRS";

  return (
    <div className="panel fade-in">
      <div className="panel-head">
        <h2>People - sorted by {sortLabel} ({sortDir})</h2>
        <div className="filters">
          <input
            className="input"
            placeholder="Search name / title..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ width: 170 }}
          />
          {departments.length > 1 && (
            <select className="select" value={dept} onChange={(e) => setDept(e.target.value)}>
              <option value="">All departments</option>
              {departments.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          )}
          {seniorities.length > 1 && (
            <select className="select" value={seniority} onChange={(e) => setSeniority(e.target.value)}>
              <option value="">All roles</option>
              {seniorities.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          )}
          <select className="select" value={band} onChange={(e) => setBand(e.target.value)}>
            <option value="">All bands</option>
            {["Low", "Moderate", "High", "Critical"].map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </div>
      </div>
      <div className="panel-body" style={{ padding: 0, overflowX: "auto" }}>
        <table className="table">
          <thead>
            <tr>
              {COLS.map((c) => (
                <th
                  key={c.key}
                  onClick={() => clickSort(c.key)}
                  className="th-sort"
                  aria-sort={sortKey === c.key ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                  style={c.num ? { textAlign: "right" } : undefined}
                >
                  {c.label}
                  <span className="sort-mark">{sortKey === c.key ? (sortDir === "asc" ? "▲" : "▼") : ""}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.employee_id} onClick={() => onSelect(r.employee_id)}>
                <td className="name">{r.full_name}</td>
                <td className="dim">{r.department}</td>
                <td className="role-cell">{r.seniority_level || "-"}</td>
                <td className="num">{r.hrs}</td>
                <td><BandChip band={r.hrs_band} /></td>
                <td className="num dim">{r.susceptibility_index}</td>
                <td className="num">{r.org_risk}</td>
                <td className="num dim">{r.campaigns_scored}</td>
              </tr>
            ))}
            {!shown.length && (
              <tr><td colSpan={8} className="faint" style={{ textAlign: "center", padding: 30 }}>No matching people.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

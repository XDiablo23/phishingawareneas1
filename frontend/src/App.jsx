import React, { useState, useEffect } from "react";
import { getSession, setSession, recompute, downloadEmployeesCsv, logout } from "./api.js";
import Login from "./components/Login.jsx";
import Overview from "./components/Overview.jsx";
import People from "./components/People.jsx";
import EmployeeDrawer from "./components/EmployeeDrawer.jsx";
import Manage from "./components/Manage.jsx";
import Trends from "./components/Trends.jsx";

export default function App() {
  const [session, setSess] = useState(getSession());
  const [tab, setTab] = useState("overview");
  const [selected, setSelected] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [recomputing, setRecomputing] = useState(false);

  function handleSession(s) {
    setSession(s);
    setSess(s);
    setTab("overview");
  }

  async function signOut() {
    setSess(null);
    setSelected(null);
    await logout(); // clears the httpOnly session cookie server-side
  }

  // If any API call reports the token expired, return to the login screen.
  useEffect(() => {
    const onExpire = () => {
      setSess(null);
      setSelected(null);
    };
    window.addEventListener("phish-unauthorized", onExpire);
    return () => window.removeEventListener("phish-unauthorized", onExpire);
  }, []);

  if (!session) return <Login onSession={handleSession} />;

  const tid = session.tenant_id;
  const canRecompute = ["super_admin", "org_admin", "operator"].includes(session.role);
  const canManage = ["super_admin", "org_admin", "operator"].includes(session.role);

  async function doRecompute() {
    setRecomputing(true);
    try {
      await recompute(tid);
      setSelected(null);
      setRefreshKey((k) => k + 1); // re-fetch the active view
    } catch {
      /* 401 handled globally; other errors surface in the views */
    } finally {
      setRecomputing(false);
    }
  }

  async function doExport() {
    try { await downloadEmployeesCsv(tid); } catch { /* surfaced via alert below */ }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brandmark">
          <div className="glyph">◇</div>
          <div>
            <div className="title">Phishing Risk Console</div>
            <div className="subtitle">Risk scoring &amp; analytics</div>
          </div>
        </div>
        <nav className="tabs">
          <button className={`tab ${tab === "overview" ? "active" : ""}`} onClick={() => setTab("overview")}>Overview</button>
          <button className={`tab ${tab === "people" ? "active" : ""}`} onClick={() => setTab("people")}>People</button>
          <button className={`tab ${tab === "trends" ? "active" : ""}`} onClick={() => setTab("trends")}>Trends</button>
          {canManage && (
            <button className={`tab ${tab === "manage" ? "active" : ""}`} onClick={() => setTab("manage")}>Manage</button>
          )}
        </nav>
        <div className="spacer" />
        <button className="ghost-btn" onClick={doExport} title="Export risk scores as CSV">⬇ Export</button>
        {canRecompute && (
          <button className="ghost-btn" onClick={doRecompute} disabled={recomputing} title="Recompute scores from the latest events">
            {recomputing ? <><span className="spinner" />Recomputing...</> : "↻ Recompute"}
          </button>
        )}
        <div className="who">
          <div className="email">{session.email}</div>
          <div className="role">
            {(session.role || "").replace("_", " ")}
            {session.department_scope ? ` - ${session.department_scope}` : ""}
          </div>
        </div>
        <button className="ghost-btn" onClick={signOut}>Sign out</button>
      </header>

      <main className="main">
        {tab === "overview" && <Overview tenantId={tid} refreshKey={refreshKey} />}
        {tab === "people" && <People tenantId={tid} onSelect={setSelected} refreshKey={refreshKey} />}
        {tab === "trends" && <Trends tenantId={tid} refreshKey={refreshKey} />}
        {tab === "manage" && canManage && <Manage tenantId={tid} role={session.role} email={session.email} />}
      </main>

      {selected && (
        <EmployeeDrawer
          tenantId={tid}
          employeeId={selected}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

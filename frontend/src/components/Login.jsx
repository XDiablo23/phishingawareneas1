import React, { useState } from "react";
import { login, seedDemo, recompute, logout } from "../api.js";

export default function Login({ onSession }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [demoUsers, setDemoUsers] = useState(null);
  const [seeding, setSeeding] = useState(false);

  async function doLogin(e, mail = email, pass = password) {
    if (e) e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const res = await login(mail, pass);
      onSession(res);
    } catch (ex) {
      setErr(ex.message || "Login failed");
    } finally {
      setBusy(false);
    }
  }

  async function createDemo() {
    setSeeding(true);
    setErr("");
    try {
      const res = await seedDemo(60, 8);
      // compute scores so the dashboard has data immediately (needs an
      // operator session - log in transiently as the operator to recompute,
      // then log back out so the user picks who to sign in as below; the
      // login call itself sets the session cookie as a side effect, so
      // there's no token to juggle by hand here)
      const op = res.demo_users.find((u) => u.role === "operator");
      await login(op.email, op.password);
      await recompute(res.tenant_id);
      await logout();
      setDemoUsers(res.demo_users);
    } catch (ex) {
      setErr(ex.message || "Could not create demo data");
    } finally {
      setSeeding(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-card panel fade-in">
        <div className="panel-body">
          <div className="brandmark" style={{ marginBottom: 16 }}>
            <div className="glyph">◇</div>
            <div>
              <div className="title">Phishing Risk Console</div>
              <div className="subtitle">Risk scoring &amp; analytics</div>
            </div>
          </div>

          <div className="login-title">Sign in</div>
          <div className="login-sub">
            Operator console for phishing-simulation risk analytics. New here?
            Spin up a demo organization with synthetic data to explore.
          </div>

          <form onSubmit={doLogin}>
            <div className="field">
              <label>Email</label>
              <input
                className="input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="operator@demo.local"
                autoComplete="username"
              />
            </div>
            <div className="field">
              <label>Password</label>
              <input
                className="input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </div>
            <button className="primary-btn" disabled={busy || !email || !password}>
              {busy ? <><span className="spinner" />Signing in...</> : "Sign in"}
            </button>
            <div className="err">{err}</div>
          </form>

          <div className="divider">or</div>

          {!demoUsers ? (
            <button className="ghost-btn" style={{ width: "100%" }} onClick={createDemo} disabled={seeding}>
              {seeding ? <><span className="spinner" />Building demo organization...</> : "Create demo organization"}
            </button>
          ) : (
            <div className="demo-users">
              <div className="faint" style={{ fontSize: 11.5, marginBottom: 4 }}>
                Demo ready. Sign in as any role:
              </div>
              {demoUsers.map((u) => (
                <button
                  key={u.email}
                  className="demo-user"
                  onClick={() => doLogin(null, u.email, u.password)}
                >
                  <span>
                    <div className="du-role">{u.role.replace("_", " ")}</div>
                    <div className="du-mail">{u.email}</div>
                  </span>
                  <span className="du-go">Sign in -></span>
                </button>
              ))}
            </div>
          )}

          <div className="note">
            Demo credentials are created for exploration only. This console
            reads simulation event metadata - it never handles real
            credentials.
          </div>
        </div>
      </div>
    </div>
  );
}

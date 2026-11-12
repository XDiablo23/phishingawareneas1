import React, { useState } from "react";
import ManageCampaigns from "./ManageCampaigns.jsx";
import ManageRoster from "./ManageRoster.jsx";
import ManageUsers from "./ManageUsers.jsx";
import Integration from "./Integration.jsx";
import ManageSettings from "./ManageSettings.jsx";

export default function Manage({ tenantId, role, email }) {
  const isAdmin = role === "org_admin" || role === "super_admin";
  const [sub, setSub] = useState("campaigns");

  return (
    <div className="fade-in">
      <div className="admin-tabs">
        <button className={`admin-tab ${sub === "campaigns" ? "active" : ""}`} onClick={() => setSub("campaigns")}>Campaigns</button>
        <button className={`admin-tab ${sub === "roster" ? "active" : ""}`} onClick={() => setSub("roster")}>Employees</button>
        {isAdmin && (
          <button className={`admin-tab ${sub === "users" ? "active" : ""}`} onClick={() => setSub("users")}>Users</button>
        )}
        <button className={`admin-tab ${sub === "integration" ? "active" : ""}`} onClick={() => setSub("integration")}>Integration</button>
        <button className={`admin-tab ${sub === "settings" ? "active" : ""}`} onClick={() => setSub("settings")}>Settings</button>
      </div>

      {sub === "campaigns" && <ManageCampaigns tenantId={tenantId} />}
      {sub === "roster" && <ManageRoster tenantId={tenantId} />}
      {sub === "users" && isAdmin && <ManageUsers tenantId={tenantId} currentEmail={email} />}
      {sub === "integration" && <Integration tenantId={tenantId} role={role} />}
      {sub === "settings" && <ManageSettings tenantId={tenantId} role={role} />}
    </div>
  );
}

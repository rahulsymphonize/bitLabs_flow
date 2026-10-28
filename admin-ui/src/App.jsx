import { useEffect, useState } from "react";
import { api, hasToken, logout } from "./api.js";
import Auth from "./pages/Auth.jsx";
import Users from "./pages/Users.jsx";
import Companies from "./pages/Companies.jsx";
import AuditLog from "./pages/AuditLog.jsx";

export default function App() {
  const [me, setMe] = useState(null);
  const [ready, setReady] = useState(!hasToken());
  const [tab, setTab] = useState("users");

  function load() {
    api
      .me()
      .then(setMe)
      .catch(() => logout())
      .finally(() => setReady(true));
  }

  useEffect(() => {
    if (hasToken()) load();
  }, []);

  if (!ready) return null;
  if (!me) return <Auth onDone={load} />;

  const isSys = me.role === "sysAdmin";
  const isAdmin = isSys || me.role === "admin";
  if (!isAdmin) {
    return (
      <div className="card login">
        <p>Your account has no admin access.</p>
        <button
          onClick={() => {
            logout();
            setMe(null);
          }}
        >
          Sign out
        </button>
      </div>
    );
  }

  const tabs = [
    ["users", "Users"],
    ...(isSys ? [["companies", "Companies"]] : []),
    ["audit", "Audit log"],
  ];

  return (
    <>
      <nav>
        <strong>Admin Panel</strong>
        {tabs.map(([key, label]) => (
          <button
            key={key}
            className={tab === key ? "active" : ""}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
        <span className="spacer" />
        <span>
          {me.email} ({me.role})
        </span>
        <button
          onClick={() => {
            logout();
            setMe(null);
          }}
        >
          Sign out
        </button>
      </nav>
      <main>
        {tab === "users" && <Users me={me} />}
        {tab === "companies" && isSys && <Companies />}
        {tab === "audit" && <AuditLog />}
      </main>
    </>
  );
}

import { useEffect, useState } from "react";
import { api } from "../api.js";

const EMPTY = {
  email: "",
  name: "",
  password: "",
  role: "user",
  company_id: "",
};

export default function Users({ me }) {
  const isSys = me.role === "sysAdmin";
  const [users, setUsers] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState("");

  const load = () =>
    api
      .users()
      .then(setUsers)
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
    if (isSys) api.companies().then(setCompanies);
  }, []);

  async function run(action) {
    setError("");
    try {
      await action();
      await load();
    } catch (e) {
      setError(e.message);
    }
  }

  function create(e) {
    e.preventDefault();
    const body = { ...form, company_id: Number(form.company_id) || null };
    run(async () => {
      await api.createUser(body);
      setForm(EMPTY);
    });
  }

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const roles = isSys ? ["user", "admin", "sysAdmin"] : ["user", "admin"];

  return (
    <>
      <h2>Users</h2>
      {error && <p className="error">{error}</p>}
      <form className="card row" onSubmit={create}>
        <input
          placeholder="Name"
          value={form.name}
          onChange={set("name")}
          required
        />
        <input
          type="email"
          autoComplete="off"
          placeholder="Email"
          value={form.email}
          onChange={set("email")}
          required
        />
        <input
          type="password"
          autoComplete="new-password"
          placeholder="Password (8+)"
          value={form.password}
          onChange={set("password")}
          minLength={8}
          required
        />
        <select value={form.role} onChange={set("role")}>
          {roles.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
        {isSys && form.role !== "sysAdmin" && (
          <select value={form.company_id} onChange={set("company_id")} required>
            <option value="">Company…</option>
            {companies
              .filter((c) => c.active)
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </select>
        )}
        <button>Add user</button>
      </form>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Role</th>
            {isSys && <th>Company</th>}
            <th>Status</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.map((u) => {
            const self = u.id === me.id;
            const editable = !self && u.role !== "sysAdmin";
            return (
              <tr key={u.id} className={u.active ? "" : "muted"}>
                <td>{u.name}</td>
                <td>{u.email}</td>
                <td>{u.role}</td>
                {isSys && <td>{u.company_id ?? "-"}</td>}
                <td>{u.active ? "Active" : "Inactive"}</td>
                <td>
                  {editable && (
                    <>
                      <button
                        onClick={() =>
                          run(() =>
                            api.updateUser(u.id, {
                              role: u.role === "admin" ? "user" : "admin",
                            }),
                          )
                        }
                      >
                        Make {u.role === "admin" ? "user" : "admin"}
                      </button>
                      <button
                        onClick={() =>
                          run(() => api.updateUser(u.id, { active: !u.active }))
                        }
                      >
                        {u.active ? "Deactivate" : "Restore"}
                      </button>
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}

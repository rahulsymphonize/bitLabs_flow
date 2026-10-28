import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Companies() {
  const [companies, setCompanies] = useState([]);
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  const load = () => api.companies().then(setCompanies);

  useEffect(() => {
    load();
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

  return (
    <>
      <h2>Companies</h2>
      {error && <p className="error">{error}</p>}
      <form
        className="card row"
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            await api.createCompany({ name });
            setName("");
          });
        }}
      >
        <input
          placeholder="Company name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <button>Add company</button>
      </form>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Name</th>
            <th>Status</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {companies.map((c) => (
            <tr key={c.id} className={c.active ? "" : "muted"}>
              <td>{c.id}</td>
              <td>{c.name}</td>
              <td>{c.active ? "Active" : "Inactive"}</td>
              <td>
                <button
                  onClick={() =>
                    run(() => api.updateCompany(c.id, { active: !c.active }))
                  }
                >
                  {c.active ? "Deactivate" : "Restore"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

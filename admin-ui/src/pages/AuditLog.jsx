import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function AuditLog() {
  const [rows, setRows] = useState([]);
  const [action, setAction] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .audit(action)
      .then(setRows)
      .catch((e) => setError(e.message));
  }, [action]);

  return (
    <>
      <h2>Audit log</h2>
      {error && <p className="error">{error}</p>}
      <input
        placeholder="Filter by action, e.g. user.create"
        value={action}
        onChange={(e) => setAction(e.target.value.trim())}
      />
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Actor</th>
            <th>Action</th>
            <th>Target</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{new Date(r.created_at + "Z").toLocaleString()}</td>
              <td>{r.actor_email ?? "-"}</td>
              <td>{r.action}</td>
              <td>
                {r.target_type ? `${r.target_type} #${r.target_id}` : "-"}
              </td>
              <td>
                <code>{JSON.stringify(r.meta)}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

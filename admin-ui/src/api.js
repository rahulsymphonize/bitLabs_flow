const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

let token = sessionStorage.getItem("token");

export const hasToken = () => Boolean(token);

export function logout() {
  token = null;
  sessionStorage.removeItem("token");
}

async function request(method, path, body) {
  const res = await fetch(BASE + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token && { Authorization: `Bearer ${token}` }),
    },
    body: body && JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const message =
      typeof detail === "string" ? detail : "Something went wrong";
    throw Object.assign(new Error(message), { status: res.status });
  }
  return data;
}

export async function login(email, password) {
  const data = await request("POST", "/auth/login", { email, password });
  token = data.access_token;
  sessionStorage.setItem("token", token);
}

export async function signup(body) {
  const data = await request("POST", "/auth/signup", body);
  token = data.access_token;
  sessionStorage.setItem("token", token);
}

export const api = {
  forgot: (email) => request("POST", "/auth/forgot-password", { email }),
  reset: (token, password) =>
    request("POST", "/auth/reset-password", { token, password }),
  me: () => request("GET", "/auth/me"),
  users: (companyId) =>
    request(
      "GET",
      "/admin/users" + (companyId ? `?company_id=${companyId}` : ""),
    ),
  createUser: (body) => request("POST", "/admin/users", body),
  updateUser: (id, body) => request("PATCH", `/admin/users/${id}`, body),
  companies: () => request("GET", "/admin/companies"),
  createCompany: (body) => request("POST", "/admin/companies", body),
  updateCompany: (id, body) => request("PATCH", `/admin/companies/${id}`, body),
  audit: (action) =>
    request("GET", "/admin/audit-logs" + (action ? `?action=${action}` : "")),
};

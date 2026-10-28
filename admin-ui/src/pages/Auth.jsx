import { useState } from "react";
import { api, login, signup } from "../api.js";

const resetToken = new URLSearchParams(window.location.search).get("reset");

export default function Auth({ onDone }) {
  const [view, setView] = useState(resetToken ? "reset" : "login");
  const [form, setForm] = useState({
    email: "",
    password: "",
    name: "",
    company_name: "",
  });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const go = (next) => () => {
    setView(next);
    setError("");
    setNotice("");
  };

  async function submit(e) {
    e.preventDefault();
    setError("");
    try {
      if (view === "login") {
        await login(form.email, form.password);
        onDone();
      } else if (view === "signup") {
        await signup(form);
        onDone();
      } else if (view === "forgot") {
        const data = await api.forgot(form.email);
        setNotice(data.detail);
      } else {
        const data = await api.reset(resetToken, form.password);
        window.history.replaceState({}, "", window.location.pathname);
        setForm({ ...form, password: "" });
        setView("login");
        setNotice(data.detail + " Please sign in.");
      }
    } catch (err) {
      setError(err.message);
    }
  }

  const titles = {
    login: "Sign in",
    signup: "Create your company",
    forgot: "Reset password",
    reset: "Choose a new password",
  };

  return (
    <form className="card login" onSubmit={submit}>
      <h1>{titles[view]}</h1>
      {view === "signup" && (
        <>
          <input
            placeholder="Company name"
            value={form.company_name}
            onChange={set("company_name")}
            required
          />
          <input
            placeholder="Your name"
            value={form.name}
            onChange={set("name")}
            required
          />
        </>
      )}
      {view !== "reset" && (
        <input
          type="email"
          placeholder="Email"
          value={form.email}
          onChange={set("email")}
          required
        />
      )}
      {view !== "forgot" && (
        <input
          type="password"
          placeholder={
            view === "login" ? "Password" : "Password (8+ characters)"
          }
          value={form.password}
          onChange={set("password")}
          minLength={view === "login" ? undefined : 8}
          required
        />
      )}
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      <button>{titles[view]}</button>
      {view === "login" && (
        <>
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              go("forgot")();
            }}
          >
            Forgot password?
          </a>
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              go("signup")();
            }}
          >
            Create a company account
          </a>
        </>
      )}
      {view !== "login" && (
        <a
          href="#"
          onClick={(e) => {
            e.preventDefault();
            go("login")();
          }}
        >
          Back to sign in
        </a>
      )}
    </form>
  );
}

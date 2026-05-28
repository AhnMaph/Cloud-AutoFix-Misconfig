import { useState } from "react";
import axios from "axios";
import { styles } from "../styles";

const API_URL = import.meta.env.VITE_BACKEND_URL;

export default function LoginForm({ onSuccess }) {
  const [form, setForm]       = useState({ username: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function handleLogin() {
    setError(null);
    if (!form.username || !form.password) {
      setError("Vui lòng nhập username và password.");
      return;
    }
    setLoading(true);
    try {
      const res = await axios.post(`${API_URL}/auth/login`, form);
      window.__authToken = res.data.access_token;
      onSuccess?.();
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div style={styles.field}>
        <label style={styles.label}>Username</label>
        <input
          style={styles.input}
          value={form.username}
          onChange={set("username")}
          placeholder="username"
          onKeyDown={(e) => e.key === "Enter" && handleLogin()}
        />
      </div>
      <div style={styles.field}>
        <label style={styles.label}>Password</label>
        <input
          style={styles.input}
          type="password"
          value={form.password}
          onChange={set("password")}
          placeholder="password"
          onKeyDown={(e) => e.key === "Enter" && handleLogin()}
        />
      </div>
      <button style={styles.btn("primary")} onClick={handleLogin} disabled={loading}>
        {loading ? "Đang đăng nhập..." : "Đăng nhập"}
      </button>
      {error && <div style={styles.error}>⚠ {error}</div>}
    </>
  );
}
import { useState } from "react";
import axios from "axios";
import { styles } from "../styles";

const API_URL = import.meta.env.VITE_BACKEND_URL;

export default function RegisterForm({ onSuccess }) {
  const [form, setForm]       = useState({ username: "", password: "", email: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);
  const [success, setSuccess] = useState(null);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function handleRegister() {
    setError(null);
    setSuccess(null);

    if (!form.username || !form.password) {
      setError("Username và password là bắt buộc.");
      return;
    }

    setLoading(true);

    try {
      const payload = {
        username: form.username.trim(),
        password: form.password,
        email: form.email.trim() || null,
      };

      const res = await axios.post(`${API_URL}/auth/register`, payload);

      setSuccess(
        `Đăng ký thành công! User: ${res.data.username} — Tenant tự động: ${res.data.tenant_id}`
      );

      setTimeout(() => onSuccess?.(), 1500);
    } catch (err) {
      setError(err.response?.data?.detail || JSON.stringify(err.response?.data) || err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div style={styles.field}>
        <label style={styles.label}>Username *</label>
        <input
          style={styles.input}
          value={form.username}
          onChange={set("username")}
          placeholder="vd: alice"
        />
      </div>

      <div style={styles.field}>
        <label style={styles.label}>Password *</label>
        <input
          style={styles.input}
          type="password"
          value={form.password}
          onChange={set("password")}
          placeholder="tối thiểu 6 ký tự"
        />
      </div>

      <div style={styles.field}>
        <label style={styles.label}>Email</label>
        <input
          style={styles.input}
          type="email"
          value={form.email}
          onChange={set("email")}
          placeholder="alice@example.com"
        />
      </div>

      <button style={styles.btn("primary")} onClick={handleRegister} disabled={loading}>
        {loading ? "Đang tạo tài khoản..." : "Đăng ký"}
      </button>

      {error   && <div style={styles.error}>⚠ {error}</div>}
      {success && <div style={styles.success}>✓ {success}</div>}
    </>
  );
}
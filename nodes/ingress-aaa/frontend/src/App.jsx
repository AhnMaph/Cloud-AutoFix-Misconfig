import { useState } from "react";
import axios from "axios";

import { styles } from "./styles";
import LoginForm from "./components/LoginForm";
import RegisterForm from "./components/RegisterForm";
import Dashboard from "./components/Dashboard";

const API_URL = import.meta.env.VITE_BACKEND_URL;

export default function App() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [me, setMe] = useState(null);
  const [tab, setTab] = useState("login");

  async function onLoginSuccess() {
    try {
      const res = await axios.get(`${API_URL}/me`, {
        headers: { Authorization: `Bearer ${window.__authToken}` },
      });
      setMe(res.data);
      setLoggedIn(true);
    } catch (err) {
      console.error("ME error:", err.response?.data || err.message);
      setLoggedIn(false);
    }
  }

  function logout() {
    window.__authToken = null;
    setLoggedIn(false);
    setMe(null);
  }

  if (loggedIn) {
    return (
      <div style={styles.root}>
        <Dashboard me={me} onLogout={logout} />
      </div>
    );
  }

  return (
    <div style={styles.root}>
      <div style={styles.card}>
        <div style={styles.logo}>Hybrid Cloud Portal</div>
        <div style={styles.title}>Chào mừng</div>

        <div style={styles.tabs}>
          <button style={styles.tab(tab === "login")} onClick={() => setTab("login")}>
            Đăng nhập
          </button>
          <button style={styles.tab(tab === "register")} onClick={() => setTab("register")}>
            Đăng ký
          </button>
        </div>

        {tab === "login" ? (
          <LoginForm onSuccess={onLoginSuccess} />
        ) : (
          <RegisterForm onSuccess={() => setTab("login")} />
        )}
      </div>
    </div>
  );
}
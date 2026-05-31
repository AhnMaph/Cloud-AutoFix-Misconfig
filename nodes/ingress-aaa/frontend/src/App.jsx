import { useEffect, useState } from "react";

import { styles } from "./styles";
import LoginForm from "./components/LoginForm";
import RegisterForm from "./components/RegisterForm";
import Dashboard from "./components/Dashboard";
import { setupApiInterceptors } from "./api/client";
import { checkSession, logout as logoutSession } from "./auth/session";

export default function App() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [me, setMe] = useState(null);
  const [tab, setTab] = useState("login");
  const [bootstrapping, setBootstrapping] = useState(true);

  function handleUnauthorized() {
    setLoggedIn(false);
    setMe(null);
  }

  useEffect(() => {
    setupApiInterceptors(handleUnauthorized);
  }, []);

  async function loadProfile() {
    const profile = await checkSession();
    setMe(profile);
    setLoggedIn(true);
    return profile;
  }

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        await loadProfile();
      } catch (err) {
        if (!cancelled) {
          setLoggedIn(false);
          setMe(null);
        }
        console.error("Session restore failed:", err.response?.data || err.message);
      } finally {
        if (!cancelled) setBootstrapping(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  async function onLoginSuccess() {
    try {
      await loadProfile();
    } catch (err) {
      console.error("ME error:", err.response?.data || err.message);
      setLoggedIn(false);
      setMe(null);
    }
  }

  async function logout() {
    await logoutSession();
    setLoggedIn(false);
    setMe(null);
  }

  if (bootstrapping) {
    return (
      <div style={styles.root}>
        <div style={{ ...styles.card, textAlign: "center", maxWidth: "320px" }}>
          <div style={styles.logo}>Hybrid Cloud Portal</div>
          <div style={{ color: "#94a3b8", fontSize: "14px", marginTop: "12px" }}>
            Restoring session…
          </div>
        </div>
      </div>
    );
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
        <div style={styles.title}>Welcome</div>

        <div style={styles.tabs}>
          <button style={styles.tab(tab === "login")} onClick={() => setTab("login")}>
            Sign in
          </button>
          <button
            style={styles.tab(tab === "register")}
            onClick={() => setTab("register")}
          >
            Register
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

import { useState } from "react";
import axios from "axios";
import { styles } from "../styles";
import { RESOURCE_TYPES } from "../constants/resources";
import ResourceForm from "./ResourceForm";
import DeployResult from "./DeployResult";

const API_URL = import.meta.env.VITE_BACKEND_URL;

export default function Dashboard({ me, onLogout }) {
  const [activeResource, setActiveResource] = useState(null);
  const [deployResult, setDeployResult]     = useState(null);
  const [error, setError]                   = useState(null);
  const [loading, setLoading]               = useState(false);

  async function handleSubmit(formData, action) {
    setError(null);
    setDeployResult(null);
    setLoading(true);
    try {
      const token = window.__authToken;
      const res = await axios.post(
        `${API_URL}/deploy`,
        { resource_type: activeResource.type, action, extra: formData },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setDeployResult(res.data);
      setActiveResource(null);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
      setActiveResource(null);
    } finally {
      setLoading(false);
    }
  }

  function openResource(r) {
    setDeployResult(null);
    setError(null);
    setActiveResource(r);
  }

  return (
    <div style={styles.dashboard}>
      <div style={styles.card}>

        {/* Header */}
        <div style={styles.dashHeader}>
          <div>
            <div style={styles.logo}>Hybrid Cloud Portal</div>
            <div style={{ fontSize: "20px", fontWeight: "700", color: "#fff" }}>
              Tenant Dashboard
            </div>
          </div>
          <button style={styles.logoutBtn} onClick={onLogout}>Logout</button>
        </div>

        <div style={styles.badge}>● ONLINE</div>

        {/* User info */}
        <div style={{ marginTop: "20px" }}>
          {[
            ["Username",  me?.username],
            ["Email",     me?.email || "—"],
          ].map(([k, v]) => (
            <div key={k} style={styles.infoRow}>
              <span style={styles.infoKey}>{k}</span>
              <span style={styles.infoVal}>{v}</span>
            </div>
          ))}
        </div>

        {/* Resource buttons */}
        <div style={{ marginTop: "24px", marginBottom: "8px" }}>
          <span style={{ fontSize: "11px", color: "#6b7280", letterSpacing: "0.1em", textTransform: "uppercase" }}>
            Deploy Resource
          </span>
        </div>
        <div style={styles.actionGrid}>
          {RESOURCE_TYPES.map((r) => (
            <button
              key={r.type}
              style={styles.actionBtn(r.color)}
              onClick={() => openResource(r)}
              disabled={loading}
            >
              {loading ? "..." : `${r.icon} ${r.label}`}
            </button>
          ))}
        </div>

        {error && <div style={styles.error}>⚠ {error}</div>}

        {deployResult && (
          <DeployResult result={deployResult} onClose={() => setDeployResult(null)} />
        )}
      </div>

      {/* Modal */}
      {activeResource && (
        <ResourceForm
          resource={activeResource}
          onClose={() => setActiveResource(null)}
          onSubmit={handleSubmit}
          loading={loading}
        />
      )}
    </div>
  );
}
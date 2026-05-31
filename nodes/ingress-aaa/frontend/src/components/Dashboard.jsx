import { useEffect, useState } from "react";
import axios from "axios";
import { styles } from "../styles";
import { RESOURCE_TYPES } from "../constants/resources";
import ResourceForm from "./ResourceForm";
import DeployResult from "./DeployResult";

const API_URL = import.meta.env.VITE_BACKEND_URL;

export default function Dashboard({ me, onLogout }) {
  const [activeResource, setActiveResource] = useState(null);
  const [deployResult, setDeployResult] = useState(null);
  const [deployment, setDeployment] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  function authHeaders() {
    const token = window.__authToken;

    return {
      Authorization: `Bearer ${token}`,
    };
  }

  async function fetchLatestDeployment() {
    try {
      const res = await axios.get(`${API_URL}/deployments/latest`, {
        headers: authHeaders(),
      });

      setDeployment(res.data.item || null);
      return res.data.item || null;
    } catch (err) {
      console.error(
        "Fetch latest deployment failed:",
        err.response?.data || err.message
      );
      return null;
    }
  }

  function startDeploymentPolling() {
    const poll = setInterval(async () => {
      const item = await fetchLatestDeployment();

      if (
        item &&
        !["submitted", "scanning", "deploying"].includes(item.status)
      ) {
        clearInterval(poll);
      }
    }, 5000);

    setTimeout(() => clearInterval(poll), 90000);
  }

  useEffect(() => {
    fetchLatestDeployment();
  }, []);

  async function handleSubmit(formData, action) {
    setError(null);
    setDeployResult(null);
    setLoading(true);

    try {
      const res = await axios.post(
        `${API_URL}/deploy/repo`,
        {
          resource_type: activeResource.type,
          action,
          region: formData.region || "us-east-1",
          extra: formData,
        },
        {
          headers: authHeaders(),
        }
      );

      setDeployResult(res.data);
      setDeployment(res.data.deployment || null);
      setActiveResource(null);

      startDeploymentPolling();
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
      setActiveResource(null);
    } finally {
      setLoading(false);
    }
  }

  async function requestFix(id) {
    try {
      setError(null);

      const res = await axios.post(
        `${API_URL}/deployments/${id}/request-fix`,
        {},
        {
          headers: authHeaders(),
        }
      );

      setDeployment(res.data.deployment);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    }
  }

  async function denyDeployment(id) {
    try {
      setError(null);

      const res = await axios.post(
        `${API_URL}/deployments/${id}/deny`,
        {},
        {
          headers: authHeaders(),
        }
      );

      setDeployment(res.data.deployment);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    }
  }

  async function acceptDeploy(id) {
    try {
      setError(null);
      setLoading(true);

      const res = await axios.post(
        `${API_URL}/deployments/${id}/accept`,
        {},
        {
          headers: authHeaders(),
        }
      );

      setDeployment(res.data.deployment);
    } catch (err) {
      const detail = err.response?.data?.detail;

      if (typeof detail === "string") {
        setError(detail);
      } else {
        setError(detail?.message || err.message);
      }
    } finally {
      setLoading(false);
    }
  }

  function openResource(r) {
    setDeployResult(null);
    setError(null);
    setActiveResource(r);
  }

  const summary = deployment?.fix_report?.summary;

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

          <button style={styles.logoutBtn} onClick={onLogout}>
            Logout
          </button>
        </div>

        <div style={styles.badge}>● ONLINE</div>

        {/* User info */}
        <div style={{ marginTop: "20px" }}>
          {[
            ["Username", me?.username],
            ["Email", me?.email || "—"],
          ].map(([k, v]) => (
            <div key={k} style={styles.infoRow}>
              <span style={styles.infoKey}>{k}</span>
              <span style={styles.infoVal}>{v}</span>
            </div>
          ))}
        </div>

        {/* Resource buttons */}
        <div style={{ marginTop: "24px", marginBottom: "8px" }}>
          <span
            style={{
              fontSize: "11px",
              color: "#6b7280",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
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

        {error && <div style={styles.error}>⚠ {formatError(error)}</div>}

        {deployResult && (
          <DeployResult
            result={deployResult}
            onClose={() => setDeployResult(null)}
          />
        )}

        {/* Deployment Security Review */}
        {deployment && (
          <div
            style={{
              marginTop: "24px",
              padding: "16px",
              border: "1px solid #2f3545",
              borderRadius: "12px",
              background: "#0f172a",
              color: "#e5e7eb",
            }}
          >
            <div
              style={{
                fontSize: "13px",
                color: "#94a3b8",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                marginBottom: "12px",
              }}
            >
              Deployment Security Review
            </div>

            <div style={infoLineStyle}>
              <b>Deployment ID:</b> {deployment.deployment_id}
            </div>

            <div style={infoLineStyle}>
              <b>Resource:</b> {deployment.provider} /{" "}
              {deployment.resource_type}
            </div>

            <div style={infoLineStyle}>
              <b>Status:</b>{" "}
              <span style={{ color: getStatusColor(deployment.status) }}>
                {deployment.status}
              </span>
            </div>

            <div style={infoLineStyle}>
              <b>OPA Decision:</b>{" "}
              <span
                style={{
                  color:
                    deployment.opa?.deny === true
                      ? "#ef4444"
                      : deployment.opa?.deny === false
                      ? "#22c55e"
                      : "#facc15",
                }}
              >
                {deployment.opa?.deny === true
                  ? "DENY"
                  : deployment.opa?.deny === false
                  ? "ALLOW"
                  : "ALLOW / PENDING"}
              </span>
            </div>

            {deployment.pipeline_url && (
              <div style={infoLineStyle}>
                <b>Pipeline:</b>{" "}
                <a
                  href={deployment.pipeline_url}
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: "#60a5fa" }}
                >
                  Open Woodpecker Pipeline
                </a>
              </div>
            )}

            {deployment.recommendation && (
              <div
                style={{
                  padding: "10px",
                  borderRadius: "8px",
                  background: "#111827",
                  color: "#d1d5db",
                  fontSize: "13px",
                  marginTop: "10px",
                  marginBottom: "12px",
                  lineHeight: "1.5",
                }}
              >
                {deployment.recommendation}
              </div>
            )}

            {summary && (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4, 1fr)",
                  gap: "8px",
                  marginBottom: "12px",
                }}
              >
                <SummaryBox label="Total" value={summary.total} />
                <SummaryBox label="Fixed" value={summary.fixed} />
                <SummaryBox label="Skipped" value={summary.skipped} />
                <SummaryBox label="Manual" value={summary.manual} />
              </div>
            )}

            <pre
              style={{
                whiteSpace: "pre-wrap",
                maxHeight: "360px",
                overflow: "auto",
                background: "#020617",
                padding: "12px",
                borderRadius: "8px",
                color: "#d1d5db",
                fontSize: "12px",
                lineHeight: "1.5",
              }}
            >
              {deployment.summary_markdown || "Waiting for CI/CD scan result..."}
            </pre>

            <div style={{ display: "flex", gap: "10px", marginTop: "14px" }}>
              {["blocked_by_policy", "needs_user_fix_decision"].includes(
                deployment.status
              ) && (
                <>
                  <button
                    style={buttonStyle("#f97316")}
                    onClick={() => requestFix(deployment.deployment_id)}
                    disabled={loading}
                  >
                    {deployment.status === "needs_user_fix_decision"
                      ? "Accept Auto-Fix"
                      : "Request Fix"}
                  </button>

                  <button
                    style={buttonStyle("#475569")}
                    onClick={() => denyDeployment(deployment.deployment_id)}
                    disabled={loading}
                  >
                    Cancel
                  </button>
                </>
              )}

              {deployment.status === "waiting_user_approval" && (
                <>
                  <button
                    style={buttonStyle("#22c55e")}
                    onClick={() => acceptDeploy(deployment.deployment_id)}
                    disabled={loading}
                  >
                    Accept Deploy
                  </button>

                  <button
                    style={buttonStyle("#475569")}
                    onClick={() => denyDeployment(deployment.deployment_id)}
                    disabled={loading}
                  >
                    Deny
                  </button>
                </>
              )}

              {deployment.status === "submitted" && (
                <span style={statusTextStyle("#facc15")}>
                  Waiting for CI/CD scan result...
                </span>
              )}

              {deployment.status === "scanning" && (
                <span style={statusTextStyle("#facc15")}>
                  CI/CD scan is running...
                </span>
              )}

              {deployment.status === "user_requested_fix" && (
                <span style={statusTextStyle("#facc15")}>
                  User requested fix. Waiting for remediation workflow.
                </span>
              )}

              {deployment.status === "user_denied" && (
                <span style={statusTextStyle("#94a3b8")}>
                  Deployment cancelled by user.
                </span>
              )}

              {deployment.status === "deploying" && (
                <span style={statusTextStyle("#60a5fa")}>
                  Terraform deployment is running...
                </span>
              )}

              {deployment.status === "applied" && (
                <span style={statusTextStyle("#22c55e")}>
                  Terraform apply completed.
                </span>
              )}

              {deployment.status === "planned" && (
                <span style={statusTextStyle("#22c55e")}>
                  Terraform plan completed.
                </span>
              )}

              {deployment.status === "apply_failed" && (
                <span style={statusTextStyle("#ef4444")}>
                  Terraform apply failed.
                </span>
              )}
            </div>

            {deployment.apply_error && (
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  maxHeight: "240px",
                  overflow: "auto",
                  background: "#1f1111",
                  padding: "12px",
                  borderRadius: "8px",
                  color: "#fecaca",
                  fontSize: "12px",
                  lineHeight: "1.5",
                  marginTop: "12px",
                }}
              >
                {deployment.apply_error}
              </pre>
            )}
          </div>
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

const infoLineStyle = {
  fontSize: "14px",
  marginBottom: "6px",
};

function SummaryBox({ label, value }) {
  return (
    <div
      style={{
        background: "#020617",
        border: "1px solid #1e293b",
        borderRadius: "8px",
        padding: "10px",
      }}
    >
      <div style={{ fontSize: "11px", color: "#94a3b8" }}>{label}</div>
      <div style={{ fontSize: "18px", fontWeight: "700", color: "#fff" }}>
        {value ?? 0}
      </div>
    </div>
  );
}

function buttonStyle(bg) {
  return {
    background: bg,
    color: "#fff",
    border: "none",
    borderRadius: "8px",
    padding: "9px 14px",
    cursor: "pointer",
    fontWeight: "600",
  };
}

function statusTextStyle(color) {
  return {
    color,
    fontSize: "13px",
    fontWeight: "600",
  };
}

function getStatusColor(status) {
  switch (status) {
    case "blocked_by_policy":
      return "#ef4444";
    case "needs_user_fix_decision":
      return "#f97316";
    case "waiting_user_approval":
      return "#22c55e";
    case "submitted":
    case "scanning":
      return "#facc15";
    case "user_requested_fix":
      return "#facc15";
    case "user_denied":
      return "#94a3b8";
    case "deploying":
      return "#60a5fa";
    case "applied":
    case "planned":
      return "#22c55e";
    case "apply_failed":
      return "#ef4444";
    default:
      return "#93c5fd";
  }
}

function formatError(error) {
  if (typeof error === "string") {
    return error;
  }

  try {
    return JSON.stringify(error, null, 2);
  } catch {
    return String(error);
  }
}
import { useEffect, useState } from "react";
import { styles } from "../styles";
import { RESOURCE_TYPES } from "../constants/resources";
import ResourceForm from "./ResourceForm";
import DeployResult from "./DeployResult";
import MarkdownContent from "./MarkdownContent";
import { api } from "../api/client";

export default function Dashboard({ me, onLogout }) {
  const [activeResource, setActiveResource] = useState(null);
  const [deployResult, setDeployResult] = useState(null);
  const [deployment, setDeployment] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function fetchLatestDeployment() {
    try {
      const res = await api.get("/deployments/latest");

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
      const res = await api.post("/deploy/repo", {
        resource_type: activeResource.type,
        action,
        region: formData.region || "us-east-1",
        extra: formData,
      });

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

      const res = await api.post(`/deployments/${id}/request-fix`, {});

      setDeployment(res.data.deployment);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    }
  }

  async function denyDeployment(id) {
    try {
      setError(null);

      const res = await api.post(`/deployments/${id}/deny`, {});

      setDeployment(res.data.deployment);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    }
  }

  async function acceptDeploy(id) {
    try {
      setError(null);
      setLoading(true);

      const res = await api.post(`/deployments/${id}/accept`, {});

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
      <div style={styles.dashboardCard}>
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
          <div style={reviewPanelStyle}>
            <div style={reviewHeaderStyle}>
              <span style={reviewTitleStyle}>Deployment Security Review</span>
              <span
                style={{
                  ...reviewStatusPillStyle,
                  color: getStatusColor(deployment.status),
                  borderColor: `${getStatusColor(deployment.status)}44`,
                  background: `${getStatusColor(deployment.status)}14`,
                }}
              >
                {deployment.status}
              </span>
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
              <div style={recommendationBoxStyle}>
                <div style={recommendationLabelStyle}>Scanner recommendation</div>
                <MarkdownContent className="markdown-content--compact">
                  {deployment.recommendation}
                </MarkdownContent>
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

            <div style={scanReportBoxStyle}>
              <div style={recommendationLabelStyle}>Scan report</div>
              {deployment.summary_markdown ? (
                <MarkdownContent className="markdown-content--compact markdown-content--scroll">
                  {deployment.summary_markdown}
                </MarkdownContent>
              ) : (
                <p style={{ margin: 0, color: "#94a3b8", fontSize: "13px" }}>
                  Waiting for CI/CD scan result…
                </p>
              )}
            </div>

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

const reviewPanelStyle = {
  marginTop: "28px",
  padding: "20px",
  border: "1px solid #2f3545",
  borderRadius: "14px",
  background: "linear-gradient(180deg, #121a2e 0%, #0f172a 100%)",
  color: "#e5e7eb",
  boxShadow: "inset 0 1px 0 rgba(255, 255, 255, 0.04)",
};

const reviewHeaderStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "12px",
  marginBottom: "16px",
  flexWrap: "wrap",
};

const reviewTitleStyle = {
  fontSize: "12px",
  color: "#94a3b8",
  textTransform: "uppercase",
  letterSpacing: "0.1em",
  fontWeight: "600",
};

const reviewStatusPillStyle = {
  fontSize: "11px",
  fontWeight: "600",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  padding: "4px 10px",
  borderRadius: "999px",
  border: "1px solid",
};

const recommendationBoxStyle = {
  padding: "14px 16px",
  borderRadius: "10px",
  background: "#111827",
  border: "1px solid #1e293b",
  marginTop: "12px",
  marginBottom: "14px",
};

const recommendationLabelStyle = {
  fontSize: "10px",
  fontWeight: "600",
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "#64748b",
  marginBottom: "10px",
};

const scanReportBoxStyle = {
  background: "#020617",
  border: "1px solid #1e293b",
  borderRadius: "10px",
  padding: "14px 16px",
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
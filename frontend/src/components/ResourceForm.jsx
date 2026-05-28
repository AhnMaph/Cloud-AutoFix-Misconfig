import { useState } from "react";
import { styles } from "../styles";
import { RESOURCE_FIELDS } from "../constants/resources";

export default function ResourceForm({ resource, onClose, onSubmit, loading }) {
  const fields = RESOURCE_FIELDS[resource.type] || [];

  const [form, setForm]   = useState(() =>
    Object.fromEntries(fields.map((f) => [f.key, f.defaultValue || ""]))
  );
  const [action, setAction] = useState("plan");

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const overlayStyle = {
    position: "fixed", inset: 0,
    background: "rgba(0,0,0,0.75)",
    display: "flex", alignItems: "center", justifyContent: "center",
    zIndex: 100, padding: "24px",
  };

  const modalStyle = {
    background: "#1a1d27",
    border: `1px solid ${resource.color}44`,
    borderRadius: "12px",
    padding: "32px",
    width: "100%",
    maxWidth: "440px",
    boxShadow: "0 16px 48px rgba(0,0,0,0.6)",
  };

  const selectStyle = {
    ...styles.input,
    appearance: "none",
    cursor: "pointer",
    background: "#0f1117",
  };

  function handleSubmit() {
    const missing = fields.filter((f) => f.required && !form[f.key]);
    if (missing.length > 0) return;
    onSubmit(form, action);
  }

  return (
    <div style={overlayStyle} onClick={onClose}>
      <div style={modalStyle} onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "24px" }}>
          <div>
            <div style={{ fontSize: "18px", fontWeight: "700", color: "#fff" }}>
                {resource.label}
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#6b7280", cursor: "pointer", fontSize: "18px", lineHeight: 1 }}>
            ✕
          </button>
        </div>

        {/* Fields */}
        {fields.map((f) => (
          <div key={f.key} style={styles.field}>
            <label style={styles.label}>
              {f.label}{" "}
              {f.required && <span style={{ color: "#ff6b6b" }}>*</span>}
            </label>
            {f.type === "select" ? (
              <select style={selectStyle} value={form[f.key]} onChange={set(f.key)}>
                {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : (
              <input
                style={styles.input}
                value={form[f.key]}
                onChange={set(f.key)}
                placeholder={f.placeholder}
              />
            )}
          </div>
        ))}

        {/* Plan / Apply toggle */}
        <div style={styles.field}>
          <label style={styles.label}>Action</label>
          <div style={{ display: "flex", gap: "8px" }}>
            {[
                { value: "plan", label: "📋 Preview" },
                { value: "apply", label: "🚀 Deploy" },
            ].map((a) => (
                <button
                    key={a.value}
                    onClick={() => setAction(a.value)}
                    style={{
                    flex: 1,
                    padding: "9px",
                    border: `1px solid ${action === a.value ? resource.color : "#2a2d3a"}`,
                    borderRadius: "6px",
                    background: action === a.value ? `${resource.color}22` : "transparent",
                    color: action === a.value ? resource.color : "#6b7280",
                    cursor: "pointer",
                    fontSize: "12px",
                    fontFamily: "inherit",
                    fontWeight: "700",
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    transition: "all 0.15s",
                    }}
                >
                    {a.label}
                </button>
            ))}
          </div>
          {action === "apply" && (
            <div style={{ marginTop: "8px", fontSize: "11px", color: "#fbbf24", padding: "8px 10px", background: "#fbbf2411", borderRadius: "4px", border: "1px solid #fbbf2422" }}>
                ⚠ This will create real cloud resources and may generate cost
            </div>
          )}
        </div>

        {/* Submit */}
        <button
          style={{ ...styles.btn("primary"), background: resource.color, border: "none", marginTop: "8px" }}
          onClick={handleSubmit}
          disabled={loading}
        >
            {loading
            ? action === "plan" ? "Creating Preview..." : "Deploying..."
            : action === "plan" ? "📋 Create Preview" : "🚀 Deploy Resource"}        
        </button>
      </div>
    </div>
  );
}
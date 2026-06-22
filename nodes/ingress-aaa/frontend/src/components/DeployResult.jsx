const getResourceLabel = (resourceType) => {
  const labels = {
    object_storage: "File Storage",
    cache: "Cache",
    vm: "Virtual Machine",
    database: "Database",
  };
  return labels[resourceType] || resourceType || "Resource";
};
export default function DeployResult({ result, onClose }) {
  const statusColor   = result.status === "planned" ? "#fbbf24"
                      : result.status === "applied"  ? "#4aff7a"
                      : result.status === "destroyed" ? "#ff6b6b"
                      : "#e8eaf0";

  const rowStyle = {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    padding: "8px 0", borderBottom: "1px solid #2a2d3a", fontSize: "12px",
  };

  return (
    <div style={{ marginTop: "16px", background: "#0f1117", border: "1px solid #2a2d3a", borderRadius: "8px", padding: "16px" }}>

      {/* Title row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
        <span style={{ fontSize: "11px", color: "#6b7280", letterSpacing: "0.1em", textTransform: "uppercase" }}>
          Result
        </span>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", color: "#6b7280", cursor: "pointer", fontSize: "14px", lineHeight: 1 }}
        >
          ✕
        </button>
      </div>

      {/* Meta rows */}
      {[
        ["Resource", getResourceLabel(result.resource_type)],
        ["Status", <span style={{ color: statusColor, fontWeight: "700" }}>{result.status?.toUpperCase()}</span>],
      ].map(([k, v]) => (
        <div key={k} style={rowStyle}>
          <span style={{ color: "#6b7280" }}>{k}</span>
          <span style={{ color: "#e8eaf0" }}>{v}</span>
        </div>
      ))}

      {/* Terraform plan output */}
      {result.terraform_output && (
        <div style={{ marginTop: "14px" }}>
          <div style={{ fontSize: "11px", color: "#6b7280", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "6px" }}>
            Terraform Output
          </div>
          <pre style={{
            background: "#0a0c12",
            border: "1px solid #2a2d3a",
            borderRadius: "4px",
            padding: "12px",
            fontSize: "11px",
            color: "#4aff7a",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
            maxHeight: "220px",
            overflowY: "auto",
            margin: 0,
            lineHeight: "1.5",
          }}>
            {result.terraform_output}
          </pre>
        </div>
      )}

      {/* Apply outputs (bucket_name, arn, etc.) */}
      {result.outputs && Object.keys(result.outputs).length > 0 && (
        <div style={{ marginTop: "14px" }}>
          <div style={{ fontSize: "11px", color: "#6b7280", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "6px" }}>
            Outputs
          </div>
          {Object.entries(result.outputs).map(([k, v]) => (
            <div key={k} style={rowStyle}>
              <span style={{ color: "#6b7280" }}>{k}</span>
              <span style={{ color: "#4aff7a", wordBreak: "break-all", textAlign: "right", maxWidth: "65%" }}>
                {v?.value ?? JSON.stringify(v)}
              </span>
            </div>
          ))}
        </div>
      )}

    </div>
  );
}

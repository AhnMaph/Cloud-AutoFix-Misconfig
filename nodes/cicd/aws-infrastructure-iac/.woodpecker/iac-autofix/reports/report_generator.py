"""Generate PR summary report in Markdown and HTML — multi-file aware."""

from __future__ import annotations
from collections import defaultdict
from pathlib import Path


SEV_EMOJI = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢", "INFO": "🔵", "UNKNOWN": "⚪"}
SEV_COLOR = {"CRITICAL": "#dc2626", "HIGH": "#ea580c", "MEDIUM": "#ca8a04",
             "LOW": "#16a34a", "INFO": "#2563eb", "UNKNOWN": "#6b7280"}


def generate_report(data: dict, md_path: Path, html_path: Path):
    md_path.write_text(_build_markdown(data), encoding="utf-8")
    html_path.write_text(_build_html(data),   encoding="utf-8")
    print(f"[+] Markdown report : {md_path}")
    print(f"[+] HTML report     : {html_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _group_by_file(items: list[dict]) -> dict[str, list[dict]]:
    g = defaultdict(list)
    for item in items:
        g[item.get("file_path", "unknown")].append(item)
    return dict(g)


def _short(path: str) -> str:
    """Return just the last 2 path components for readability."""
    parts = Path(path).parts
    return "/".join(parts[-2:]) if len(parts) >= 2 else path


# ─────────────────────────────────────────────────────────────────────────────
# Markdown
# ─────────────────────────────────────────────────────────────────────────────

def _build_markdown(data: dict) -> str:
    s   = data["summary"]
    ts  = data["timestamp"]
    dry = " *(dry-run — no files changed)*" if data["dry_run"] else ""

    tf_files     = data.get("tf_files", [])
    patched_map  = data.get("patched_files", {})
    fix_results  = data["fix_results"]
    no_fix       = data["no_fix"]

    fixed   = [r for r in fix_results if r["status"] == "fixed"]
    skipped = [r for r in fix_results if r["status"] == "skipped"]
    failed  = [r for r in fix_results if r["status"] == "failed"]

    lines = [
        f"# IaC Auto-Fix PR Summary{dry}",
        "",
        f"**Generated:** {ts}  ",
        f"**Scope:** `{data.get('tf_dir', '')}`  ",
        "",
        "## 📊 Summary",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| .tf files scanned | {len(tf_files)} |",
        f"| .tf files patched | {s.get('files_patched', 0)} |",
        f"| Total findings | {s['total']} |",
        f"| ✅ Auto-fixed | {s['fixed']} |",
        f"| ⏭ Skipped (no rule) | {s['skipped']} |",
        f"| ❌ Fix failed | {s['failed']} |",
        f"| 📋 Manual review | {s['manual']} |",
        "",
    ]

    # ── Files touched ─────────────────────────────────────────────────────────
    if patched_map:
        lines += ["## 📁 Patched Files", ""]
        for src, dst in patched_map.items():
            lines.append(f"- `{_short(src)}` → `{dst}`")
        lines.append("")

    # ── Fixed — grouped by file ───────────────────────────────────────────────
    if fixed:
        lines += ["## ✅ Auto-Fixed Issues", ""]
        for file_path, items in _group_by_file(fixed).items():
            lines.append(f"### 📄 `{_short(file_path)}`")
            lines.append("")
            lines += [
                "| Check ID | Severity | Resource | Fix |",
                "|----------|----------|----------|-----|",
            ]
            for r in items:
                sev   = r.get("severity", "UNKNOWN")
                emoji = SEV_EMOJI.get(sev, "⚪")
                lines.append(
                    f"| `{r['rule_id']}` | {emoji} {sev} "
                    f"| `{r.get('resource','N/A')}` | {r.get('rule','attr patch')} |"
                )
            lines.append("")

    # ── Failed ────────────────────────────────────────────────────────────────
    if failed:
        lines += ["## ❌ Fix Failures", ""]
        for file_path, items in _group_by_file(failed).items():
            lines.append(f"**`{_short(file_path)}`**")
            for r in items:
                lines.append(
                    f"- `{r['rule_id']}` on `{r.get('resource','?')}`: "
                    f"{r.get('reason','unknown')}"
                )
        lines.append("")

    # ── Skipped ───────────────────────────────────────────────────────────────
    if skipped:
        lines += [
            "<details>",
            "<summary>⏭ Skipped findings (no fixer rule)</summary>",
            "",
            "| Check ID | Severity | File | Resource | Reason |",
            "|----------|----------|------|----------|--------|",
        ]
        for r in skipped:
            sev   = r.get("severity", "UNKNOWN")
            emoji = SEV_EMOJI.get(sev, "⚪")
            lines.append(
                f"| `{r['rule_id']}` | {emoji} {sev} | `{_short(r.get('file_path', ''))}` "
                f"| `{r.get('resource','N/A')}` | {r.get('reason','')} |"
            )
        lines += ["", "</details>", ""]

    # ── Manual review — grouped by file ──────────────────────────────────────
    if no_fix:
        lines += [
            "## 📋 Manual Review Required (HIGH / CRITICAL)",
            "",
            "These findings were **not auto-fixed**. Address before merging.",
            "",
        ]
        for file_path, items in _group_by_file(no_fix).items():
            lines.append(f"### 📄 `{_short(file_path)}`")
            lines.append("")
            lines += [
                "| Severity | Check ID | Resource | Source | Guideline |",
                "|----------|----------|----------|--------|-----------|",
            ]
            for r in items:
                sev        = r.get("severity", "UNKNOWN")
                emoji      = SEV_EMOJI.get(sev, "⚪")
                guide      = r.get("guideline", "")
                guide_cell = f"[docs]({guide})" if guide else "—"
                lines.append(
                    f"| {emoji} {sev} | `{r['rule_id']}` "
                    f"| `{r.get('resource','N/A')}` "
                    f"| {r.get('scanner', '').upper()} | {guide_cell} |"
                )
            lines.append("")

    lines += [
        "---",
        "",
        "> ⚠️ **Config Drift Warning**  ",
        "> Always run `terraform plan` on patched files before applying.",
        "> Review diffs in `fix_output/` against your tfstate.",
        "",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# HTML
# ─────────────────────────────────────────────────────────────────────────────

def _build_html(data: dict) -> str:
    s           = data["summary"]
    ts          = data["timestamp"]
    dry         = " (DRY RUN)" if data["dry_run"] else ""
    tf_files    = data.get("tf_files", [])
    patched_map = data.get("patched_files", {})
    fix_results = data["fix_results"]
    no_fix      = data["no_fix"]

    fixed   = [r for r in fix_results if r["status"] == "fixed"]
    skipped = [r for r in fix_results if r["status"] == "skipped"]
    failed  = [r for r in fix_results if r["status"] == "failed"]

    def badge(sev):
        c = SEV_COLOR.get(sev, "#6b7280")
        return (f'<span style="background:{c};color:#fff;padding:2px 8px;'
                f'border-radius:4px;font-size:11px;font-weight:700">{sev}</span>')

    def file_header(path):
        return (f'<div class="file-header">📄 <code>{_short(path)}</code></div>')

    def fixed_table(items):
        rows = "".join(
            f"<tr><td><code>{r['rule_id']}</code></td>"
            f"<td>{badge(r.get('severity','UNKNOWN'))}</td>"
            f"<td><code>{r.get('resource','N/A')}</code></td>"
            f"<td>{r.get('scanner', '').upper()}</td>"
            f"<td>{r.get('rule','—')}</td></tr>"
            for r in items
        )
        return (
            "<table><tr><th>Check ID</th><th>Severity</th>"
            "<th>Resource</th><th>Source</th><th>Fix Applied</th></tr>"
            f"{rows}</table>"
        )

    def manual_table(items):
        def link(r):
            g = r.get("guideline", "")
            return f'<a href="{g}" target="_blank">docs</a>' if g else "—"
        rows = "".join(
            f"<tr><td>{badge(r.get('severity','UNKNOWN'))}</td>"
            f"<td><code>{r['rule_id']}</code></td>"
            f"<td><code>{r.get('resource','N/A')}</code></td>"
            f"<td>{r.get('scanner', '').upper()}</td>"
            f"<td>{link(r)}</td></tr>"
            for r in items
        )
        return (
            "<table><tr><th>Severity</th><th>Check ID</th>"
            "<th>Resource</th><th>Source</th><th>Guideline</th></tr>"
            f"{rows}</table>"
        )

    # Build grouped sections
    fixed_html = ""
    for fp, items in _group_by_file(fixed).items():
        fixed_html += file_header(fp) + fixed_table(items)

    manual_html = ""
    for fp, items in _group_by_file(no_fix).items():
        manual_html += file_header(fp) + manual_table(items)

    patched_list = "".join(
        f"<li><code>{_short(src)}</code> → <code>{dst}</code></li>"
        for src, dst in patched_map.items()
    ) or "<li>None</li>"

    skipped_rows = "".join(
        f"<tr><td><code>{r['rule_id']}</code></td>"
        f"<td>{badge(r.get('severity','UNKNOWN'))}</td>"
        f"<td><code>{_short(r.get('file_path', ''))}</code></td>"
        f"<td><code>{r.get('resource','N/A')}</code></td>"
        f"<td>{r.get('reason','')}</td></tr>"
        for r in skipped
    )

    failed_rows = "".join(
        f"<tr><td><code>{r['rule_id']}</code></td>"
        f"<td><code>{_short(r.get('file_path', ''))}</code></td>"
        f"<td>{r.get('reason','')}</td></tr>"
        for r in failed
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IaC Auto-Fix Report{dry}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f172a;color:#e2e8f0;padding:32px;line-height:1.6}}
h1{{font-size:1.8rem;color:#38bdf8;margin-bottom:4px}}
.meta{{color:#94a3b8;font-size:.875rem;margin-bottom:28px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:16px;margin-bottom:32px}}
.card{{background:#1e293b;border-radius:12px;padding:20px;text-align:center;border:1px solid #334155}}
.card .num{{font-size:2rem;font-weight:700;color:#38bdf8}}
.card .label{{font-size:.75rem;color:#94a3b8;margin-top:4px}}
.card.green .num{{color:#4ade80}}.card.red .num{{color:#f87171}}
.card.yellow .num{{color:#facc15}}.card.orange .num{{color:#fb923c}}
section{{margin-bottom:32px}}
h2{{font-size:1rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;
    margin-bottom:12px;padding-bottom:6px;border-bottom:1px solid #334155}}
.file-header{{background:#1e293b;border-left:3px solid #38bdf8;padding:8px 14px;
              margin:14px 0 6px;border-radius:0 6px 6px 0;font-size:.875rem;color:#7dd3fc}}
table{{width:100%;border-collapse:collapse;font-size:.85rem;margin-bottom:8px}}
th{{background:#1e293b;color:#94a3b8;font-weight:600;text-align:left;
    padding:8px 12px;border-bottom:2px solid #334155}}
td{{padding:8px 12px;border-bottom:1px solid #1e293b;vertical-align:middle}}
tr:hover td{{background:#1e293b}}
code{{background:#0f172a;color:#7dd3fc;padding:2px 6px;border-radius:4px;font-size:.8rem}}
a{{color:#38bdf8}}
ul{{list-style:none;padding:0}}
ul li{{padding:4px 0;font-size:.875rem;color:#94a3b8}}
details summary{{cursor:pointer;color:#94a3b8;font-size:.875rem;margin-bottom:8px}}
.warn{{background:#422006;border:1px solid #92400e;border-radius:8px;
       padding:14px 18px;color:#fde68a;font-size:.875rem;margin-top:8px}}
</style>
</head>
<body>
<h1>🔒 IaC Auto-Fix Report{dry}</h1>
<div class="meta">Generated: {ts} &nbsp;|&nbsp; Scope: <code>{data.get('tf_dir','')}</code></div>

<div class="cards">
  <div class="card"><div class="num">{len(tf_files)}</div><div class="label">Files Scanned</div></div>
  <div class="card blue" style="--c:#38bdf8"><div class="num" style="color:#38bdf8">{s.get('files_patched',0)}</div><div class="label">Files Patched</div></div>
  <div class="card"><div class="num">{s['total']}</div><div class="label">Total Findings</div></div>
  <div class="card green"><div class="num">{s['fixed']}</div><div class="label">✅ Auto-Fixed</div></div>
  <div class="card yellow"><div class="num">{s['skipped']}</div><div class="label">⏭ Skipped</div></div>
  <div class="card red"><div class="num">{s['failed']}</div><div class="label">❌ Failed</div></div>
  <div class="card orange"><div class="num">{s['manual']}</div><div class="label">📋 Manual</div></div>
</div>

<section>
  <h2>📁 Patched Files</h2>
  <ul>{patched_list}</ul>
</section>

<section>
  <h2>✅ Auto-Fixed Issues</h2>
  {fixed_html or '<p style="color:#6b7280;font-size:.875rem">None</p>'}
</section>

{'<section><h2>❌ Fix Failures</h2><table><tr><th>Check ID</th><th>File</th><th>Reason</th></tr>' + failed_rows + '</table></section>' if failed else ''}

{'<section><details><summary>⏭ Skipped findings (' + str(len(skipped)) + ')</summary><table><tr><th>Check ID</th><th>Severity</th><th>File</th><th>Resource</th><th>Reason</th></tr>' + skipped_rows + '</table></details></section>' if skipped else ''}

<section>
  <h2>📋 Manual Review Required</h2>
  {manual_html or '<p style="color:#6b7280;font-size:.875rem">None — great job!</p>'}
</section>

<div class="warn">
  ⚠️ <strong>Config Drift Warning:</strong> Always run <code>terraform plan</code>
  on each patched file before applying. Review diffs in <code>fix_output/</code>
  against your tfstate.
</div>
</body>
</html>"""

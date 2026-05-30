#!/usr/bin/env python3
"""
IaC Auto-Fix Framework
Normalizes findings from Checkov + tfsec + Trivy,
auto-patches LOW/MEDIUM severity misconfigs across multiple .tf files,
and generates a PR summary report (Markdown + HTML).
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

from normalizers.checkov_normalizer import normalize_checkov
from normalizers.tfsec_normalizer   import normalize_tfsec
from normalizers.trivy_normalizer   import normalize_trivy
from patchers.tf_patcher            import MultiFilePatcher
from reports.report_generator       import generate_report


def load_json(path: str) -> dict | list:
    with open(path) as f:
        return json.load(f)


def merge_findings(sources: list[list[dict]]) -> list[dict]:
    """Merge normalized findings, dedup by (file_path, resource, rule_id)."""
    seen, merged = set(), []
    for source in sources:
        for finding in source:
            key = (finding["file_path"], finding["resource"], finding["rule_id"])
            if key not in seen:
                seen.add(key)
                merged.append(finding)
    return merged


def discover_tf_files(tf_dir: str) -> list[Path]:
    """Recursively find all .tf files under tf_dir."""
    return sorted(Path(tf_dir).rglob("*.tf"))


def main():
    parser = argparse.ArgumentParser(
        description="Auto-fix LOW/MEDIUM severity IaC misconfigs from Checkov/tfsec/Trivy"
    )
    # Accept either a directory (multi-file) or explicit file list
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tf-dir",   help="Directory to scan recursively for .tf files")
    group.add_argument("--tf-files", nargs="+", metavar="FILE",
                       help="Explicit list of .tf files to patch")

    parser.add_argument("--checkov",  default=None, help="Checkov JSON output")
    parser.add_argument("--tfsec",    default=None, help="tfsec JSON output")
    parser.add_argument("--trivy",    default=None, help="Trivy JSON output")
    parser.add_argument("--out-dir",  default="./fix_output", help="Output directory")
    parser.add_argument("--dry-run",  action="store_true", help="Preview only, no file changes")
    parser.add_argument("--severity", default="LOW",
                        help="Comma-separated severities to auto-fix (default: LOW)")
    args = parser.parse_args()

    if not any([args.checkov, args.tfsec, args.trivy]):
        parser.error("Provide at least one scan output (--checkov / --tfsec / --trivy)")

    target_severities = {s.strip().upper() for s in args.severity.split(",")}
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resolve target files
    if args.tf_dir:
        tf_files = discover_tf_files(args.tf_dir)
        tf_label = args.tf_dir
    else:
        tf_files = [Path(f) for f in args.tf_files]
        tf_label = ", ".join(args.tf_files)

    if not tf_files:
        print("[!] No .tf files found. Exiting.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  IaC Auto-Fix  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"  Target        : {tf_label}")
    print(f"  .tf files     : {len(tf_files)}")
    for f in tf_files:
        print(f"                  {f}")
    print(f"  Fix severities: {', '.join(sorted(target_severities))}")
    print(f"  Dry run       : {args.dry_run}")
    print(f"{'='*60}\n")

    # ── 1. Normalize ──────────────────────────────────────────────────────────
    all_sources = []
    if args.checkov:
        print(f"[+] Loading Checkov  : {args.checkov}")
        all_sources.append(normalize_checkov(load_json(args.checkov)))
    if args.tfsec:
        print(f"[+] Loading tfsec    : {args.tfsec}")
        all_sources.append(normalize_tfsec(load_json(args.tfsec)))
    if args.trivy:
        print(f"[+] Loading Trivy    : {args.trivy}")
        all_sources.append(normalize_trivy(load_json(args.trivy)))

    findings = merge_findings(all_sources)
    print(f"\n[*] Total unique findings : {len(findings)}")

    # ── 2. Partition ──────────────────────────────────────────────────────────
    to_fix = [f for f in findings if f["severity"].upper() in target_severities]
    no_fix = [f for f in findings if f["severity"].upper() not in target_severities]
    print(f"[*] To auto-fix           : {len(to_fix)}")
    print(f"[*] Manual review (higher): {len(no_fix)}")

    # ── 3. Patch all files ────────────────────────────────────────────────────
    patcher     = MultiFilePatcher(tf_files, out_dir=out_dir, dry_run=args.dry_run)
    fix_results = patcher.apply(to_fix)

    # ── 4. Write patched files ─────────────────────────────────────────────────
    written = patcher.write_all()
    if not args.dry_run:
        for src, dst in written.items():
            print(f"[+] Patched : {src}  →  {dst}")
    else:
        print("\n[!] Dry-run mode — no files written.")

    # ── 5. Report ─────────────────────────────────────────────────────────────
    report_data = {
        "timestamp"     : datetime.now().isoformat(),
        "tf_dir"        : tf_label,
        "tf_files"      : [str(f) for f in tf_files],
        "patched_files" : {str(k): str(v) for k, v in written.items()},
        "dry_run"       : args.dry_run,
        "fix_results"   : fix_results,
        "no_fix"        : no_fix,
        "summary"       : {
            "total"        : len(findings),
            "fixed"        : sum(1 for r in fix_results if r["status"] == "fixed"),
            "skipped"      : sum(1 for r in fix_results if r["status"] == "skipped"),
            "failed"       : sum(1 for r in fix_results if r["status"] == "failed"),
            "manual"       : len(no_fix),
            "files_patched": len(written),
        },
    }

    generate_report(report_data, out_dir / "PR_SUMMARY.md", out_dir / "PR_SUMMARY.html")
    with open(out_dir / "fix_report.json", "w") as f:
        json.dump(report_data, f, indent=2)

    # ── 6. Final summary ──────────────────────────────────────────────────────
    s = report_data["summary"]
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Total findings   : {s['total']}")
    print(f"  ✅ Fixed          : {s['fixed']}")
    print(f"  ⏭  Skipped        : {s['skipped']}  (no fixer rule)")
    print(f"  ❌ Failed         : {s['failed']}")
    print(f"  📋 Manual review  : {s['manual']}  (HIGH/CRITICAL)")
    print(f"  📁 Files patched  : {s['files_patched']} / {len(tf_files)}")
    print(f"{'='*60}")
    print(f"  Output: {out_dir}/")
    print(f"{'='*60}\n")

    sys.exit(1 if s["failed"] > 0 else 0)


if __name__ == "__main__":
    main()

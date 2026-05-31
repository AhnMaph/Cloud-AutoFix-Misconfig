#!/usr/bin/env python3
"""
os-autofix.py — IaC Auto-Fix cho OpenStack Terraform provider
Scan tool: Checkov  |  Resource focus: Networking
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

from normalizers.checkov_normalizer import normalize_checkov
from patchers.os_tf_patcher         import MultiFilePatcher
from reports.report_generator       import generate_report


def load_json(path: str) -> dict | list:
    with open(path) as f:
        return json.load(f)


def merge_findings(sources: list[list[dict]]) -> list[dict]:
    seen, merged = set(), []
    for source in sources:
        for finding in source:
            key = (finding["file_path"], finding["resource"], finding["rule_id"])
            if key not in seen:
                seen.add(key)
                merged.append(finding)
    return merged


def discover_tf_files(tf_dir: str) -> list[Path]:
    return sorted(Path(tf_dir).rglob("*.tf"))


def main():
    parser = argparse.ArgumentParser(
        description="Auto-fix OpenStack IaC misconfigs from Checkov"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tf-dir",   help="Directory to scan recursively for .tf files")
    group.add_argument("--tf-files", nargs="+", metavar="FILE")

    parser.add_argument("--checkov",  required=True, help="Checkov JSON output")
    parser.add_argument("--out-dir",  default="./fix_output")
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--severity", default="LOW,MEDIUM",
                        help="Severities to auto-fix (default: LOW,MEDIUM)")
    args = parser.parse_args()

    target_severities = {s.strip().upper() for s in args.severity.split(",")}
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tf_files = discover_tf_files(args.tf_dir) if args.tf_dir \
               else [Path(f) for f in args.tf_files]
    tf_label = args.tf_dir or ", ".join(args.tf_files)

    if not tf_files:
        print("[!] No .tf files found.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  OpenStack IaC Auto-Fix | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"  Target        : {tf_label}")
    print(f"  .tf files     : {len(tf_files)}")
    for f in tf_files:
        print(f"                  {f}")
    print(f"  Fix severities: {', '.join(sorted(target_severities))}")
    print(f"  Dry run       : {args.dry_run}")
    print(f"{'='*60}\n")

    # ── Normalize ─────────────────────────────────────────────────────────────
    print(f"[+] Loading Checkov: {args.checkov}")
    findings = merge_findings([normalize_checkov(load_json(args.checkov))])

    # Filter only OpenStack checks
    os_findings = [f for f in findings if "OPENSTACK" in f["rule_id"].upper()]
    other       = [f for f in findings if "OPENSTACK" not in f["rule_id"].upper()]
    if other:
        print(f"  ℹ️  Skipped {len(other)} non-OpenStack findings")

    print(f"\n[*] OpenStack findings : {len(os_findings)}")

    to_fix = [f for f in os_findings if f["severity"].upper() in target_severities]
    no_fix = [f for f in os_findings if f["severity"].upper() not in target_severities]
    print(f"[*] To auto-fix        : {len(to_fix)}")
    print(f"[*] Manual review      : {len(no_fix)}")

    # ── Patch ─────────────────────────────────────────────────────────────────
    patcher     = MultiFilePatcher(tf_files, out_dir=out_dir, dry_run=args.dry_run)
    fix_results = patcher.apply(to_fix)
    written     = patcher.write_all()

    if not args.dry_run:
        for src, dst in written.items():
            print(f"[+] Patched: {src}  →  {dst}")
    else:
        print("\n[!] Dry-run — no files written.")

    # ── Report ────────────────────────────────────────────────────────────────
    report_data = {
        "timestamp"    : datetime.now().isoformat(),
        "tf_dir"       : tf_label,
        "tf_files"     : [str(f) for f in tf_files],
        "patched_files": {str(k): str(v) for k, v in written.items()},
        "dry_run"      : args.dry_run,
        "fix_results"  : fix_results,
        "no_fix"       : no_fix,
        "summary": {
            "total"        : len(os_findings),
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

    s = report_data["summary"]
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Total findings   : {s['total']}")
    print(f"  ✅ Fixed          : {s['fixed']}")
    print(f"  ⏭  Skipped        : {s['skipped']}")
    print(f"  ❌ Failed         : {s['failed']}")
    print(f"  📋 Manual review  : {s['manual']}")
    print(f"  📁 Files patched  : {s['files_patched']} / {len(tf_files)}")
    print(f"{'='*60}\n")

    sys.exit(1 if s["failed"] > 0 else 0)


if __name__ == "__main__":
    main()
